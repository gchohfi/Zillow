"""Tests for external red-flag checks."""

from src.config import Config
from src.models import Listing, ViabilityResult
from src.red_flags import apply_red_flags, check_flood_red_flag


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _cfg(block=False):
    return Config(raw={
        "red_flags": {
            "flood": {
                "enabled": True,
                "query_url": "https://example.test/query",
                "timeout_seconds": 1,
                "fail_open": True,
                "block_high_risk": block,
                "high_risk_zones": ["AE", "VE"],
            }
        }
    })


def test_fema_high_risk_zone_adds_risk_flag(monkeypatch):
    def fake_get(url, params, timeout):
        assert url == "https://example.test/query"
        assert params["geometry"] == "-81.6,28.2"
        return _Response({
            "features": [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T"}}]
        })

    monkeypatch.setattr("src.red_flags.requests.get", fake_get)
    listing = Listing(id="x", price=1, lat=28.2, lng=-81.6)

    result = check_flood_red_flag(listing, _cfg())

    assert result.risk_flags == ["FEMA flood zone AE / SFHA"]
    assert not result.blocks_alert


def test_apply_red_flags_can_block_when_configured(monkeypatch):
    monkeypatch.setattr(
        "src.red_flags.requests.get",
        lambda *args, **kwargs: _Response({
            "features": [{"attributes": {"FLD_ZONE": "VE", "SFHA_TF": "F"}}]
        }),
    )
    listing = Listing(id="x", price=1, lat=28.2, lng=-81.6)
    result = ViabilityResult(
        listing=listing,
        arv=1,
        land_cost=1,
        construction_cost=0,
        soft_cost=0,
        purchase_closing_cost=0,
        contingency_cost=0,
        carrying_cost=0,
        selling_cost=0,
        total_cost=1,
        profit=0,
        margin=0,
        land_to_arv=1,
        land_to_total_investment=1,
        is_viable=True,
    )

    apply_red_flags(result, _cfg(block=True))

    assert not result.is_viable
    assert "FEMA flood zone VE" in result.risk_flags
    assert any("bloqueado" in reason for reason in result.reasons)


def test_fema_failure_fails_open(monkeypatch):
    def fake_get(*args, **kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr("src.red_flags.requests.get", fake_get)
    listing = Listing(id="x", price=1, lat=28.2, lng=-81.6)

    result = check_flood_red_flag(listing, _cfg())

    assert result.risk_flags == ["FEMA flood check indisponivel: TimeoutError"]
    assert not result.blocks_alert
