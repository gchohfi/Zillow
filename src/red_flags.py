"""External red-flag checks before an opportunity is alerted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from .config import Config
from .models import Listing, ViabilityResult


@dataclass
class RedFlagResult:
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    blocks_alert: bool = False
    zone: str = ""              # zona FEMA (ex.: AE); vazio se fora/indisponível
    high_risk: bool = False     # SFHA ou zona listada como alto risco


def _truthy_sfha(value: Any) -> bool:
    return str(value or "").strip().upper() in {"T", "TRUE", "1", "Y", "YES"}


def _query_fema_flood_zone(listing: Listing, flood_cfg: dict[str, Any]) -> dict[str, Any] | None:
    url = flood_cfg.get(
        "query_url",
        "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query",
    )
    timeout = float(flood_cfg.get("timeout_seconds") or 12)
    params = {
        "f": "json",
        "geometry": f"{listing.lng},{listing.lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE",
        "returnGeometry": "false",
    }
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    features = data.get("features") or []
    if not features:
        return None
    return features[0].get("attributes") or {}


def check_flood_red_flag(listing: Listing, cfg: Config) -> RedFlagResult:
    """Check FEMA NFHL by point and return alert annotations."""
    flood_cfg = cfg.raw.get("red_flags", {}).get("flood", {})
    if not flood_cfg.get("enabled", False):
        return RedFlagResult()

    if not listing.lat or not listing.lng:
        return RedFlagResult(risk_flags=["FEMA flood: coordenada ausente"])

    fail_open = bool(flood_cfg.get("fail_open", True))
    try:
        attrs = _query_fema_flood_zone(listing, flood_cfg)
    except Exception as exc:  # noqa: BLE001
        flag = f"FEMA flood check indisponivel: {type(exc).__name__}"
        return RedFlagResult(
            reasons=[f"⚠ {flag}"],
            risk_flags=[flag],
            blocks_alert=not fail_open,
        )

    if attrs is None:
        return RedFlagResult(reasons=["✓ FEMA flood: sem interseção NFHL no ponto"])

    zone = str(attrs.get("FLD_ZONE") or "").strip().upper()
    subtype = str(attrs.get("ZONE_SUBTY") or "").strip()
    sfha = _truthy_sfha(attrs.get("SFHA_TF"))
    high_risk_zones = {
        str(value).upper()
        for value in flood_cfg.get("high_risk_zones", ["A", "AE", "AH", "AO", "AR", "A99", "V", "VE"])
    }
    is_high_risk = sfha or zone in high_risk_zones
    label = f"FEMA flood zone {zone or 'n/d'}"
    if subtype:
        label += f" ({subtype})"
    if sfha:
        label += " / SFHA"

    if is_high_risk:
        block = bool(flood_cfg.get("block_high_risk", False))
        return RedFlagResult(
            reasons=[f"⚠ {label}"],
            risk_flags=[label],
            blocks_alert=block,
            zone=zone,
            high_risk=True,
        )

    return RedFlagResult(reasons=[f"✓ {label}"], zone=zone)


def mark_flood_zone(listing: Listing, cfg: Config) -> RedFlagResult:
    """Consulta a zona FEMA ANTES da avaliação e marca a listagem.

    O motor de viabilidade lê o marcador para encarecer o seguro do
    carrego em zona de alto risco. O RedFlagResult retornado deve ser
    passado a apply_red_flags depois, para não consultar a FEMA 2x.
    """
    flood = check_flood_red_flag(listing, cfg)
    if flood.high_risk:
        listing.raw["_flood_high_risk"] = True
    if flood.zone:
        listing.raw["_flood_zone"] = flood.zone
    return flood


def apply_red_flags(
    result: ViabilityResult, cfg: Config, flood: RedFlagResult | None = None
) -> None:
    """Attach configured red flags to a viability result."""
    if flood is None:
        flood = check_flood_red_flag(result.listing, cfg)
    result.reasons.extend(flood.reasons)
    for flag in flood.risk_flags:
        if flag not in result.risk_flags:
            result.risk_flags.append(flag)
    if flood.blocks_alert:
        result.is_viable = False
        result.reasons.append("✗ bloqueado por red flag de flood zone")
