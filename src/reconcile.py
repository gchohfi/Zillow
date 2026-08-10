"""Reconciliação somente leitura entre chaves vistas e avaliações persistidas."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from .address_normalizer import has_address_locator, normalize_address


def _price_key(value: object) -> str:
    try:
        return str(round(float(value)))
    except (TypeError, ValueError):
        return "unknown"


def _csv_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            price = _price_key(row.get("land_price"))
            keys.add(f"id:{row.get('id', '')}:{price}")
            address = row.get("address", "")
            normalized = row.get("normalized_address") or (
                normalize_address(address) if has_address_locator(address) else ""
            )
            if normalized:
                keys.add(f"addr:{normalized}:{price}")
    return keys


def reconcile(db_path: str, evaluations_csv: str) -> dict:
    """Retorna lacunas sem escrever no SQLite ou no CSV."""
    db = Path(db_path).resolve()
    evaluations = Path(evaluations_csv).resolve()
    evaluated = _csv_keys(evaluations)
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(seen_listings)").fetchall()
        }
        normalized_expr = (
            "normalized_address" if "normalized_address" in columns else "NULL"
        )
        seen_key_expr = "seen_key" if "seen_key" in columns else "id"
        rows = conn.execute(
            f"""
            SELECT {seen_key_expr}, id, first_seen, price, address, {normalized_expr}
            FROM seen_listings
            ORDER BY first_seen, id
            """
        ).fetchall()
    finally:
        conn.close()

    missing = []
    for seen_key, listing_id, first_seen, price, address, normalized in rows:
        price_key = _price_key(price)
        normalized = normalized or (
            normalize_address(address or "") if has_address_locator(address) else ""
        )
        candidates = {str(seen_key), f"id:{listing_id}:{price_key}", f"{listing_id}:{price_key}"}
        if normalized:
            candidates.add(f"addr:{normalized}:{price_key}")
        if candidates.isdisjoint(evaluated):
            missing.append({
                "seen_key": seen_key,
                "id": listing_id,
                "price": price,
                "first_seen": first_seen,
            })
    return {
        "mode": "dry-run",
        "seen_count": len(rows),
        "missing_evaluation_count": len(missing),
        "missing": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lista chaves vistas sem avaliação; não altera nenhum arquivo."
    )
    parser.add_argument("--db-path", default="seen_listings.db")
    parser.add_argument("--evaluations-csv", default="evaluations.csv")
    args = parser.parse_args()
    print(json.dumps(reconcile(args.db_path, args.evaluations_csv), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
