"""Motor de viabilidade para spec build (comprar terreno → construir → vender).

A fórmula e as regras de corte vêm todas do config.yaml, então você ajusta o
comportamento sem mexer no código.
"""

from __future__ import annotations

from .config import Config
from .models import Listing, ViabilityResult

_RESIDENTIAL_HINTS = ("resid", "rsf", "rs-", "r-1", "r1", "single")


def _looks_residential(zoning: str | None) -> bool | None:
    """True/False se der pra inferir; None se o dado não existe."""
    if not zoning:
        return None
    z = zoning.lower()
    return any(hint in z for hint in _RESIDENTIAL_HINTS)


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


def evaluate(listing: Listing, cfg: Config) -> ViabilityResult:
    """Aplica a fórmula de spec build (com parâmetros do segmento) e diz se é viável."""
    land_cost = float(listing.price)
    if land_cost <= 0:
        raise ValueError(f"preco invalido para a listagem {listing.id!r}: {land_cost}")

    tier = _resolve_tier(float(listing.price), cfg)
    tier_label = tier.get("label") or tier.get("name") or ""

    # Parâmetros base, sobrescritos pelos do segmento quando existirem.
    build = _merged(cfg.build, tier.get("build"))
    costs = _merged(cfg.costs, tier.get("costs"))
    rules = _merged(cfg.rules, tier.get("rules"))

    living_area = float(build["living_area_sqft"])

    # --- Componentes da fórmula ---
    arv = float(build["resale_price_per_sqft"]) * living_area
    construction_cost = float(build["construction_cost_per_sqft"]) * living_area
    soft_cost = float(costs["soft_cost_pct"]) * construction_cost
    purchase_closing_cost = float(costs.get("purchase_closing_pct", 0)) * land_cost
    contingency_cost = float(costs.get("contingency_pct", 0)) * construction_cost
    if "carrying_cost_annual_pct" in costs:
        carrying_pct = float(costs["carrying_cost_annual_pct"]) * (
            float(costs.get("carrying_months", 12)) / 12
        )
    else:
        carrying_pct = float(costs.get("carrying_cost_pct", 0))
    carrying_cost = carrying_pct * (land_cost + construction_cost)
    selling_cost = float(costs["selling_cost_pct"]) * arv

    total_cost = (
        land_cost
        + construction_cost
        + soft_cost
        + purchase_closing_cost
        + contingency_cost
        + carrying_cost
        + selling_cost
    )
    profit = arv - total_cost
    margin = profit / arv if arv else 0.0
    land_to_arv = land_cost / arv if arv else float("inf")
    land_to_total_investment = land_cost / total_cost if total_cost else float("inf")

    # --- Regras de corte ---
    reasons: list[str] = []
    is_viable = True
    if tier_label:
        reasons.append(f"• segmento: {tier_label}")

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
        residential = _looks_residential(listing.zoning)
        if residential is False:
            is_viable = False
            reasons.append(f"✗ zoneamento '{listing.zoning}' não parece residencial")
        elif residential is None:
            reasons.append("⚠ zoneamento desconhecido (verifique manualmente)")
        else:
            reasons.append("✓ zoneamento residencial")

    return ViabilityResult(
        listing=listing,
        arv=arv,
        land_cost=land_cost,
        construction_cost=construction_cost,
        soft_cost=soft_cost,
        purchase_closing_cost=purchase_closing_cost,
        contingency_cost=contingency_cost,
        carrying_cost=carrying_cost,
        selling_cost=selling_cost,
        total_cost=total_cost,
        profit=profit,
        margin=margin,
        land_to_arv=land_to_arv,
        land_to_total_investment=land_to_total_investment,
        is_viable=is_viable,
        tier=tier_label,
        reasons=reasons,
    )
