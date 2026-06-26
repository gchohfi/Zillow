"""Modelos de dados compartilhados pelo pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Listing:
    """Uma listagem de terreno, normalizada (independente da fonte de dados)."""

    id: str
    price: float                      # preço pedido pelo terreno (USD)
    lat: float
    lng: float
    address: str = ""
    lot_size_sqft: Optional[float] = None
    property_type: str = "land"
    zoning: Optional[str] = None      # ex.: "RSF-1", "residential", None se desconhecido
    listing_date: Optional[str] = None
    url: str = ""
    source: str = ""
    distance_km: Optional[float] = None   # preenchido pelo geofiltro
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ViabilityResult:
    """Resultado do motor de viabilidade para uma listagem."""

    listing: Listing
    arv: float
    land_cost: float
    construction_cost: float
    soft_cost: float
    carrying_cost: float
    selling_cost: float
    total_cost: float
    profit: float
    margin: float
    land_to_arv: float
    is_viable: bool
    reasons: list[str] = field(default_factory=list)   # por que passou / reprovou
