"""Tests for the RentCast datasource adapter."""

from src.config import Config
from src.datasource import RentCastSource


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_rentcast_parses_sale_listing(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    source = RentCastSource({"rentcast": {}})

    listing = source._parse({
        "id": "123-main",
        "formattedAddress": "123 Main St, Orlando, FL 32801",
        "latitude": 28.5384,
        "longitude": -81.3789,
        "propertyType": "Land",
        "price": 95000,
        "lotSize": 10000,
        "listedDate": "2026-06-27T00:00:00.000Z",
    })

    assert listing.id == "123-main"
    assert listing.price == 95000
    assert listing.lat == 28.5384
    assert listing.lng == -81.3789
    assert listing.address == "123 Main St, Orlando, FL 32801"
    assert listing.lot_size_sqft == 10000
    assert listing.property_type == "Land"
    assert listing.source == "rentcast"


def test_rentcast_fetches_land_with_api_key_and_pagination(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    calls = []
    pages = [
        [{"id": "a", "price": 90000, "latitude": 28.5, "longitude": -81.3, "propertyType": "Land"}],
        [],
    ]

    def fake_get(url, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return _Response(pages[len(calls) - 1])

    monkeypatch.setattr("src.datasource.requests.get", fake_get)
    cfg = Config(raw={
        "search": {"center_lat": 28.5384, "center_lng": -81.3789, "radius_km": 180},
        "datasource": {},
    })
    source = RentCastSource({
        "rentcast": {
            "limit": 1,
            "max_pages": 2,
            "params": {"daysOld": "1-14"},
            "search_points": [{"name": "Orlando", "lat": 28.5384, "lng": -81.3789, "radius_miles": 100}],
        }
    })

    listings = source.fetch_new_land_listings(cfg)

    assert [listing.id for listing in listings] == ["a"]
    assert len(calls) == 2
    assert calls[0]["url"] == "https://api.rentcast.io/v1/listings/sale"
    assert calls[0]["headers"]["X-Api-Key"] == "test-key"
    assert calls[0]["params"]["propertyType"] == "Land"
    assert calls[0]["params"]["status"] == "Active"
    assert calls[0]["params"]["daysOld"] == "1-14"
    assert calls[0]["params"]["limit"] == 1
    assert calls[0]["params"]["offset"] == 0
    assert calls[1]["params"]["offset"] == 1
