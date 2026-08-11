"""ZHVI mensal por ZIP usando o CSV estável publicado pelo Zillow Research."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

ZHVI_ZIP_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)


class ZillowResearchCache:
    """Cache versionado por ``(zip, dataset)`` para evitar sobrescritas."""

    def __init__(self, db_path: str = "region_signals.db") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        existing = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zillow_research'"
        ).fetchone()
        if existing:
            info = self.conn.execute("PRAGMA table_info(zillow_research)").fetchall()
            primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
            if primary_key != ["zip", "dataset"]:
                self.conn.execute("ALTER TABLE zillow_research RENAME TO zillow_research_legacy")
                self._create_table()
                columns = {row[1] for row in info}
                if {"zip", "dataset", "fetched_at", "payload"}.issubset(columns):
                    self.conn.execute(
                        "INSERT OR REPLACE INTO zillow_research "
                        "(zip, dataset, fetched_at, payload) "
                        "SELECT zip, dataset, fetched_at, payload FROM zillow_research_legacy"
                    )
                self.conn.execute("DROP TABLE zillow_research_legacy")
                self.conn.commit()
                return
        self._create_table()
        self.conn.commit()

    def _create_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS zillow_research (
                zip TEXT NOT NULL,
                dataset TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (zip, dataset)
            )
            """
        )

    def get(self, zip_code: str, dataset: str, max_age_days: float) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM zillow_research WHERE zip = ? AND dataset = ?",
            (zip_code, dataset),
        ).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row[0])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > timedelta(days=max_age_days):
            return None
        try:
            payload = json.loads(row[1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def put(self, zip_code: str, dataset: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO zillow_research "
            "(zip, dataset, fetched_at, payload) VALUES (?, ?, ?, ?)",
            (
                zip_code,
                dataset,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(payload),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _date_columns(fieldnames: Iterable[str] | None) -> list[str]:
    columns: list[str] = []
    for name in fieldnames or []:
        try:
            datetime.strptime(name, "%Y-%m-%d")
        except ValueError:
            continue
        columns.append(name)
    return sorted(columns)


def parse_zhvi_csv(csv_text: str, target_zips: set[str]) -> dict[str, dict[str, Any]]:
    return _parse_reader(csv.DictReader(io.StringIO(csv_text)), target_zips)


def _parse_reader(
    reader: csv.DictReader,
    target_zips: set[str],
) -> dict[str, dict[str, Any]]:
    dates = _date_columns(reader.fieldnames)
    result: dict[str, dict[str, Any]] = {}
    for row in reader:
        zip_code = str(row.get("RegionName") or "").strip().zfill(5)
        if zip_code not in target_zips:
            continue
        values: list[tuple[str, float]] = []
        for date in dates:
            try:
                value = float(row.get(date) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                values.append((date, value))
        if not values:
            continue
        latest_date, latest = values[-1]
        year_ago = values[-13][1] if len(values) >= 13 else None
        three_months_ago = values[-4][1] if len(values) >= 4 else None
        result[zip_code] = {
            "zhvi_latest": latest,
            "zhvi_period": latest_date[:7],
            "zhvi_12m_pct": (latest - year_ago) / year_ago if year_ago else None,
            "zhvi_3m_pct": (
                (latest - three_months_ago) / three_months_ago
                if three_months_ago else None
            ),
        }
    return result


def refresh_zhvi(
    target_zips: set[str],
    *,
    url: str = ZHVI_ZIP_URL,
    timeout_seconds: float = 90,
) -> dict[str, dict[str, Any]]:
    """Lê o arquivo oficial em streaming; o URL estável sempre aponta ao mês atual."""
    response = requests.get(
        url,
        headers={"User-Agent": "orlando-land-detector/2.0"},
        timeout=timeout_seconds,
        stream=True,
    )
    response.raise_for_status()
    response.raw.decode_content = True
    wrapper = io.TextIOWrapper(response.raw, encoding="utf-8-sig", newline="")
    try:
        return _parse_reader(csv.DictReader(wrapper), target_zips)
    finally:
        wrapper.detach()
        response.close()


def get_zhvi_for_zip(
    zip_code: str,
    *,
    target_zips: set[str],
    db_path: str,
    max_age_days: float,
    url: str = ZHVI_ZIP_URL,
    timeout_seconds: float = 90,
) -> dict[str, Any] | None:
    cache = ZillowResearchCache(db_path)
    try:
        cached = cache.get(zip_code, "zhvi", max_age_days)
        if cached is not None:
            return cached
        fresh = refresh_zhvi(
            target_zips | {zip_code}, url=url, timeout_seconds=timeout_seconds
        )
        for target, payload in fresh.items():
            cache.put(target, "zhvi", payload)
        return fresh.get(zip_code)
    finally:
        cache.close()


def enrich_with_zhvi(signals: dict[str, Any], zhvi: dict[str, Any] | None) -> dict[str, Any]:
    if not zhvi:
        return signals
    signals.update({
        "zillow_zhvi": zhvi.get("zhvi_latest"),
        "zillow_zhvi_period": zhvi.get("zhvi_period"),
        "zillow_zhvi_12m": zhvi.get("zhvi_12m_pct"),
        "zillow_zhvi_3m": zhvi.get("zhvi_3m_pct"),
    })
    if zhvi.get("zhvi_latest"):
        signals.setdefault("summary", []).append(
            f"ZHVI US${zhvi['zhvi_latest']:,.0f} ({zhvi.get('zhvi_period', 'período desconhecido')})"
        )
    if zhvi.get("zhvi_12m_pct") is not None:
        signals.setdefault("summary", []).append(
            f"valorizacao ZHVI 12m {zhvi['zhvi_12m_pct']:+.1%}"
        )
    return signals
