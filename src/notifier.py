"""Envio de alertas: console (sempre), e-mail, Telegram e WhatsApp — opcionais."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Callable, Protocol
from urllib.parse import quote_plus

import requests

from .config import env
from .memo import memo_slug
from .models import ViabilityResult


class AlertDeliveryStore(Protocol):
    def has_alert_delivery(self, channel: str, message: str) -> bool: ...

    def record_alert_delivery(self, channel: str, message: str) -> None: ...


def _deliver_once(
    channel: str,
    message: str,
    send: Callable[[], bool],
    delivery_store: AlertDeliveryStore | None,
) -> bool:
    if delivery_store is not None and delivery_store.has_alert_delivery(channel, message):
        print(f"[{channel}] entrega já confirmada; retry ignorado")
        return True
    delivered = send()
    if delivered and delivery_store is not None:
        delivery_store.record_alert_delivery(channel, message)
    return delivered


def _cadastral_radar_priority(result: ViabilityResult) -> int:
    if result.review_status != "radar_zoneamento_pendente":
        return 0
    if "residential" in (result.cadastral_use or "").lower():
        return 2
    return 1 if result.cadastral_use else 0


def _format_result(r: ViabilityResult) -> str:
    L = r.listing
    dist = f"{L.distance_km:.0f} km" if L.distance_km is not None else "?"
    lines = [
        f"🏗️  OPORTUNIDADE VIÁVEL [{r.tier or 'n/d'}] — {L.address or L.id}",
        f"    Mercado       : {r.market_priority or 'n/d'}"
        + (f" · {r.market_region}" if r.market_region else ""),
        f"    Preço terreno : US$ {r.land_cost:,.0f}",
        f"    ARV (revenda) : US$ {r.arv:,.0f}",
        f"    Custo total   : US$ {r.total_cost:,.0f}",
        f"    Closing compra: US$ {r.purchase_closing_cost:,.0f}",
        f"    Contingência  : US$ {r.contingency_cost:,.0f}",
        f"    Lucro estimado: US$ {r.profit:,.0f}  (margem {r.margin:.1%})",
        f"    Terreno/invest: {r.land_to_total_investment:.1%}",
        f"    Distância     : {dist} de Orlando",
        f"    Crescimento   : "
        + (f"{r.growth_score:.1f}/10" if r.growth_score is not None else "n/d"),
        f"    Link          : {L.url or '(sem link)'}",
        f"    Teses         : {', '.join(r.market_strategies) if r.market_strategies else 'n/d'}",
        f"    Atenções      : {', '.join(r.risk_flags) if r.risk_flags else 'n/d'}",
        "    " + " | ".join(r.reasons),
    ]
    return "\n".join(lines)


def notify(
    results: list[ViabilityResult],
    dry_run: bool = False,
    delivery_store: AlertDeliveryStore | None = None,
) -> bool:
    """Notifica as oportunidades viáveis pelos canais configurados."""
    if not results:
        print("Nenhuma oportunidade viável nova nesta rodada.")
        return True

    body = "\n\n".join(_format_result(r) for r in results)
    header = f"{len(results)} oportunidade(s) viável(is) de terreno perto de Orlando:\n"
    subject = f"[Orlando Land] {len(results)} oportunidade(s) viável(is)"
    full_message = header + "\n" + body
    print(full_message)
    if dry_run:
        print("\n[dry-run] envios externos não foram realizados.")
        return True
    telegram_message = f"{subject}\n\n{full_message}"
    return all([
        _deliver_once(
            "email",
            f"{subject}\n\n{full_message}",
            lambda: _maybe_send_email(subject, full_message),
            delivery_store,
        ),
        _deliver_once(
            "telegram",
            telegram_message,
            lambda: _maybe_send_telegram(telegram_message),
            delivery_store,
        ),
        _maybe_send_zapi_whatsapp_results(results, delivery_store=delivery_store),
    ])


def notify_radar(
    results: list[ViabilityResult],
    dry_run: bool = False,
    max_messages: int = 10,
    delivery_store: AlertDeliveryStore | None = None,
) -> bool:
    """Envia candidatos de Radar apenas pelo WhatsApp/status operacional."""
    if not results:
        print("Nenhum candidato de Radar nesta rodada.")
        return True

    ranked = sorted(
        results,
        key=lambda r: (
            r.market_score,
            _cadastral_radar_priority(r),
            r.margin,
            r.profit,
        ),
        reverse=True,
    )
    selected = ranked[:max_messages]
    print(f"{len(results)} candidato(s) no Radar; {len(selected)} selecionado(s) para WhatsApp.")
    if dry_run:
        print("\n[dry-run] Radar WhatsApp não foi enviado.")
        return True

    success = True
    if len(results) > max_messages:
        summary = (
            f"[Orlando Land Radar] {len(results)} candidatos para revisar. "
            f"Enviando os {max_messages} melhores por tese/margem/lucro."
        )
        success = _deliver_once(
            "whatsapp",
            summary,
            lambda: _maybe_send_zapi_whatsapp(summary),
            delivery_store,
        ) and success
    for result in selected:
        message = _format_whatsapp_radar_result(result)
        success = _deliver_once(
            "whatsapp",
            message,
            lambda message=message: _maybe_send_zapi_whatsapp(message),
            delivery_store,
        ) and success
    return success


def send_message(
    subject: str,
    body: str,
    dry_run: bool = False,
    delivery_store: AlertDeliveryStore | None = None,
) -> bool:
    """Mostra no console e dispara para os canais configurados."""
    print(body)
    if dry_run:
        print("\n[dry-run] envios externos não foram realizados.")
        return True
    message = f"{subject}\n\n{body}"
    return all([
        _deliver_once(
            "email",
            message,
            lambda: _maybe_send_email(subject, body),
            delivery_store,
        ),
        _deliver_once(
            "telegram",
            message,
            lambda: _maybe_send_telegram(message),
            delivery_store,
        ),
        _deliver_once(
            "whatsapp",
            message,
            lambda: _maybe_send_zapi_whatsapp(message),
            delivery_store,
        ),
    ])


def send_whatsapp_status(
    message: str,
    dry_run: bool = False,
    delivery_store: AlertDeliveryStore | None = None,
) -> bool:
    """Send an operational status message only through WhatsApp."""
    print(message)
    if dry_run:
        print("\n[dry-run] resumo WhatsApp não foi enviado.")
        return True
    return _deliver_once(
        "whatsapp",
        message,
        lambda: _maybe_send_zapi_whatsapp(message),
        delivery_store,
    )


def _regrid_map_url(lat: float, lng: float) -> str:
    """Link do mapa da Regrid nas coordenadas do lote (conta Pro mostra
    dono da parcela e zoneamento). Se o formato do hash mudar, o mapa
    abre na visão padrão e a busca manual continua funcionando."""
    return f"https://app.regrid.com/map#ll={lat:.6f},{lng:.6f}&z=17"


def _format_whatsapp_result(r: ViabilityResult) -> str:
    listing = r.listing
    raw = listing.raw or {}
    address = listing.address or listing.id
    dist = f"{listing.distance_km:.0f} km" if listing.distance_km is not None else "?"
    maps_query = quote_plus(address) if address else quote_plus(f"{listing.lat},{listing.lng}")
    zillow_query = quote_plus(address)
    realtor_query = quote_plus(address)

    lines = [
        "Oportunidade Orlando Land",
        "",
        address,
        f"Segmento: {r.tier or 'n/d'}",
        f"Mercado: {r.market_priority or 'n/d'}"
        + (f" - {r.market_region}" if r.market_region else ""),
        f"ZIP: {r.zip_code or 'n/d'}",
        f"Tese: {', '.join(r.market_strategies) if r.market_strategies else 'n/d'}",
        f"Terreno: US$ {r.land_cost:,.0f}",
        f"ARV estimado: US$ {r.arv:,.0f}",
        f"ARV fonte: {'RentCast comps' if r.arv_source == 'rentcast_avm' else 'premissa fixa'}",
        f"Custo total: US$ {r.total_cost:,.0f}",
        f"Lucro estimado: US$ {r.profit:,.0f}",
        f"Margem: {r.margin:.1%}"
        + (f" (pessimista: {r.margin_stress:.1%})" if r.margin_stress is not None else ""),
        f"Terreno/invest: {r.land_to_total_investment:.1%}",
        f"Distancia: {dist} de Orlando",
    ]
    if r.rent_monthly:
        rent_line = (
            f"Se alugar: US$ {r.rent_monthly:,.0f}/mes"
            + (f" | NOI US$ {r.noi_annual:,.0f}/ano" if r.noi_annual is not None else "")
            + (f" | cap {r.cap_rate:.1%}" if r.cap_rate is not None else "")
            + (f" | DSCR {r.dscr:.2f}" if r.dscr is not None else "")
        )
        lines.append(rent_line)
    top_shocks = [s for s in r.sensitivity if s.get("delta_pp", 0) > 0][:2]
    if top_shocks:
        lines.append(
            "Vigiar: " + "; ".join(
                f"{s['label']} derruba margem p/ {s['margin']:.1%}" for s in top_shocks
            )
        )
    if r.growth_score is not None:
        lines.append(f"Crescimento regiao: {r.growth_score:.1f}/10")
        summary = r.growth_signals.get("summary", [])
        if summary:
            lines.append(f"Sinais: {'; '.join(summary)}")
    if r.risk_flags:
        lines.append(f"Atencoes: {'; '.join(r.risk_flags)}")
    mls = " ".join(str(part) for part in [raw.get("mlsName"), raw.get("mlsNumber")] if part)
    if mls:
        lines.append(f"MLS: {mls}")
    if raw.get("status"):
        lines.append(f"Status fonte: {raw.get('status')}")
    if raw.get("lastSeenDate"):
        lines.append(f"Fonte viu em: {str(raw.get('lastSeenDate'))[:10]}")
    if r.arv_comps_count:
        detail = f"Comps ARV: {r.arv_comps_count}"
        if r.arv_confidence:
            detail += f" / confiança {r.arv_confidence}"
        lines.append(detail)
    agent = raw.get("listingAgent") or {}
    if isinstance(agent, dict) and (agent.get("name") or agent.get("phone")):
        lines.append(f"Agente: {' / '.join(str(v) for v in [agent.get('name'), agent.get('phone')] if v)}")
    if listing.url:
        lines.extend(["", f"Link original: {listing.url}"])
    lines.extend([
        "",
        f"Google Maps: https://www.google.com/maps/search/?api=1&query={maps_query}",
        f"Zillow: https://www.zillow.com/homes/{zillow_query}_rb/",
        f"Realtor: https://www.realtor.com/realestateandhomes-search/{realtor_query}",
        f"Regrid (dono/zoneamento): {_regrid_map_url(listing.lat, listing.lng)}",
    ])
    dashboard = (env("DASHBOARD_URL") or "").strip()
    if dashboard:
        lines.append(f"Memorando: {dashboard.rstrip('/')}/memo/{memo_slug(listing.id)}.html")
    return "\n".join(lines)


def _format_whatsapp_radar_result(r: ViabilityResult) -> str:
    listing = r.listing
    raw = listing.raw or {}
    address = listing.address or listing.id
    dist = f"{listing.distance_km:.0f} km" if listing.distance_km is not None else "?"
    maps_query = quote_plus(address) if address else quote_plus(f"{listing.lat},{listing.lng}")
    zillow_query = quote_plus(address)
    realtor_query = quote_plus(address)
    status_label = {
        "radar_zoneamento_pendente": "Radar - zoneamento pendente",
        "radar_analise_manual": "Radar - analise manual",
        "radar_desenvolvimento": "Radar - desenvolvimento imobiliario",
    }.get(r.review_status, "Radar - revisar")

    attention = [reason for reason in r.reasons if reason.startswith(("✗", "⚠"))]
    lines = [
        "Radar Orlando Land",
        status_label,
        (
            "NAO OFERTAR antes de confirmar area liquida, acesso, utilities e entitlement."
            if r.review_status == "radar_desenvolvimento"
            else "NAO OFERTAR antes de confirmar zoneamento/county GIS."
        ),
        "",
        address,
        f"Motivo: {r.review_reason or 'revisar diligencia'}",
        f"Segmento: {r.tier or 'n/d'}",
        f"Mercado: {r.market_priority or 'n/d'}"
        + (f" - {r.market_region}" if r.market_region else ""),
        f"ZIP: {r.zip_code or 'n/d'}",
        f"Tese: {', '.join(r.market_strategies) if r.market_strategies else 'n/d'}",
        f"Terreno: US$ {r.land_cost:,.0f}",
        f"ARV estimado: US$ {r.arv:,.0f}",
        f"ARV fonte: {'RentCast comps' if r.arv_source == 'rentcast_avm' else 'premissa fixa'}",
        f"Custo total: US$ {r.total_cost:,.0f}",
        f"Lucro estimado: US$ {r.profit:,.0f}",
        f"Margem: {r.margin:.1%}"
        + (f" (pessimista: {r.margin_stress:.1%})" if r.margin_stress is not None else ""),
        f"Terreno/invest: {r.land_to_total_investment:.1%}",
        f"Distancia: {dist} de Orlando",
    ]
    if r.cadastral_use:
        lines.append(
            "Uso cadastral (INDICATIVO): "
            f"{r.cadastral_use}"
            + (f" ({r.cadastral_use_code})" if r.cadastral_use_code else "")
            + (f" via {r.cadastral_use_source}" if r.cadastral_use_source else "")
            + "; confirmar zoning legal"
        )
    if r.review_status == "radar_desenvolvimento":
        lines.extend([
            f"Perfil: {r.development_profile or 'desenvolvimento'}",
            f"Area bruta: {r.gross_acres or (listing.lot_size_sqft or 0) / 43_560:.1f} acres",
            "Area liquida preliminar: " + (
                f"{r.estimated_net_developable_acres:.1f} acres "
                f"({r.net_estimate_confidence} confianca)"
                if r.estimated_net_developable_acres is not None else "nao calculada"
            ),
            f"Diligencia: {(r.due_diligence_completion_pct or 0):.0%} confirmada",
            f"Recomendacao: {r.due_diligence_recommendation or 'hold'}",
            "Preco/acre liquido: " + (
                f"US$ {r.price_per_net_acre:,.0f}"
                if r.price_per_net_acre is not None else "nao calculado"
            ),
            f"Entitlement: {r.entitlement_stage or 'nao confirmado'}",
        ])
        if r.pending_confirmations:
            lines.append(f"Confirmar: {'; '.join(r.pending_confirmations)}")
        if r.rules_as_of:
            lines.append(f"Regra/fonte datada: {r.rules_as_of}")
    if r.growth_score is not None:
        lines.append(f"Crescimento regiao: {r.growth_score:.1f}/10")
        summary = r.growth_signals.get("summary", [])
        if summary:
            lines.append(f"Sinais: {'; '.join(summary)}")
    if r.risk_flags:
        lines.append(f"Atencoes: {'; '.join(r.risk_flags)}")
    if attention:
        lines.append(f"Pendencias: {'; '.join(attention[:4])}")
    mls = " ".join(str(part) for part in [raw.get("mlsName"), raw.get("mlsNumber")] if part)
    if mls:
        lines.append(f"MLS: {mls}")
    if raw.get("status"):
        lines.append(f"Status fonte: {raw.get('status')}")
    if raw.get("lastSeenDate"):
        lines.append(f"Fonte viu em: {str(raw.get('lastSeenDate'))[:10]}")
    if listing.url:
        lines.extend(["", f"Link original: {listing.url}"])
    lines.extend([
        "",
        f"Google Maps: https://www.google.com/maps/search/?api=1&query={maps_query}",
        f"Zillow manual: https://www.zillow.com/homes/{zillow_query}_rb/",
        f"Realtor manual: https://www.realtor.com/realestateandhomes-search/{realtor_query}",
        f"Regrid (dono/zoneamento): {_regrid_map_url(listing.lat, listing.lng)}",
    ])
    return "\n".join(lines)


def _maybe_send_zapi_whatsapp_results(
    results: list[ViabilityResult],
    delivery_store: AlertDeliveryStore | None = None,
) -> bool:
    max_messages = int(env("WHATSAPP_MAX_OPPORTUNITIES", "10") or 10)
    ranked = sorted(results, key=lambda r: (r.market_score, r.margin, r.profit), reverse=True)
    selected = ranked[:max_messages]
    if not selected:
        return True

    success = True
    if len(results) > max_messages:
        summary = (
            f"[Orlando Land] {len(results)} oportunidades viaveis. "
            f"Enviando as {max_messages} melhores por tese/margem/lucro."
        )
        success = _deliver_once(
            "whatsapp",
            summary,
            lambda: _maybe_send_zapi_whatsapp(summary),
            delivery_store,
        ) and success
    for result in selected:
        message = _format_whatsapp_result(result)
        success = _deliver_once(
            "whatsapp",
            message,
            lambda message=message: _maybe_send_zapi_whatsapp(message),
            delivery_store,
        ) and success
    return success


def _maybe_send_email(subject: str, message: str) -> bool:
    host = env("SMTP_HOST")
    to_addr = env("ALERT_EMAIL_TO")
    if not host or not to_addr:
        return True
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
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[email] falhou: {type(exc).__name__}")
        return False


def _maybe_send_telegram(message: str) -> bool:
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return True
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=30,
        )
        resp.raise_for_status()
        print("[telegram] enviado")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] falhou: {type(exc).__name__}")
        return False


def _maybe_send_zapi_whatsapp(message: str) -> bool:
    instance_id = env("ZAPI_INSTANCE_ID")
    instance_token = env("ZAPI_INSTANCE_TOKEN")
    client_token = env("ZAPI_CLIENT_TOKEN")
    phone = env("ZAPI_PHONE")
    if not all([instance_id, instance_token, phone]):
        return True

    url = (
        "https://api.z-api.io/instances/"
        f"{instance_id}/token/{instance_token}/send-text"
    )
    headers = {"Content-Type": "application/json"}
    if client_token:
        headers["Client-Token"] = client_token

    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"phone": phone, "message": message},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"[whatsapp] enviado para {phone}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[whatsapp] falhou: {type(exc).__name__}")
        return False
