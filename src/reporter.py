"""Grava as oportunidades viáveis numa planilha CSV (acrescentando)."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import ViabilityResult

_COLUMNS = [
    "found_at",
    "review_status",
    "review_reason",
    "tier",
    "zip_code",
    "market_priority",
    "market_region",
    "market_score",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    "appreciation_score",
    "appreciation_label",
    "regional_appreciation_score",
    "property_potential_score",
    "county_projection_growth_pct",
    "max_supported_land_price",
    "asking_premium_to_supported",
    "appreciation_factors",
    "id",
    "address",
    "normalized_address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "arv",
    "arv_source",
    "arv_comps_count",
    "arv_confidence",
    "total_cost",
    "purchase_closing_cost",
    "contingency_cost",
    "site_prep_cost",
    "impact_fees",
    "profit",
    "margin",
    "profit_stress",
    "margin_stress",
    "land_to_total_investment",
    "land_to_arv",
    "zoning",
    "url",
]

_EVALUATION_COLUMNS = [
    "found_at",
    "is_viable",
    "review_status",
    "review_reason",
    "tier",
    "zip_code",
    "market_priority",
    "market_region",
    "market_score",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    "appreciation_score",
    "appreciation_label",
    "regional_appreciation_score",
    "property_potential_score",
    "county_projection_growth_pct",
    "max_supported_land_price",
    "asking_premium_to_supported",
    "appreciation_factors",
    "reasons",
    "id",
    "address",
    "normalized_address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "arv",
    "arv_source",
    "arv_comps_count",
    "arv_confidence",
    "total_cost",
    "purchase_closing_cost",
    "contingency_cost",
    "site_prep_cost",
    "impact_fees",
    "profit",
    "margin",
    "profit_stress",
    "margin_stress",
    "land_to_total_investment",
    "land_to_arv",
    "zoning",
    "url",
]


def _ensure_header(csv_path: str, fieldnames: list[str]) -> bool:
    """Return True when a new header must be written; migrate old headers."""
    parent = Path(csv_path).expanduser().parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return True

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        old_fields = reader.fieldnames or []
        if old_fields == fieldnames:
            return False
        rows = list(reader)

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return False


def _base_row(r: ViabilityResult, found_at: str) -> dict[str, object]:
    """Campos compartilhados entre o CSV final e o CSV de auditoria."""
    listing = r.listing
    return {
        "found_at": found_at,
        "review_status": r.review_status or ("viavel" if r.is_viable else "reprovado"),
        "review_reason": r.review_reason,
        "tier": r.tier,
        "zip_code": r.zip_code or "",
        "market_priority": r.market_priority,
        "market_region": r.market_region,
        "market_score": f"{r.market_score:.1f}",
        "market_strategies": "; ".join(r.market_strategies),
        "risk_flags": "; ".join(r.risk_flags),
        "growth_score": "" if r.growth_score is None else f"{r.growth_score:.1f}",
        "growth_signals": "; ".join(r.growth_signals.get("summary", [])),
        "appreciation_score": "" if r.appreciation_score is None else f"{r.appreciation_score:.1f}",
        "appreciation_label": r.appreciation_label,
        "regional_appreciation_score": (
            "" if r.regional_appreciation_score is None else f"{r.regional_appreciation_score:.1f}"
        ),
        "property_potential_score": (
            "" if r.property_potential_score is None else f"{r.property_potential_score:.1f}"
        ),
        "county_projection_growth_pct": (
            "" if r.county_projection_growth_pct is None else f"{r.county_projection_growth_pct:.3f}"
        ),
        "max_supported_land_price": round(r.max_supported_land_price),
        "asking_premium_to_supported": (
            "" if r.asking_premium_to_supported is None else f"{r.asking_premium_to_supported:.3f}"
        ),
        "appreciation_factors": "; ".join(r.appreciation_factors),
        "id": listing.id,
        "address": listing.address,
        "normalized_address": listing.normalized_address,
        "lat": listing.lat,
        "lng": listing.lng,
        "distance_km": (
            round(listing.distance_km, 1) if listing.distance_km is not None else ""
        ),
        "land_price": round(r.land_cost),
        "arv": round(r.arv),
        "arv_source": r.arv_source,
        "arv_comps_count": r.arv_comps_count or "",
        "arv_confidence": r.arv_confidence or "",
        "total_cost": round(r.total_cost),
        "purchase_closing_cost": round(r.purchase_closing_cost),
        "contingency_cost": round(r.contingency_cost),
        "site_prep_cost": round(r.site_prep_cost),
        "impact_fees": round(r.impact_fees),
        "profit": round(r.profit),
        "margin": f"{r.margin:.3f}",
        "profit_stress": "" if r.profit_stress is None else round(r.profit_stress),
        "margin_stress": "" if r.margin_stress is None else f"{r.margin_stress:.3f}",
        "land_to_total_investment": f"{r.land_to_total_investment:.3f}",
        "land_to_arv": f"{r.land_to_arv:.3f}",
        "zoning": listing.zoning or "",
        "url": listing.url,
    }


def append_results(results: list[ViabilityResult], csv_path: str) -> None:
    """Acrescenta as oportunidades viáveis ao CSV (cria com cabeçalho se novo)."""
    if not results:
        return

    is_new = _ensure_header(csv_path, _COLUMNS)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        if is_new:
            writer.writeheader()
        for r in results:
            writer.writerow(_base_row(r, now))
    print(f"[csv] {len(results)} oportunidade(s) acrescentada(s) em {csv_path}")


def append_evaluations(results: list[ViabilityResult], csv_path: str) -> None:
    """Append every newly evaluated listing to a CSV for dashboard/debugging."""
    if not results:
        return

    is_new = _ensure_header(csv_path, _EVALUATION_COLUMNS)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_EVALUATION_COLUMNS)
        if is_new:
            writer.writeheader()
        for r in results:
            row = {
                "is_viable": "yes" if r.is_viable else "no",
                "reasons": " | ".join(r.reasons),
            }
            row.update(_base_row(r, now))
            writer.writerow(row)
    print(f"[csv] {len(results)} avaliação(ões) acrescentada(s) em {csv_path}")
