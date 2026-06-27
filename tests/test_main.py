"""Tests for the batch orchestration behavior."""

from src.config import Config
from src.main import run
from src.models import Listing


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
