"""Tests for the daily summary message."""

import csv
from datetime import datetime, timedelta, timezone

from src.config import Config
from src.summary import build_message

NOW = datetime.now(timezone.utc)
RECENT = NOW.isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=3)).isoformat(timespec="seconds")


def _cfg(tmp_path):
    return Config(raw={
        "output": {
            "csv_path": str(tmp_path / "opportunities.csv"),
            "evaluations_csv_path": str(tmp_path / "evaluations.csv"),
        },
        "summary": {"period_hours": 24},
    })


def _write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def test_summary_sends_sign_of_life_even_without_data(tmp_path):
    subject, body = build_message(_cfg(tmp_path))

    assert "0 oportunidade(s)" in subject
    assert "Terrenos novos avaliados: 0" in body
    assert "sistema de pé" in body


def test_summary_counts_evaluations_radar_and_lists_top_opportunities(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://example.github.io/Zillow/")
    _write_csv(tmp_path / "evaluations.csv", [
        {"found_at": RECENT, "review_status": "viavel", "address": "1 Main St"},
        {"found_at": RECENT, "review_status": "radar_zoneamento_pendente", "address": "2 Main St"},
        {"found_at": RECENT, "review_status": "reprovada", "address": "3 Main St"},
        {"found_at": OLD, "review_status": "viavel", "address": "4 Main St"},
    ], ["found_at", "review_status", "address"])
    _write_csv(tmp_path / "opportunities.csv", [
        {"found_at": RECENT, "address": "1 Main St", "land_price": "50000",
         "profit": "80000", "margin": "0.21", "url": "https://ex.com/1"},
    ], ["found_at", "address", "land_price", "profit", "margin", "url"])

    subject, body = build_message(_cfg(tmp_path))

    assert "1 oportunidade(s)" in subject
    assert "Terrenos novos avaliados: 3" in body
    assert "Oportunidades viáveis: 1" in body
    assert "No radar (revisão manual): 1" in body
    assert "1 Main St" in body and "margem 21.0%" in body
    assert "Dashboard: https://example.github.io/Zillow/" in body
