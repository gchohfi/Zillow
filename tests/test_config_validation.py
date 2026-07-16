"""Tests for config.yaml schema validation."""

from src.config import Config, validate_config


def _valid_raw():
    return {
        "search": {"center_lat": 28.5, "center_lng": -81.4, "radius_km": 80},
        "build": {
            "living_area_sqft": 2000,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {"soft_cost_pct": 0.10, "selling_cost_pct": 0.07},
        "rules": {"target_margin": 0.18, "max_land_to_total_investment_pct": 0.27},
        "tiers": [{"name": "t", "costs": {"selling_cost_pct": 0.08}}],
    }


def test_real_config_yaml_is_valid():
    assert validate_config(Config.load()) == []


def test_valid_raw_passes():
    assert validate_config(Config(raw=_valid_raw())) == []


def test_missing_section_and_bad_values_are_reported():
    raw = _valid_raw()
    del raw["search"]
    raw["costs"]["selling_cost_pct"] = 7          # 7 = 700%, claramente errado
    raw["rules"]["target_margin"] = "abc"
    raw["tiers"][0]["costs"]["selling_cost_pct"] = 8

    errors = validate_config(Config(raw=raw))
    assert any("search" in error for error in errors)
    assert any("selling_cost_pct" in error and "≤ 1" in error for error in errors)
    assert any("target_margin" in error for error in errors)
    assert any("tiers[0]" in error for error in errors)


def test_appreciation_thresholds_are_validated():
    raw = _valid_raw()
    raw["appreciation"] = {
        "minimum_score": 11,
        "minimum_margin": 1.2,
    }

    errors = validate_config(Config(raw=raw))

    assert any("appreciation.minimum_score" in error for error in errors)
    assert any("appreciation.minimum_margin" in error for error in errors)
