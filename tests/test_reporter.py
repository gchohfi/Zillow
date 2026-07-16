"""Tests for CSV reporting."""

import csv

from src.models import Listing, ViabilityResult
from src.reporter import append_evaluations, append_results


def _result() -> ViabilityResult:
    listing = Listing(
        id="lot-1",
        price=54_900,
        lat=28.262,
        lng=-81.618,
        address="121 Central Ave, Davenport, FL 33896",
        distance_km=36.2,
        zoning="residential",
        url="https://example.com/lot-1",
    )
    return ViabilityResult(
        listing=listing,
        arv=726_000,
        land_cost=54_900,
        construction_cost=363_000,
        soft_cost=36_300,
        purchase_closing_cost=1_098,
        contingency_cost=25_410,
        carrying_cost=37_611,
        selling_cost=50_820,
        total_cost=569_139,
        profit=156_861,
        margin=0.216,
        land_to_arv=0.076,
        land_to_total_investment=0.096,
        is_viable=True,
        tier="Medio padrao",
        reasons=["ok"],
        zip_code="33896",
        market_region="Kissimmee",
        market_priority="Alta",
        market_score=7.5,
        market_strategies=["SFR"],
        risk_flags=["checar HOA"],
        review_status="viavel",
        review_reason="passou nos filtros automaticos",
        growth_score=8.1,
        growth_signals={"summary": ["6 escolas em 3 km"]},
    )


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_append_csvs_create_parent_directories_and_share_core_fields(tmp_path):
    result = _result()
    opportunities_path = tmp_path / "nested" / "opportunities.csv"
    evaluations_path = tmp_path / "nested" / "audit" / "evaluations.csv"

    append_results([result], str(opportunities_path))
    append_evaluations([result], str(evaluations_path))

    opportunity = _rows(opportunities_path)[0]
    evaluation = _rows(evaluations_path)[0]

    for field in ("id", "address", "market_score", "growth_score", "profit", "url"):
        assert opportunity[field] == evaluation[field]
    assert evaluation["is_viable"] == "yes"
    assert evaluation["reasons"] == "ok"
