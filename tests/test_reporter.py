"""Regression tests for idempotent CSV outputs."""

import csv

from src.config import Config
from src.models import Listing
from src.reporter import append_evaluations, append_results
from src.viability import evaluate


def _result():
    cfg = Config.load()
    cfg.raw["costs"]["site_prep_cost"] = 0
    cfg.raw["costs"]["impact_fees"] = 0
    for tier in cfg.raw.get("tiers", []):
        tier.get("costs", {}).pop("site_prep_cost", None)
        tier.get("costs", {}).pop("impact_fees", None)
    listing = Listing(
        id="csv-retry",
        price=12_000,
        lat=28.5384,
        lng=-81.3789,
        address="CSV retry",
        zoning="residential",
        lot_size_sqft=8000,
    )
    return evaluate(listing, cfg)


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_opportunity_csv_retry_does_not_duplicate(tmp_path):
    path = tmp_path / "opportunities.csv"
    result = _result()

    append_results([result], str(path))
    append_results([result], str(path))

    assert len(_rows(path)) == 1


def test_evaluations_csv_retry_does_not_duplicate(tmp_path):
    path = tmp_path / "evaluations.csv"
    result = _result()

    append_evaluations([result], str(path))
    append_evaluations([result], str(path))

    assert len(_rows(path)) == 1
