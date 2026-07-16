"""Tests for the batch orchestration behavior."""

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

    run(use_mock=False, dry_run=False)

    assert messages
    assert messages[0][0] == "[Orlando Land] Falha na fonte de dados"
    assert "timeout na RentCast" in messages[0][1]


def test_source_failure_closes_seen_store(monkeypatch, tmp_path):
    cfg = Config.load()
    cfg.raw["storage"]["db_path"] = str(tmp_path / "seen.db")
    closed = []

    class Source:
        errors = ["timeout na RentCast"]

        def fetch_new_land_listings(self, _cfg):
            return []

    class Store:
        def close(self):
            closed.append(True)

    monkeypatch.setattr("src.main.Config.load", lambda: cfg)
    monkeypatch.setattr("src.main.get_source", lambda _cfg, _use_mock: Source())
    monkeypatch.setattr("src.main.SeenStore", lambda _db_path: Store())
    monkeypatch.setattr("src.main.send_message", lambda subject, body, dry_run=False: None)

    run(use_mock=False, dry_run=True)

    assert closed == [True]


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
