"""Tests for GIS-based zoning/land-use confirmation."""

from src.config import Config
from src.models import Listing
from src.viability import evaluate
from src.zoning import ZoningCache, _label_from_value, enrich_zoning, lookup_zoning

_DOR_MAP = {"00": "vacant residential", "10": "vacant commercial"}


def _cfg(tmp_path, **overrides):
    section = {
        "enabled": True,
        "cache_db": str(tmp_path / "zoning.db"),
        "cache_days": 90,
        "timeout_seconds": 5,
        "sources": [{
            "name": "fl_parcelas",
            "query_url": "https://gis.example.com/parcels/query",
            "fields": ["PARUSEDESC", "DOR_UC"],
        }],
    }
    section.update(overrides)
    return Config(raw={"zoning_lookup": section})


def _listing(**kwargs):
    base = dict(id="x", price=45_000, lat=28.47, lng=-81.62)
    base.update(kwargs)
    return Listing(**base)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _arcgis_payload(attrs):
    return {"features": [{"attributes": attrs}]}


def test_label_from_value_maps_dor_codes_and_passes_text():
    assert _label_from_value("0000", _DOR_MAP) == "vacant residential"
    assert _label_from_value("10", _DOR_MAP) == "vacant commercial"
    assert _label_from_value("VACANT RESIDENTIAL", _DOR_MAP) == "vacant residential"
    assert _label_from_value("", _DOR_MAP) is None


def test_lookup_prefers_text_field_and_caches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeResponse(_arcgis_payload({
            "PARUSEDESC": "VACANT RESIDENTIAL",
            "DOR_UC": "0000",
        }))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    cfg = _cfg(tmp_path)

    zoning, note = lookup_zoning(_listing(), cfg)
    assert zoning == "vacant residential"
    assert "GIS fl_parcelas" in note

    # Mesmo ponto: cache, sem nova consulta.
    zoning2, _ = lookup_zoning(_listing(), cfg)
    assert zoning2 == "vacant residential"
    assert calls["n"] == 1


def test_lookup_falls_back_to_dor_code(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"DOR_UC": "1000"})),
    )
    zoning, _ = lookup_zoning(_listing(), _cfg(tmp_path))
    assert zoning == "vacant commercial"


def test_lookup_fails_open(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        import requests
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("src.zoning.requests.get", boom)
    zoning, note = lookup_zoning(_listing(), _cfg(tmp_path))
    assert zoning is None and note is None


def test_lookup_disabled_or_missing_coords(tmp_path):
    assert lookup_zoning(_listing(), _cfg(tmp_path, enabled=False)) == (None, None)
    assert lookup_zoning(_listing(lat=0, lng=0), _cfg(tmp_path)) == (None, None)


def test_enrich_zoning_fills_missing_and_respects_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"PARUSEDESC": "VACANT RESIDENTIAL"})),
    )
    cfg = _cfg(tmp_path)

    listing = _listing()
    note = enrich_zoning(listing, cfg)
    assert listing.zoning == "vacant residential"
    assert note and "uso do solo" in note

    already = _listing(zoning="R-1")
    assert enrich_zoning(already, cfg) is None
    assert already.zoning == "R-1"


def test_confirmed_residential_zoning_unlocks_viability(tmp_path, monkeypatch):
    """Radar de zoneamento pendente vira viável quando o GIS confirma residencial."""
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"PARUSEDESC": "VACANT RESIDENTIAL"})),
    )
    eval_cfg = Config(raw={
        "build": {
            "living_area_sqft": 1400,
            "construction_cost_per_sqft": 120,
            "resale_price_per_sqft": 225,
        },
        "costs": {
            "soft_cost_pct": 0.10,
            "selling_cost_pct": 0.07,
        },
        "rules": {
            "target_margin": 0.10,
            "max_land_to_total_investment_pct": 0.30,
            "require_residential_zoning": True,
            "require_known_zoning": True,
        },
        "tiers": [],
        "zoning_lookup": _cfg(tmp_path).raw["zoning_lookup"],
    })

    listing = _listing(price=40_000)
    # Sem zoneamento: bloqueada pela exigência de zoneamento conhecido.
    blocked = evaluate(listing, eval_cfg)
    assert not blocked.is_viable

    enrich_zoning(listing, eval_cfg)
    confirmed = evaluate(listing, eval_cfg)
    assert confirmed.is_viable
    assert any("zoneamento residencial" in reason for reason in confirmed.reasons)


