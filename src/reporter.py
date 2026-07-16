"""Grava as oportunidades viáveis numa planilha CSV (acrescentando)."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

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
    "id",
    "address",
    "normalized_address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "lot_size_sqft",
    "lot_size_acres",
    "price_per_acre",
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
    "rent_monthly",
    "noi_annual",
    "cap_rate",
    "dscr",
    "cash_on_cash",
    "sensitivity_top",
    "flood_zone",
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
    "reasons",
    "id",
    "address",
    "normalized_address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "lot_size_sqft",
    "lot_size_acres",
    "price_per_acre",
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
    "rent_monthly",
    "noi_annual",
    "cap_rate",
    "dscr",
    "cash_on_cash",
    "sensitivity_top",
    "flood_zone",
    "land_to_total_investment",
    "land_to_arv",
    "zoning",
    "url",
]


def _sensitivity_summary(r: ViabilityResult, top: int = 3) -> str:
    """Choques que mais destroem a margem, em string compacta para o CSV."""
    shocks = [s for s in r.sensitivity if s.get("delta_pp", 0) > 0][:top]
    return "; ".join(
        f"{s['label']}: margem {s['margin']:.1%} (-{s['delta_pp']:.1f}pp)" for s in shocks
    )


def _ensure_header(csv_path: str, fieldnames: list[str]) -> bool:
    """Return True when a new header must be written; migrate old headers."""
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
            L = r.listing
            writer.writerow({
                "found_at": now,
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
                "id": L.id,
                "address": L.address,
                "normalized_address": L.normalized_address,
                "lat": L.lat,
                "lng": L.lng,
                "distance_km": round(L.distance_km, 1) if L.distance_km is not None else "",
                "land_price": round(r.land_cost),
                "lot_size_sqft": "" if L.lot_size_sqft is None else round(L.lot_size_sqft),
                "lot_size_acres": (
                    "" if L.lot_size_sqft is None else f"{L.lot_size_sqft / 43_560:.2f}"
                ),
                "price_per_acre": (
                    "" if not L.lot_size_sqft
                    else round(r.land_cost / (L.lot_size_sqft / 43_560))
                ),
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
                "rent_monthly": "" if r.rent_monthly is None else round(r.rent_monthly),
                "noi_annual": "" if r.noi_annual is None else round(r.noi_annual),
                "cap_rate": "" if r.cap_rate is None else f"{r.cap_rate:.4f}",
                "dscr": "" if r.dscr is None else f"{r.dscr:.2f}",
                "cash_on_cash": "" if r.cash_on_cash is None else f"{r.cash_on_cash:.4f}",
                "sensitivity_top": _sensitivity_summary(r),
                "flood_zone": r.flood_zone or "",
                "land_to_total_investment": f"{r.land_to_total_investment:.3f}",
                "land_to_arv": f"{r.land_to_arv:.3f}",
                "zoning": L.zoning or "",
                "url": L.url,
            })
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
            L = r.listing
            writer.writerow({
                "found_at": now,
                "is_viable": "yes" if r.is_viable else "no",
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
                "reasons": " | ".join(r.reasons),
                "id": L.id,
                "address": L.address,
                "normalized_address": L.normalized_address,
                "lat": L.lat,
                "lng": L.lng,
                "distance_km": round(L.distance_km, 1) if L.distance_km is not None else "",
                "land_price": round(r.land_cost),
                "lot_size_sqft": "" if L.lot_size_sqft is None else round(L.lot_size_sqft),
                "lot_size_acres": (
                    "" if L.lot_size_sqft is None else f"{L.lot_size_sqft / 43_560:.2f}"
                ),
                "price_per_acre": (
                    "" if not L.lot_size_sqft
                    else round(r.land_cost / (L.lot_size_sqft / 43_560))
                ),
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
                "rent_monthly": "" if r.rent_monthly is None else round(r.rent_monthly),
                "noi_annual": "" if r.noi_annual is None else round(r.noi_annual),
                "cap_rate": "" if r.cap_rate is None else f"{r.cap_rate:.4f}",
                "dscr": "" if r.dscr is None else f"{r.dscr:.2f}",
                "cash_on_cash": "" if r.cash_on_cash is None else f"{r.cash_on_cash:.4f}",
                "sensitivity_top": _sensitivity_summary(r),
                "flood_zone": r.flood_zone or "",
                "land_to_total_investment": f"{r.land_to_total_investment:.3f}",
                "land_to_arv": f"{r.land_to_arv:.3f}",
                "zoning": L.zoning or "",
                "url": L.url,
            })
    print(f"[csv] {len(results)} avaliação(ões) acrescentada(s) em {csv_path}")
