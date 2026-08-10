"""Regression tests for idempotent CSV outputs."""

import csv

from src.config import Config
from src.models import Listing
from src.reporter import append_evaluations, append_results
from src.viability import evaluate


def _result(listing_id="csv-retry", address="123 Main Street, Orlando, FL 32801"):
    cfg = Config.load()
    cfg.raw["costs"]["site_prep_cost"] = 0
    cfg.raw["costs"]["impact_fees"] = 0
    for tier in cfg.raw.get("tiers", []):
        tier.get("costs", {}).pop("site_prep_cost", None)
        tier.get("costs", {}).pop("impact_fees", None)
    return evaluate(Listing(id=listing_id, price=12_000, lat=28.5384, lng=-81.3789,
                            address=address, zoning="residential", lot_size_sqft=8000), cfg)


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_csv_retries_and_normalized_duplicates_are_idempotent(tmp_path):
    evaluations = tmp_path / "evaluations.csv"
    opportunities = tmp_path / "opportunities.csv"
    first = _result()
    duplicate = _result("other-source", "123 Main St Orlando Florida 32801")

    append_evaluations([first, duplicate], str(evaluations))
    append_evaluations([first], str(evaluations))
    append_results([first, duplicate], str(opportunities))
    append_results([first], str(opportunities))

    assert len(_rows(evaluations)) == 1
    assert len(_rows(opportunities)) == 1
