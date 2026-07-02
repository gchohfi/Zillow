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

    def fake_post(url, data=None, timeout=None):
        calls["post"] += 1
        return _FakeResponse(overpass_payload)

    def fake_get(url, params=None, timeout=None):
        calls["get"] += 1
        year = int(url.rstrip("/").split("/data/")[1].split("/")[0])
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
