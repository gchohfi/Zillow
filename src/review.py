"""Classifica resultados entre alerta final, Radar e reprovação."""

from __future__ import annotations

import re
import unicodedata

from .config import Config
from .models import ViabilityResult
from .viability import resolve_parameters


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _fatal_reasons(result: ViabilityResult) -> list[str]:
    return [reason for reason in result.reasons if reason.strip().startswith("✗")]


def _has_unknown_zoning(result: ViabilityResult) -> bool:
    return any("zoneamento desconhecido" in _plain(reason) for reason in result.reasons)


def _has_manual_review(result: ViabilityResult) -> bool:
    return any("analise manual" in _plain(reason) for reason in result.reasons)


def _has_high_flood_risk(result: ViabilityResult, cfg: Config) -> bool:
    flood_cfg = cfg.raw.get("red_flags", {}).get("flood", {})
    high_risk_zones = {
        str(zone).upper()
        for zone in flood_cfg.get("high_risk_zones", ["A", "AE", "AH", "AO", "AR", "A99", "V", "VE"])
    }
    for flag in result.risk_flags:
        plain = _plain(flag)
        if "fema flood zone" not in plain:
            continue
        upper = flag.upper()
        if "SFHA" in upper:
            return True
        zone_match = re.search(r"FEMA FLOOD ZONE\s+([A-Z0-9]+)", upper)
        if zone_match and zone_match.group(1) in high_risk_zones:
            return True
    return False


def _passes_numeric_filters(result: ViabilityResult, cfg: Config) -> bool:
    """Confirma que o que ficou pendente é diligência, não a matemática."""
    _, _, _, rules = resolve_parameters(result.listing, cfg)

    target_margin = float(rules["target_margin"])
    if result.margin < target_margin:
        return False

    max_land = float(rules["max_land_to_total_investment_pct"])
    if result.land_to_total_investment > max_land:
        return False

    max_land_price = float(rules.get("max_land_price") or 0)
    if max_land_price > 0 and result.land_cost > max_land_price:
        return False

    min_lot = float(rules.get("min_lot_size_sqft") or 0)
    if (
        min_lot > 0
        and result.listing.lot_size_sqft is not None
        and result.listing.lot_size_sqft < min_lot
    ):
        return False

    return True


def _is_development_candidate(result: ViabilityResult, cfg: Config) -> bool:
    """Identifica áreas grandes cuja tese não é construir apenas uma casa."""
    development = cfg.raw.get("development", {})
    if not development.get("enabled", False):
        return False

    lot_size = result.listing.lot_size_sqft
    min_lot_size = float(development.get("min_lot_size_sqft", 0) or 0)
    if lot_size is None or lot_size < min_lot_size:
        return False

    acres = lot_size / 43_560
    price_per_acre = result.land_cost / acres if acres else float("inf")
    max_price_per_acre = float(development.get("max_price_per_acre", 0) or 0)
    if max_price_per_acre > 0 and price_per_acre > max_price_per_acre:
        return False

    zoning = _plain(result.listing.zoning or "")
    blocked_hints = development.get(
        "blocked_zoning_hints", ["conservation", "wetland"]
    )
    return not any(
        _plain(str(hint)) in zoning for hint in blocked_hints if hint
    )


def classify_review_status(result: ViabilityResult, cfg: Config) -> None:
    """Seta o bucket de revisão usado por CSV, dashboard e WhatsApp."""
    if result.is_viable:
        result.review_status = "viavel"
        result.review_reason = "passou nos filtros automaticos"
        return

    radar_cfg = cfg.raw.get("radar", {})
    if not radar_cfg.get("enabled", False):
        result.review_status = "reprovado"
        result.review_reason = "fora dos filtros atuais"
        return

    if _is_development_candidate(result, cfg):
        lot_size = float(result.listing.lot_size_sqft or 0)
        acres = lot_size / 43_560
        price_per_acre = result.land_cost / acres
        zoning_note = "; zoneamento pendente" if not result.listing.zoning else ""
        result.review_status = "radar_desenvolvimento"
        result.review_reason = (
            f"area de {acres:.1f} acres para desenvolvimento; "
            f"US$ {price_per_acre:,.0f}/acre{zoning_note}"
        )
        result.reasons.append(
            f"◆ tese de desenvolvimento: {acres:.1f} acres, "
            f"US$ {price_per_acre:,.0f}/acre"
        )
        return

    if not _passes_numeric_filters(result, cfg):
        result.review_status = "reprovado"
        result.review_reason = "nao passou nos filtros financeiros"
        return

    if (
        not radar_cfg.get("include_high_flood_risk", True)
        and _has_high_flood_risk(result, cfg)
    ):
        result.review_status = "reprovado"
        result.review_reason = "flood zone alto risco"
        return

    fatal_reasons = _fatal_reasons(result)
    unknown_zoning = _has_unknown_zoning(result)
    manual_review = _has_manual_review(result)

    allowed_fatal = []
    if radar_cfg.get("include_unknown_zoning", True):
        allowed_fatal.append("zoneamento desconhecido")

    disallowed_fatal = [
        reason for reason in fatal_reasons
        if not any(allowed in _plain(reason) for allowed in allowed_fatal)
    ]
    if disallowed_fatal:
        result.review_status = "reprovado"
        result.review_reason = "tem bloqueio automatico nao permitido no radar"
        return

    if unknown_zoning and radar_cfg.get("include_unknown_zoning", True):
        result.review_status = "radar_zoneamento_pendente"
        result.review_reason = "numeros bons; falta confirmar zoneamento"
        return

    if manual_review and radar_cfg.get("include_manual_review_segments", True):
        result.review_status = "radar_analise_manual"
        result.review_reason = "numeros bons; segmento exige analise manual"
        return

    result.review_status = "reprovado"
    result.review_reason = "fora dos filtros atuais"


def is_radar_candidate(result: ViabilityResult) -> bool:
    return result.review_status.startswith("radar_")
