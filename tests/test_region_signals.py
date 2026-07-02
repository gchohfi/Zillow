"""Tests for region growth signals (schools, commerce, population, income)."""

import json

from src.config import Config
from src.region_signals import (
    SignalsCache,
    build_summary,
    compute_score,
    get_region_signals,
)


def _cfg(tmp_path, **overrides):
    section = {
        "enabled": True,
        "cache_db": str(tmp_path / "signals.db"),
        "cache_days": 30,
        "radius_km": 3,
        "census_latest_year": 2023,
        "census_base_year": 2018,
        "timeout_seconds": 5,
        "fetch_pause_seconds": 0,
    }
    section.update(overrides)
    return Config(raw={"region_signals": section})


def test_compute_score_full_signals():
    score = compute_score({
        "schools": 6,          # teto -> 1.0
        "commerce": 15,        # metade -> 0.5
        "pop_growth_pct": 0.05,     # metade -> 0.5
        "income_growth_pct": 0.30,  # teto -> 1.0
    })
    assert score == 7.5


def test_compute_score_renormalizes_missing_components():
    assert compute_score({"schools": 6}) == 10.0
    assert compute_score({}) is None
    assert compute_score({"pop_growth_pct": -0.05, "schools": None}) == 0.0


def test_build_summary_lists_only_available_signals():
    summary = build_summary(
        {"schools": 4, "commerce": None, "pop_growth_pct": 0.083, "income_growth_pct": None},
        radius_km=3,
    )
    assert summary == ["4 escolas em 3 km", "populacao +8.3% em 5 anos"]


