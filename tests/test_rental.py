"""Tests for the rental (buy & hold) lens."""

import pytest

from src.config import Config
from src.models import Listing, ViabilityResult
from src.rental import _annual_debt_service, apply_rental_analysis


def _result(rent=2400.0, flood_high_risk=False):
    listing = Listing(id="r1", price=60000, lat=28.5, lng=-81.4,
                      address="1 Main St, Orlando, FL 32801",
                      rent_estimate=rent, rent_source="rentcast_rent_avm",
                      rent_comps_count=8)
    return ViabilityResult(
        listing=listing,
        arv=400000.0,
        land_cost=60000.0,
        construction_cost=280000.0,
        soft_cost=28000.0,
        purchase_closing_cost=1200.0,
        contingency_cost=19600.0,
        carrying_cost=30600.0,
        selling_cost=28000.0,
        total_cost=447400.0,
        profit=-47400.0,
        margin=-0.1185,
        land_to_arv=0.15,
        land_to_total_investment=0.134,
        is_viable=False,
        flood_high_risk=flood_high_risk,
    )


def _cfg(**overrides):
    rental = {
        "enabled": True,
        "vacancy_pct": 0.08,
        "property_tax_pct": 0.011,
        "insurance_annual": 2800,
        "hoa_monthly": 0,
        "maintenance_pct": 0.08,
        "management_pct": 0.08,
        "reserves_pct": 0.05,
        "min_dscr_warn": 1.2,
        "financing": {"down_payment_pct": 0.25, "interest_rate": 0.07, "amort_years": 30},
    }
    rental.update(overrides)
    return Config(raw={"rental": rental,
                       "red_flags": {"flood": {"insurance_surcharge_annual": 5000}}})


def test_debt_service_matches_price_table():
    # US$ 300k, 7% a.a., 30 anos → ~US$ 1.995,91/mês
    annual = _annual_debt_service(300000, 0.07, 30)
    assert annual == pytest.approx(1995.91 * 12, rel=1e-3)


def test_rental_analysis_computes_noi_cap_dscr_and_flags_low_dscr():
    result = _result(rent=2400.0)
    apply_rental_analysis(result, _cfg())

    basis = 447400.0 - 28000.0  # total_cost - selling_cost
    gross = 2400.0 * 12
    effective = gross * 0.92
    noi_expected = (effective - 0.011 * 400000.0 - 2800
                    - (0.08 + 0.08 + 0.05) * effective)
    assert result.rent_monthly == 2400.0
    assert result.noi_annual == pytest.approx(noi_expected)
    assert result.cap_rate == pytest.approx(noi_expected / basis)
    assert result.dscr is not None and result.dscr < 1.2
    assert any("DSCR" in flag for flag in result.risk_flags)
    assert any("renda (buy & hold)" in reason for reason in result.reasons)


def test_rental_analysis_adds_flood_surcharge_to_insurance():
    base = _result(rent=2400.0)
    flooded = _result(rent=2400.0, flood_high_risk=True)
    apply_rental_analysis(base, _cfg())
    apply_rental_analysis(flooded, _cfg())

    assert flooded.noi_annual == pytest.approx(base.noi_annual - 5000)


def test_rental_analysis_skips_without_rent_or_when_disabled():
    no_rent = _result(rent=None)
    apply_rental_analysis(no_rent, _cfg())
    assert no_rent.noi_annual is None

    disabled = _result(rent=2400.0)
    apply_rental_analysis(disabled, _cfg(enabled=False))
    assert disabled.noi_annual is None
