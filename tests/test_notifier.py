"""Tests for optional notification channels."""

from src.notifier import _maybe_send_zapi_whatsapp


class _Response:
    def raise_for_status(self):
        return None


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
