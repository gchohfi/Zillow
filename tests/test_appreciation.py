"""Tests for appreciation and negotiation scoring."""

import pytest

from src.appreciation import assess_appreciation
from src.config import Config
from src.models import Listing
from src.review import classify_review_status
from src.viability import evaluate


def _cfg() -> Config:
    return Config(raw={
        "build": {
            "living_area_sqft": 1000,
            "construction_cost_per_sqft": 100,
            "resale_price_per_sqft": 300,
        },
        "costs": {"soft_cost_pct": 0, "selling_cost_pct": 0},
        "rules": {
            "target_margin": 0.18,
            "max_land_price": 0,
            "max_land_to_total_investment_pct": 0.65,
            "require_residential_zoning": True,
            "require_known_zoning": True,
            "min_lot_size_sqft": 5000,
        },
        "tiers": [],
        "county_costs": {"zip_to_county": {"34772": "osceola"}},
        "market_strategy": {
            "default_priority": "fora",
            "default_score": 0,
            "zip_groups": [{
                "label": "St. Cloud",
                "priority": "Alta",
                "score": 9,
                "zips": ["34772"],
            }],
        },
        "radar": {
            "enabled": True,
            "include_appreciation_candidates": True,
            "include_unknown_zoning": True,
            "include_manual_review_segments": True,
            "include_high_flood_risk": True,
        },
        "appreciation": {
            "enabled": True,
            "minimum_score": 7,
            "minimum_regional_score": 7,
            "minimum_property_score": 5.5,
            "minimum_margin": 0.10,
            "max_margin_shortfall": 0.08,
            "max_land_ratio_overage": 0.05,
            "max_ask_above_supported_pct": 0.65,
            "max_negotiation_gap_usd": 25_000,
            "regional_weight": 0.60,
            "property_weight": 0.40,
            "metro_hpi": {"one_year_pct": -0.0089, "five_year_pct": 0.4895},
            "county_growth_full_score_pct": 0.25,
            "county_population_growth_2025_2035": {"osceola": 0.2919},
        },
    })


def _near_miss(zoning="residential"):
    return Listing(
        id="near-miss",
        price=150_000,
        lat=28.2,
        lng=-81.2,
        address="123 Test Rd, Saint Cloud, FL 34772",
        zoning=zoning,
        lot_size_sqft=8000,
    )


def test_max_supported_price_adapts_to_target_margin():
    result = evaluate(_near_miss(), _cfg())

    assert result.margin == 50_000 / 300_000
    assert result.max_supported_land_price == pytest.approx(146_000)
    assert round(result.asking_premium_to_supported, 4) == round(4_000 / 146_000, 4)


def test_strong_region_near_miss_becomes_appreciation_radar():
    cfg = _cfg()
    result = evaluate(_near_miss(), cfg)
    assess_appreciation(result, cfg)
    classify_review_status(result, cfg)

    assert not result.is_viable
    assert result.regional_appreciation_score >= 7
    assert result.appreciation_score >= 7
    assert result.review_status == "radar_valorizacao"
    assert result.max_supported_land_price < result.land_cost


def test_appreciation_never_rescues_commercial_zoning():
    cfg = _cfg()
    result = evaluate(_near_miss(zoning="commercial"), cfg)
    assess_appreciation(result, cfg)
    classify_review_status(result, cfg)

    assert result.review_status == "reprovado"


def test_large_price_gap_stays_rejected():
    cfg = _cfg()
    listing = _near_miss()
    listing.price = 190_000
    result = evaluate(listing, cfg)
    assess_appreciation(result, cfg)
    classify_review_status(result, cfg)

    assert result.review_status == "reprovado"
