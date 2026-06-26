"""Resumo diário: consolida as oportunidades do CSV e envia por e-mail/Telegram.

Pensado para rodar 1x por dia no cron, separado da varredura de hora em hora.
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


def build_and_send(dry_run: bool = False) -> None:
    cfg = Config.load()
    csv_path = cfg.raw.get("output", {}).get("csv_path", "opportunities.csv")
    hours = float(cfg.raw.get("summary", {}).get("period_hours", 24))

    if not os.path.exists(csv_path):
        print(f"[resumo] sem CSV ({csv_path}); nada a resumir.")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    recent = [r for r in rows if (dt := _parse_dt(r.get("found_at", ""))) and dt >= cutoff]

    if not recent:
        print(f"[resumo] nenhuma oportunidade nas últimas {hours:.0f}h.")
        return

    # Ordena pela maior margem primeiro.
    recent.sort(key=lambda r: float(r.get("margin", 0) or 0), reverse=True)

    lines = [f"Resumo das últimas {hours:.0f}h — {len(recent)} oportunidade(s) viável(is):", ""]
    for r in recent:
        margin = float(r.get("margin", 0) or 0)
        lines.append(
            f"• {r.get('address') or r.get('id')} — "
            f"terreno US$ {_money(r.get('land_price'))}, "
            f"lucro US$ {_money(r.get('profit'))} (margem {margin:.1%}), "
            f"{r.get('distance_km')} km"
        )
        if r.get("url"):
            lines.append(f"  {r['url']}")

    subject = f"[Orlando Land] Resumo diário — {len(recent)} oportunidade(s)"
    send_message(subject, "\n".join(lines), dry_run=dry_run)


def _money(value: str | None) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value or "?")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Resumo diário das oportunidades.")
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra no console mas não envia e-mail/Telegram")
    args = parser.parse_args()
    build_and_send(dry_run=args.dry_run)
