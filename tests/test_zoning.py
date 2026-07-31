"""Tests for legal zoning and indicative cadastral-use lookup."""

from src.config import Config
from src.models import Listing
from src.viability import evaluate
from src.zoning import ZoningCache, _label_from_value, enrich_zoning, lookup_zoning

_DOR_MAP = {
    "00": "vacant residential",
    "10": "vacant commercial",
    "48": "industrial warehouse",
    "80": "government",
}


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
            "zoning_fields": [],
            "cadastral_use_fields": ["PARUSEDESC", "DOR_UC"],
        }],
    }
    section.update(overrides)
    return Config(raw={"zoning_lookup": section})


def _legal_cfg(tmp_path, **overrides):
    return _cfg(tmp_path, sources=[{
        "name": "county_zoning",
        "query_url": "https://gis.example.com/zoning/query",
        "fields": ["ZONE_DESC"],
        "zoning_fields": ["ZONE_DESC"],
        "cadastral_use_fields": [],
    }], **overrides)


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


def test_label_from_value_normalizes_current_and_legacy_dor_codes():
    assert _label_from_value("000", _DOR_MAP, field="DOR_UC") == "vacant residential"
    assert _label_from_value("080", _DOR_MAP, field="DOR_UC") == "government"
    assert _label_from_value("048", _DOR_MAP, field="DOR_UC") == "industrial warehouse"
    assert _label_from_value("100", _DOR_MAP, field="DOR_UC") is None
    assert _label_from_value("0000", _DOR_MAP, field="DOR_UC") == "vacant residential"
    assert _label_from_value("1000", _DOR_MAP, field="DOR_UC") == "vacant commercial"
    assert _label_from_value("80.0", _DOR_MAP, field="DOR_UC") == "government"
    assert _label_from_value("080", _DOR_MAP, field="PA_UC") is None
    assert _label_from_value(
        "VACANT RESIDENTIAL", _DOR_MAP, field="PARUSEDESC"
    ) == "vacant residential"
    assert _label_from_value("", _DOR_MAP) is None


def test_lookup_records_cadastral_use_without_confirming_zoning_and_caches(
    tmp_path, monkeypatch
):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeResponse(_arcgis_payload({
            "PARUSEDESC": "VACANT RESIDENTIAL",
            "DOR_UC": "0000",
        }))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    cfg = _cfg(tmp_path)

    listing = _listing()
    zoning, note = lookup_zoning(listing, cfg)
    assert (zoning, note) == (None, None)
    assert listing.zoning is None
    assert listing.raw["_cadastral_use"] == "vacant residential"
    assert listing.raw["_cadastral_use_status"] == "indicativo"

    # Mesmo ponto: cache, sem nova consulta.
    cached_listing = _listing()
    zoning2, note2 = lookup_zoning(cached_listing, cfg)
    assert (zoning2, note2) == (None, None)
    assert cached_listing.raw["_cadastral_use"] == "vacant residential"
    assert calls["n"] == 1


def test_lookup_falls_back_to_dor_code(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"DOR_UC": "1000"})),
    )
    listing = _listing()
    zoning, note = lookup_zoning(listing, _cfg(tmp_path))
    assert (zoning, note) == (None, None)
    assert listing.raw["_cadastral_use"] == "vacant commercial"


def test_lookup_fails_open(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        import requests
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("src.zoning.requests.get", boom)
    listing = _listing()
    zoning, note = lookup_zoning(listing, _cfg(tmp_path))
    assert zoning is None and note is None
    assert listing.raw["_source_errors"] == [{
        "source": "fl_parcelas",
        "operation": "zoning_lookup",
        "error": "ConnectionError",
    }]


def test_lookup_disabled_or_missing_coords(tmp_path):
    assert lookup_zoning(_listing(), _cfg(tmp_path, enabled=False)) == (None, None)
    assert lookup_zoning(_listing(lat=0, lng=0), _cfg(tmp_path)) == (None, None)


def test_enrich_zoning_fills_missing_and_respects_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"ZONE_DESC": "R-1"})),
    )
    cfg = _legal_cfg(tmp_path)

    listing = _listing()
    note = enrich_zoning(listing, cfg)
    assert listing.zoning == "r-1"
    assert note and "zoning legal" in note

    already = _listing(zoning="R-1")
    assert enrich_zoning(already, cfg) is None
    assert already.zoning == "R-1"


def test_confirmed_residential_zoning_unlocks_viability(tmp_path, monkeypatch):
    """Radar de zoneamento pendente vira viável quando o GIS confirma residencial."""
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(
            _arcgis_payload({"ZONE_DESC": "Single Family Residential"})
        ),
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
        "zoning_lookup": _legal_cfg(tmp_path).raw["zoning_lookup"],
    })

    listing = _listing(price=40_000)
    # Sem zoneamento: bloqueada pela exigência de zoneamento conhecido.
    blocked = evaluate(listing, eval_cfg)
    assert not blocked.is_viable

    enrich_zoning(listing, eval_cfg)
    confirmed = evaluate(listing, eval_cfg)
    assert confirmed.is_viable
    assert any("zoneamento residencial" in reason for reason in confirmed.reasons)


