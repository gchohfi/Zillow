"""Tests for Radar/manual-review classification."""

from src.config import Config
from src.models import Listing
from src.review import classify_review_status
from src.viability import evaluate


def _cfg() -> Config:
    return Config(raw={
        "search": {"center_lat": 28.5384, "center_lng": -81.3789, "radius_km": 80},
        "build": {
            "living_area_sqft": 2000,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {"soft_cost_pct": 0.10, "carrying_cost_pct": 0.06, "selling_cost_pct": 0.07},
        "rules": {
            "target_margin": 0.18,
            "max_land_price": 0,
            "max_land_to_total_investment_pct": 0.27,
            "require_residential_zoning": True,
            "require_known_zoning": True,
            "min_lot_size_sqft": 5000,
        },
        "radar": {
            "enabled": True,
            "include_financial_near_misses": True,
            "min_margin": 0.10,
            "include_unknown_zoning": True,
            "include_manual_review_segments": True,
            "include_high_flood_risk": True,
        },
        "market_strategy": {"default_priority": "fora", "default_score": 0, "zip_groups": []},
        "storage": {"db_path": ":memory:"},
    })


def test_unknown_zoning_with_good_numbers_becomes_radar():
    cfg = _cfg()
    lot = Listing(
        id="zoning-pending",
        price=95_000,
        lat=28.41,
        lng=-81.50,
        address="123 Main St, Orlando, FL",
        lot_size_sqft=8000,
        zoning=None,
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert not result.is_viable
    assert result.review_status == "radar_zoneamento_pendente"
    assert "zoneamento" in result.review_reason


def test_bad_numbers_do_not_become_radar_even_with_unknown_zoning():
    cfg = _cfg()
    lot = Listing(
        id="too-expensive",
        price=300_000,
        lat=28.41,
        lng=-81.50,
        lot_size_sqft=8000,
        zoning=None,
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert not result.is_viable
    assert result.review_status == "reprovado"
    assert result.review_reason == "nao passou nos filtros financeiros"


def test_positive_margin_near_target_becomes_radar():
    cfg = _cfg()
    lot = Listing(
        id="near-margin",
        price=125_000,
        lat=28.41,
        lng=-81.50,
        lot_size_sqft=8000,
        zoning="residential",
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert 0.10 <= result.margin < 0.18
    assert not result.is_viable
    assert result.review_status == "radar_margem_limite"
    assert "abaixo do alvo" in result.review_reason


def test_near_margin_still_rejects_commercial_zoning():
    cfg = _cfg()
    lot = Listing(
        id="near-margin-commercial",
        price=125_000,
        lat=28.41,
        lng=-81.50,
        lot_size_sqft=8000,
        zoning="commercial",
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert result.review_status == "reprovado"
    assert "bloqueio automatico" in result.review_reason


def test_manual_review_segment_with_good_numbers_becomes_radar():
    cfg = _cfg()
    cfg.raw["rules"]["require_known_zoning"] = False
    cfg.raw["tiers"] = [
        {
            "name": "alto_padrao",
            "label": "Alto padrão",
            "max_price": None,
            "rules": {"manual_review_only": True},
        }
    ]
    lot = Listing(
        id="manual",
        price=95_000,
        lat=28.41,
        lng=-81.50,
        lot_size_sqft=8000,
        zoning="residential",
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert not result.is_viable
    assert result.review_status == "radar_analise_manual"


def test_commercial_zoning_stays_rejected():
    cfg = _cfg()
    lot = Listing(
        id="commercial",
        price=95_000,
        lat=28.41,
        lng=-81.50,
        lot_size_sqft=8000,
        zoning="commercial",
    )

    result = evaluate(lot, cfg)
    classify_review_status(result, cfg)

    assert not result.is_viable
    assert result.review_status == "reprovado"
    assert "bloqueio automatico" in result.review_reason
