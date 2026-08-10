"""The reconciliation command is strictly read-only."""

import csv
import hashlib

from src.models import Listing
from src.reconcile import reconcile
from src.storage import SeenStore


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reconcile_reports_missing_without_mutating_inputs(tmp_path):
    db = tmp_path / "seen.db"
    evaluations = tmp_path / "evaluations.csv"
    store = SeenStore(str(db))
    store.mark_seen(Listing(id="evaluated", price=10_000, lat=1, lng=1, address="1 A St"))
    store.mark_seen(Listing(id="missing", price=20_000, lat=1, lng=1, address="2 B St"))
    store.close()
    with evaluations.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "land_price", "address"])
        writer.writeheader()
        writer.writerow({"id": "evaluated", "land_price": "10000", "address": "1 A St"})
    before = (_digest(db), _digest(evaluations))

    report = reconcile(str(db), str(evaluations))

    assert report["mode"] == "dry-run"
    assert report["missing_evaluation_count"] == 1
    assert report["missing"][0]["id"] == "missing"
    assert (_digest(db), _digest(evaluations)) == before
