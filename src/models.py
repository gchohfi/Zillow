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
    rent_estimate: Optional[float] = None  # aluguel mensal da casa pronta via AVM
    rent_source: Optional[str] = None
    rent_comps_count: Optional[int] = None
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
    profit_stress: Optional[float] = None   # lucro no cenário pessimista
    margin_stress: Optional[float] = None   # margem no cenário pessimista
    # Matriz de sensibilidade: choques univariados ordenados pelo estrago
    # na margem (delta_pp = pontos percentuais perdidos vs. cenário-base)
    sensitivity: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)   # por que passou / reprovou
    arv_source: str = "config"
    arv_comps_count: Optional[int] = None
    arv_confidence: Optional[str] = None
    zip_code: Optional[str] = None
    county: str = ""
    cadastral_use: str = ""
    cadastral_use_code: str = ""
    cadastral_use_source: str = ""
    cadastral_use_status: str = ""
    market_region: str = ""
    market_priority: str = ""
    market_score: float = 0
    market_strategies: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    review_status: str = ""       # viavel, radar_zoneamento_pendente, radar_analise_manual, reprovado
    review_reason: str = ""
    growth_score: Optional[float] = None            # 0-10, sinais de crescimento da região
    growth_signals: dict[str, Any] = field(default_factory=dict)  # escolas, comércio, pop, renda
    flood_zone: str = ""                            # zona FEMA (ex.: AE), vazio se fora/desconhecida
    flood_high_risk: bool = False                   # SFHA/zona de alto risco
    # Lente de renda (buy & hold) — informativa, não muda viabilidade spec build
    rent_monthly: Optional[float] = None            # aluguel estimado (US$/mês)
    noi_annual: Optional[float] = None              # resultado operacional líquido anual
    cap_rate: Optional[float] = None                # NOI / investimento total (yield on cost)
    dscr: Optional[float] = None                    # NOI / serviço da dívida
    cash_on_cash: Optional[float] = None            # (NOI - dívida) / capital próprio
    max_supported_land_price: float = 0.0
    asking_premium_to_supported: Optional[float] = None
    regional_appreciation_score: Optional[float] = None
    property_potential_score: Optional[float] = None
    appreciation_score: Optional[float] = None
    appreciation_label: str = ""
    appreciation_factors: list[str] = field(default_factory=list)
    county_projection_growth_pct: Optional[float] = None
    development_profile: str = ""
    gross_acres: Optional[float] = None
    estimated_net_developable_acres: Optional[float] = None
    net_developable_pct: Optional[float] = None
    net_estimate_confidence: str = ""
    due_diligence_status: str = ""
    due_diligence_completion_pct: Optional[float] = None
    evidence_status: dict[str, str] = field(default_factory=dict)
    pending_confirmations: list[str] = field(default_factory=list)
    entitlement_stage: str = ""
    rules_as_of: str = ""
    parcel_id: str = ""
    owner_name: str = ""
    jurisdiction: str = ""
    future_land_use: str = ""
    electric_utility: str = ""
    water_utility: str = ""
    sewer_utility: str = ""
    access_authority: str = ""
    environmental_authority: str = ""
    sources_consulted: list[str] = field(default_factory=list)
    net_area_scenarios: dict[str, float] = field(default_factory=dict)
    price_per_net_acre: Optional[float] = None
    due_diligence_recommendation: str = ""
    # Lente adicional de busca: tese de infill residencial / ciclo de 18 meses.
    # É informativa e auditável; não altera sozinha a aprovação do spec build.
    search_spec_name: str = ""
    search_spec_status: str = ""
    search_spec_score: Optional[float] = None
    search_spec_region: str = ""
    search_spec_reasons: list[str] = field(default_factory=list)
    search_spec_target_land_min: Optional[float] = None
    search_spec_target_land_max: Optional[float] = None
    search_spec_target_construction_per_sqft: Optional[float] = None
    search_spec_target_resale_per_sqft: Optional[float] = None
    search_spec_target_exit_price: Optional[float] = None
    search_spec_cycle_months: Optional[float] = None
    search_spec_target_irr_annual: Optional[float] = None