def test_cadastral_residential_use_does_not_unlock_viability(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(_arcgis_payload({"DOR_UC": "000"})),
    )
    cfg = Config(raw={
        "build": {
            "living_area_sqft": 1400,
            "construction_cost_per_sqft": 120,
            "resale_price_per_sqft": 225,
        },
        "costs": {"soft_cost_pct": 0.10, "selling_cost_pct": 0.07},
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

    assert enrich_zoning(listing, cfg) is None
    result = evaluate(listing, cfg)

    assert listing.zoning is None
    assert result.cadastral_use == "vacant residential"
    assert result.cadastral_use_status == "indicativo"
    assert not result.is_viable
    assert any("zoneamento desconhecido" in reason for reason in result.reasons)


def test_zoning_cache_roundtrip(tmp_path):
    cache = ZoningCache(str(tmp_path / "z.db"))
    key = ZoningCache.key_for(28.47, -81.62)
    cache.put(key, {"zoning": "single family residential", "note": "n"})
    assert cache.get(key, max_age_days=90)["zoning"] == "single family residential"
    assert cache.get(key, max_age_days=0) is None
    cache.close()


def test_legacy_cache_cannot_restore_cadastral_use_as_legal_zoning(
    tmp_path, monkeypatch
):
    cfg = _cfg(tmp_path)
    cache = ZoningCache(str(tmp_path / "zoning.db"))
    key = ZoningCache.key_for(28.47, -81.62)
    cache.put(key, {
        "zoning": "vacant residential",
        "note": "uso do solo via DOR_UC",
    })
    cache.close()
    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse({"features": []})

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    listing = _listing()

    assert lookup_zoning(listing, cfg) == (None, None)
    assert listing.zoning is None
    assert calls["n"] == 1


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

    listing = _listing()
    zoning, note = lookup_zoning(listing, _cfg(tmp_path))
    assert (zoning, note) == (None, None)
    assert listing.raw["_cadastral_use"] == "vacant residential"
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
    listing = _listing()
    zoning, note = lookup_zoning(listing, _cfg(tmp_path))
    assert (zoning, note) == (None, None)
    assert listing.raw["_cadastral_use"] == "vacant residential"
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
         "fields": ["DOR_UC"], "zoning_fields": [],
         "cadastral_use_fields": ["DOR_UC"]},
        {"name": "county", "query_url_by_county": {
            "orange": "https://gis.example.com/orange/query",
        }, "fields": ["DOR_UC"], "zoning_fields": [],
         "cadastral_use_fields": ["DOR_UC"]},
    ])
    cfg.raw["county_costs"] = {
        "counties": {"orange": {}},
        "zip_to_county": {"32801": "orange"},
    }

    listing = _listing(address="400 S Orange Ave, Orlando, FL 32801")
    zoning, note = lookup_zoning(listing, cfg)
    assert (zoning, note) == (None, None)
    assert listing.raw["_cadastral_use"] == "vacant residential"
    assert listing.raw["_cadastral_use_source"] == "county"
    assert any("orange" in u for u in seen_urls)

    # Sem ZIP mapeado: a fonte por county é pulada e o resultado é vazio.
    seen_urls.clear()
    no_zip = _listing(address="Sem ZIP", lat=28.1, lng=-81.1)
    assert lookup_zoning(no_zip, cfg) == (None, None)
    assert not any("orange" in u for u in seen_urls)


