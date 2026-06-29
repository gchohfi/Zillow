"""ARV estimation using RentCast AVM, with config fallback."""

from __future__ import annotations

from typing import Any

import requests

from .config import Config, env
from .models import Listing
from .viability import resolve_parameters


def _first_number(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_list(data: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def enrich_arv(listing: Listing, cfg: Config) -> None:
    """Attach an ARV estimate to the listing when the configured provider can."""
    arv_cfg = cfg.raw.get("arv", {})
    if not arv_cfg.get("enabled", True):
        return
    if arv_cfg.get("provider", "rentcast_avm") != "rentcast_avm":
        return

    key = env("RENTCAST_API_KEY")
    if not key:
        return

    _, build, _, _ = resolve_parameters(listing, cfg)
    living_area = float(build["living_area_sqft"])
    params: dict[str, Any] = {
        "propertyType": arv_cfg.get("property_type", "Single Family"),
        "squareFootage": int(living_area),
        "maxRadius": arv_cfg.get("max_radius_miles", 2),
        "daysOld": arv_cfg.get("days_old", 180),
        "compCount": arv_cfg.get("comp_count", 10),
    }
    for key_name in ("bedrooms", "bathrooms"):
        if build.get(key_name):
            params[key_name] = build[key_name]
    if listing.address:
        params["address"] = listing.address
    else:
        params["latitude"] = listing.lat
        params["longitude"] = listing.lng

    url = (
        cfg.raw.get("datasource", {})
        .get("rentcast", {})
        .get("base_url", "https://api.rentcast.io/v1")
        .rstrip("/")
        + arv_cfg.get("path", "/avm/value")
    )
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json", "X-Api-Key": key},
            timeout=float(arv_cfg.get("timeout_seconds", 20)),
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  [aviso] AVM RentCast falhou para {listing.id or listing.address}: {type(exc).__name__}")
        return

    if not isinstance(data, dict):
        return

    value = _first_number(data, ["price", "value", "estimatedValue", "estimate", "avm"])
    comps = _first_list(data, ["comparables", "comps", "properties"])
    min_comps = int(arv_cfg.get("min_comps", 3) or 0)
    if not value or len(comps) < min_comps:
        print(
            f"  [aviso] AVM RentCast insuficiente para {listing.id or listing.address}: "
            f"valor={value or 'n/d'} comps={len(comps)}"
        )
        return

    listing.arv_estimate = value
    listing.arv_source = "rentcast_avm"
    listing.arv_comps_count = len(comps)
    listing.arv_confidence = str(data.get("confidenceScore") or data.get("confidence") or "")
    if listing.arv_confidence == "":
        listing.arv_confidence = None