def test_zoning_cache_roundtrip(tmp_path):
    cache = ZoningCache(str(tmp_path / "z.db"))
    key = ZoningCache.key_for(28.47, -81.62)
    cache.put(key, {"zoning": "single family residential", "note": "n"})
    assert cache.get(key, max_age_days=90)["zoning"] == "single family residential"
    assert cache.get(key, max_age_days=0) is None
    cache.close()


def test_query_requests_only_needed_fields_and_retries_timeout(tmp_path, monkeypatch):
    import requests as req

    captured = {"outFields": None, "calls": 0}

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        captured["calls"] += 1
        captured["outFields"] = (params or {}).get("outFields")
        if captured["calls"] == 1:
            raise req.Timeout("lenta na primeira")
        return _FakeResponse(_arcgis_payload({"PARUSEDESC": "VACANT RESIDENTIAL"}))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    monkeypatch.setattr("src.zoning.time.sleep", lambda s: None)

    zoning, _ = lookup_zoning(_listing(), _cfg(tmp_path))
    assert zoning == "vacant residential"
    assert captured["calls"] == 2                     # retry após timeout
    assert captured["outFields"] == "PARUSEDESC,DOR_UC"  # só os campos pedidos


def test_invalid_field_falls_back_to_all_fields(tmp_path, monkeypatch):
    """Campo inexistente na camada -> refaz com outFields=* em vez de falhar."""
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        seen.append((params or {}).get("outFields"))
        if (params or {}).get("outFields") != "*":
            return _FakeResponse({"error": {"code": 400, "message": "Invalid field: PARUSEDESC"}})
        return _FakeResponse(_arcgis_payload({"DOR_UC": "0000", "PA_UC": "00"}))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    zoning, _ = lookup_zoning(_listing(), _cfg(tmp_path))
    assert zoning == "vacant residential"
    assert seen == ["PARUSEDESC,DOR_UC", "*"]


def test_county_source_resolves_url_by_zip(tmp_path, monkeypatch):
    """Fonte por county usa a URL do county da listagem; sem county, pula."""
    seen_urls = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        seen_urls.append(url)
        if "estadual" in url:
            import requests as req
            raise req.Timeout("estadual lenta")
        return _FakeResponse(_arcgis_payload({"DOR_UC": "0000"}))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    monkeypatch.setattr("src.zoning.time.sleep", lambda s: None)

    cfg = _cfg(tmp_path, sources=[
        {"name": "estadual", "query_url": "https://gis.example.com/estadual/query",
         "fields": ["DOR_UC"]},
        {"name": "county", "query_url_by_county": {
            "orange": "https://gis.example.com/orange/query",
        }, "fields": ["DOR_UC"]},
    ])
    cfg.raw["county_costs"] = {
        "counties": {"orange": {}},
        "zip_to_county": {"32801": "orange"},
    }

    listing = _listing(address="400 S Orange Ave, Orlando, FL 32801")
    zoning, note = lookup_zoning(listing, cfg)
    assert zoning == "vacant residential"
    assert "county" in note
    assert any("orange" in u for u in seen_urls)

    # Sem ZIP mapeado: a fonte por county é pulada e o resultado é vazio.
    seen_urls.clear()
    no_zip = _listing(address="Sem ZIP", lat=28.1, lng=-81.1)
    assert lookup_zoning(no_zip, cfg) == (None, None)
    assert not any("orange" in u for u in seen_urls)
