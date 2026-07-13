"""Regression tests for mock seen-store persistence rules."""

from src.config import Config
from src.main import _seen_store_path


def _cfg_with_db_path(tmp_path):
    return Config(raw={"storage": {"db_path": str(tmp_path / "seen.db")}})


def test_mock_dry_run_uses_ephemeral_seen_store(tmp_path):
    cfg = _cfg_with_db_path(tmp_path)

    assert _seen_store_path(cfg, use_mock=True, dry_run=True) == ":memory:"


def test_mock_with_side_effects_keeps_persistent_seen_store(tmp_path):
    cfg = _cfg_with_db_path(tmp_path)

    assert _seen_store_path(cfg, use_mock=True, dry_run=False) == str(tmp_path / "seen.db")


def test_real_dry_run_uses_ephemeral_seen_store(tmp_path):
    cfg = _cfg_with_db_path(tmp_path)

    assert _seen_store_path(cfg, use_mock=False, dry_run=True) == ":memory:"
