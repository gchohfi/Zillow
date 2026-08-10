"""Tests for the batch orchestration behavior."""

import csv

import pytest

from src.config import Config
from src.main import _format_run_summary, run
from src.models import Listing


def _zero_site_costs(cfg: Config) -> None:
    """Isola os testes de orquestração da calibragem de custos de lote."""
    cfg.raw["costs"]["site_prep_cost"] = 0
    cfg.raw["costs"]["impact_fees"] = 0
    for tier in cfg.raw.get("tiers", []):
        tier.get("costs", {}).pop("site_prep_cost", None)
        tier.get("costs", {}).pop("impact_fees", None)


def test_failed_evaluation_is_not_marked_seen(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [
                Listing(
                    id="bad-price",
                    price=0,
                    lat=28.5384,
                    lng=-81.3789,
                    address="Bad price",
                    zoning="residential",
                )
            ]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    run(use_mock=True, dry_run=True)

    from src.storage import SeenStore

    store = SeenStore(str(tmp_path / "seen.db"))
    assert store.is_new("bad-price")
    store.close()


def test_unavailable_listing_is_not_marked_seen(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["csv_path"] = str(tmp_path / "opportunities.csv")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [
                Listing(
                    id="removed",
                    price=50_000,
                    lat=28.5384,
                    lng=-81.3789,
                    address="Removed",
                    zoning="residential",
                    raw={
                        "status": "Inactive",
                        "removedDate": "2026-06-28T00:00:00Z",
                        "lastSeenDate": "2026-06-28T00:00:00Z",
                        "listedDate": "2026-06-28T00:00:00Z",
                        "mlsNumber": "O123",
                    },
                )
            ]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    run(use_mock=True, dry_run=True)

    from src.storage import SeenStore

    store = SeenStore(str(tmp_path / "seen.db"))
    assert store.is_new("removed")
    store.close()


def test_source_failure_sends_status_message(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["run_status_path"] = str(tmp_path / "scan-status.json")
    messages = []

    class Source:
        errors = ["timeout na RentCast"]

        def fetch_new_land_listings(self, _cfg):
            return []

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr(
        "src.main.send_message",
        lambda subject, body, dry_run=False: messages.append((subject, body, dry_run)),
    )

    outcome = run(use_mock=False, dry_run=False)

    assert outcome.status == "failed"
    assert outcome.source_status == "failed"
    assert messages
    assert messages[0][0] == "[Orlando Land] Falha na fonte de dados"
    assert "timeout na RentCast" in messages[0][1]


def test_legitimate_empty_source_is_healthy(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["run_status_path"] = str(tmp_path / "scan-status.json")
    cfg.raw["region_signals"]["enabled"] = False
    cfg.raw["zoning_lookup"]["enabled"] = False
    cfg.raw["notifications"]["whatsapp_run_summary"]["enabled"] = False

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return []

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())

    outcome = run(use_mock=False, dry_run=False)

    assert outcome.status == "healthy"
    assert outcome.source_status == "healthy"


def test_intra_run_duplicate_is_evaluated_once(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["output"]["csv_path"] = str(tmp_path / "opportunities.csv")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")
    cfg.raw["notifications"]["whatsapp_run_summary"]["enabled"] = False
    _zero_site_costs(cfg)
    evaluated = []

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [
                Listing(id="one", price=12_000, lat=28.5384, lng=-81.3789,
                        address="123 Main Street, Orlando, FL 32801", zoning="residential",
                        lot_size_sqft=8000),
                Listing(id="two", price=12_000, lat=28.5384, lng=-81.3789,
                        address="123 Main St Orlando Florida 32801", zoning="residential",
                        lot_size_sqft=8000),
            ]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    real_evaluate = __import__("src.main", fromlist=["evaluate"]).evaluate
    monkeypatch.setattr(
        "src.main.evaluate",
        lambda listing, run_cfg: evaluated.append(listing.id) or real_evaluate(listing, run_cfg),
    )

    run(use_mock=True, dry_run=False)

    with open(tmp_path / "evaluations.csv", newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 1
    assert evaluated == ["one"]


def test_persistence_failure_does_not_consume_candidate(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")
    cfg.raw["output"]["run_status_path"] = str(tmp_path / "scan-status.json")
    cfg.raw["region_signals"]["enabled"] = False
    cfg.raw["zoning_lookup"]["enabled"] = False
    cfg.raw["red_flags"]["flood"]["enabled"] = False
    cfg.raw["arv"]["enabled"] = False
    cfg.raw["rental"]["enabled"] = False
    cfg.raw["notifications"]["whatsapp_run_summary"]["enabled"] = False
    cfg.raw["availability"] = {
        "require_status_active": False,
        "reject_removed": False,
        "max_last_seen_hours": 0,
        "max_listed_age_days": 0,
        "require_mls_number": False,
    }
    _zero_site_costs(cfg)
    listing = Listing(id="crash", price=12_000, lat=28.5384, lng=-81.3789,
                      address="Crash lot", zoning="residential", lot_size_sqft=8000)

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [listing]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr(
        "src.main.append_evaluations",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cancelled")),
    )

    with pytest.raises(OSError, match="cancelled"):
        run(use_mock=False, dry_run=False)

    from src.storage import SeenStore

    store = SeenStore(str(tmp_path / "seen.db"))
    assert store.is_new(listing)
    assert store.get_stage(listing) == ("failed", "OSError")
    store.close()


def test_required_channel_failure_is_retryable_without_duplicate_csv(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["csv_path"] = str(tmp_path / "opportunities.csv")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")
    cfg.raw["output"]["run_status_path"] = str(tmp_path / "scan-status.json")
    cfg.raw["region_signals"]["enabled"] = False
    cfg.raw["zoning_lookup"]["enabled"] = False
    cfg.raw["red_flags"]["flood"]["enabled"] = False
    cfg.raw["arv"]["enabled"] = False
    cfg.raw["rental"]["enabled"] = False
    cfg.raw["notifications"]["whatsapp_run_summary"]["enabled"] = False
    cfg.raw["availability"] = {
        "require_status_active": False, "reject_removed": False,
        "max_last_seen_hours": 0, "max_listed_age_days": 0,
        "require_mls_number": False,
    }
    _zero_site_costs(cfg)
    listing = Listing(id="retry", price=12_000, lat=28.5384, lng=-81.3789,
                      address="Retry lot", zoning="residential", lot_size_sqft=8000)
    attempts = []

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [listing]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr(
        "src.main.notify",
        lambda results, dry_run=False: attempts.append(len(results)) or len(attempts) > 1,
    )

    with pytest.raises(RuntimeError, match="required notification"):
        run(use_mock=False, dry_run=False)
    run(use_mock=False, dry_run=False)

    with open(tmp_path / "evaluations.csv", newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 1
    with open(tmp_path / "opportunities.csv", newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 1
    assert attempts == [1, 1]


def test_run_summary_reports_empty_round():
    summary = _format_run_summary(
        source_name="RentCastSource",
        radius_km=80,
        total=37,
        out_of_radius=0,
        already_seen=0,
        unavailable=0,
        not_viable=37,
        failed=0,
        viable_new=0,
    )

    assert "Sem oportunidade viável nova" in summary
    assert "Listagens encontradas: 37" in summary
    assert "Radar/revisão: 0" in summary
    assert "Reprovadas: 37" in summary


def test_mock_mode_uses_in_memory_seen_store(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["csv_path"] = str(tmp_path / "opportunities.csv")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")
    _zero_site_costs(cfg)
    calls = []

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [
                Listing(
                    id="mock-repeat",
                    price=12_000,
                    lat=28.5384,
                    lng=-81.3789,
                    address="Mock repeat",
                    zoning="residential",
                    lot_size_sqft=8000,
                )
            ]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr("src.main.notify", lambda results, dry_run=False: calls.append(len(results)))

    run(use_mock=True, dry_run=True)
    run(use_mock=True, dry_run=True)

    assert calls == [1, 1]


def test_run_sends_financially_good_unknown_zoning_to_radar(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    cfg.raw["output"]["csv_path"] = str(tmp_path / "opportunities.csv")
    cfg.raw["output"]["evaluations_csv_path"] = str(tmp_path / "evaluations.csv")
    cfg.raw["rules"]["require_known_zoning"] = True
    _zero_site_costs(cfg)
    cfg.raw["radar"] = {
        "enabled": True,
        "send_whatsapp": True,
        "max_candidates": 10,
        "include_unknown_zoning": True,
        "include_manual_review_segments": True,
        "include_high_flood_risk": True,
    }
    viable_calls = []
    radar_calls = []

    class Source:
        def fetch_new_land_listings(self, _cfg):
            return [
                Listing(
                    id="radar-zoning",
                    price=12_000,
                    lat=28.5384,
                    lng=-81.3789,
                    address="Radar zoning, Orlando, FL",
                    lot_size_sqft=8000,
                    zoning=None,
                )
            ]

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr("src.main.notify", lambda results, dry_run=False: viable_calls.append(len(results)))
    monkeypatch.setattr(
        "src.main.notify_radar",
        lambda results, dry_run=False, max_messages=10: radar_calls.append(len(results)),
    )
    monkeypatch.setattr("src.main.send_whatsapp_status", lambda message, dry_run=False: None)

    run(use_mock=True, dry_run=True)

    assert viable_calls == [0]
    assert radar_calls == [1]
