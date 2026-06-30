"""Tests for market thesis classification."""

from src.config import Config
from src.market_strategy import classify_market, extract_zip
from src.models import Listing


def _cfg() -> Config:
    return Config(raw={
        "market_strategy": {
            "default_priority": "fora",
            "default_score": 0,
            "zip_groups": [
                {
                    "label": "Lake Nona / Narcoossee",
                    "priority": "Alta",
                    "score": 10,
                    "zips": ["32827", "34771"],
                    "strategies": ["SFR/BTR"],
                    "risk_flags": ["checar utilities"],
                }
            ],
        }
    })


def test_extract_zip_from_address():
    listing = Listing(id="x", price=1, lat=0, lng=0, address="123 Main, Orlando, FL 32827")
    assert extract_zip(listing) == "32827"


def test_extract_zip_from_raw_nested_address():
    listing = Listing(
        id="x",
        price=1,
        lat=0,
        lng=0,
        raw={"address": {"zipCode": "34771-1234"}},
    )
    assert extract_zip(listing) == "34771"


def test_classify_market_priority_group():
    listing = Listing(id="x", price=1, lat=0, lng=0, address="Narcoossee, FL 34771")
    market = classify_market(listing, _cfg())

    assert market["zip_code"] == "34771"
    assert market["region"] == "Lake Nona / Narcoossee"
    assert market["priority"] == "Alta"
    assert market["score"] == 10
    assert market["strategies"] == ["SFR/BTR"]
    assert market["risk_flags"] == ["checar utilities"]


def test_classify_market_unknown_zip_gets_default_flag():
    listing = Listing(id="x", price=1, lat=0, lng=0, address="Other, FL 99999")
    market = classify_market(listing, _cfg())

    assert market["priority"] == "fora"
    assert market["score"] == 0
    assert market["risk_flags"] == ["ZIP fora das teses priorizadas no relatório"]
