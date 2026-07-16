"""Pontuação de valorização regional e potencial específico do lote.

Esta camada não muda a régua conservadora de ``is_viable``. Ela serve para
encontrar *near misses* negociáveis: imóveis que ainda não podem ser aprovados,
mas merecem Radar por estarem em uma região estruturalmente forte e próximos
do preço que faria a conta fechar.
"""

from __future__ import annotations

from math import pow
from typing import Any

from .config import Config
from .models import ViabilityResult
from .viability import resolve_parameters


def _clamp(value: float, minimum: float = 0.0, maximum: float = 10.0) -> float:
    return max(minimum, min(value, maximum))


def _weighted_score(components: list[tuple[float | None, float]]) -> float | None:
    available = [(value, weight) for value, weight in components if value is not None and weight > 0]
    if not available:
        return None
    total_weight = sum(weight for _, weight in available)
    return round(sum(float(value) * weight for value, weight in available) / total_weight, 1)


def _county_for_zip(zip_code: str | None, cfg: Config) -> str:
    if not zip_code:
        return ""
    mapping = cfg.raw.get("county_costs", {}).get("zip_to_county", {})
    return str(mapping.get(str(zip_code)) or "")


def _metro_cycle_score(section: dict[str, Any]) -> float | None:
    """Converte o HPI metropolitano recente e de cinco anos em score 0–10.

    O longo prazo pesa mais, mas um ano negativo reduz o entusiasmo. Isso
    evita transformar crescimento populacional em justificativa para pagar
    qualquer preço no ciclo atual.
    """
    hpi = section.get("metro_hpi") or {}
    try:
        one_year = float(hpi["one_year_pct"])
        five_year = float(hpi["five_year_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if five_year <= -1:
        return 0.0
    annualized = pow(1 + five_year, 1 / 5) - 1
    long_term = _clamp(annualized / 0.08 * 10)
    recent = _clamp(5 + one_year * 50)
    return round(0.65 * long_term + 0.35 * recent, 1)


def _arv_confidence_score(result: ViabilityResult) -> float:
    if result.arv_source != "rentcast_avm":
        return 4.0
    confidence = str(result.arv_confidence or "").lower()
    if confidence == "high":
        return 10.0
    if confidence in {"medium", "med", "moderate"}:
        return 8.0
    if confidence == "low":
        return 5.0
    return 7.0


def assess_appreciation(result: ViabilityResult, cfg: Config) -> None:
    """Preenche scores de valorização e negociação no resultado."""
    section = cfg.raw.get("appreciation", {})
    if not section.get("enabled", False):
        return

    regional_weights = section.get("regional_weights") or {}
    county = _county_for_zip(result.zip_code, cfg)
    county_growth_map = section.get("county_population_growth_2025_2035") or {}
    county_growth = county_growth_map.get(county)
    try:
        county_growth = float(county_growth) if county_growth is not None else None
    except (TypeError, ValueError):
        county_growth = None
    county_growth_score = (
        _clamp(county_growth / float(section.get("county_growth_full_score_pct", 0.25)) * 10)
        if county_growth is not None
        else None
    )

    metro_score = _metro_cycle_score(section)
    result.county_projection_growth_pct = county_growth
    result.regional_appreciation_score = _weighted_score([
        (result.market_score, float(regional_weights.get("market_thesis", 0.40))),
        (county_growth_score, float(regional_weights.get("county_projection", 0.30))),
        (result.growth_score, float(regional_weights.get("local_signals", 0.15))),
        (metro_score, float(regional_weights.get("metro_cycle", 0.15))),
    ])

    _, _, _, rules = resolve_parameters(result.listing, cfg)
    target_margin = float(rules["target_margin"])
    min_lot = float(rules.get("min_lot_size_sqft") or 0)
    max_premium = float(section.get("max_ask_above_supported_pct", 0.12) or 0.12)
    max_gap_usd = float(section.get("max_negotiation_gap_usd", 25_000) or 25_000)

    margin_score = _clamp(result.margin / target_margin * 10) if target_margin else 10.0
    premium = result.asking_premium_to_supported
    if premium is None:
        negotiation_score = 0.0
    elif premium <= 0:
        negotiation_score = 10.0
    else:
        gap_usd = max(0.0, result.land_cost - result.max_supported_land_price)
        pct_score = _clamp((1 - premium / max_premium) * 10) if max_premium else 0.0
        usd_score = _clamp((1 - gap_usd / max_gap_usd) * 10) if max_gap_usd else 0.0
        negotiation_score = (pct_score + usd_score) / 2

    if result.margin_stress is None:
        stress_score = 5.0
    else:
        stress_score = _clamp((result.margin_stress + 0.05) / (target_margin + 0.05) * 10)

    if min_lot <= 0:
        lot_score = 10.0
    elif result.listing.lot_size_sqft is None:
        lot_score = 6.0
    elif result.listing.lot_size_sqft >= min_lot:
        lot_score = 10.0
    else:
        lot_score = _clamp(result.listing.lot_size_sqft / min_lot * 6)

    property_weights = section.get("property_weights") or {}
    result.property_potential_score = _weighted_score([
        (margin_score, float(property_weights.get("margin", 0.25))),
        (negotiation_score, float(property_weights.get("negotiation", 0.30))),
        (stress_score, float(property_weights.get("stress", 0.15))),
        (_arv_confidence_score(result), float(property_weights.get("arv_confidence", 0.20))),
        (lot_score, float(property_weights.get("lot_fit", 0.10))),
    ])

    result.appreciation_score = _weighted_score([
        (result.regional_appreciation_score, float(section.get("regional_weight", 0.60))),
        (result.property_potential_score, float(section.get("property_weight", 0.40))),
    ])
    score = result.appreciation_score or 0.0
    result.appreciation_label = "alta" if score >= 8 else "media" if score >= 6.5 else "baixa"

    factors: list[str] = []
    if county_growth is not None:
        factors.append(f"{county.title()} County +{county_growth:.1%} projetado 2025–2035")
    if metro_score is not None:
        factors.append(f"ciclo metro {metro_score:.1f}/10")
    if result.max_supported_land_price > 0:
        if premium is not None and premium > 0:
            factors.append(f"pedida {premium:.1%} acima do preço-alvo")
        else:
            factors.append("pedida dentro do preço-alvo")
    result.appreciation_factors = factors

    if result.appreciation_score is not None:
        result.reasons.append(
            f"• valorização: {result.appreciation_score:.1f}/10 "
            f"(região {result.regional_appreciation_score or 0:.1f}, "
            f"imóvel {result.property_potential_score or 0:.1f})"
        )
    if result.max_supported_land_price > 0:
        result.reasons.append(
            f"• preço máximo para margem-alvo: US$ {result.max_supported_land_price:,.0f}"
        )
