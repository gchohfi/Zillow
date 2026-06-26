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


def evaluate(listing: Listing, cfg: Config) -> ViabilityResult:
    """Aplica a fórmula de spec build a uma listagem e diz se é viável."""
    build = cfg.build
    costs = cfg.costs
    rules = cfg.rules

    living_area = float(build["living_area_sqft"])

    # --- Componentes da fórmula ---
    arv = float(build["resale_price_per_sqft"]) * living_area
    land_cost = float(listing.price)
    construction_cost = float(build["construction_cost_per_sqft"]) * living_area
    soft_cost = float(costs["soft_cost_pct"]) * construction_cost
    carrying_cost = float(costs["carrying_cost_pct"]) * (land_cost + construction_cost)
    selling_cost = float(costs["selling_cost_pct"]) * arv

    total_cost = land_cost + construction_cost + soft_cost + carrying_cost + selling_cost
    profit = arv - total_cost
    margin = profit / arv if arv else 0.0
    land_to_arv = land_cost / arv if arv else float("inf")

    # --- Regras de corte ---
    reasons: list[str] = []
    is_viable = True

    target_margin = float(rules["target_margin"])
    if margin >= target_margin:
        reasons.append(f"✓ margem {margin:.1%} ≥ alvo {target_margin:.0%}")
    else:
        is_viable = False
        reasons.append(f"✗ margem {margin:.1%} < alvo {target_margin:.0%}")

    max_land = float(rules["max_land_to_arv_pct"])
    if land_to_arv <= max_land:
        reasons.append(f"✓ terreno {land_to_arv:.1%} do ARV ≤ {max_land:.0%}")
    else:
        is_viable = False
        reasons.append(f"✗ terreno {land_to_arv:.1%} do ARV > {max_land:.0%}")

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
        carrying_cost=carrying_cost,
        selling_cost=selling_cost,
        total_cost=total_cost,
        profit=profit,
        margin=margin,
        land_to_arv=land_to_arv,
        is_viable=is_viable,
        reasons=reasons,
    )
