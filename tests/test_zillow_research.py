"""Tests for the official ZIP-level Zillow Research integration."""

import json
import sqlite3

from src.zillow_research import ZHVI_ZIP_URL, ZillowResearchCache, parse_zhvi_csv


def test_stable_official_url_is_not_pinned_to_a_month():
    assert "Zip_zhvi" in ZHVI_ZIP_URL
    assert "2025-" not in ZHVI_ZIP_URL
    assert "2026-" not in ZHVI_ZIP_URL


def test_parse_zhvi_uses_latest_period_and_changes():
    dates = [f"2025-{month:02d}-28" for month in range(1, 13)] + ["2026-01-31"]
    values = [str(300_000 + month * 2_500) for month in range(13)]
    csv_text = (
        "RegionID,SizeRank,RegionName,RegionType,StateName," + ",".join(dates) + "\n"
        "1,1,32801,zip,FL," + ",".join(values) + "\n"
        "2,2,99999,zip,FL," + ",".join(["100000"] * 13) + "\n"
    )
    parsed = parse_zhvi_csv(csv_text, {"32801"})
    assert set(parsed) == {"32801"}
    assert parsed["32801"]["zhvi_latest"] == 330_000
    assert parsed["32801"]["zhvi_period"] == "2026-01"
    assert parsed["32801"]["zhvi_12m_pct"] == 0.1


def test_cache_migrates_old_zip_only_primary_key(tmp_path):
    db_path = tmp_path / "signals.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE zillow_research ("
        "zip TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, "
        "dataset TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO zillow_research VALUES (?, ?, ?, ?)",
        ("32801", "2099-01-01T00:00:00+00:00", "zhvi", json.dumps({"value": 1})),
    )
    connection.commit()
    connection.close()

    cache = ZillowResearchCache(str(db_path))
    info = cache.conn.execute("PRAGMA table_info(zillow_research)").fetchall()
    primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    assert primary_key == ["zip", "dataset"]
    cache.put("32801", "market_temp", {"value": 2})
    assert cache.get("32801", "zhvi", 36500) == {"value": 1}
    assert cache.get("32801", "market_temp", 36500) == {"value": 2}
    cache.close()
