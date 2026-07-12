"""Resumo diário: sinal de vida + consolidação das últimas 24h.

Pensado para rodar 1x por dia (workflow summary.yml às 8h de Orlando),
separado da varredura de hora em hora. Sempre envia — mesmo sem
oportunidade nova — para que silêncio no WhatsApp nunca deixe dúvida
de que o sistema está rodando.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone

from .config import Config
from .notifier import send_message


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recent_rows(path: str, cutoff: datetime) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if (dt := _parse_dt(r.get("found_at", ""))) and dt >= cutoff]


def build_message(cfg: Config, now: datetime | None = None) -> tuple[str, str]:
    """Monta (assunto, corpo) do resumo. Sempre produz mensagem."""
    now = now or datetime.now(timezone.utc)
    output_cfg = cfg.raw.get("output", {})
    hours = float(cfg.raw.get("summary", {}).get("period_hours", 24))
    cutoff = now - timedelta(hours=hours)

    evals = _recent_rows(output_cfg.get("evaluations_csv_path", "evaluations.csv"), cutoff)
    opps = _recent_rows(output_cfg.get("csv_path", "opportunities.csv"), cutoff)
    radar = [r for r in evals if (r.get("review_status") or "").startswith("radar")]

    lines = [
        f"Bom dia! Orlando Land — últimas {hours:.0f}h:",
        "",
        f"Terrenos novos avaliados: {len(evals)}",
        f"Oportunidades viáveis: {len(opps)}",
        f"No radar (revisão manual): {len(radar)}",
    ]

    if opps:
        opps.sort(key=lambda r: float(r.get("margin", 0) or 0), reverse=True)
        lines.append("")
        lines.append("Melhores do dia:")
        for r in opps[:5]:
            margin = float(r.get("margin", 0) or 0)
            lines.append(
                f"• {r.get('address') or r.get('id')} — "
                f"terreno US$ {_money(r.get('land_price'))}, "
                f"lucro US$ {_money(r.get('profit'))} (margem {margin:.1%})"
            )
            if r.get("url"):
                lines.append(f"  {r['url']}")
    elif not evals:
        lines.append("")
        lines.append("Nenhuma listagem nova apareceu na janela — mercado parado, sistema de pé.")

    dashboard = os.environ.get("DASHBOARD_URL", "").strip()
    if dashboard:
        lines.extend(["", f"Dashboard: {dashboard}"])

    subject = f"[Orlando Land] Resumo diário — {len(opps)} oportunidade(s)"
    return subject, "\n".join(lines)


def build_and_send(dry_run: bool = False) -> None:
    subject, body = build_message(Config.load())
    send_message(subject, body, dry_run=dry_run)


def _money(value: str | None) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value or "?")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Resumo diário das oportunidades.")
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra no console mas não envia para os canais")
    args = parser.parse_args()
    build_and_send(dry_run=args.dry_run)
