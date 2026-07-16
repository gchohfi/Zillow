"""Tests for RentCast AVM ARV enrichment."""

from src.arv import enrich_arv
from src.config import Config
from src.models import Listing
from src.viability import evaluate


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _cfg() -> Config:
    return Config(raw={
        "datasource": {"rentcast": {"base_url": "https://api.rentcast.io/v1"}},
        "arv": {
            "enabled": True,
            "provider": "rentcast_avm",
            "path": "/avm/value",
            "property_type": "Single Family",
            "max_radius_miles": 2,
            "days_old": 180,
            "comp_count": 10,
            "min_comps": 3,
        },
        "search": {"center_lat": 28.5384, "center_lng": -81.3789, "radius_km": 80},
        "build": {
            "living_area_sqft": 2000,
            "bedrooms": 4,
            "bathrooms": 3,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {"soft_cost_pct": 0.10, "carrying_cost_pct": 0.06, "selling_cost_pct": 0.07},
        "rules": {
            "target_margin": 0.18,
            "max_land_price": 0,
            "max_land_to_total_investment_pct": 0.27,
            "require_residential_zoning": False,
        },
    })


def test_enrich_arv_uses_rentcast_value(monkeypatch):
    calls = []
    cfg = _cfg()
    listing = Listing(
        id="x",
        price=50_000,
        lat=28.5,
        lng=-81.3,
        address="121 Central Ave, Davenport, FL",
    )
    monkeypatch.setenv("RENTCAST_API_KEY", "key")

    def fake_get(url, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return _Response({
            "price": 410_000,
            "comparables": [{"id": 1}, {"id": 2}, {"id": 3}],
            "confidenceScore": "high",
        })

    monkeypatch.setattr("src.arv.requests.get", fake_get)

    enrich_arv(listing, cfg)
    result = evaluate(listing, cfg)

    assert listing.arv_estimate == 410_000
    assert result.arv == 410_000
    assert result.arv_source == "rentcast_avm"
    assert result.arv_comps_count == 3
    assert calls[0]["params"]["propertyType"] == "Single Family"
    assert calls[0]["params"]["squareFootage"] == 2000
    assert calls[0]["params"]["bedrooms"] == 4
    assert calls[0]["params"]["bathrooms"] == 3


def test_enrich_arv_falls_back_when_comps_are_insufficient(monkeypatch):
    cfg = _cfg()
    listing = Listing(id="x", price=50_000, lat=28.5, lng=-81.3, address="No comps")
    monkeypatch.setenv("RENTCAST_API_KEY", "key")
    monkeypatch.setattr(
        "src.arv.requests.get",
        lambda *args, **kwargs: _Response({"price": 410_000, "comparables": [{"id": 1}]}),
    )

    enrich_arv(listing, cfg)
    result = evaluate(listing, cfg)

    assert listing.arv_estimate is None
    assert result.arv == 660_000
    assert result.arv_source == "config"


def test_enrich_arv_caps_low_confidence_at_config_premise(monkeypatch):
    cfg = _cfg()
    listing = Listing(id="x", price=50_000, lat=28.5, lng=-81.3, address="Low conf")
    monkeypatch.setenv("RENTCAST_API_KEY", "key")
    monkeypatch.setattr(
        "src.arv.requests.get",
        lambda *args, **kwargs: _Response({
            "price": 900_000,   # bem acima da premissa de 660k
            "comparables": [{"id": i} for i in range(5)],
            "confidenceScore": "low",
        }),
    )

    enrich_arv(listing, cfg)

    # Premissa: 2000 sqft x 330 = 660k
    assert listing.arv_estimate == 660_000
    assert "limitado à premissa" in listing.arv_confidence


def test_enrich_arv_keeps_high_confidence_value(monkeypatch):
    cfg = _cfg()
    listing = Listing(id="x", price=50_000, lat=28.5, lng=-81.3, address="High conf")
    monkeypatch.setenv("RENTCAST_API_KEY", "key")
    monkeypatch.setattr(
        "src.arv.requests.get",
        lambda *args, **kwargs: _Response({
            "price": 900_000,
            "comparables": [{"id": i} for i in range(5)],
            "confidenceScore": "high",
        }),
    )

    enrich_arv(listing, cfg)
    assert listing.arv_estimate == 900_000
    assert listing.arv_confidence == "high"
