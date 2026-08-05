"""Lentes adicionais e independentes para priorizar resultados de busca."""

from __future__ import annotations

import unicodedata

from .config import Config
from .market_strategy import extract_zip
from .models import ViabilityResult


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _market_for_zip(section: dict, zip_code: str | None) -> dict:
    if not zip_code:
        return {}
    for market in section.get("markets", []):
        if zip_code in {str(value) for value in market.get("zips", [])}:
            return dict(market)
    return {}


def apply_search_spec(result: ViabilityResult, cfg: Config) -> None:
    """Avalia a tese de infill sem substituir o underwriting principal.

    A pontuação mede aderência para triagem, não probabilidade de retorno:
    mercado (35), preço de aquisição (25), evidência de saída (20), zoning
    (10), risco/diligência (10).
    """
    section = cfg.raw.get("search_spec_infill_18m", {})
    if not section.get("enabled", False):
        return

    result.search_spec_name = str(section.get("label") or "Infill residencial — 18 meses")
    result.search_spec_cycle_months = float(section.get("cycle_months", 18) or 18)
    result.search_spec_target_irr_annual = float(section.get("target_irr_annual", 0.23) or 0.23)

    zip_code = result.zip_code or extract_zip(result.listing)
    market = _market_for_zip(section, zip_code)
    if not market:
        result.search_spec_status = "fora"
        result.search_spec_score = 0.0
        result.search_spec_reasons = ["ZIP fora dos mercados definidos para esta lente"]
        return

    result.search_spec_region = str(market.get("label") or market.get("name") or "")
    result.search_spec_target_land_min = _optional_float(market.get("land_price_min"))
    result.search_spec_target_land_max = _optional_float(market.get("land_price_max"))
    result.search_spec_target_construction_per_sqft = _midpoint(
        market.get("construction_per_sqft_min"), market.get("construction_per_sqft_max")
    )
    result.search_spec_target_resale_per_sqft = _midpoint(
        market.get("resale_per_sqft_min"), market.get("resale_per_sqft_max")
    )
    result.search_spec_target_exit_price = _midpoint(
        market.get("exit_price_min"), market.get("exit_price_max")
    )

    score = 35.0
    reasons = [f"mercado-alvo: {result.search_spec_region}"]
    hard_block = False

    # Preço de aquisição: abaixo da faixa segue interessante, mas precisa
    # confirmação de condição/localização; acima de 15% do teto é bloqueio.
    ask = float(result.land_cost)
    price_min = result.search_spec_target_land_min
    price_max = result.search_spec_target_land_max
    if price_max is None:
        reasons.append("faixa de aquisição ainda não calibrada para o mercado")
    elif ask <= price_max:
        score += 25
        if price_min is not None and ask < price_min:
            reasons.append("preço abaixo da faixa de referência; confirmar condição e localização")
        else:
            reasons.append("preço dentro da faixa de aquisição de referência")
    elif ask <= price_max * 1.15:
        score += 10
        reasons.append("preço até 15% acima do teto; negociar e recalcular")
    else:
        hard_block = True
        reasons.append("preço mais de 15% acima do teto de referência")

    # Saída precisa de comps/AVM. Fallback de configuração recebe apenas
    # crédito parcial para não tratar premissa como evidência confirmada.
    exit_min = _optional_float(market.get("exit_price_min"))
    if result.arv_source and result.arv_source != "config":
        if exit_min is None or result.arv >= exit_min:
            score += 20
            reasons.append("ARV com fonte externa alcança a faixa de saída")
        else:
            score += 5
            reasons.append("ARV com fonte externa abaixo da faixa de saída")
    else:
        score += 8
        reasons.append("ARV ainda baseado em premissa; validar com comps vendidos")

    zoning = _plain(result.listing.zoning)
    prohibited = tuple(
        _plain(value)
        for value in cfg.raw.get("rules", {}).get("prohibited_zoning_hints", [])
        if value
    )
    residential = tuple(
        _plain(value)
        for value in cfg.raw.get("rules", {}).get("residential_zoning_hints", [])
        if value
    )
    if not zoning:
        score += 3
        reasons.append("zoning, FAR e setbacks pendentes")
    elif any(value in zoning for value in prohibited):
        hard_block = True
        reasons.append("zoning incompatível com residencial")
    elif any(value in zoning for value in residential):
        score += 10
        reasons.append("zoning residencial indicativo; confirmar capacidade construtiva")
    else:
        score += 3
        reasons.append("zoning exige interpretação manual")

    if result.flood_high_risk:
        reasons.append("flood de alto risco exige orçamento e mitigação")
    elif result.due_diligence_status in {"impeditivo", "bloqueio"}:
        hard_block = True
        reasons.append("diligência contém bloqueio")
    else:
        score += 10
        reasons.append("sem bloqueio ambiental conhecido nesta triagem")

    score = min(100.0, score)
    if hard_block:
        status = "fora"
    elif score >= float(section.get("score_qualified", 70) or 70):
        status = "aderente"
    elif score >= float(section.get("score_review", 45) or 45):
        status = "revisar"
    else:
        status = "fora"

    result.search_spec_score = round(score, 1)
    result.search_spec_status = status
    result.search_spec_reasons = reasons


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _midpoint(low: object, high: object) -> float | None:
    low_value = _optional_float(low)
    high_value = _optional_float(high)
    if low_value is None:
        return high_value
    if high_value is None:
        return low_value
    return (low_value + high_value) / 2
