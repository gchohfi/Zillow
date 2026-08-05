"""Grava as oportunidades viáveis numa planilha CSV (acrescentando)."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from .config import Config
from .models import ViabilityResult

_DEVELOPMENT_COLUMNS = [
    "cadastral_use",
    "cadastral_use_code",
    "cadastral_use_source",
    "cadastral_use_status",
    "development_profile",
    "gross_acres",
    "estimated_net_developable_acres",
    "net_developable_pct",
    "net_estimate_confidence",
    "due_diligence_status",
    "due_diligence_completion_pct",
    "due_diligence_recommendation",
    "evidence_status",
    "pending_confirmations",
    "entitlement_stage",
    "rules_as_of",
    "parcel_id",
    "owner_name",
    "jurisdiction",
    "future_land_use",
    "electric_utility",
    "water_utility",
    "sewer_utility",
    "access_authority",
    "environmental_authority",
    "sources_consulted",
    "net_area_scenarios",
    "price_per_net_acre",
]

_SEARCH_SPEC_COLUMNS = [
    "search_spec_name",
    "search_spec_status",
    "search_spec_score",
    "search_spec_region",
    "search_spec_reasons",
    "search_spec_target_land_min",
    "search_spec_target_land_max",
    "search_spec_target_construction_per_sqft",
    "search_spec_target_resale_per_sqft",
    "search_spec_target_exit_price",
    "search_spec_cycle_months",
    "search_spec_target_irr_annual",
]

_COLUMNS = [
    "found_at",
    "review_status",
    "review_reason",
    "tier",
    "zip_code",
    "county",
    "market_priority",
    "market_region",
    "market_score",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    *_SEARCH_SPEC_COLUMNS,
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
    *_DEVELOPMENT_COLUMNS,
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
    "county",
    "market_priority",
    "market_region",
    "market_score",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    "reasons",
    *_SEARCH_SPEC_COLUMNS,
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
    *_DEVELOPMENT_COLUMNS,
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


def _ensure_header(
    csv_path: str,
    fieldnames: list[str],
    cfg: Config | None = None,
) -> bool:
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
            migrated = {field: row.get(field, "") for field in fieldnames}
            if cfg is not None and not migrated.get("county"):
                zip_map = cfg.raw.get("county_costs", {}).get("zip_to_county", {})
                migrated["county"] = str(zip_map.get(str(row.get("zip_code") or "")) or "")
            writer.writerow(migrated)
    return False


def _development_row(r: ViabilityResult) -> dict[str, object]:
    """Campos de triagem para áreas de desenvolvimento."""
    return {
        "cadastral_use": r.cadastral_use,
        "cadastral_use_code": r.cadastral_use_code,
        "cadastral_use_source": r.cadastral_use_source,
        "cadastral_use_status": r.cadastral_use_status,
        "development_profile": r.development_profile,
        "gross_acres": "" if r.gross_acres is None else f"{r.gross_acres:.2f}",
        "estimated_net_developable_acres": (
            "" if r.estimated_net_developable_acres is None
            else f"{r.estimated_net_developable_acres:.2f}"
        ),
        "net_developable_pct": (
            "" if r.net_developable_pct is None else f"{r.net_developable_pct:.3f}"
        ),
        "net_estimate_confidence": r.net_estimate_confidence,
        "due_diligence_status": r.due_diligence_status,
        "due_diligence_completion_pct": (
            "" if r.due_diligence_completion_pct is None
            else f"{r.due_diligence_completion_pct:.3f}"
        ),
        "due_diligence_recommendation": r.due_diligence_recommendation,
        "evidence_status": "; ".join(
            f"{key}={value}" for key, value in r.evidence_status.items()
        ),
        "pending_confirmations": "; ".join(r.pending_confirmations),
        "entitlement_stage": r.entitlement_stage,
        "rules_as_of": r.rules_as_of,
        "parcel_id": r.parcel_id,
        "owner_name": r.owner_name,
        "jurisdiction": r.jurisdiction,
        "future_land_use": r.future_land_use,
        "electric_utility": r.electric_utility,
        "water_utility": r.water_utility,
        "sewer_utility": r.sewer_utility,
        "access_authority": r.access_authority,
        "environmental_authority": r.environmental_authority,
        "sources_consulted": "; ".join(r.sources_consulted),
        "net_area_scenarios": "; ".join(
            f"{name}={value:.2f}" for name, value in r.net_area_scenarios.items()
        ),
        "price_per_net_acre": (
            "" if r.price_per_net_acre is None else round(r.price_per_net_acre)
        ),
    }


def _search_spec_row(r: ViabilityResult) -> dict[str, object]:
    """Campos auditáveis da lente adicional de busca."""
    return {
        "search_spec_name": r.search_spec_name,
        "search_spec_status": r.search_spec_status,
        "search_spec_score": (
            "" if r.search_spec_score is None else f"{r.search_spec_score:.1f}"
        ),
        "search_spec_region": r.search_spec_region,
        "search_spec_reasons": "; ".join(r.search_spec_reasons),
        "search_spec_target_land_min": (
            "" if r.search_spec_target_land_min is None else round(r.search_spec_target_land_min)
        ),
        "search_spec_target_land_max": (
            "" if r.search_spec_target_land_max is None else round(r.search_spec_target_land_max)
        ),
        "search_spec_target_construction_per_sqft": (
            "" if r.search_spec_target_construction_per_sqft is None
            else round(r.search_spec_target_construction_per_sqft)
        ),
        "search_spec_target_resale_per_sqft": (
            "" if r.search_spec_target_resale_per_sqft is None
            else round(r.search_spec_target_resale_per_sqft)
        ),
        "search_spec_target_exit_price": (
            "" if r.search_spec_target_exit_price is None
            else round(r.search_spec_target_exit_price)
        ),
        "search_spec_cycle_months": (
            "" if r.search_spec_cycle_months is None else r.search_spec_cycle_months
        ),
        "search_spec_target_irr_annual": (
            "" if r.search_spec_target_irr_annual is None
            else f"{r.search_spec_target_irr_annual:.4f}"
        ),
    }


def append_results(
    results: list[ViabilityResult],
    csv_path: str,
    cfg: Config | None = None,
) -> None:
    """Acrescenta as oportunidades viáveis ao CSV (cria com cabeçalho se novo)."""
    if not results:
        return

    is_new = _ensure_header(csv_path, _COLUMNS, cfg=cfg)
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
                "county": r.county,
                "market_priority": r.market_priority,
                "market_region": r.market_region,
                "market_score": f"{r.market_score:.1f}",
                "market_strategies": "; ".join(r.market_strategies),
                "risk_flags": "; ".join(r.risk_flags),
                "growth_score": "" if r.growth_score is None else f"{r.growth_score:.1f}",
                "growth_signals": "; ".join(r.growth_signals.get("summary", [])),
                **_search_spec_row(r),
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
                **_development_row(r),
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


def append_evaluations(
    results: list[ViabilityResult],
    csv_path: str,
    cfg: Config | None = None,
) -> None:
    """Append every newly evaluated listing to a CSV for dashboard/debugging."""
    if not results:
        return

    is_new = _ensure_header(csv_path, _EVALUATION_COLUMNS, cfg=cfg)
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
                "county": r.county,
                "market_priority": r.market_priority,
                "market_region": r.market_region,
                "market_score": f"{r.market_score:.1f}",
                "market_strategies": "; ".join(r.market_strategies),
                "risk_flags": "; ".join(r.risk_flags),
                "growth_score": "" if r.growth_score is None else f"{r.growth_score:.1f}",
                "growth_signals": "; ".join(r.growth_signals.get("summary", [])),
                "reasons": " | ".join(r.reasons),
                **_search_spec_row(r),
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
                **_development_row(r),
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
