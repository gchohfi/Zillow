"""Budget and parsing tests for the Zillapi adapter."""

from src.config import Config
from src.datasource_zillapi import ZillapiSource


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self):
        return self.payload


def _source(monkeypatch, **overrides):
    monkeypatch.setenv("ZILLAPI_KEY", "test-only")
    section = {
        "base_url": "https://api.zillapi.test/v1",
        "max_items_per_run": 29,
        "bboxes_per_run": 1,
        "reserve_credits": 100,
        "bboxes": [
            {"west": -81.5, "south": 28.0, "east": -81.0, "north": 28.8},
            {"west": -82.0, "south": 27.8, "east": -81.5, "north": 28.4},
        ],
    }
    section.update(overrides)
    return ZillapiSource({"zillapi": section})


def _cfg():
    return Config(raw={"search": {"center_lat": 28.5, "center_lng": -81.4, "radius_km": 80}})


def test_search_has_hard_cap_and_records_balance(monkeypatch):
    balances = iter([1000, 971])
    posts = []

    def fake_get(*args, **kwargs):
        return _Response({"data": {"credits": {"balance": next(balances)}}})

    def fake_post(url, json=None, **kwargs):
        posts.append(json)
        rows = [
            {
                "zpid": str(index),
                "unformattedPrice": 100_000,
                "latLong": {"latitude": 28.5, "longitude": -81.4},
                "addressStreet": f"Lot {index}",
                "addressCity": "Orlando",
                "addressState": "FL",
                "addressZipcode": "32801",
                "lotAreaString": "0.25 acres",
            }
            for index in range(29)
        ]
        return _Response({"data": rows})

    monkeypatch.setattr("src.datasource_zillapi.requests.get", fake_get)
    monkeypatch.setattr("src.datasource_zillapi.requests.post", fake_post)

    source = _source(monkeypatch)
    listings = source.fetch_new_land_listings(_cfg())

    assert len(listings) == 29
    assert posts[0]["maxItems"] == 29
    assert posts[0]["filters"]["homeTypes"] == ["lot"]
    assert source.metrics["credits_consumed"] == 29
    assert source.metrics["credit_balance_after"] == 971
    assert listings[0].lot_size_sqft == 10_890


def test_search_shrinks_allowance_near_credit_floor(monkeypatch):
    balances = iter([110, 100])
    requested = []
    monkeypatch.setattr(
        "src.datasource_zillapi.requests.get",
        lambda *args, **kwargs: _Response(
            {"data": {"credits": {"balance": next(balances)}}}
        ),
    )

    def fake_post(url, json=None, **kwargs):
        requested.append(json["maxItems"])
        return _Response({"data": [{"zpid": str(i)} for i in range(10)]})

    monkeypatch.setattr("src.datasource_zillapi.requests.post", fake_post)
    source = _source(monkeypatch)
    source.fetch_new_land_listings(_cfg())
    assert requested == [10]
    assert source.metrics["credit_balance_after"] == 100


def test_scan_pauses_at_credit_floor_without_search(monkeypatch):
    monkeypatch.setattr(
        "src.datasource_zillapi.requests.get",
        lambda *args, **kwargs: _Response({"data": {"credits": {"balance": 100}}}),
    )
    monkeypatch.setattr(
        "src.datasource_zillapi.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("search called")),
    )
    source = _source(monkeypatch)
    assert source.fetch_new_land_listings(_cfg()) == []
    assert source.outcome.status == "degraded"
    assert source.metrics["max_items_allowed"] == 0

