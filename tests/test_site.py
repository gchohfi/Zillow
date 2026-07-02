"""Tests for the static dashboard generator."""

import csv
import json
import re
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)
RECENT = NOW.isoformat(timespec="seconds")
YESTERDAY = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=90)).isoformat(timespec="seconds")

from src.config import Config
from src.site import build_payload, generate_site


def _cfg(tmp_path, period_days=30):
    return Config(raw={
        "output": {
            "csv_path": str(tmp_path / "opportunities.csv"),
            "evaluations_csv_path": str(tmp_path / "evaluations.csv"),
        },
        "site": {"dir": str(tmp_path / "site"), "period_days": period_days},
    })


def _write_evaluations(tmp_path, rows):
    fields = [
        "found_at", "is_viable", "review_status", "review_reason", "tier",
        "zip_code", "market_priority", "market_region", "market_strategies",
        "risk_flags", "reasons", "id", "address", "normalized_address",
        "lat", "lng", "distance_km", "land_price", "arv", "arv_source",
        "arv_comps_count", "arv_confidence", "total_cost",
        "purchase_closing_cost", "contingency_cost", "profit", "margin",
        "land_to_total_investment", "land_to_arv", "zoning", "url",
    ]
    with open(tmp_path / "evaluations.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def test_generate_site_without_data_still_writes_page(tmp_path):
    index = generate_site(_cfg(tmp_path))
    assert index.exists()
    assert "Orlando Land Detector" in index.read_text(encoding="utf-8")


def test_build_payload_reads_evaluations_and_parses_numbers(tmp_path):
    _write_evaluations(tmp_path, [
        {
            "found_at": RECENT,
            "is_viable": "yes",
            "review_status": "viavel",
            "address": "123 Main St, Orlando, FL 32801",
            "lat": "28.5", "lng": "-81.3",
            "land_price": "45000", "arv": "420000",
            "profit": "80000", "margin": "0.190",
        },
        {
            "found_at": YESTERDAY,
            "is_viable": "no",
            "review_status": "radar_zoneamento_pendente",
            "review_reason": "numeros bons; falta confirmar zoneamento",
            "address": "Lot 9, Clermont, FL 34711",
            "land_price": "38000", "arv": "310000",
            "profit": "60000", "margin": "0.194",
        },
    ])

    payload = build_payload(_cfg(tmp_path))
    assert payload["total_rows"] == 2
    assert payload["source"] == "evaluations"
    # Mais recente primeiro.
    assert payload["rows"][0]["address"].startswith("123 Main")
    assert payload["rows"][0]["margin"] == 0.19
    assert payload["rows"][1]["review_status"] == "radar_zoneamento_pendente"


def test_generate_site_embeds_data_and_copies_csvs(tmp_path):
    _write_evaluations(tmp_path, [{
        "found_at": RECENT,
        "is_viable": "yes",
        "review_status": "viavel",
        "address": "123 Main St, Orlando, FL 32801",
        "land_price": "45000",
    }])
    (tmp_path / "opportunities.csv").write_text("found_at\n", encoding="utf-8")

    index = generate_site(_cfg(tmp_path))
    html = index.read_text(encoding="utf-8")

    match = re.search(r"const DATA = (\{.*?\});\n", html, re.DOTALL)
    assert match, "payload JSON deve estar embutido no HTML"
    data = json.loads(match.group(1))
    assert data["rows"][0]["address"] == "123 Main St, Orlando, FL 32801"

    assert (index.parent / "evaluations.csv").exists()
    assert (index.parent / "opportunities.csv").exists()


def test_build_payload_filters_by_period(tmp_path):
    _write_evaluations(tmp_path, [
        {"found_at": RECENT, "review_status": "viavel", "address": "Nova"},
        {"found_at": OLD, "review_status": "viavel", "address": "Antiga"},
    ])
    payload = build_payload(_cfg(tmp_path, period_days=30))
    addresses = [row["address"] for row in payload["rows"]]
    assert "Nova" in addresses
    assert "Antiga" not in addresses
