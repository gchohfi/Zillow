"""Motor de viabilidade para spec build (comprar terreno → construir → vender).

A fórmula e as regras de corte vêm todas do config.yaml, então você ajusta o
comportamento sem mexer no código.
"""

from __future__ import annotations

from .config import Config
from .market_strategy import classify_market, extract_zip
from .models import Listing, ViabilityResult

_RESIDENTIAL_HINTS = (
    "resid",
    "single family",
    "single-family",
    "sfr",
    "rsf",
    "rs-",
    "r-1",
    "r1",
    "r-2",
    "r2",
    "r-3",
    "r3",
    "pud",
    "planned unit development",
)
_PROHIBITED_ZONING_HINTS = (
    "commercial",
    "industrial",
    "office",
    "retail",
    "warehouse",
    "conservation",
    "wetland",
    "agricultural",
)


def _as_hints(values: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        return default
    if isinstance(values, str):
        return (values.lower(),)
    if isinstance(values, list):
        return tuple(str(value).lower() for value in values if value)
    return default


def _looks_residential(zoning: str | None, rules: dict | None = None) -> bool | None:
    """True/False se der pra inferir; None se o dado não existe."""
    if not zoning:
        return None
    rules = rules or {}
    z = zoning.lower()
    prohibited = _as_hints(rules.get("prohibited_zoning_hints"), _PROHIBITED_ZONING_HINTS)
    if any(hint in z for hint in prohibited):
        return False
    residential = _as_hints(rules.get("residential_zoning_hints"), _RESIDENTIAL_HINTS)
    return any(hint in z for hint in residential)


def _resolve_tier(price: float, cfg: Config) -> dict:
    """Acha o segmento (padrão) cujo teto max_price >= preço. Vazio se não houver."""
    for tier in cfg.raw.get("tiers", []):
        ceiling = tier.get("max_price")
        if ceiling is None or price <= float(ceiling):
            return tier
    return {}


def _merged(base: dict, override: dict | None) -> dict:
    """Mescla os parâmetros do segmento por cima dos padrões base."""
    if not override:
        return dict(base)
    return {**base, **override}


def resolve_county(listing: Listing, cfg: Config) -> tuple[str, dict]:
    """County da listagem (via ZIP) e os overrides de custo dele, se houver."""
    section = cfg.raw.get("county_costs", {})
    counties = section.get("counties") or {}
    zip_map = section.get("zip_to_county") or {}
    if not counties or not zip_map:
        return "", {}
    zip_code = extract_zip(listing)
    county = str(zip_map.get(zip_code or "") or "")
    if not county:
        return "", {}
    return county, dict(counties.get(county) or {})


def resolve_parameters(listing: Listing, cfg: Config) -> tuple[str, dict, dict, dict]:
    """Resolve segmento e parâmetros efetivos para uma listagem.

    Ordem de precedência dos custos: base → segmento → county (via ZIP).
    """
    tier = _resolve_tier(float(listing.price), cfg)
    tier_label = tier.get("label") or tier.get("name") or ""

    build = _merged(cfg.build, tier.get("build"))
    costs = _merged(cfg.costs, tier.get("costs"))
    _, county_costs = resolve_county(listing, cfg)
    costs = _merged(costs, county_costs)
    rules = _merged(cfg.rules, tier.get("rules"))
    return tier_label, build, costs, rules


def evaluate(listing: Listing, cfg: Config) -> ViabilityResult:
    """Aplica a fórmula de spec build (com parâmetros do segmento) e diz se é viável."""
    land_cost = float(listing.price)
    if land_cost <= 0:
        raise ValueError(f"preco invalido para a listagem {listing.id!r}: {land_cost}")

    # Parâmetros base, sobrescritos pelos do segmento quando existirem.
    tier_label, build, costs, rules = resolve_parameters(listing, cfg)

    living_area = float(build["living_area_sqft"])

    # --- Componentes da fórmula ---
    config_arv = float(build["resale_price_per_sqft"]) * living_area
    arv = float(listing.arv_estimate or config_arv)
    arv_source = listing.arv_source or "config"
    construction_cost = float(build["construction_cost_per_sqft"]) * living_area
    soft_cost = float(costs["soft_cost_pct"]) * construction_cost
    purchase_closing_cost = float(costs.get("purchase_closing_pct", 0)) * land_cost
    contingency_cost = float(costs.get("contingency_pct", 0)) * construction_cost
    site_prep_cost = float(costs.get("site_prep_cost", 0) or 0)
    impact_fees = float(costs.get("impact_fees", 0) or 0)
    if "carrying_cost_annual_pct" in costs:
        carrying_pct = float(costs["carrying_cost_annual_pct"]) * (
            float(costs.get("carrying_months", 12)) / 12
        )
    else:
        carrying_pct = float(costs.get("carrying_cost_pct", 0))
    carrying_cost = carrying_pct * (land_cost + construction_cost)
    # Seguro sensível a risco climático: zona FEMA de alto risco encarece o
    # seguro durante a obra (o marcador vem do check de flood, pré-avaliação).
    flood_high_risk = bool(listing.raw.get("_flood_high_risk"))
    flood_surcharge_annual = float(
        cfg.raw.get("red_flags", {}).get("flood", {})
        .get("insurance_surcharge_annual", 0) or 0
    )
    flood_insurance_cost = 0.0
    if flood_high_risk and flood_surcharge_annual:
        flood_insurance_cost = flood_surcharge_annual * float(costs.get("carrying_months", 12)) / 12
        carrying_cost += flood_insurance_cost
    selling_cost = float(costs["selling_cost_pct"]) * arv

    total_cost = (
        land_cost
        + construction_cost
        + soft_cost
        + purchase_closing_cost
        + contingency_cost
        + site_prep_cost
        + impact_fees
        + carrying_cost
        + selling_cost
    )
    profit = arv - total_cost
    margin = profit / arv if arv else 0.0
    land_to_arv = land_cost / arv if arv else float("inf")
    land_to_total_investment = land_cost / total_cost if total_cost else float("inf")

    # --- Cenário pessimista (análise de sensibilidade) ---
    stress_cfg = cfg.raw.get("stress", {})
    arv_drop = float(stress_cfg.get("arv_drop_pct", 0.10) or 0)
    cost_rise = float(stress_cfg.get("construction_rise_pct", 0.10) or 0)
    profit_stress = margin_stress = None
    if arv_drop or cost_rise:
        s_arv = arv * (1 - arv_drop)
        s_construction = construction_cost * (1 + cost_rise)
        s_total = (
            land_cost
            + s_construction
            + float(costs["soft_cost_pct"]) * s_construction
            + purchase_closing_cost
            + float(costs.get("contingency_pct", 0)) * s_construction
            + site_prep_cost
            + impact_fees
            + carrying_pct * (land_cost + s_construction)
            + flood_insurance_cost
            + float(costs["selling_cost_pct"]) * s_arv
        )
        profit_stress = s_arv - s_total
        margin_stress = profit_stress / s_arv if s_arv else 0.0

    # --- Regras de corte ---
    reasons: list[str] = []
    is_viable = True
    market = classify_market(listing, cfg)
    if tier_label:
        reasons.append(f"• segmento: {tier_label}")
    if site_prep_cost or impact_fees:
        reasons.append(
            f"• custos de lote: US$ {site_prep_cost:,.0f} preparação"
            f" + US$ {impact_fees:,.0f} impact fees"
        )
    if flood_insurance_cost:
        reasons.append(
            f"⚠ seguro de enchente no carrego: +US$ {flood_insurance_cost:,.0f} "
            f"(zona FEMA de alto risco)"
        )
    if market["region"]:
        reasons.append(
            f"• mercado: {market['priority']} - {market['region']}"
            + (f" ({market['zip_code']})" if market["zip_code"] else "")
        )
    elif market["priority"]:
        reasons.append(f"• mercado: {market['priority']}")
    for flag in market["risk_flags"]:
        reasons.append(f"⚠ {flag}")
    county, _ = resolve_county(listing, cfg)
    if county and (site_prep_cost or impact_fees):
        reasons.append(f"• custos de lote calibrados para county {county}")
    if arv_source == "rentcast_avm":
        extra = ""
        if listing.arv_comps_count:
            extra += f" ({listing.arv_comps_count} comps"
            if listing.arv_confidence:
                extra += f", {listing.arv_confidence}"
            extra += ")"
        reasons.append(f"✓ ARV por comps RentCast{extra}")
        # Divergência grande entre comps e premissa = incerteza no ARV.
        warn_pct = float(cfg.raw.get("arv", {}).get("divergence_warn_pct", 0.15) or 0)
        if warn_pct and config_arv:
            divergence = (arv - config_arv) / config_arv
            if abs(divergence) > warn_pct:
                flag = (
                    f"ARV dos comps diverge {divergence:+.0%} da premissa "
                    f"(US$ {config_arv:,.0f}) — conferir comps"
                )
                reasons.append(f"⚠ {flag}")
                market["risk_flags"].append(flag)
    else:
        reasons.append("⚠ ARV por premissa fixa do config")
    if margin_stress is not None:
        label = (
            f"• pessimista (ARV −{arv_drop:.0%}, obra +{cost_rise:.0%}): "
            f"lucro US$ {profit_stress:,.0f}, margem {margin_stress:.1%}"
        )
        reasons.append(label)
        if margin_stress < 0:
            market["risk_flags"].append("margem negativa no cenario pessimista")

    max_land_price = float(rules.get("max_land_price") or 0)
    if max_land_price > 0:
        if land_cost <= max_land_price:
            reasons.append(f"✓ terreno US$ {land_cost:,.0f} ≤ teto US$ {max_land_price:,.0f}")
        else:
            is_viable = False
            reasons.append(f"✗ terreno US$ {land_cost:,.0f} > teto US$ {max_land_price:,.0f}")

    target_margin = float(rules["target_margin"])
    if margin >= target_margin:
        reasons.append(f"✓ margem {margin:.1%} ≥ alvo {target_margin:.0%}")
    else:
        is_viable = False
        reasons.append(f"✗ margem {margin:.1%} < alvo {target_margin:.0%}")

    max_land = float(rules["max_land_to_total_investment_pct"])
    if land_to_total_investment <= max_land:
        reasons.append(
            f"✓ terreno {land_to_total_investment:.1%} do investimento total ≤ {max_land:.0%}"
        )
    else:
        is_viable = False
        reasons.append(
            f"✗ terreno {land_to_total_investment:.1%} do investimento total > {max_land:.0%}"
        )

    min_lot = float(rules.get("min_lot_size_sqft") or 0)
    if min_lot > 0:
        if listing.lot_size_sqft is None:
            reasons.append("⚠ tamanho do lote desconhecido (verifique manualmente)")
        elif listing.lot_size_sqft >= min_lot:
            reasons.append(f"✓ lote {listing.lot_size_sqft:,.0f} sqft ≥ {min_lot:,.0f}")
        else:
            is_viable = False
            reasons.append(f"✗ lote {listing.lot_size_sqft:,.0f} sqft < mínimo {min_lot:,.0f}")

    if rules.get("require_residential_zoning"):
        residential = _looks_residential(listing.zoning, rules)
        if residential is False:
            is_viable = False
            reasons.append(f"✗ zoneamento '{listing.zoning}' não parece residencial")
        elif residential is None:
            if rules.get("require_known_zoning"):
                is_viable = False
                reasons.append("✗ zoneamento desconhecido; exige conferência antes do alerta")
            else:
                reasons.append("⚠ zoneamento desconhecido (verifique manualmente)")
        else:
            reasons.append("✓ zoneamento residencial")

    if rules.get("manual_review_only"):
        is_viable = False
        reasons.append(
            "⚠ segmento exige análise manual de localização/bairro antes de virar alerta"
        )

    return ViabilityResult(
        listing=listing,
        arv=arv,
        land_cost=land_cost,
        construction_cost=construction_cost,
        soft_cost=soft_cost,
        purchase_closing_cost=purchase_closing_cost,
        contingency_cost=contingency_cost,
        site_prep_cost=site_prep_cost,
        impact_fees=impact_fees,
        carrying_cost=carrying_cost,
        selling_cost=selling_cost,
        total_cost=total_cost,
        profit=profit,
        margin=margin,
        profit_stress=profit_stress,
        margin_stress=margin_stress,
        land_to_arv=land_to_arv,
        land_to_total_investment=land_to_total_investment,
        is_viable=is_viable,
        tier=tier_label,
        reasons=reasons,
        arv_source=arv_source,
        arv_comps_count=listing.arv_comps_count,
        arv_confidence=listing.arv_confidence,
        flood_zone=str(listing.raw.get("_flood_zone") or ""),
        flood_high_risk=flood_high_risk,
        zip_code=market["zip_code"],
        market_region=market["region"],
        market_priority=market["priority"],
        market_score=market["score"],
        market_strategies=market["strategies"],
        risk_flags=market["risk_flags"],
    )
