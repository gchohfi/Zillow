"""Memória de listagens já vistas, em SQLite, para detectar o que é NOVO."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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
                payload     TEXT
            )
            """
        )
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
                payload     TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_listings (seen_key, id, first_seen, price, address, payload)
            SELECT
                id || ':' || COALESCE(printf('%.0f', price), 'unknown'),
                id,
                first_seen,
                price,
                address,
                payload
            FROM seen_listings_old
            """
        )
        self.conn.execute("DROP TABLE seen_listings_old")

    @staticmethod
    def key_for(listing: Listing) -> str:
        """Dedup key: same listing at a new price should alert again."""
        try:
            price = str(round(float(listing.price)))
        except (TypeError, ValueError):
            price = "unknown"
        return f"{listing.id}:{price}"

    def is_new(self, listing: Listing | str) -> bool:
        if isinstance(listing, Listing):
            key = self.key_for(listing)
            cur = self.conn.execute(
                "SELECT 1 FROM seen_listings WHERE seen_key = ?", (key,)
            )
            return cur.fetchone() is None
        cur = self.conn.execute("SELECT 1 FROM seen_listings WHERE id = ?", (listing,))
        return cur.fetchone() is None

    def mark_seen(self, listing: Listing) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_listings (seen_key, id, first_seen, price, address, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.key_for(listing),
                listing.id,
                datetime.now(timezone.utc).isoformat(),
                listing.price,
                listing.address,
                json.dumps(listing.raw, default=str),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
