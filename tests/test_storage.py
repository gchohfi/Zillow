"""Tests for listing deduplication memory."""

import sqlite3

from src.models import Listing
from src.storage import SeenStore


def test_seen_store_dedups_by_listing_id_and_price(tmp_path):
    store = SeenStore(str(tmp_path / "seen.db"))
    lot = Listing(id="abc", price=50_000, lat=28.5, lng=-81.3)
    same_price = Listing(id="abc", price=50_000, lat=28.5, lng=-81.3)
    new_price = Listing(id="abc", price=45_000, lat=28.5, lng=-81.3)

    assert store.is_new(lot)
    store.mark_seen(lot)
    assert not store.is_new(same_price)
    assert store.is_new(new_price)
    store.close()


def test_seen_store_dedups_by_normalized_address_across_sources(tmp_path):
    store = SeenStore(str(tmp_path / "seen.db"))
    first = Listing(
        id="rentcast-1",
        price=50_000,
        lat=28.5,
        lng=-81.3,
        address="123 Main Street, Orlando, FL 32801",
    )
    same_address = Listing(
        id="mls-2",
        price=50_000,
        lat=28.5,
        lng=-81.3,
        address="123 Main St Orlando Florida 32801",
    )
    new_price = Listing(
        id="mls-2",
        price=45_000,
        lat=28.5,
        lng=-81.3,
        address="123 Main St Orlando Florida 32801",
    )

    store.mark_seen(first)

    assert not store.is_new(same_address)
    assert store.is_new(new_price)
    store.close()


def test_seen_store_migrates_old_id_primary_key_schema(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE seen_listings (
            id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            price REAL,
            address TEXT,
            payload TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO seen_listings (id, first_seen, price, address, payload) VALUES (?, ?, ?, ?, ?)",
        ("abc", "2026-06-29T00:00:00+00:00", 50_000, "Old", "{}"),
    )
    conn.commit()
    conn.close()

    store = SeenStore(str(db_path))
    assert not store.is_new(Listing(id="abc", price=50_000, lat=28.5, lng=-81.3))
    assert store.is_new(Listing(id="abc", price=45_000, lat=28.5, lng=-81.3))
    store.close()
