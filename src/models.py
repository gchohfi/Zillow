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
    normalized_address: str = ""          # preenchido ao normalizar/deduplicar endereço
    distance_km: Optional[float] = None   # preenchido pelo geofiltro
    arv_estimate: Optional[float] = None   # ARV da casa pronta via comps/AVM
    arv_source: Optional[str] = None
    arv_comps_count: Optional[int] = None
    arv_confidence: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ViabilityResult:
    """Resultado do motor de viabilidade para uma listagem."""

    listing: Listing
    arv: float
    land_cost: float
    construction_cost: float
    soft_cost: float
    purchase_closing_cost: float
    contingency_cost: float
    carrying_cost: float
    selling_cost: float
    total_cost: float
    profit: float
    margin: float
    land_to_arv: float
    land_to_total_investment: float
    is_viable: bool
    tier: str = ""                                      # segmento: baixo/médio/alto padrão
    site_prep_cost: float = 0.0    # preparação do lote (limpeza, aterro, conexões)
    impact_fees: float = 0.0       # taxas de impacto do county
    reasons: list[str] = field(default_factory=list)   # por que passou / reprovou
    arv_source: str = "config"
    arv_comps_count: Optional[int] = None
    arv_confidence: Optional[str] = None
    zip_code: Optional[str] = None
    market_region: str = ""
    market_priority: str = ""
    market_score: float = 0
    market_strategies: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    review_status: str = ""       # viavel, radar_zoneamento_pendente, radar_analise_manual, reprovado
    review_reason: str = ""
    growth_score: Optional[float] = None            # 0-10, sinais de crescimento da região
    growth_signals: dict[str, Any] = field(default_factory=dict)  # escolas, comércio, pop, renda
