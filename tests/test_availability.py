"""Tests for pre-alert availability checks."""

from datetime import datetime, timedelta, timezone

from src.availability import check_availability
from src.config import Config
from src.models import Listing


def _cfg(**overrides) -> Config:
    availability = {
        "require_status_active": True,
        "allowed_statuses": ["Active"],
        "reject_removed": True,
        "max_last_seen_hours": 36,
        "max_listed_age_days": 3,
        "require_mls_number": True,
    }
    availability.update(overrides)
    return Config(raw={"availability": availability})


def _listing(**raw):
    now = datetime.now(timezone.utc)
    base = {
        "status": "Active",
        "removedDate": None,
        "lastSeenDate": now.isoformat(),
        "listedDate": (now - timedelta(days=1)).isoformat(),
        "mlsName": "StellarMLS",
        "mlsNumber": "O123",
    }
    base.update(raw)
    return Listing(id="x", price=50_000, lat=28.5, lng=-81.3, raw=base)


def test_active_recent_listing_passes_availability():
    ok, reasons = check_availability(_listing(), _cfg())
    assert ok
    assert any("status fonte: Active" in reason for reason in reasons)
    assert any("MLS:" in reason for reason in reasons)


def test_removed_listing_fails_availability():
    ok, reasons = check_availability(_listing(removedDate="2026-06-28T00:00:00Z"), _cfg())
    assert not ok
    assert any("removedDate" in reason for reason in reasons)


def test_stale_listing_fails_availability():
    old = datetime.now(timezone.utc) - timedelta(days=10)
    ok, reasons = check_availability(
        _listing(lastSeenDate=old.isoformat(), listedDate=old.isoformat()),
        _cfg(),
    )
    assert not ok
    assert any("listado ha" in reason for reason in reasons)


def test_missing_mls_fails_availability():
    ok, reasons = check_availability(_listing(mlsNumber=None), _cfg())
    assert not ok
    assert any("MLS ausente" in reason for reason in reasons)


def test_missing_mls_warns_but_passes_when_not_required():
    ok, reasons = check_availability(
        _listing(mlsNumber=None), _cfg(require_mls_number=False)
    )
    assert ok
    assert any("MLS ausente" in reason for reason in reasons)
