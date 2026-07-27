"""Tests for the development due-diligence triage."""

import pytest

from src.config import Config
from src.due_diligence import assess_due_diligence
from src.models import Listing
from src.review import classify_review_status
from src.viability import evaluate


def _cfg() -> Config:
    return Config(raw={
        "build": {
            "living_area_sqft": 2_000,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {
            "soft_cost_pct": 0.10,
            "carrying_cost_pct": 0.06,
            "selling_cost_pct": 0.07,
        },
        "rules": {
            "target_margin": 0.18,
            "max_land_to_total_investment_pct": 0.27,
            "require_residential_zoning": True,
            "require_known_zoning": True,
        },
        "due_diligence": {
            "enabled": True,
            "apply_to_min_lot_size_sqft": 43_560,
            "rules_as_of": "2026-07-20",
            "default_stormwater_reserve_pct": 0.12,
            "default_internal_infrastructure_pct": 0.08,
            "default_unknown_constraints_reserve_pct": 0.15,
            "max_total_deduction_pct": 0.90,
            "wetland_alert_pct": 0.20,
            "flood_alert_pct": 0.25,
            "hard_block_zoning_hints": ["conservation only"],
        },
        "radar": {"enabled": True},
        "development": {
            "enabled": True,
            "min_lot_size_sqft": 2 * 43_560,
            "max_price_per_acre": 0,
            "min_confirmed_net_acres": 1,
            "hard_blocked_zoning_hints": ["conservation only"],
        },
        "county_costs": {
            "counties": {"orange": {}},
            "zip_to_county": {"32801": "orange"},
        },
    })


def _assess(*, zoning=None, raw=None):
    listing = Listing(
        id="development",
        price=800_000,
        lat=28.54,
        lng=-81.38,
        address="Orlando, FL 32801",
        lot_size_sqft=5 * 43_560,
        zoning=zoning,
        source="listing",
        raw=raw or {},
    )
    result = evaluate(listing, _cfg())
    assess_due_diligence(result, _cfg())
    return result


def test_missing_data_stays_unconfirmed_and_uses_low_confidence_scenarios():
    result = _assess()
    classify_review_status(result, _cfg())

    assert result.gross_acres == pytest.approx(5)
    assert result.estimated_net_developable_acres == pytest.approx(4)
    assert result.net_area_scenarios == pytest.approx({
        "conservador": 3.25,
        "provavel": 4,
        "agressivo": 4.5,
    })
    assert result.net_estimate_confidence == "baixa"
    assert result.evidence_status["wetlands"] == "nao_confirmado"
    assert result.due_diligence_recommendation == "hold"
    assert result.review_status == "radar_desenvolvimento"
    assert "wetlands/delimitação" in result.pending_confirmations


def test_gis_percentages_reduce_net_area_and_create_alerts():
    result = _assess(
        zoning="agricultural",
        raw={"_parcel_data": {"wetlands_pct": 25, "floodplain_pct": 30}},
    )

    assert result.estimated_net_developable_acres == pytest.approx(1.25)
    assert result.evidence_status["wetlands"] == "alerta"
    assert result.evidence_status["flood"] == "alerta"
    assert result.due_diligence_recommendation == "avancar_com_condicoes"


def test_low_risk_fema_zone_is_indicative_not_alert():
    result = _assess(zoning="agricultural")
    result.reasons.append("✓ FEMA flood zone X")
    assess_due_diligence(result, _cfg())

    assert result.evidence_status["flood"] == "indicativo"


def test_document_flags_promote_evidence_to_confirmed_without_invention():
    result = _assess(
        zoning="PD",
        raw={"_parcel_data": {
            "future_land_use": "Activity Center Mixed Use",
            "future_land_use_confirmed": True,
            "zoning_confirmed": True,
            "wetlands_pct": 0,
            "wetlands_formal": True,
            "utility_capacity": "capacity letter on file",
            "utility_availability_letter": True,
            "legal_access": "recorded access",
            "legal_access_confirmed": True,
            "entitlement_stage": "approved development plan",
            "entitlements_confirmed": True,
            "net_developable_acres": 3.2,
            "net_developable_confirmed": True,
        }},
    )

    assert result.estimated_net_developable_acres == pytest.approx(3.2)
    assert result.net_estimate_confidence == "alta"
    assert result.evidence_status["wetlands"] == "confirmado"
    assert result.evidence_status["utilities"] == "confirmado"
    assert result.price_per_net_acre == pytest.approx(250_000)


def test_explicit_hard_zoning_block_recommends_discard():
    result = _assess(zoning="conservation only")
    classify_review_status(result, _cfg())

    assert result.due_diligence_status == "bloqueio"
    assert result.due_diligence_recommendation == "descartar"
    assert result.evidence_status["zoning"] == "bloqueio"
    assert result.review_status == "reprovado"
