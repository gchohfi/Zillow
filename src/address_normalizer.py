"""US address normalization helpers for cross-source deduplication."""

from __future__ import annotations

import re
import string

from .models import Listing

try:
    import usaddress
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    usaddress = None

_PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation if ch not in "-#"})
_SPACE_RE = re.compile(r"\s+")
_ZIP4_RE = re.compile(r"\b(\d{5})-\d{4}\b")
_STREET_LOCATOR_RE = re.compile(
    r"\b\d+[A-Z]?\s+(?:[A-Z0-9]+\s+){0,6}"
    r"(?:STREET|ST|ROAD|RD|AVENUE|AVE|DRIVE|DR|LANE|LN|COURT|CT|BOULEVARD|BLVD|"
    r"PARKWAY|PKWY|WAY|TERRACE|TER|PLACE|PL|CIRCLE|CIR|TRAIL|TRL)\b"
)
_LOT_LOCATOR_RE = re.compile(r"\b(?:LOT|UNIT|PARCEL|TRACT|BLOCK)\s+[A-Z0-9-]+\b")

_TOKEN_MAP = {
    "STREET": "ST",
    "ST": "ST",
    "ROAD": "RD",
    "RD": "RD",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "DRIVE": "DR",
    "DR": "DR",
    "LANE": "LN",
    "LN": "LN",
    "COURT": "CT",
    "CT": "CT",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "PARKWAY": "PKWY",
    "PKWY": "PKWY",
    "TERRACE": "TER",
    "TER": "TER",
    "PLACE": "PL",
    "PL": "PL",
    "CIRCLE": "CIR",
    "CIR": "CIR",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    "FLORIDA": "FL",
    "UNITED": "",
    "STATES": "",
    "USA": "",
}


def _compact(value: str) -> str:
    value = _ZIP4_RE.sub(r"\1", value.upper())
    value = value.translate(_PUNCT_TABLE)
    tokens = []
    for token in _SPACE_RE.split(value.strip()):
        mapped = _TOKEN_MAP.get(token, token)
        if mapped:
            tokens.append(mapped)
    return " ".join(tokens)


def normalize_address(address: str | None) -> str:
    """Return a stable uppercase address string for comparison."""
    if not address:
        return ""

    if usaddress is not None:
        try:
            tagged, _address_type = usaddress.tag(address)
            ordered = [
                "AddressNumber",
                "StreetNamePreDirectional",
                "StreetName",
                "StreetNamePostType",
                "OccupancyType",
                "OccupancyIdentifier",
                "PlaceName",
                "StateName",
                "ZipCode",
            ]
            parsed = " ".join(str(tagged.get(part, "")) for part in ordered if tagged.get(part))
            if parsed:
                return _compact(parsed)
        except (usaddress.RepeatedLabelError, ValueError):
            pass

    return _compact(address)


def has_address_locator(address: str | None) -> bool:
    """Avoid deduping vague land descriptions such as only a road name."""
    if not address:
        return False
    compacted = _compact(address)
    return bool(_STREET_LOCATOR_RE.search(compacted) or _LOT_LOCATOR_RE.search(compacted))


def listing_address(listing: Listing) -> str:
    """Pick the best available address string from normalized and raw listing data."""
    raw = listing.raw or {}
    parts = [
        raw.get("addressLine1"),
        raw.get("city"),
        raw.get("state"),
        raw.get("zipCode"),
    ]
    raw_address = raw.get("formattedAddress") or raw.get("address") or ", ".join(
        str(part) for part in parts if part
    )
    return listing.address or str(raw_address or "")


def address_fingerprint(listing: Listing) -> str:
    """Return a dedupe-safe address fingerprint, or blank for vague addresses."""
    address = listing_address(listing)
    if not has_address_locator(address):
        return ""
    normalized = normalize_address(address)
    listing.normalized_address = normalized
    return normalized
