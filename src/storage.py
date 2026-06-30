"""Memória de listagens já vistas, em SQLite, para detectar o que é NOVO."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .address_normalizer import address_fingerprint, normalize_address
from .models import Listing


class SeenStore:
    """Guarda os IDs de listagens já processadas."""

    def __init__(self, db_path: str = "seen_listings.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30)
        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._migrate_schema()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                seen_key    TEXT PRIMARY KEY,
                id          TEXT NOT NULL,
                first_seen  TEXT NOT NULL,
                price       REAL,
                address     TEXT,
                normalized_address TEXT,
                payload     TEXT
            )
            """
        )
        self._ensure_normalized_address_column()
        self._backfill_normalized_addresses()
        self.conn.commit()

    def _migrate_schema(self) -> None:
        cols = {
            row[1]: row
            for row in self.conn.execute("PRAGMA table_info(seen_listings)").fetchall()
        }
        if not cols or "seen_key" in cols:
            return

        self.conn.execute("ALTER TABLE seen_listings RENAME TO seen_listings_old")
        self.conn.execute(
            """
            CREATE TABLE seen_listings (
                seen_key    TEXT PRIMARY KEY,
                id          TEXT NOT NULL,
                first_seen  TEXT NOT NULL,
                price       REAL,
                address     TEXT,
                normalized_address TEXT,
                payload     TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_listings (
                seen_key, id, first_seen, price, address, normalized_address, payload
            )
            SELECT
                id || ':' || COALESCE(printf('%.0f', price), 'unknown'),
                id,
                first_seen,
                price,
                address,
                NULL,
                payload
            FROM seen_listings_old
            """
        )
        self.conn.execute("DROP TABLE seen_listings_old")

    def _ensure_normalized_address_column(self) -> None:
        cols = {
            row[1]: row
            for row in self.conn.execute("PRAGMA table_info(seen_listings)").fetchall()
        }
        if cols and "normalized_address" not in cols:
            self.conn.execute("ALTER TABLE seen_listings ADD COLUMN normalized_address TEXT")

    def _backfill_normalized_addresses(self) -> None:
        rows = self.conn.execute(
            """
            SELECT seen_key, address
            FROM seen_listings
            WHERE (normalized_address IS NULL OR normalized_address = '')
              AND address IS NOT NULL
              AND address != ''
            """
        ).fetchall()
        for seen_key, address in rows:
            normalized = normalize_address(address)
            if normalized:
                self.conn.execute(
                    "UPDATE seen_listings SET normalized_address = ? WHERE seen_key = ?",
                    (normalized, seen_key),
                )

    @staticmethod
    def _price_key(listing: Listing) -> str:
        try:
            return str(round(float(listing.price)))
        except (TypeError, ValueError):
            return "unknown"

    @classmethod
    def legacy_key_for(cls, listing: Listing) -> str:
        """Key used by earlier versions, kept for migration compatibility."""
        return f"{listing.id}:{cls._price_key(listing)}"

    @staticmethod
    def key_for(listing: Listing) -> str:
        """Dedup key: same listing at a new price should alert again."""
        price = SeenStore._price_key(listing)
        fingerprint = address_fingerprint(listing)
        if fingerprint:
            return f"addr:{fingerprint}:{price}"
        return f"id:{listing.id}:{price}"

    def is_new(self, listing: Listing | str) -> bool:
        if isinstance(listing, Listing):
            key = self.key_for(listing)
            cur = self.conn.execute(
                "SELECT 1 FROM seen_listings WHERE seen_key IN (?, ?)",
                (key, self.legacy_key_for(listing)),
            )
            if cur.fetchone() is not None:
                return False

            if listing.normalized_address:
                try:
                    price = round(float(listing.price))
                except (TypeError, ValueError):
                    price = None
                cur = self.conn.execute(
                    """
                    SELECT 1 FROM seen_listings
                    WHERE normalized_address = ?
                      AND (? IS NULL OR ROUND(price) = ?)
                    """,
                    (listing.normalized_address, price, price),
                )
                return cur.fetchone() is None

            return True
        cur = self.conn.execute("SELECT 1 FROM seen_listings WHERE id = ?", (listing,))
        return cur.fetchone() is None

    def mark_seen(self, listing: Listing) -> None:
        key = self.key_for(listing)
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_listings ("
            "seen_key, id, first_seen, price, address, normalized_address, payload"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                listing.id,
                datetime.now(timezone.utc).isoformat(),
                listing.price,
                listing.address,
                listing.normalized_address or normalize_address(listing.address),
                json.dumps(listing.raw, default=str),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
