"""Market thesis classification for Orlando-area opportunities."""

from __future__ import annotations

import re
from typing import Any

from .config import Config
from .models import Listing

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def _dig(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def extract_zip(listing: Listing) -> str | None:
    """Extract a five-digit ZIP from normalized or raw listing data."""
    raw = listing.raw or {}
    for path in (
        "zipCode",
        "zip",
        "postalCode",
        "address.zipCode",
        "address.postalCode",
        "location.address.postal_code",
    ):
        value = _dig(raw, path)
        if value:
            match = _ZIP_RE.search(str(value))
            if match:
                return match.group(1)

    for value in (listing.address, raw.get("formattedAddress")):
        if value:
            match = _ZIP_RE.search(str(value))
            if match:
                return match.group(1)
    return None


def classify_market(listing: Listing, cfg: Config) -> dict[str, Any]:
    """Return market thesis metadata based primarily on ZIP code."""
    section = cfg.raw.get("market_strategy", {})
    zip_code = extract_zip(listing)
    default_priority = section.get("default_priority", "fora da tese principal")
    default_score = float(section.get("default_score", 0) or 0)

    if not zip_code:
        return {
            "zip_code": None,
            "region": "",
            "priority": default_priority,
            "score": default_score,
            "strategies": [],
            "risk_flags": ["ZIP ausente; classificar mercado manualmente"],
        }

    for group in section.get("zip_groups", []):
        if zip_code in {str(z) for z in group.get("zips", [])}:
            return {
                "zip_code": zip_code,
                "region": group.get("label") or group.get("name") or "",
                "priority": group.get("priority", default_priority),
                "score": float(group.get("score", default_score) or 0),
                "strategies": list(group.get("strategies", [])),
                "risk_flags": list(group.get("risk_flags", [])),
            }

    return {
        "zip_code": zip_code,
        "region": "",
        "priority": default_priority,
        "score": default_score,
        "strategies": [],
        "risk_flags": ["ZIP fora das teses priorizadas no relatório"],
    }
