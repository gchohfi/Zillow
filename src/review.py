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


def _passes_appreciation_radar(result: ViabilityResult, cfg: Config) -> bool:
    """Aceita somente near misses financeiros com tese regional e preço negociável."""
    section = cfg.raw.get("appreciation", {})
    radar_cfg = cfg.raw.get("radar", {})
    if not section.get("enabled", False) or not radar_cfg.get(
        "include_appreciation_candidates", False
    ):
        return False

    if (result.appreciation_score or 0) < float(section.get("minimum_score", 7.0)):
        return False
    if (result.regional_appreciation_score or 0) < float(
        section.get("minimum_regional_score", 7.0)
    ):
        return False
    if (result.property_potential_score or 0) < float(
        section.get("minimum_property_score", 5.5)
    ):
        return False

    _, _, _, rules = resolve_parameters(result.listing, cfg)
    target_margin = float(rules["target_margin"])
    margin_floor = max(
        float(section.get("minimum_margin", 0.10)),
        target_margin - float(section.get("max_margin_shortfall", 0.08)),
    )
    if result.margin < margin_floor:
        return False

    max_land = float(rules["max_land_to_total_investment_pct"])
    if result.land_to_total_investment > max_land + float(
        section.get("max_land_ratio_overage", 0.05)
    ):
        return False

    premium = result.asking_premium_to_supported
    if premium is None or premium > float(section.get("max_ask_above_supported_pct", 0.12)):
        return False
    price_gap = max(0.0, result.land_cost - result.max_supported_land_price)
    if price_gap > float(section.get("max_negotiation_gap_usd", 25_000)):
        return False

    if _has_high_flood_risk(result, cfg) and not radar_cfg.get("include_high_flood_risk", True):
        return False

    # Nunca deixa valorização encobrir uso comercial/industrial, flood bloqueado
    # ou outro impedimento físico/jurídico. Só tolera os bloqueios abaixo.
    allowed = (
        "margem",
        "investimento total",
        "zoneamento desconhecido",
        "lote",
    )
    return not any(
        not any(term in _plain(reason) for term in allowed)
        for reason in _fatal_reasons(result)
    )


def _is_financial_near_miss(result: ViabilityResult, cfg: Config) -> bool:
    """Aceita no Radar somente a margem curta; os demais cortes seguem rígidos."""
    radar_cfg = cfg.raw.get("radar", {})
    if not radar_cfg.get("include_financial_near_misses", False):
        return False

    _, _, _, rules = resolve_parameters(result.listing, cfg)
    target_margin = float(rules["target_margin"])
    min_margin = float(radar_cfg.get("min_margin", target_margin))
    if not min_margin <= result.margin < target_margin:
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

    if _passes_appreciation_radar(result, cfg):
        result.review_status = "radar_valorizacao"
        result.review_reason = (
            "regiao forte; conta proxima do alvo e candidata a negociacao"
        )
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

    financial_near_miss = _is_financial_near_miss(result, cfg)
    if not _passes_numeric_filters(result, cfg) and not financial_near_miss:
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
    if financial_near_miss:
        allowed_fatal.append("margem")

    disallowed_fatal = [
        reason for reason in fatal_reasons
        if not any(allowed in _plain(reason) for allowed in allowed_fatal)
    ]
    if disallowed_fatal:
        result.review_status = "reprovado"
        result.review_reason = "tem bloqueio automatico nao permitido no radar"
        return

    if financial_near_miss:
        _, _, _, rules = resolve_parameters(result.listing, cfg)
        zoning_note = "; zoneamento pendente" if unknown_zoning else ""
        result.review_status = "radar_margem_limite"
        result.review_reason = (
            f"margem {result.margin:.1%} abaixo do alvo "
            f"{float(rules['target_margin']):.0%}; revisar{zoning_note}"
        )
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
