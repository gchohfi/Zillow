"""Pre-send availability checks for listings returned by data providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Config
from .models import Listing


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_availability(listing: Listing, cfg: Config) -> tuple[bool, list[str]]:
    """Returns whether a listing looks still available enough to alert on."""
    rules = cfg.raw.get("availability", {})
    raw = listing.raw or {}
    reasons: list[str] = []
    ok = True

    status = str(raw.get("status") or "").strip()
    allowed_statuses = [str(s).lower() for s in rules.get("allowed_statuses", ["Active"])]
    if rules.get("require_status_active", True) and status:
        if status.lower() in allowed_statuses:
            reasons.append(f"status fonte: {status}")
        else:
            ok = False
            reasons.append(f"status fonte nao ativo: {status}")

    if rules.get("reject_removed", True) and raw.get("removedDate"):
        ok = False
        reasons.append(f"removedDate preenchido: {raw.get('removedDate')}")

    now = datetime.now(timezone.utc)
    max_last_seen_hours = float(rules.get("max_last_seen_hours") or 0)
    last_seen = _parse_dt(raw.get("lastSeenDate"))
    if max_last_seen_hours > 0:
        if last_seen is None:
            ok = False
            reasons.append("lastSeenDate ausente")
        else:
            age_hours = (now - last_seen).total_seconds() / 3600
            if age_hours <= max_last_seen_hours:
                reasons.append(f"visto pela fonte ha {age_hours:.1f}h")
            else:
                ok = False
                reasons.append(f"visto pela fonte ha {age_hours:.1f}h")

    max_listed_age_days = float(rules.get("max_listed_age_days") or 0)
    listed = _parse_dt(raw.get("listedDate") or listing.listing_date)
    if max_listed_age_days > 0:
        if listed is None:
            ok = False
            reasons.append("listedDate ausente")
        else:
            age_days = (now - listed).total_seconds() / 86400
            if age_days <= max_listed_age_days:
                reasons.append(f"listado ha {age_days:.1f}d")
            else:
                ok = False
                reasons.append(f"listado ha {age_days:.1f}d")

    if rules.get("require_mls_number", True):
        if raw.get("mlsNumber"):
            reasons.append(f"MLS: {raw.get('mlsName') or 'n/d'} {raw.get('mlsNumber')}")
        else:
            ok = False
            reasons.append("MLS ausente")

    return ok, reasons
