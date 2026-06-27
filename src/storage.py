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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                id          TEXT PRIMARY KEY,
                first_seen  TEXT NOT NULL,
                price       REAL,
                address     TEXT,
                payload     TEXT
            )
            """
        )
        self.conn.commit()

    def is_new(self, listing_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_listings WHERE id = ?", (listing_id,)
        )
        return cur.fetchone() is None

    def mark_seen(self, listing: Listing) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_listings (id, first_seen, price, address, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
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