def test_failed_lookup_is_cached_and_retried_after_window(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from src.zoning import ZoningCache
    import requests as req

    calls = {"n": 0}

    def always_timeout(*args, **kwargs):
        calls["n"] += 1
        raise req.ConnectTimeout("bloqueado")

    monkeypatch.setattr("src.zoning.requests.get", always_timeout)
    monkeypatch.setattr("src.zoning.time.sleep", lambda s: None)
    cfg = _cfg(tmp_path, failure_retry_hours=6)

    assert lookup_zoning(_listing(), cfg) == (None, None)
    first_calls = calls["n"]
    assert first_calls > 0

    # Dentro da janela: falha cacheada, nenhuma nova chamada.
    assert lookup_zoning(_listing(), cfg) == (None, None)
    assert calls["n"] == first_calls

    # Envelhece a falha para além das 6h: volta a tentar.
    cache = ZoningCache(str(tmp_path / "zoning.db"))
    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    cache.conn.execute("UPDATE zoning_cache SET fetched_at = ?", (old,))
    cache.conn.commit()
    cache.close()

    assert lookup_zoning(_listing(), cfg) == (None, None)
    assert calls["n"] > first_calls


def _regrid_cfg(tmp_path):
    return _cfg(tmp_path, sources=[
        {"name": "regrid", "type": "regrid",
         "query_url": "https://app.regrid.com/api/v2/parcels/point",
         "fields": ["zoning_description", "zoning", "usedesc", "usecode"],
         "zoning_fields": ["zoning_description", "zoning"],
         "cadastral_use_fields": ["usedesc", "usecode"]},
    ])


def test_regrid_source_confirms_zoning_and_owner(tmp_path, monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return _FakeResponse({"parcels": {"type": "FeatureCollection", "features": [{
            "properties": {"fields": {
                "zoning": "R-1",
                "zoning_description": "Single Family Residential",
                "usedesc": "VACANT RESIDENTIAL",
                "owner": "SMITH JOHN",
            }}
        }]}})

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    monkeypatch.setenv("REGRID_API_KEY", "sandbox-token")

    listing = _listing()
    zoning, note = lookup_zoning(listing, _regrid_cfg(tmp_path))
    assert zoning == "single family residential"
    assert "regrid" in note and "dono: SMITH JOHN" in note
    assert listing.raw["_cadastral_use"] == "vacant residential"
    assert listing.raw["_cadastral_use_status"] == "indicativo"
    assert captured["params"]["token"] == "sandbox-token"
    assert captured["params"]["lat"] == 28.47


def test_radius_reaches_parcel_across_the_street(tmp_path, monkeypatch):
    """radius_m vira 'radius' na Regrid e 'distance' em metros no ArcGIS."""
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        captured[url] = dict(params or {})
        if "regrid" in url:
            return _FakeResponse({"parcels": {"type": "FeatureCollection", "features": [{
                "properties": {"fields": {"zoning": "R-1"}}
            }]}})
        return _FakeResponse(_arcgis_payload({"DOR_UC": "0000"}))

    monkeypatch.setattr("src.zoning.requests.get", fake_get)
    monkeypatch.setenv("REGRID_API_KEY", "sandbox-token")

    cfg = _cfg(tmp_path, radius_m=30, sources=[
        {"name": "regrid", "type": "regrid",
         "query_url": "https://regrid.example.com/point", "fields": ["zoning"],
         "zoning_fields": ["zoning"], "cadastral_use_fields": []},
    ])
    zoning, _ = lookup_zoning(_listing(), cfg)
    assert zoning == "r-1"
    assert captured["https://regrid.example.com/point"]["radius"] == 30

    cfg2 = _cfg(tmp_path, radius_m=30)
    cfg2.raw["zoning_lookup"]["cache_db"] = str(tmp_path / "z2.db")
    arc_listing = _listing(lat=28.48)
    zoning2, note2 = lookup_zoning(arc_listing, cfg2)
    assert (zoning2, note2) == (None, None)
    assert arc_listing.raw["_cadastral_use"] == "vacant residential"
    arcgis_params = captured["https://gis.example.com/parcels/query"]
    assert arcgis_params["distance"] == 30
    assert arcgis_params["units"] == "esriSRUnit_Meter"


def test_regrid_unexpected_body_fails_open_with_warning(tmp_path, monkeypatch, capsys):
    """Corpo 200 sem lista de feições (erro disfarçado) vira aviso, não silêncio."""
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse({"error": "invalid token"}),
    )
    monkeypatch.setenv("REGRID_API_KEY", "sandbox-token")

    assert lookup_zoning(_listing(), _regrid_cfg(tmp_path)) == (None, None)
    output = capsys.readouterr().out
    assert "source_error source=regrid" in output
    assert "error=RuntimeError" in output


def test_empty_features_logs_no_parcel_warning(tmp_path, monkeypatch, capsys):
    """Resposta válida porém vazia (sem parcela no ponto) fica visível no log."""
    monkeypatch.setattr(
        "src.zoning.requests.get",
        lambda *a, **k: _FakeResponse(
            {"parcels": {"type": "FeatureCollection", "features": []}}
        ),
    )
    monkeypatch.setenv("REGRID_API_KEY", "sandbox-token")

    assert lookup_zoning(_listing(), _regrid_cfg(tmp_path)) == (None, None)
    assert "sem parcela no ponto" in capsys.readouterr().out


def test_regrid_source_skipped_without_key(tmp_path, monkeypatch):
    def no_call(*args, **kwargs):
        raise AssertionError("nao deveria chamar a Regrid sem chave")

    monkeypatch.setattr("src.zoning.requests.get", no_call)
    monkeypatch.delenv("REGRID_API_KEY", raising=False)

    assert lookup_zoning(_listing(), _regrid_cfg(tmp_path)) == (None, None)