def test_cache_roundtrip_and_expiry(tmp_path):
    cache = SignalsCache(str(tmp_path / "signals.db"))
    cache.put("34787", {"score": 8.0})
    assert cache.get("34787", max_age_days=30) == {"score": 8.0}
    assert cache.get("34787", max_age_days=0) is None
    assert cache.get("00000", max_age_days=30) is None
    cache.close()


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    @property
    def text(self):
        return json.dumps(self._payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_get_region_signals_fetches_scores_and_caches(tmp_path, monkeypatch):
    overpass_payload = {"elements": [
        {"type": "count", "tags": {"total": "5"}},
        {"type": "count", "tags": {"total": "24"}},
    ]}
    census_by_year = {
        2023: [["B01003_001E", "B19013_001E", "zip"], ["55000", "91000", "34787"]],
        2018: [["B01003_001E", "B19013_001E", "zip"], ["50000", "70000", "34787"]],
    }
    calls = {"post": 0, "get": 0}
    census_params = {}

    def fake_post(url, data=None, timeout=None, **kwargs):
        calls["post"] += 1
        return _FakeResponse(overpass_payload)

    def fake_get(url, params=None, timeout=None, **kwargs):
        calls["get"] += 1
        year = int(url.rstrip("/").split("/data/")[1].split("/")[0])
        census_params[year] = dict(params or {})
        return _FakeResponse(census_by_year[year])

    monkeypatch.setattr("src.region_signals.requests.post", fake_post)
    monkeypatch.setattr("src.region_signals.requests.get", fake_get)

    cfg = _cfg(tmp_path)
    signals = get_region_signals("34787", 28.47, -81.62, cfg)

    assert signals["schools"] == 5
    assert signals["commerce"] == 24
    assert round(signals["pop_growth_pct"], 3) == 0.1
    assert round(signals["income_growth_pct"], 3) == 0.3
    assert signals["score"] is not None
    assert any("escolas" in s for s in signals["summary"])
    # ZCTA aninhado por estado até o vintage 2019; nacional a partir de 2020.
    assert census_params[2018].get("in") == "state:12"
    assert "in" not in census_params[2023]

    # Segunda chamada vem do cache: sem novas requisições.
    before = dict(calls)
    cached = get_region_signals("34787", 28.47, -81.62, cfg)
    assert cached["schools"] == 5
    assert calls == before


def test_get_region_signals_fails_open(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        import requests
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("src.region_signals.requests.post", boom)
    monkeypatch.setattr("src.region_signals.requests.get", boom)

    signals = get_region_signals("34787", 28.47, -81.62, _cfg(tmp_path))
    assert signals is not None
    assert signals["schools"] is None
    assert signals["pop_growth_pct"] is None
    assert signals["score"] is None


def test_get_region_signals_disabled_or_no_zip(tmp_path):
    assert get_region_signals("34787", 28.5, -81.4, _cfg(tmp_path, enabled=False)) is None
    assert get_region_signals(None, 28.5, -81.4, _cfg(tmp_path)) is None


def test_prefetch_config_zips_geocodes_and_caches(tmp_path, monkeypatch):
    from src.region_signals import prefetch_config_zips

    cfg = _cfg(tmp_path, prefetch_thesis_zips=True, prefetch_pause_seconds=0)
    cfg.raw["market_strategy"] = {"zip_groups": [
        {"label": "Lake Nona", "priority": "Alta", "zips": ["32827", "32832"]},
    ]}

    monkeypatch.setattr("src.region_signals._geocode_zip", lambda z, s: (28.4, -81.25))
    monkeypatch.setattr(
        "src.region_signals._fetch_overpass_counts", lambda lat, lng, r, s: (4, 20)
    )
    monkeypatch.setattr(
        "src.region_signals._fetch_census_acs",
        lambda z, year, s: (50000.0, 80000.0) if year == 2018 else (56000.0, 95000.0),
    )

    assert prefetch_config_zips(cfg) == 2
    # Segunda chamada: tudo em cache, nada novo.
    assert prefetch_config_zips(cfg) == 0


def test_prefetch_disabled_returns_zero(tmp_path):
    from src.region_signals import prefetch_config_zips
    assert prefetch_config_zips(_cfg(tmp_path, prefetch_thesis_zips=False)) == 0


def test_cached_signals_for_zips_reads_without_network(tmp_path):
    from src.region_signals import cached_signals_for_zips

    cfg = _cfg(tmp_path)
    cache = SignalsCache(str(tmp_path / "signals.db"))
    cache.put("32827", {"score": 7.2, "summary": ["4 escolas em 3 km"]})
    cache.close()

    result = cached_signals_for_zips(["32827", "99999"], cfg)
    assert result["32827"]["score"] == 7.2
    assert "99999" not in result


def test_overpass_falls_back_to_mirror(tmp_path, monkeypatch):
    from src.region_signals import _fetch_overpass_counts
    import requests as req

    attempts = []

    def fake_post(url, data=None, timeout=None, **kwargs):
        attempts.append(url)
        if "overpass-api.de" in url:
            raise req.HTTPError("429 Too Many Requests")
        return _FakeResponse({"elements": [
            {"type": "count", "tags": {"total": "3"}},
            {"type": "count", "tags": {"total": "17"}},
        ]})

    monkeypatch.setattr("src.region_signals.requests.post", fake_post)
    schools, commerce = _fetch_overpass_counts(28.5, -81.4, 3000, {})
    assert (schools, commerce) == (3, 17)
    assert len(attempts) == 2


def test_failed_fetch_is_retried_after_grace_period(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    cfg = _cfg(tmp_path, failure_retry_hours=6)
    cache = SignalsCache(str(tmp_path / "signals.db"))
    cache.put("34787", {"score": None, "schools": None})
    # Envelhece a falha para além da janela de retry (7h atrás).
    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    cache.conn.execute("UPDATE region_signals SET fetched_at = ?", (old,))
    cache.conn.commit()

    monkeypatch.setattr(
        "src.region_signals._fetch_overpass_counts", lambda lat, lng, r, s: (4, 20)
    )
    monkeypatch.setattr(
        "src.region_signals._fetch_census_acs",
        lambda z, year, s: (50000.0, 80000.0) if year == 2018 else (56000.0, 95000.0),
    )
    signals = get_region_signals("34787", 28.47, -81.62, cfg, cache=cache)
    assert signals["score"] is not None
    assert signals["schools"] == 4
    cache.close()


def test_recent_failure_is_not_hammered(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, failure_retry_hours=6)
    cache = SignalsCache(str(tmp_path / "signals.db"))
    cache.put("34787", {"score": None, "schools": None})

    def boom(*args, **kwargs):
        raise AssertionError("nao deveria buscar de novo dentro da janela")

    monkeypatch.setattr("src.region_signals._fetch_overpass_counts", boom)
    monkeypatch.setattr("src.region_signals._fetch_census_acs", boom)
    signals = get_region_signals("34787", 28.47, -81.62, cfg, cache=cache)
    assert signals["score"] is None
    cache.close()
