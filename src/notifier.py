"""Envio de alertas: console (sempre), e-mail, Telegram e WhatsApp — opcionais."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

import requests

from .config import env
from .models import ViabilityResult


def _format_result(r: ViabilityResult) -> str:
    L = r.listing
    dist = f"{L.distance_km:.0f} km" if L.distance_km is not None else "?"
    lines = [
        f"🏗️  OPORTUNIDADE VIÁVEL [{r.tier or 'n/d'}] — {L.address or L.id}",
        f"    Preço terreno : US$ {r.land_cost:,.0f}",
        f"    ARV (revenda) : US$ {r.arv:,.0f}",
        f"    Custo total   : US$ {r.total_cost:,.0f}",
        f"    Closing compra: US$ {r.purchase_closing_cost:,.0f}",
        f"    Contingência  : US$ {r.contingency_cost:,.0f}",
        f"    Lucro estimado: US$ {r.profit:,.0f}  (margem {r.margin:.1%})",
        f"    Terreno/invest: {r.land_to_total_investment:.1%}",
        f"    Distância     : {dist} de Orlando",
        f"    Link          : {L.url or '(sem link)'}",
        "    " + " | ".join(r.reasons),
    ]
    return "\n".join(lines)


def notify(results: list[ViabilityResult], dry_run: bool = False) -> None:
    """Notifica as oportunidades viáveis pelos canais configurados."""
    if not results:
        print("Nenhuma oportunidade viável nova nesta rodada.")
        return

    body = "\n\n".join(_format_result(r) for r in results)
    header = f"{len(results)} oportunidade(s) viável(is) de terreno perto de Orlando:\n"
    subject = f"[Orlando Land] {len(results)} oportunidade(s) viável(is)"
    send_message(subject, header + "\n" + body, dry_run=dry_run)


def send_message(subject: str, body: str, dry_run: bool = False) -> None:
    """Mostra no console e dispara para os canais configurados."""
    print(body)
    if dry_run:
        print("\n[dry-run] envios externos não foram realizados.")
        return
    _maybe_send_email(subject, body)
    _maybe_send_telegram(f"{subject}\n\n{body}")
    _maybe_send_zapi_whatsapp(f"{subject}\n\n{body}")


def _maybe_send_email(subject: str, message: str) -> None:
    host = env("SMTP_HOST")
    to_addr = env("ALERT_EMAIL_TO")
    if not host or not to_addr:
        return
    user = env("SMTP_USER")
    password = env("SMTP_PASSWORD")
    port = int(env("SMTP_PORT", "587") or 587)

    msg = MIMEText(message, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user or "orlando-land-detector"
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        print(f"[email] enviado para {to_addr}")
    except Exception as exc:  # noqa: BLE001
        print(f"[email] falhou: {exc}")


def _maybe_send_telegram(message: str) -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=30,
        )
        resp.raise_for_status()
        print("[telegram] enviado")
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] falhou: {type(exc).__name__}")


def _maybe_send_zapi_whatsapp(message: str) -> None:
    instance_id = env("ZAPI_INSTANCE_ID")
    instance_token = env("ZAPI_INSTANCE_TOKEN")
    client_token = env("ZAPI_CLIENT_TOKEN")
    phone = env("ZAPI_PHONE")
    if not all([instance_id, instance_token, client_token, phone]):
        return

    url = (
        "https://api.z-api.io/instances/"
        f"{instance_id}/token/{instance_token}/send-text"
    )
    try:
        resp = requests.post(
            url,
            headers={"Client-Token": client_token, "Content-Type": "application/json"},
            json={"phone": phone, "message": message},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"[whatsapp] enviado para {phone}")
    except Exception as exc:  # noqa: BLE001
        print(f"[whatsapp] falhou: {type(exc).__name__}")
