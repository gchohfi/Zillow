"""Tests for optional notification channels."""

from src.models import Listing, ViabilityResult
from src.notifier import (
    _format_whatsapp_result,
    _maybe_send_zapi_whatsapp,
    _maybe_send_zapi_whatsapp_results,
)


class _Response:
    def raise_for_status(self):
        return None


def _result(address="121 Central Ave, Davenport, FL 33896", margin=0.216, profit=156861):
    listing = Listing(
        id=address,
        price=54_900,
        lat=28.262,
        lng=-81.618,
        address=address,
        distance_km=36,
    )
    return ViabilityResult(
        listing=listing,
        arv=726_000,
        land_cost=54_900,
        construction_cost=363_000,
        soft_cost=36_300,
        purchase_closing_cost=1_098,
        contingency_cost=25_410,
        carrying_cost=37_611,
        selling_cost=50_820,
        total_cost=569_139,
        profit=profit,
        margin=margin,
        land_to_arv=0.076,
        land_to_total_investment=0.096,
        is_viable=True,
        tier="Médio padrão",
        reasons=[],
        zip_code="33896",
        market_region="Kissimmee / Four Corners / Davenport / ChampionsGate",
        market_priority="Alta com cautela",
        market_score=7.5,
        market_strategies=["STR legal-by-address", "SFR hybrid"],
        risk_flags=["checar STR legality por endereco", "checar HOA/CDD"],
    )


def test_zapi_whatsapp_payload(monkeypatch):
    calls = []
    monkeypatch.setenv("ZAPI_INSTANCE_ID", "instance-id")
    monkeypatch.setenv("ZAPI_INSTANCE_TOKEN", "instance-token")
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "client-token")
    monkeypatch.setenv("ZAPI_PHONE", "15551234567")

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("src.notifier.requests.post", fake_post)

    _maybe_send_zapi_whatsapp("hello")

    assert calls == [{
        "url": "https://api.z-api.io/instances/instance-id/token/instance-token/send-text",
        "headers": {"Content-Type": "application/json", "Client-Token": "client-token"},
        "json": {"phone": "15551234567", "message": "hello"},
        "timeout": 30,
    }]


def test_zapi_whatsapp_payload_without_client_token(monkeypatch):
    calls = []
    monkeypatch.setenv("ZAPI_INSTANCE_ID", "instance-id")
    monkeypatch.setenv("ZAPI_INSTANCE_TOKEN", "instance-token")
    monkeypatch.delenv("ZAPI_CLIENT_TOKEN", raising=False)
    monkeypatch.setenv("ZAPI_PHONE", "15551234567")

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("src.notifier.requests.post", fake_post)

    _maybe_send_zapi_whatsapp("hello")

    assert calls == [{
        "url": "https://api.z-api.io/instances/instance-id/token/instance-token/send-text",
        "headers": {"Content-Type": "application/json"},
        "json": {"phone": "15551234567", "message": "hello"},
        "timeout": 30,
    }]


def test_zapi_whatsapp_skips_when_not_configured(monkeypatch):
    calls = []
    monkeypatch.delenv("ZAPI_INSTANCE_ID", raising=False)
    monkeypatch.delenv("ZAPI_INSTANCE_TOKEN", raising=False)
    monkeypatch.delenv("ZAPI_CLIENT_TOKEN", raising=False)
    monkeypatch.delenv("ZAPI_PHONE", raising=False)
    monkeypatch.setattr("src.notifier.requests.post", lambda *args, **kwargs: calls.append(kwargs))

    _maybe_send_zapi_whatsapp("hello")

    assert calls == []


def test_whatsapp_result_format_includes_details_and_links():
    message = _format_whatsapp_result(_result())

    assert "Oportunidade Orlando Land" in message
    assert "121 Central Ave, Davenport, FL 33896" in message
    assert "Mercado: Alta com cautela - Kissimmee / Four Corners / Davenport / ChampionsGate" in message
    assert "ZIP: 33896" in message
    assert "Tese: STR legal-by-address, SFR hybrid" in message
    assert "Atencoes: checar STR legality por endereco; checar HOA/CDD" in message
    assert "Terreno: US$ 54,900" in message
    assert "Margem: 21.6%" in message
    assert "Google Maps: https://www.google.com/maps/search/?api=1&query=121+Central" in message
    assert "Zillow: https://www.zillow.com/homes/121+Central" in message
    assert "Realtor: https://www.realtor.com/realestateandhomes-search/121+Central" in message


def test_zapi_whatsapp_results_sends_top_ranked_with_limit(monkeypatch):
    calls = []
    monkeypatch.setenv("ZAPI_INSTANCE_ID", "instance-id")
    monkeypatch.setenv("ZAPI_INSTANCE_TOKEN", "instance-token")
    monkeypatch.setenv("ZAPI_PHONE", "15551234567")
    monkeypatch.setenv("WHATSAPP_MAX_OPPORTUNITIES", "2")

    def fake_post(url, headers, json, timeout):
        calls.append(json["message"])
        return _Response()

    monkeypatch.setattr("src.notifier.requests.post", fake_post)

    _maybe_send_zapi_whatsapp_results([
        _result(address="Weak Lot", margin=0.18, profit=10),
        _result(address="Best Lot", margin=0.25, profit=20),
        _result(address="Second Lot", margin=0.22, profit=30),
    ])

    assert calls[0].startswith("[Orlando Land] 3 oportunidades viaveis")
    assert "Best Lot" in calls[1]
    assert "Second Lot" in calls[2]
    assert len(calls) == 3
