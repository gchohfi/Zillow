"""Grava as oportunidades viáveis numa planilha CSV (acrescentando)."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from .models import ViabilityResult

_COLUMNS = [
    "found_at",
    "tier",
    "id",
    "address",
    "distance_km",
    "land_price",
    "arv",
    "total_cost",
    "profit",
    "margin",
    "land_to_arv",
    "zoning",
    "url",
]


def append_results(results: list[ViabilityResult], csv_path: str) -> None:
    """Acrescenta as oportunidades viáveis ao CSV (cria com cabeçalho se novo)."""
    if not results:
        return

    is_new = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        if is_new:
            writer.writeheader()
        for r in results:
            L = r.listing
            writer.writerow({
                "found_at": now,
                "tier": r.tier,
                "id": L.id,
                "address": L.address,
                "distance_km": round(L.distance_km, 1) if L.distance_km is not None else "",
                "land_price": round(r.land_cost),
                "arv": round(r.arv),
                "total_cost": round(r.total_cost),
                "profit": round(r.profit),
                "margin": f"{r.margin:.3f}",
                "land_to_arv": f"{r.land_to_arv:.3f}",
                "zoning": L.zoning or "",
                "url": L.url,
            })
    print(f"[csv] {len(results)} oportunidade(s) acrescentada(s) em {csv_path}")
