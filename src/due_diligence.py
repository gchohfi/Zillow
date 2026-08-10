"""Triagem de due diligence para terrenos de desenvolvimento.

Esta camada não concede aprovação nem transforma ausência de informação em
resposta positiva. Ela organiza o que já veio da listagem/Regrid/GIS, estima a
área líquida apenas quando possível e registra as confirmações ainda pendentes.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .config import Config
from .models import ViabilityResult
from .viability import resolve_county

CONFIRMED = "confirmado"
INDICATION = "indicativo"
UNCONFIRMED = "nao_confirmado"
BLOCKING = "bloqueio"
ALERT = "alerta"

_EVIDENCE_LABELS = {
    "future_land_use": "Future Land Use",
    "zoning": "zoneamento",
    "wetlands": "wetlands/delimitação",
    "flood": "floodplain/floodway",
    "utilities": "capacidade de água e esgoto",
    "access": "acesso viário legal e operacional",
    "entitlements": "entitlements e permits",
}


def _plain(value: Any) -> str:
    return str(value or "").strip().lower()


def _first(data: dict[str, Any], names: Iterable[str]) -> Any:
    """Primeiro campo preenchido, aceitando variações comuns de provedores."""
    lowered = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fraction(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if number > 1:
        number /= 100
    return min(max(number, 0), 1)


def _source_data(result: ViabilityResult) -> dict[str, Any]:
    raw = result.listing.raw or {}
    parcel = raw.get("_parcel_data")
    combined = dict(raw)
    if isinstance(parcel, dict):
        combined.update(parcel)
    return combined


def _status(value: Any, *, blocking_hints: Iterable[str] = ()) -> str:
    text = _plain(value)
    if not text:
        return UNCONFIRMED
    if any(_plain(hint) in text for hint in blocking_hints if hint):
        return BLOCKING
    return INDICATION


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "confirmed"}


def _evidence_status(
    value: Any,
    *,
    confirmed: Any = None,
    blocking_hints: Iterable[str] = (),
) -> str:
    status = _status(value, blocking_hints=blocking_hints)
    if status != BLOCKING and value not in (None, "") and _truthy(confirmed):
        return CONFIRMED
    return status


def _has_flood_evidence(result: ViabilityResult) -> bool:
    return any("fema flood zone" in _plain(flag) for flag in result.risk_flags) or any(
        "fema flood:" in _plain(reason) or "fema flood zone" in _plain(reason)
        for reason in result.reasons
    )


def _has_high_flood_risk(result: ViabilityResult) -> bool:
    """Red flags só recebem a zona quando FEMA marcou SFHA/alto risco."""
    return any("fema flood zone" in _plain(flag) for flag in result.risk_flags)


def _development_profile(acres: float) -> str:
    if acres >= 40:
        return "grande escala / master plan"
    if acres >= 10:
        return "médio porte / multifamily-BTR-loteamento"
    if acres >= 2:
        return "pequeno desenvolvimento / townhomes-loteamento"
    return "lote individual"


def assess_due_diligence(result: ViabilityResult, cfg: Config) -> None:
    """Enriquece o resultado com área líquida e estados de evidência.

    A estimativa é uma peneira de aquisição, não uma conclusão de engenharia.
    Percentuais ambientais só são deduzidos quando a fonte fornece um valor.
    Reservas de stormwater e infraestrutura são premissas configuráveis e ficam
    explicitamente marcadas como estimativa de baixa confiança.
    """
    section = cfg.raw.get("due_diligence", {})
    if not section.get("enabled", False):
        return

    lot_sqft = result.listing.lot_size_sqft
    min_sqft = float(section.get("apply_to_min_lot_size_sqft", 43_560) or 0)
    if lot_sqft is None or lot_sqft < min_sqft:
        return

    data = _source_data(result)
    gross_acres = lot_sqft / 43_560
    result.gross_acres = gross_acres
    result.development_profile = _development_profile(gross_acres)
    result.rules_as_of = str(section.get("rules_as_of") or date.today().isoformat())

    flu = _first(data, ("future_land_use", "futurelanduse", "future_landuse", "flu", "flum"))
    zoning = result.listing.zoning or _first(
        data, ("zoning_description", "zoning", "zoning_type")
    )
    access = _first(data, ("legal_access", "road_access", "access_type", "access"))
    electric = _first(data, ("electric_utility", "power_provider", "electric_provider"))
    water = _first(data, ("water_utility", "water_provider", "water_service"))
    sewer = _first(data, ("sewer_utility", "sewer_provider", "sewer_service"))
    utilities = _first(data, ("utility_capacity", "water_sewer_availability", "utilities"))
    if utilities in (None, "") and any(value not in (None, "") for value in (electric, water, sewer)):
        utilities = "; ".join(str(value) for value in (electric, water, sewer) if value not in (None, ""))
    entitlement = _first(
        data,
        ("entitlement_stage", "entitlements", "development_status", "permit_status"),
    )
    result.entitlement_stage = str(entitlement or "não confirmado")

    county, _ = resolve_county(result.listing, cfg)
    jurisdiction = _first(data, ("jurisdiction", "municipality", "city", "county_name", "county"))
    result.parcel_id = str(_first(data, ("parcel_id", "parcelid", "parcelnumb", "apn", "folio")) or "")
    result.owner_name = str(_first(data, ("owner", "owner_name", "ownername")) or "")
    result.jurisdiction = str(jurisdiction or (f"{county.title()} County" if county else "não confirmada"))
    result.future_land_use = str(flu or "")
    result.electric_utility = str(electric or "não confirmada")
    result.water_utility = str(water or "não confirmada")
    result.sewer_utility = str(sewer or "não confirmada")
    result.access_authority = str(
        _first(data, ("access_authority", "road_authority", "road_jurisdiction"))
        or "não confirmada"
    )
    result.environmental_authority = str(
        _first(data, ("environmental_authority", "water_management_district"))
        or "não confirmada"
    )
    sources = [result.listing.source, str(result.listing.raw.get("_parcel_source") or "")]
    extra_sources = result.listing.raw.get("_data_sources")
    if isinstance(extra_sources, list):
        sources.extend(str(source) for source in extra_sources)
    result.sources_consulted = list(dict.fromkeys(source for source in sources if source))

    hard_zoning_hints = section.get(
        "hard_block_zoning_hints",
        ["conservation only", "preservation", "wetland/water"],
    )
    evidence = {
        "future_land_use": _evidence_status(
            flu, confirmed=_first(data, ("future_land_use_confirmed", "flu_confirmed"))
        ),
        "zoning": _evidence_status(
            zoning,
            confirmed=_first(data, ("zoning_confirmed", "zoning_documented")),
            blocking_hints=hard_zoning_hints,
        ),
        "wetlands": UNCONFIRMED,
        "flood": INDICATION if _has_flood_evidence(result) else UNCONFIRMED,
        "utilities": _evidence_status(
            utilities,
            confirmed=_first(data, ("utilities_confirmed", "utility_availability_letter")),
        ),
        "access": _evidence_status(
            access, confirmed=_first(data, ("legal_access_confirmed", "driveway_permit"))
        ),
        "entitlements": _evidence_status(
            entitlement, confirmed=_first(data, ("entitlements_confirmed", "permit_approved"))
        ),
    }

    wetland_pct = _fraction(_first(data, ("wetlands_pct", "wetland_pct", "wetland_percent")))
    flood_pct = _fraction(
        _first(data, ("floodway_pct", "sfha_pct", "floodplain_pct", "flood_pct"))
    )
    easement_pct = _fraction(_first(data, ("easement_pct", "easements_pct")))
    explicit_net_acres = _number(
        _first(data, ("net_developable_acres", "buildable_acres", "net_buildable_acres"))
    )

    if wetland_pct is not None:
        formal_wetlands = _first(data, ("wetlands_formal", "formal_wetland_determination"))
        evidence["wetlands"] = CONFIRMED if _truthy(formal_wetlands) else INDICATION
    if flood_pct is not None:
        evidence["flood"] = INDICATION

    wetland_alert_pct = float(section.get("wetland_alert_pct", 0.20) or 0.20)
    flood_alert_pct = float(section.get("flood_alert_pct", 0.25) or 0.25)
    if wetland_pct is not None and wetland_pct >= wetland_alert_pct:
        evidence["wetlands"] = ALERT
    if (flood_pct is not None and flood_pct >= flood_alert_pct) or _has_high_flood_risk(result):
        evidence["flood"] = ALERT

    if explicit_net_acres is not None:
        net_acres = min(max(explicit_net_acres, 0), gross_acres)
        confidence = "alta" if _truthy(_first(
            data, ("net_developable_confirmed", "engineered_site_plan")
        )) else "média"
        scenarios = {
            "conservador": max(0, net_acres * 0.90),
            "provavel": net_acres,
            "agressivo": min(gross_acres, net_acres * 1.05),
        }
    else:
        known_deductions = sum(
            value for value in (wetland_pct, flood_pct, easement_pct) if value is not None
        )
        stormwater = float(section.get("default_stormwater_reserve_pct", 0.12) or 0)
        infrastructure = float(section.get("default_internal_infrastructure_pct", 0.08) or 0)
        max_deduction = float(section.get("max_total_deduction_pct", 0.90) or 0.90)
        uncertainty = float(section.get("default_unknown_constraints_reserve_pct", 0.15) or 0)
        probable_deduction = min(max_deduction, known_deductions + stormwater + infrastructure)
        conservative_deduction = min(max_deduction, probable_deduction + uncertainty)
        aggressive_deduction = min(
            max_deduction,
            known_deductions + (stormwater + infrastructure) * 0.50,
        )
        scenarios = {
            "conservador": gross_acres * (1 - conservative_deduction),
            "provavel": gross_acres * (1 - probable_deduction),
            "agressivo": gross_acres * (1 - aggressive_deduction),
        }
        net_acres = scenarios["provavel"]
        confidence = "baixa"

    result.estimated_net_developable_acres = net_acres
    result.net_developable_pct = net_acres / gross_acres if gross_acres else None
    result.net_estimate_confidence = confidence
    result.net_area_scenarios = scenarios
    result.price_per_net_acre = result.land_cost / net_acres if net_acres > 0 else None
    result.evidence_status = evidence

    pending = [
        label
        for key, label in _EVIDENCE_LABELS.items()
        if evidence.get(key) in {UNCONFIRMED, INDICATION, ALERT}
    ]
    result.pending_confirmations = pending
    result.due_diligence_completion_pct = (
        sum(status == CONFIRMED for status in evidence.values()) / len(evidence)
    )
    if any(status == BLOCKING for status in evidence.values()):
        result.due_diligence_status = BLOCKING
        result.due_diligence_recommendation = "descartar"
    elif pending:
        result.due_diligence_status = "diligencia_pendente"
        critical = ("future_land_use", "zoning", "utilities", "access")
        if all(evidence.get(key) == UNCONFIRMED for key in critical):
            result.due_diligence_recommendation = "hold"
        else:
            result.due_diligence_recommendation = "avancar_com_condicoes"
    else:
        result.due_diligence_status = "triagem_confirmada"
        result.due_diligence_recommendation = "avancar"

    result.reasons.append(
        f"◆ desenvolvimento: {gross_acres:.1f} acres brutos; "
        f"{net_acres:.1f} acres líquidos preliminares ({confidence} confiança)"
    )
    result.reasons.append(
        f"• base normativa/fonte registrada em {result.rules_as_of}"
    )
    if pending:
        result.reasons.append("⚠ confirmar: " + "; ".join(pending))
    result.reasons.append(
        "• cenários líquidos: "
        + "; ".join(f"{name} {value:.1f} ac" for name, value in scenarios.items())
    )
    result.reasons.append(
        "• recomendação de triagem: " + result.due_diligence_recommendation
    )
    if result.due_diligence_status == BLOCKING:
        result.reasons.append("✗ bloqueio identificado na triagem de desenvolvimento")
