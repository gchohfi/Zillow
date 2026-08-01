"""Gera o dashboard estático (site/index.html) a partir dos CSVs.

Pensado para rodar logo após a varredura (local ou GitHub Actions) e ser
publicado no GitHub Pages, para a empresa acompanhar as oportunidades por link.

O layout é otimizado para triagem: cartões de oportunidade ranqueados no topo
(o que o captador precisa ver primeiro), reprovadas fora do caminho.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .memo import build_memo_html, memo_slug
from .region_signals import cached_signals_for_zips

MAX_EMBEDDED_ROWS = 1000

_ROW_FIELDS = (
    "found_at",
    "review_status",
    "review_reason",
    "reasons",
    "is_viable",
    "tier",
    "zip_code",
    "county",
    "cadastral_use",
    "cadastral_use_code",
    "cadastral_use_source",
    "cadastral_use_status",
    "market_priority",
    "market_region",
    "market_score",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    "address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "lot_size_sqft",
    "lot_size_acres",
    "price_per_acre",
    "development_profile",
    "gross_acres",
    "estimated_net_developable_acres",
    "net_developable_pct",
    "net_estimate_confidence",
    "due_diligence_status",
    "due_diligence_completion_pct",
    "due_diligence_recommendation",
    "evidence_status",
    "pending_confirmations",
    "entitlement_stage",
    "rules_as_of",
    "parcel_id",
    "owner_name",
    "jurisdiction",
    "future_land_use",
    "electric_utility",
    "water_utility",
    "sewer_utility",
    "access_authority",
    "environmental_authority",
    "sources_consulted",
    "net_area_scenarios",
    "price_per_net_acre",
    "arv",
    "arv_source",
    "total_cost",
    "profit",
    "margin",
    "margin_stress",
    "land_to_total_investment",
    "rent_monthly",
    "noi_annual",
    "cap_rate",
    "dscr",
    "cash_on_cash",
    "sensitivity_top",
    "flood_zone",
    "zoning",
    "url",
    "id",
)

_FLOAT_FIELDS = {
    "lat", "lng", "distance_km", "land_price", "lot_size_sqft",
    "lot_size_acres", "price_per_acre", "arv", "total_cost",
    "profit", "margin", "margin_stress", "land_to_total_investment",
    "growth_score", "market_score",
    "rent_monthly", "noi_annual", "cap_rate", "dscr", "cash_on_cash",
    "gross_acres", "estimated_net_developable_acres", "net_developable_pct",
    "due_diligence_completion_pct", "price_per_net_acre",
}


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_rows(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _status_of(row: dict) -> str:
    status = str(row.get("review_status") or "").strip()
    if status:
        return status
    return "viavel" if str(row.get("is_viable", "")).lower() in {"yes", "true", "1"} else "reprovado"


def _normalize(row: dict) -> dict:
    out: dict = {}
    for field in _ROW_FIELDS:
        value = row.get(field, "")
        if field in _FLOAT_FIELDS:
            out[field] = _to_float(value)
        else:
            out[field] = str(value or "")
    out["review_status"] = _status_of(row)
    # A trilha completa de diligência só interessa nos cartões (viável/radar);
    # zerar nas reprovadas mantém o HTML pequeno mesmo com histórico grande.
    if out["review_status"] == "reprovado" or out["review_status"].startswith("reprovado"):
        out["reasons"] = ""
    return out


def build_payload(cfg: Config, now: datetime | None = None) -> dict:
    """Monta o payload de dados embutido no HTML."""
    now = now or datetime.now(timezone.utc)
    output_cfg = cfg.raw.get("output", {})
    site_cfg = cfg.raw.get("site", {})
    period_days = float(site_cfg.get("period_days", 30) or 30)

    rows = _load_rows(output_cfg.get("evaluations_csv_path", "evaluations.csv"))
    source = "evaluations"
    if not rows:
        rows = _load_rows(output_cfg.get("csv_path", "opportunities.csv"))
        source = "opportunities"

    cutoff = now - timedelta(days=period_days)
    recent = []
    for row in rows:
        dt = _parse_dt(row.get("found_at", ""))
        if dt is None or dt >= cutoff:
            recent.append(_normalize(row))
    recent.sort(key=lambda r: r.get("found_at") or "", reverse=True)

    total = len(recent)
    embedded = recent[:MAX_EMBEDDED_ROWS]
    if total > MAX_EMBEDDED_ROWS:
        print(f"[site] {total - MAX_EMBEDDED_ROWS} linha(s) antigas fora do HTML (limite {MAX_EMBEDDED_ROWS})")

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "period_days": period_days,
        "source": source,
        "total_rows": total,
        "rows": embedded,
        "regions": _merge_thesis_regions(_aggregate_regions(embedded), cfg),
    }


def _aggregate_regions(rows: list[dict]) -> list[dict]:
    """Agrega os sinais de crescimento por ZIP para os cards do dashboard.

    As linhas chegam ordenadas da mais recente para a mais antiga, então o
    primeiro valor visto de cada campo é o mais atual.
    """
    by_zip: dict[str, dict] = {}
    for row in rows:
        zip_code = row.get("zip_code") or ""
        if not zip_code:
            continue
        group = by_zip.setdefault(zip_code, {
            "zip": zip_code,
            "region": "",
            "priority": "",
            "growth_score": None,
            "growth_signals": "",
            "viable": 0,
            "radar": 0,
            "total": 0,
        })
        group["total"] += 1
        status = row.get("review_status", "")
        if status == "viavel":
            group["viable"] += 1
        elif status.startswith("radar_"):
            group["radar"] += 1
        if not group["region"] and row.get("market_region"):
            group["region"] = row["market_region"]
        if not group["priority"] and row.get("market_priority"):
            group["priority"] = row["market_priority"]
        if group["growth_score"] is None and row.get("growth_score") is not None:
            group["growth_score"] = row["growth_score"]
            group["growth_signals"] = row.get("growth_signals", "")
    return sorted(
        by_zip.values(),
        key=lambda g: (g["growth_score"] is not None, g["growth_score"] or 0, g["viable"]),
        reverse=True,
    )


def _merge_thesis_regions(regions: list[dict], cfg: Config) -> list[dict]:
    """Completa a seção de regiões com os ZIPs das teses já em cache.

    Assim o potencial da região aparece no dashboard mesmo antes de surgir
    uma oportunidade naquele ZIP (o pipeline pré-carrega o cache).
    """
    zip_meta: dict[str, tuple[str, str]] = {}
    for group in cfg.raw.get("market_strategy", {}).get("zip_groups", []):
        label = group.get("label") or group.get("name") or ""
        priority = group.get("priority", "")
        for zip_code in group.get("zips", []):
            zip_meta[str(zip_code)] = (label, priority)
    if not zip_meta:
        return regions

    cached = cached_signals_for_zips(list(zip_meta), cfg)
    by_zip = {group["zip"]: group for group in regions}
    for zip_code, signals in cached.items():
        if signals.get("score") is None:
            continue
        entry = by_zip.get(zip_code)
        if entry is None:
            entry = {
                "zip": zip_code,
                "region": "",
                "priority": "",
                "growth_score": None,
                "growth_signals": "",
                "viable": 0,
                "radar": 0,
                "total": 0,
            }
            by_zip[zip_code] = entry
        if entry["growth_score"] is None:
            entry["growth_score"] = signals.get("score")
            entry["growth_signals"] = "; ".join(signals.get("summary", []))
        label, priority = zip_meta[zip_code]
        if not entry["region"]:
            entry["region"] = label
        if not entry["priority"]:
            entry["priority"] = priority
    return sorted(
        by_zip.values(),
        key=lambda g: (g["growth_score"] is not None, g["growth_score"] or 0, g["viable"]),
        reverse=True,
    )


def generate_site(cfg: Config | None = None, out_dir: str | None = None) -> Path:
    """Gera o site estático e retorna o caminho do index.html."""
    cfg = cfg or Config.load()
    site_cfg = cfg.raw.get("site", {})
    out_dir = out_dir or site_cfg.get("dir", "site")
    payload = build_payload(cfg)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html = _TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    index = out / "index.html"
    index.write_text(html, encoding="utf-8")

    # O mesmo payload em JSON puro, para apps externos (Lovable, planilhas,
    # scripts) consumirem sem parsear HTML. GitHub Pages serve com CORS
    # aberto, então qualquer front-end consegue buscar direto.
    (out / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # Publica também os CSVs para download direto pelo link do dashboard.
    output_cfg = cfg.raw.get("output", {})
    for key in ("csv_path", "evaluations_csv_path"):
        path = output_cfg.get(key)
        if path and os.path.exists(path):
            shutil.copy(path, out / Path(path).name)

    # Memorando de decisão por oportunidade viável/radar da janela.
    memo_dir = out / "memo"
    memo_dir.mkdir(exist_ok=True)
    n_memos = 0
    for row in payload["rows"]:
        status = str(row.get("review_status") or "")
        if status == "viavel" or status.startswith("radar"):
            slug = memo_slug(str(row.get("id") or ""))
            (memo_dir / f"{slug}.html").write_text(
                build_memo_html(row, generated_at=payload.get("generated_at")),
                encoding="utf-8",
            )
            row["memo"] = f"memo/{slug}.html"
            n_memos += 1

    # Regrava o payload com os links de memo incluídos.
    html = _TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    index.write_text(html, encoding="utf-8")
    (out / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"[site] dashboard gerado em {index} ({payload['total_rows']} avaliações, "
          f"últimos {payload['period_days']:.0f} dias, {n_memos} memo(s))")
    return index


_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orlando Land Detector — Oportunidades</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%231769d2'/%3E%3Ctext x='32' y='40' text-anchor='middle' font-family='Arial' font-size='24' font-weight='700' fill='white'%3EOL%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  :root {
    --surface-1: #ffffff;
    --page: #f5f7fa;
    --text-primary: #101828;
    --text-secondary: #475467;
    --text-muted: #7b8798;
    --grid: #eef1f5;
    --border: #e4e7ec;
    --status-good: #168457;
    --status-good-text: #116c49;
    --status-good-wash: #eaf7f0;
    --status-warning: #e2a126;
    --status-warning-text: #9a6500;
    --status-warning-wash: #fff7e6;
    --status-critical: #c63d38;
    --status-muted: #98a2b3;
    --accent: #1769d2;
    --accent-strong: #0f58b5;
    --accent-wash: #eaf2fd;
    --meter-track: #e6eef8;
    --meter-fill: #2774d8;
    --chip-bg: #f2f4f7;
    --shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.04);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  button, input, select { font: inherit; }
  button { color: inherit; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
  }
  .app-shell { min-height: 100vh; display: flex; }
  .sidebar {
    width: 224px; flex: 0 0 224px; min-height: 100vh; padding: 22px 16px 18px;
    background: var(--surface-1); border-right: 1px solid var(--border);
    position: sticky; top: 0; align-self: flex-start; height: 100vh;
    display: flex; flex-direction: column; z-index: 30;
  }
  .brand { display: flex; align-items: center; gap: 11px; padding: 0 8px 24px; }
  .brand-mark {
    width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center;
    color: #fff; background: linear-gradient(145deg, #2679dd, #1255b5);
    box-shadow: 0 6px 16px rgba(23,105,210,.22); font-weight: 800; letter-spacing: -.5px;
  }
  .brand-copy strong { display: block; font-size: 14px; letter-spacing: -.1px; }
  .brand-copy span { color: var(--text-muted); font-size: 11px; }
  .side-label { margin: 10px 10px 7px; color: var(--text-muted); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
  .side-nav { display: grid; gap: 3px; }
  .side-nav a {
    min-height: 42px; padding: 0 11px; border-radius: 8px; display: flex; align-items: center; gap: 10px;
    color: var(--text-secondary); font-size: 13px; font-weight: 600;
  }
  .side-nav a:hover { text-decoration: none; background: #f7f9fc; color: var(--text-primary); }
  .side-nav a.active { color: var(--accent); background: var(--accent-wash); }
  .nav-icon { width: 18px; text-align: center; color: currentColor; font-size: 12px; }
  .sidebar-foot { margin-top: auto; padding: 16px 9px 0; border-top: 1px solid var(--grid); color: var(--text-muted); font-size: 11px; }
  .app-main { flex: 1; min-width: 0; }
  .topbar {
    min-height: 64px; padding: 10px 28px; background: rgba(255,255,255,.96); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 18px; position: sticky; top: 0; z-index: 25; backdrop-filter: blur(10px);
  }
  .breadcrumb { color: var(--text-muted); font-size: 12px; white-space: nowrap; }
  .breadcrumb strong { color: var(--text-secondary); font-weight: 600; }
  .topbar-actions { margin-left: auto; display: flex; align-items: center; gap: 9px; min-width: 0; }
  .search-wrap { position: relative; min-width: 220px; }
  .search-wrap::before { content: "⌕"; position: absolute; left: 12px; top: 8px; color: var(--text-muted); font-size: 17px; pointer-events: none; }
  #search {
    width: 100%; min-height: 40px; padding: 8px 12px 8px 35px; border: 1px solid var(--border);
    border-radius: 8px; background: #fbfcfe; color: var(--text-primary); font-size: 12px;
  }
  .top-action, .primary-action {
    min-height: 40px; padding: 0 13px; border-radius: 8px; border: 1px solid var(--border);
    display: inline-flex; align-items: center; justify-content: center; gap: 7px;
    background: var(--surface-1); color: var(--text-secondary); font-size: 12px; font-weight: 700; white-space: nowrap;
  }
  .top-action:hover { text-decoration: none; border-color: #cdd4df; color: var(--text-primary); }
  .primary-action { color: #fff; background: var(--accent); border-color: var(--accent); }
  .primary-action:hover { text-decoration: none; color: #fff; background: var(--accent-strong); }
  .content { width: 100%; max-width: 1560px; margin: 0 auto; padding: 29px 28px 52px; }
  .page-head { margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
  .eyebrow { color: var(--accent); font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .09em; margin-bottom: 7px; }
  .page-head h1 { margin: 0; font-size: clamp(23px, 2.3vw, 31px); line-height: 1.18; letter-spacing: -.035em; }
  .page-head p { margin: 7px 0 0; color: var(--text-secondary); font-size: 13px; }
  .scan-meta { padding-top: 5px; text-align: right; color: var(--text-muted); font-size: 11px; }
  .scan-meta strong { display: block; color: var(--status-good-text); font-size: 12px; }
  .banner-new {
    display: none;
    margin: 16px 0 0; padding: 11px 14px 11px 42px; border-radius: 9px; position: relative;
    background: var(--accent-wash);
    border: 1px solid #c9ddf8; color: #174f94; font-weight: 650; font-size: 12px;
  }
  .banner-new::before { content: "N"; position: absolute; left: 14px; top: 9px; width: 21px; height: 21px; border-radius: 6px; display: grid; place-items: center; background: var(--accent); color: white; font-size: 10px; font-weight: 800; }
  .kpis {
    display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); margin: 20px 0 18px;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 11px;
    box-shadow: var(--shadow); overflow: hidden;
  }
  .kpi {
    min-height: 91px; padding: 18px 20px; display: flex; flex-direction: column; justify-content: center;
    border-left: 1px solid var(--grid);
  }
  .kpi:first-child { border-left: 0; }
  .kpi .value { font-size: 24px; line-height: 1; font-weight: 760; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
  .kpi .label { margin-top: 8px; color: var(--text-muted); font-size: 11px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 0 0 18px; }
  .controls-spacer { flex: 1; }
  .chip {
    border: 1px solid var(--border);
    background: var(--surface-1);
    color: var(--text-secondary);
    border-radius: 8px; padding: 0 13px; min-height: 38px;
    display: inline-flex; align-items: center; cursor: pointer; font-size: 12px; font-weight: 650;
  }
  .chip:hover { border-color: #c7d0dc; }
  .chip.active { border-color: #bad2f1; background: var(--accent-wash); color: var(--accent-strong); }
  select#sort, select#min-margin {
    padding: 8px 34px 8px 11px; min-height: 38px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    color: var(--text-primary);
    font-size: 12px;
  }
  .chip:focus-visible, .show-more:focus-visible, #search:focus-visible,
  select:focus-visible, .opp-star:focus-visible, .opp-dismiss:focus-visible,
  summary:focus-visible, a:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, .88fr); gap: 18px; align-items: start; }
  .panel {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 11px;
    box-shadow: var(--shadow); overflow: hidden;
  }
  .panel-head { padding: 17px 18px 13px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .panel-head h2 { font-size: 14px; margin: 0; letter-spacing: -.012em; }
  .panel-head .hint { color: var(--text-muted); font-size: 11px; margin: 4px 0 0; }
  .panel-count { padding: 4px 8px; border-radius: 999px; background: var(--chip-bg); color: var(--text-muted); font-size: 10px; font-weight: 700; white-space: nowrap; }
  .opportunity-panel { min-width: 0; }
  .opportunity-body { padding: 0 10px 12px; }
  .insights-column { display: grid; gap: 18px; min-width: 0; }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }

  /* ---- Feed de oportunidades (herói) ---- */
  .opps { display: grid; gap: 8px; }
  .opp {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px;
    padding: 13px 14px; display: flex; flex-direction: column; gap: 9px;
    transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
  }
  .opp:hover { border-color: #cfd6e0; box-shadow: 0 7px 20px rgba(16,24,40,.07); transform: translateY(-1px); }
  .opp.viavel { border-left: 3px solid var(--status-good); }
  .opp.radar { border-left: 3px solid var(--status-warning); }
  .opp-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .opp-head .when { margin-left: auto; color: var(--text-muted); font-size: 12px; white-space: nowrap; }
  .tag-new {
    background: var(--accent-wash); color: var(--accent-strong); border: 1px solid #cbdff8;
    font-size: 9px; font-weight: 800; border-radius: 999px; padding: 2px 7px; letter-spacing: .06em;
  }
  .opp-title { font-size: 14px; font-weight: 760; line-height: 1.3; letter-spacing: -.01em; }
  .opp-sub { margin-top: 2px; color: var(--text-muted); font-size: 11px; }
  .opp-stats {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
    padding: 10px 0; border-top: 1px solid var(--grid); border-bottom: 1px solid var(--grid);
  }
  .stat { min-width: 0; padding: 0 11px; border-left: 1px solid var(--grid); }
  .stat:first-child { padding-left: 0; border-left: 0; }
  .stat .l { color: var(--text-muted); font-size: 9px; text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; }
  .stat .v { margin-top: 2px; font-size: 13px; font-weight: 720; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .opp-alert { font-size: 11px; color: var(--status-warning-text); }
  .opp-alert.ok { color: var(--status-good-text); }
  .opp-actions { display: flex; gap: 13px; flex-wrap: wrap; margin-top: auto; }
  .opp-actions a {
    min-height: 28px; display: inline-flex; align-items: center;
    font-size: 11px; font-weight: 700;
  }
  .opp-group {
    font-size: 10px; font-weight: 800; color: var(--text-muted);
    margin: 14px 5px 7px; text-transform: uppercase; letter-spacing: .08em;
  }
  .opp-group:first-child { margin-top: 2px; }
  .opp-group .count { color: var(--text-muted); font-weight: 500; text-transform: none; }
  .opp-star, .opp-dismiss {
    border: none; background: transparent; cursor: pointer; border-radius: 6px;
    font-size: 14px; color: var(--text-muted); padding: 0;
    min-width: 28px; min-height: 28px;
    display: inline-flex; align-items: center; justify-content: center;
  }
  .opp-star:hover, .opp-dismiss:hover { color: var(--accent); background: var(--accent-wash); }
  .opp-star.on { color: var(--status-warning); }
  .opp.starred { border-color: var(--accent); }
  .opp-diligence { margin-top: 2px; }
  .opp-diligence summary {
    cursor: pointer; font-size: 11px; font-weight: 700;
    color: var(--accent); list-style: none;
  }
  .opp-diligence summary::-webkit-details-marker { display: none; }
  .opp-diligence summary::before { content: "▸ "; }
  .opp-diligence[open] summary::before { content: "▾ "; }
  .opp-diligence ul { margin: 6px 0 0; padding-left: 4px; list-style: none; }
  .opp-diligence li { font-size: 12px; padding: 3px 0; border-top: 1px dashed var(--grid); }
  .opp-diligence li:first-child { border-top: none; }
  .chk-ok { color: var(--status-good-text); }
  .chk-bad { color: var(--status-critical, #d03b3b); }
  .chk-warn { color: var(--status-warning-text); }
  .dismissed-note {
    margin-top: 8px; font-size: 11px; color: var(--text-muted);
    background: none; border: none; cursor: pointer; padding: 8px 4px;
  }
  .dismissed-note:hover { color: var(--accent); }
  .show-more {
    margin: 10px 0 0;
    width: 100%;
    padding: 9px;
    border: 1px dashed var(--border);
    border-radius: 8px;
    background: none;
    color: var(--accent);
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
  }

  .badge { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 3px 8px; font-size: 10px; white-space: nowrap; }
  .badge .dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
  .badge.viavel .dot { background: var(--status-good); }
  .badge.viavel { color: var(--status-good-text); background: var(--status-good-wash); font-weight: 700; }
  .badge.radar .dot { background: var(--status-warning); }
  .badge.radar { color: var(--status-warning-text); background: var(--status-warning-wash); font-weight: 700; }
  .badge.reprovado .dot { background: var(--status-muted); }
  .badge.reprovado { color: var(--text-muted); background: var(--chip-bg); }

  .map-wrap { border-top: 1px solid var(--grid); }
  #map { height: 320px; background: #edf2f6; }
  .map-legend { display: flex; flex-wrap: wrap; gap: 13px; padding: 10px 15px 13px; color: var(--text-muted); font-size: 10px; border-top: 1px solid var(--grid); }
  .map-legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
  .legend-dot.good { background: var(--status-good); }
  .legend-dot.warning { background: var(--status-warning); }
  .legend-dot.muted { background: var(--status-muted); }
  .regions { display: grid; gap: 0; border-top: 1px solid var(--grid); }
  .region-card {
    background: var(--surface-1); border-top: 1px solid var(--grid); padding: 12px 16px;
    display: grid; grid-template-columns: minmax(105px, 1.2fr) minmax(95px, .8fr); gap: 8px 14px; align-items: center;
  }
  .region-card:first-child { border-top: 0; }
  .region-card .zip { font-size: 12px; font-weight: 760; }
  .region-card .name { color: var(--text-muted); font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meter-row { display: flex; align-items: center; gap: 8px; }
  .meter { flex: 1; height: 6px; border-radius: 4px; background: var(--meter-track); overflow: hidden; }
  .meter > span { display: block; height: 100%; border-radius: 4px; background: var(--meter-fill); }
  .meter-value { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .sig-chips { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 4px; }
  .sig-chip {
    background: var(--chip-bg);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 2px 7px;
    font-size: 9px;
    white-space: nowrap;
  }
  .region-card .counts { grid-column: 1 / -1; color: var(--text-muted); font-size: 9px; }

  .comparison-panel { margin-top: 18px; }
  details.tbl { margin-top: 18px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow); }
  details.tbl > summary {
    cursor: pointer; font-size: 12px; font-weight: 700; padding: 14px 16px; color: var(--text-secondary);
  }
  .table-scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; min-width: 980px; }
  th, td { text-align: left; padding: 8px 10px; border-top: 1px solid var(--grid); vertical-align: top; }
  thead th {
    border-top: none;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 600;
    position: sticky; top: 0;
    background: var(--surface-1);
  }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .links a { margin-right: 8px; white-space: nowrap; }
  .muted { color: var(--text-muted); }
  .small { font-size: 12px; }
  .empty { padding: 24px; color: var(--text-muted); text-align: center; }
  .growth-cell { min-width: 110px; }
  .growth-cell .meter { height: 6px; }
  footer { margin-top: 18px; padding: 19px 4px 0; color: var(--text-muted); font-size: 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 15px; }
  footer a { font-weight: 700; }
  footer span { flex: 1 1 440px; text-align: right; }
  @media (max-width: 1180px) {
    .sidebar { width: 76px; flex-basis: 76px; padding-inline: 10px; }
    .brand { padding-inline: 11px; }
    .brand-copy, .side-label, .side-nav a span:not(.nav-icon), .sidebar-foot { display: none; }
    .side-nav a { justify-content: center; padding: 0; }
    .dashboard-grid { grid-template-columns: minmax(0, 1fr) minmax(300px, .72fr); }
    .kpi { padding-inline: 14px; }
  }
  @media (max-width: 920px) {
    .dashboard-grid { grid-template-columns: 1fr; }
    .insights-column { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .kpis { grid-template-columns: repeat(3, 1fr); }
    .kpi { border-top: 1px solid var(--grid); }
    .kpi:nth-child(-n+3) { border-top: 0; }
    .kpi:nth-child(4) { border-left: 0; }
  }
  @media (max-width: 720px) {
    .app-shell { display: block; }
    .sidebar { width: auto; min-height: 0; height: auto; position: static; padding: 10px 14px; border-right: 0; border-bottom: 1px solid var(--border); }
    .brand { padding: 0; }
    .brand-copy { display: block; }
    .side-label, .sidebar-foot { display: none; }
    .side-nav { display: flex; overflow-x: auto; margin-top: 10px; padding-bottom: 2px; }
    .side-nav a { flex: 0 0 auto; min-height: 35px; padding: 0 11px; }
    .side-nav a span:not(.nav-icon) { display: inline; }
    .topbar { position: static; padding: 10px 14px; flex-wrap: wrap; gap: 8px; }
    .breadcrumb { width: 100%; }
    .topbar-actions { width: 100%; margin: 0; }
    .search-wrap { flex: 1; min-width: 120px; }
    .top-action { padding-inline: 10px; }
    .content { padding: 22px 14px 38px; }
    .page-head { display: block; }
    .scan-meta { margin-top: 11px; text-align: left; }
    .kpis { display: flex; overflow-x: auto; scroll-snap-type: x proximity; }
    .kpi { flex: 0 0 142px; border-top: 0; scroll-snap-align: start; }
    .controls { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; }
    .controls-spacer { display: none; }
    .chip, select#sort, select#min-margin { flex: 0 0 auto; }
    .insights-column { grid-template-columns: 1fr; }
    .opp-stats { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px 0; }
    .stat:nth-child(odd) { border-left: 0; padding-left: 0; }
    .panel-head { padding-inline: 14px; }
    footer span { text-align: left; }
  }
</style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar" aria-label="Navegação principal">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">OL</div>
      <div class="brand-copy"><strong>Land Detector</strong><span>Orlando · Florida</span></div>
    </div>
    <div class="side-label">Workspace</div>
    <nav class="side-nav">
      <a class="active" href="#visao-geral"><span class="nav-icon">01</span><span>Visão geral</span></a>
      <a href="#oportunidades"><span class="nav-icon">02</span><span>Oportunidades</span></a>
      <a href="#mapa"><span class="nav-icon">03</span><span>Mapa</span></a>
      <a href="#regioes"><span class="nav-icon">04</span><span>Regiões</span></a>
      <a href="#avaliacoes"><span class="nav-icon">05</span><span>Avaliações</span></a>
    </nav>
    <div class="side-label">Dados</div>
    <nav class="side-nav">
      <a href="opportunities.csv" download><span class="nav-icon">CSV</span><span>Oportunidades</span></a>
      <a href="evaluations.csv" download><span class="nav-icon">CSV</span><span>Avaliações</span></a>
    </nav>
    <div class="sidebar-foot">Radar automatizado de terrenos para spec build.</div>
  </aside>

  <div class="app-main">
    <header class="topbar">
      <div class="breadcrumb">Portfólio / <strong>Orlando Land Detector</strong></div>
      <div class="topbar-actions">
        <label class="search-wrap"><span class="sr-only">Buscar oportunidades</span><input id="search" type="search" placeholder="Buscar endereço, ZIP ou região"></label>
        <a class="top-action" href="evaluations.csv" download>Exportar CSV</a>
      </div>
    </header>

    <main class="content" id="visao-geral">
      <section class="page-head">
        <div>
          <div class="eyebrow">Radar de oportunidades</div>
          <h1>Orlando Land Detector</h1>
          <p>Terrenos para spec build em um raio de 80 km de Orlando, com viabilidade e sinais de valorização.</p>
        </div>
        <div class="scan-meta"><strong>Varredura concluída</strong>Atualizado em <span id="updated">—</span></div>
      </section>
      <div class="banner-new" id="banner-new"></div>

      <div class="kpis" aria-label="Indicadores do radar">
        <div class="kpi"><span class="value" id="kpi-new24">0</span><span class="label">Novas nas últimas 24h</span></div>
        <div class="kpi"><span class="value" id="kpi-viable">0</span><span class="label">Viáveis para oferta</span></div>
        <div class="kpi"><span class="value" id="kpi-radar">0</span><span class="label">Em diligência</span></div>
        <div class="kpi"><span class="value" id="kpi-margin">—</span><span class="label">Maior margem estimada</span></div>
        <div class="kpi"><span class="value" id="kpi-total">0</span><span class="label" id="kpi-total-label">Avaliadas</span></div>
      </div>

      <div class="controls" aria-label="Filtros de oportunidades">
        <button class="chip active" data-status="opp">Oportunidades</button>
        <button class="chip" data-status="viavel">Viáveis</button>
        <button class="chip" data-status="radar">Radar</button>
        <button class="chip" data-status="all">Todas</button>
        <span class="controls-spacer"></span>
        <select id="sort" aria-label="Ordenar oportunidades">
          <option value="rank">Ordem recomendada</option>
          <option value="recent">Mais recentes</option>
          <option value="margin">Maior margem</option>
          <option value="profit">Maior lucro</option>
        </select>
        <select id="min-margin" aria-label="Margem mínima">
          <option value="0">Margem: todas</option>
          <option value="0.15">Margem 15%+</option>
          <option value="0.20">Margem 20%+</option>
          <option value="0.25">Margem 25%+</option>
          <option value="0.30">Margem 30%+</option>
        </select>
      </div>

      <div class="dashboard-grid">
        <section class="panel opportunity-panel" id="oportunidades">
          <div class="panel-head">
            <div><h2>Oportunidades em aberto</h2><p class="hint">Prontas para oferta ou com uma pendência objetiva de diligência.</p></div>
            <span class="panel-count">Ranking dinâmico</span>
          </div>
          <div class="opportunity-body">
            <div id="opp-cards"></div>
            <button class="show-more" id="show-more" style="display:none"></button>
            <button class="dismissed-note" id="dismissed-note" style="display:none"></button>
          </div>
        </section>

        <aside class="insights-column" aria-label="Mapa e regiões">
          <section class="panel" id="mapa">
            <div class="panel-head"><div><h2>Mapa de oportunidades</h2><p class="hint">Clique em um ponto para abrir os indicadores.</p></div></div>
            <div class="map-wrap"><div id="map"></div></div>
            <div class="map-legend"><span><i class="legend-dot good"></i>Viável</span><span><i class="legend-dot warning"></i>Radar</span><span><i class="legend-dot muted"></i>Reprovada</span></div>
          </section>

          <section class="panel" id="sec-regions">
            <div class="panel-head" id="regioes"><div><h2>Crescimento por região</h2><p class="hint">Score combinado por ZIP, de 0 a 10.</p></div></div>
            <div class="regions" id="region-cards"></div>
            <div class="opportunity-body"><button class="show-more" id="show-more-regions" style="display:none"></button></div>
          </section>
        </aside>
      </div>

      <section class="panel comparison-panel" id="sec-compare">
        <div class="panel-head">
          <div><h2>Comparador de oportunidades</h2><p class="hint">Abertas lado a lado, com a mesma base de custos, prazo e dívida.</p></div>
          <span class="panel-count">Ordenado por margem</span>
        </div>
        <div class="table-scroll"><table id="tbl-compare"></table></div>
      </section>

      <details class="tbl" id="avaliacoes">
        <summary>Tabela completa — todas as avaliações do período, inclusive reprovadas</summary>
        <div class="table-scroll"><table id="tbl-all"></table></div>
      </details>

      <footer id="premissas">
        <a href="opportunities.csv" download>Baixar oportunidades</a>
        <a href="evaluations.csv" download>Baixar avaliações</a>
        <span>Valores em USD e estimativas para triagem. Confirme título, zoneamento, infraestrutura e comps antes de investir.</span>
      </footer>
    </main>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const DATA = __DATA__;

const fmtMoney = v => (v == null || isNaN(v)) ? "n/d" :
  "US$ " + Math.round(v).toLocaleString("pt-BR");
const fmtPct = v => (v == null || isNaN(v)) ? "n/d" : (v * 100).toFixed(1) + "%";
const fmtKm = v => (v == null || isNaN(v)) ? "?" : Math.round(v) + " km";
const fmtDate = iso => {
  const d = new Date(iso);
  return isNaN(d) ? (iso || "n/d") : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
};
const fmtAgo = iso => {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const h = (Date.now() - d.getTime()) / 3600000;
  if (h < 1) return "há " + Math.max(1, Math.round(h * 60)) + " min";
  if (h < 48) return "há " + Math.round(h) + " h";
  return "há " + Math.round(h / 24) + " dias";
};
const statusKind = s => s === "viavel" ? "viavel" : (s || "").startsWith("radar_") ? "radar" : "reprovado";
const statusLabel = s => ({
  viavel: "Viável",
  radar_zoneamento_pendente: "Radar · Zoneamento",
  radar_analise_manual: "Radar · Análise manual",
  radar_desenvolvimento: "Radar · Desenvolvimento",
  radar_valorizacao: "Radar · Valorização",
}[s] || (statusKind(s) === "radar" ? "Radar" : "Reprovada"));

const NOW = new Date(DATA.generated_at).getTime() || Date.now();
const isNew = r => {
  const t = new Date(r.found_at).getTime();
  return t && (NOW - t) < 24 * 3600000;
};
const rankOf = r => {
  const g = growthOf(r);
  const base = r.kind === "viavel" ? 2 : r.kind === "radar" ? 1 : 0;
  const q = 0.5 * Math.min((r.margin || 0) / 0.25, 1)
          + 0.3 * ((g ? g.score : 0) / 10)
          + 0.2 * ((r.market_score != null ? r.market_score : 0) / 10);
  const cadastralBonus = r.review_status === "radar_zoneamento_pendente"
    ? (/residential/i.test(r.cadastral_use || "") ? 0.20 : (r.cadastral_use ? 0.05 : 0))
    : 0;
  return base + q + cadastralBonus + (isNew(r) ? 0.3 : 0);
};

const regionByZip = {};
(DATA.regions || []).forEach(g => { if (g.growth_score != null) regionByZip[g.zip] = g; });

// Score de crescimento da linha, com fallback para o score do ZIP
// (pré-carregado das regiões-alvo) quando a avaliação não tem o próprio.
const growthOf = r => {
  if (r.growth_score != null) return { score: r.growth_score, signals: r.growth_signals };
  const g = regionByZip[r.zip_code];
  return g ? { score: g.growth_score, signals: g.growth_signals } : null;
};

const rows = DATA.rows.map(r => ({ ...r, kind: statusKind(r.review_status) }));

document.getElementById("updated").textContent = fmtDate(DATA.generated_at);

const viable = rows.filter(r => r.kind === "viavel");
const radar = rows.filter(r => r.kind === "radar");
const opportunities = rows.filter(r => r.kind !== "reprovado");
document.getElementById("kpi-new24").textContent = opportunities.filter(isNew).length;
document.getElementById("kpi-viable").textContent = viable.length;
document.getElementById("kpi-radar").textContent = radar.length;
document.getElementById("kpi-total").textContent = DATA.total_rows;
document.getElementById("kpi-total-label").textContent =
  "avaliadas em " + Math.round(DATA.period_days) + " dias";
const candidates = viable.length ? viable : radar;
const best = candidates.reduce((a, r) => (r.margin != null && (!a || r.margin > a.margin)) ? r : a, null);
if (best) document.getElementById("kpi-margin").textContent = fmtPct(best.margin);

// "Novas desde a sua última visita" (memória local do navegador).
try {
  const KEY = "oland-last-visit";
  const last = parseInt(localStorage.getItem(KEY) || "0", 10);
  if (last) {
    const fresh = opportunities.filter(r => new Date(r.found_at).getTime() > last);
    if (fresh.length) {
      const b = document.getElementById("banner-new");
      b.textContent = fresh.length + " nova(s) oportunidade(s) desde a sua última visita";
      b.style.display = "block";
    }
  }
  localStorage.setItem(KEY, String(Date.now()));
} catch (e) { /* navegação privada */ }

function linkParts(r) {
  const links = [];
  if (r.url) links.push(['Anúncio', r.url]);
  if (r.address) {
    const q = encodeURIComponent(r.address);
    links.push(['Zillow', 'https://www.zillow.com/homes/' + q + '_rb/']);
    links.push(['Maps', 'https://www.google.com/maps/search/?api=1&query=' + q]);
    links.push(['Realtor', 'https://www.realtor.com/realestateandhomes-search/' + q]);
  } else if (r.lat != null && r.lng != null) {
    links.push(['Maps', 'https://www.google.com/maps/search/?api=1&query=' + r.lat + ',' + r.lng]);
  }
  // Mapa da Regrid nas coordenadas: com conta Pro mostra dono da parcela
  // e zoneamento — dado-chave para abordagem off-market.
  if (r.lat != null && r.lng != null) {
    links.push(['Regrid', 'https://app.regrid.com/map#ll=' + r.lat + ',' + r.lng + '&z=17']);
  }
  if (r.memo) links.push(['Memo', r.memo]);
  return links;
}
const linkCell = r => linkParts(r).map(([t, u]) =>
  '<a href="' + u + '" target="_blank" rel="noopener">' + t + "</a>").join(" ");

const esc = s => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const SIG_ICONS = [
  [/escola/i, "Escolas"],
  [/comercio/i, "Comércio"],
  [/populacao/i, "População"],
  [/renda/i, "Renda"],
];
function sigChips(signals) {
  if (!signals) return "";
  return signals.split(";").map(s => s.trim()).filter(Boolean).map(s => {
    const category = (SIG_ICONS.find(([re]) => re.test(s)) || [null, "Sinal"])[1];
    return '<span class="sig-chip" title="' + esc(s) + '">' + category + "</span>";
  }).join("");
}

function meterHtml(score) {
  const pct = Math.max(0, Math.min(100, (score / 10) * 100));
  return '<div class="meter-row"><div class="meter"><span style="width:' + pct.toFixed(0) +
    '%"></span></div><span class="meter-value">' + score.toFixed(1) + '</span></div>';
}

function growthCell(r) {
  const g = growthOf(r);
  if (!g) return '<span class="muted small">n/d</span>';
  return '<div class="growth-cell" title="' + esc(g.signals) + '">' +
    meterHtml(g.score) + "</div>";
}

function badge(r) {
  return '<span class="badge ' + r.kind + '" role="status"><span class="dot" aria-hidden="true"></span>' + statusLabel(r.review_status) + '</span>';
}

// ---- Curadoria do captador: descartar / acompanhar (memória do navegador) ----
const DISMISSED_KEY = "oland-dismissed";
const STARRED_KEY = "oland-starred";
let dismissed = new Set();
let starred = new Set();
try {
  dismissed = new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]"));
  starred = new Set(JSON.parse(localStorage.getItem(STARRED_KEY) || "[]"));
} catch (e) { /* navegação privada */ }
let showDismissed = false;

function persistSets() {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed]));
    localStorage.setItem(STARRED_KEY, JSON.stringify([...starred]));
  } catch (e) { /* navegação privada */ }
}

function reasonChecklist(r) {
  if (!r.reasons) return "";
  const items = r.reasons.split("|").map(s => s.trim()).filter(Boolean);
  if (!items.length) return "";
  const rows = items.map(item => {
    const bad = item.startsWith("\\u2717");
    const warn = item.startsWith("\\u26A0");
    const info = item.startsWith("\\u2022");
    const cls = bad ? "chk-bad" : warn ? "chk-warn" : info ? "muted" : "chk-ok";
    return '<li class="' + cls + '">' + esc(item) + "</li>";
  }).join("");
  return '<details class="opp-diligence"><summary>Diligência completa (' +
    items.length + ' itens)</summary><ul>' + rows + "</ul></details>";
}

// ---- Cartões de oportunidade ----
let showAllCards = false;
const CARD_LIMIT = 8;

function oppCard(r) {
  const alert = r.kind === "viavel"
    ? '<div class="opp-alert ok">Pronta para oferta — confirme diligência básica</div>'
    : '<div class="opp-alert">Pendente: ' + esc(r.review_reason || "revisar diligência") + "</div>";
  const g = growthOf(r);
  const growth = g
    ? '<div class="stat" title="' + esc(g.signals) + '"><div class="l">região \\u2191</div><div class="v">' + g.score.toFixed(1) + "/10</div></div>"
    : '<div class="stat"><div class="l">região \\u2191</div><div class="v muted">n/d</div></div>';
  const isStarred = starred.has(r.id);
  const isDismissed = dismissed.has(r.id);
  const isDevelopment = r.review_status === "radar_desenvolvimento";
  const thesisStats = isDevelopment
    ? '<div class="stat"><div class="l">área bruta</div><div class="v">' +
        (r.gross_acres == null ? (r.lot_size_acres == null ? "n/d" : Number(r.lot_size_acres).toFixed(1) + " ac") : Number(r.gross_acres).toFixed(1) + " ac") + "</div></div>" +
      '<div class="stat"><div class="l">líquida preliminar</div><div class="v">' +
        (r.estimated_net_developable_acres == null ? "n/d" : Number(r.estimated_net_developable_acres).toFixed(1) + " ac") +
        '</div><div class="small muted">conf. ' + esc(r.net_estimate_confidence || "n/d") + "</div></div>" +
      '<div class="stat"><div class="l">preço/acre líquido</div><div class="v">' + fmtMoney(r.price_per_net_acre) + "</div></div>" +
      '<div class="stat"><div class="l">diligência</div><div class="v">' +
        (r.due_diligence_completion_pct == null ? "n/d" : Math.round(r.due_diligence_completion_pct * 100) + "%") +
        '</div><div class="small muted">' + esc(r.due_diligence_recommendation || "hold") + "</div></div>"
    : '<div class="stat"><div class="l">lucro est.</div><div class="v">' + fmtMoney(r.profit) + "</div></div>" +
      '<div class="stat"><div class="l">margem</div><div class="v">' + fmtPct(r.margin) +
        (r.margin_stress != null ? '</div><div class="small muted">pess. ' + fmtPct(r.margin_stress) + "</div>" : "</div>") + "</div>";
  return '<article class="opp ' + r.kind + (isStarred ? " starred" : "") + '">' +
    '<div class="opp-head">' + badge(r) +
      (isNew(r) ? '<span class="tag-new">NOVA</span>' : "") +
      '<span class="when">' + fmtAgo(r.found_at) + "</span>" +
      '<button class="opp-star' + (isStarred ? " on" : "") + '" data-id="' + esc(r.id) +
        '" title="' + (isStarred ? "Deixar de acompanhar" : "Acompanhar") + '" aria-label="' +
        (isStarred ? "Deixar de acompanhar oportunidade" : "Acompanhar oportunidade") + '" aria-pressed="' + isStarred + '">' +
        (isStarred ? "\\u2605" : "\\u2606") + "</button>" +
      '<button class="opp-dismiss" data-id="' + esc(r.id) +
        '" title="' + (isDismissed ? "Restaurar" : "Descartar") + '" aria-label="' +
        (isDismissed ? "Restaurar oportunidade" : "Descartar oportunidade") + '">' +
        (isDismissed ? "\\u21BA" : "\\u2715") + "</button>" +
    "</div>" +
    '<div><div class="opp-title">' + esc(r.address || r.id) + "</div>" +
    '<div class="opp-sub">' + esc(r.market_region || "fora das regiões-alvo") +
      (r.zip_code ? " · ZIP " + esc(r.zip_code) : "") +
      (r.cadastral_use ? " · uso cadastral: " + esc(r.cadastral_use) + " (indicativo)" : "") +
      (r.tier ? " · " + esc(r.tier) : "") +
      (r.distance_km != null ? " · " + fmtKm(r.distance_km) : "") + "</div></div>" +
    '<div class="opp-stats">' +
      '<div class="stat"><div class="l">terreno</div><div class="v">' + fmtMoney(r.land_price) + "</div></div>" +
      (!isDevelopment ? '<div class="stat"><div class="l">ARV</div><div class="v">' + fmtMoney(r.arv) + "</div></div>" : "") +
      thesisStats +
      growth +
    "</div>" +
    alert +
    reasonChecklist(r) +
    '<div class="opp-actions">' + linkCell(r) + "</div>" +
  "</article>";
}

function renderCards(visible) {
  const el = document.getElementById("opp-cards");
  const more = document.getElementById("show-more");
  const note = document.getElementById("dismissed-note");

  let cards = visible.filter(r => r.kind !== "reprovado");
  const hiddenCount = cards.filter(r => dismissed.has(r.id)).length;
  if (!showDismissed) cards = cards.filter(r => !dismissed.has(r.id));
  // Favoritos primeiro, preservando a ordenação escolhida dentro dos grupos.
  cards = [...cards].sort((a, b) =>
    (starred.has(b.id) ? 1 : 0) - (starred.has(a.id) ? 1 : 0));

  if (hiddenCount > 0) {
    note.textContent = showDismissed
      ? "Ocultar " + hiddenCount + " descartada(s)"
      : hiddenCount + " oportunidade(s) descartada(s) por você \\u00b7 mostrar";
    note.style.display = "block";
  } else {
    note.style.display = "none";
  }

  if (!cards.length) {
    el.innerHTML = '<div class="card empty">Nenhuma oportunidade em aberto no período/filtro.' +
      (searchTerm ? " Tente limpar a busca." : "") +
      (minMargin > 0 ? " Tente reduzir a margem mínima." : "") +
      " As reprovadas ficam na tabela completa no fim da página.</div>";
    more.style.display = "none";
    return;
  }

  const shown = showAllCards ? cards : cards.slice(0, CARD_LIMIT);
  const ready = shown.filter(r => r.kind === "viavel");
  const pending = shown.filter(r => r.kind === "radar");
  const section = (title, list) => !list.length ? "" :
    '<div class="opp-group">' + title + ' <span class="count">(' + list.length + ")</span></div>" +
    '<div class="opps">' + list.map(oppCard).join("") + "</div>";
  el.innerHTML =
    section("Prontas para oferta", ready) +
    section("Em diligência", pending);

  if (cards.length > CARD_LIMIT && !showAllCards) {
    more.textContent = "Mostrar todas as " + cards.length + " oportunidades";
    more.style.display = "block";
  } else {
    more.style.display = "none";
  }
}
document.getElementById("show-more").addEventListener("click", () => {
  showAllCards = true;
  renderAll();
});
document.getElementById("dismissed-note").addEventListener("click", () => {
  showDismissed = !showDismissed;
  renderAll();
});
// Delegação: estrela e descartar funcionam mesmo com re-render do innerHTML.
document.getElementById("opp-cards").addEventListener("click", event => {
  const star = event.target.closest(".opp-star");
  const dis = event.target.closest(".opp-dismiss");
  if (star) {
    const id = star.dataset.id;
    starred.has(id) ? starred.delete(id) : starred.add(id);
    persistSets();
    renderAll();
  } else if (dis) {
    const id = dis.dataset.id;
    dismissed.has(id) ? dismissed.delete(id) : dismissed.add(id);
    persistSets();
    renderAll();
  }
});
document.getElementById("show-more-regions").addEventListener("click", () => {
  showAllRegions = true;
  renderRegions();
});

// ---- Tabela completa (recolhida) ----
const COLS = [
  { h: "Data", c: r => '<span class="small muted">' + fmtDate(r.found_at) + "</span>" },
  { h: "Status", c: badge },
  { h: "Endereço", c: r => "<b>" + esc(r.address || r.id) + "</b>" +
      (r.review_reason && r.kind !== "viavel" ? '<div class="small muted">' + esc(r.review_reason) + "</div>" : "") },
  { h: "ZIP", c: r => esc(r.zip_code) || '<span class="muted">n/d</span>' },
  { h: "Condado", c: r => esc(r.county) || '<span class="muted">n/d</span>' },
  { h: "Uso cadastral", c: r => r.cadastral_use ? esc(r.cadastral_use) + '<div class="small muted">indicativo · confirmar zoning</div>' : '<span class="muted">n/d</span>' },
  { h: "Mercado", c: r => esc(r.market_priority) +
      (r.market_region ? '<div class="small muted">' + esc(r.market_region) + "</div>" : "") },
  { h: "Segmento", c: r => esc(r.tier) || '<span class="muted">n/d</span>' },
  { h: "Terreno", c: r => fmtMoney(r.land_price), num: true },
  { h: "Área", c: r => r.lot_size_acres == null ? '<span class="muted">n/d</span>' : Number(r.lot_size_acres).toFixed(2) + " ac", num: true },
  { h: "Área líquida", c: r => r.estimated_net_developable_acres == null ? '<span class="muted">n/d</span>' : Number(r.estimated_net_developable_acres).toFixed(2) + " ac", num: true },
  { h: "Diligência", c: r => r.due_diligence_completion_pct == null ? '<span class="muted">n/d</span>' : Math.round(r.due_diligence_completion_pct * 100) + "%", num: true },
  { h: "Preço/acre", c: r => fmtMoney(r.price_per_acre), num: true },
  { h: "Preço/acre líquido", c: r => fmtMoney(r.price_per_net_acre), num: true },
  { h: "ARV", c: r => fmtMoney(r.arv) +
      (r.arv_source === "rentcast_avm" ? '<div class="small muted">comps</div>' : '<div class="small muted">premissa</div>'), num: true },
  { h: "Lucro", c: r => fmtMoney(r.profit), num: true },
  { h: "Margem", c: r => fmtPct(r.margin), num: true },
  { h: "Região ↑", c: growthCell },
  { h: "Dist.", c: r => fmtKm(r.distance_km), num: true },
  { h: "Atenções", c: r => '<span class="small">' + esc(r.risk_flags) + "</span>" },
  { h: "Links", c: r => '<span class="links small">' + linkCell(r) + "</span>" },
];

function renderTable(el, data, emptyMsg) {
  if (!data.length) {
    el.innerHTML = '<tr><td class="empty">' + emptyMsg + "</td></tr>";
    return;
  }
  const head = "<thead><tr>" + COLS.map(c =>
    "<th" + (c.num ? ' class="num"' : "") + ">" + c.h + "</th>").join("") + "</tr></thead>";
  const body = "<tbody>" + data.map(r => "<tr>" + COLS.map(c =>
    "<td" + (c.num ? ' class="num"' : "") + ">" + c.c(r) + "</td>").join("") + "</tr>").join("") + "</tbody>";
  el.innerHTML = head + body;
}

const COMPARE_LIMIT = 12;

function renderCompare() {
  const el = document.getElementById("tbl-compare");
  // Lotes de desenvolvimento ficam de fora: a base deles é preço/acre e
  // densidade, não a margem de casa única — comparar seria enganoso.
  const open = rows
    .filter(r => r.review_status === "viavel" || r.review_status.startsWith("radar"))
    .filter(r => r.review_status !== "radar_desenvolvimento")
    .filter(r => !dismissed.has(r.id))
    .sort((a, b) => (b.margin || -1) - (a.margin || -1))
    .slice(0, COMPARE_LIMIT);
  if (open.length < 2) {
    document.getElementById("sec-compare").style.display = "none";
    return;
  }
  const cols = [
    { h: "Endereço", c: r => (r.memo
        ? '<a href="' + r.memo + '" target="_blank" rel="noopener">' + esc(r.address || r.id) + "</a>"
        : esc(r.address || r.id)) },
    { h: "Status", c: r => r.review_status === "viavel" ? "✓ viável" : "⚠ radar" },
    { h: "Terreno", num: true, c: r => fmtMoney(r.land_price) },
    { h: "Investimento", num: true, c: r => fmtMoney(r.total_cost) },
    { h: "Lucro", num: true, c: r => fmtMoney(r.profit) },
    { h: "Margem", num: true, c: r => fmtPct(r.margin) },
    { h: "Pessimista", num: true, c: r => fmtPct(r.margin_stress) },
    { h: "Cap (renda)", num: true, c: r => fmtPct(r.cap_rate) },
    { h: "DSCR", num: true, c: r => r.dscr == null ? "n/d" : r.dscr.toFixed(2) },
    { h: "Mercado", num: true, c: r => r.market_score == null ? "n/d" : r.market_score.toFixed(1) },
    { h: "Crescimento", num: true, c: r => r.growth_score == null ? "n/d" : r.growth_score.toFixed(1) },
    { h: "Vigiar", c: r => esc((r.sensitivity_top || "").split(";")[0] || "—") },
  ];
  el.innerHTML =
    "<thead><tr>" + cols.map(c =>
      "<th" + (c.num ? ' class="num"' : "") + ">" + c.h + "</th>").join("") + "</tr></thead>" +
    "<tbody>" + open.map(r => "<tr>" + cols.map(c =>
      "<td" + (c.num ? ' class="num"' : "") + ">" + c.c(r) + "</td>").join("") + "</tr>").join("") + "</tbody>";
}

let showAllRegions = false;
const REGION_LIMIT = 8;

function renderRegions() {
  const el = document.getElementById("region-cards");
  const more = document.getElementById("show-more-regions");
  const regions = (DATA.regions || []).filter(g => g.growth_score != null);
  if (!regions.length) {
    document.getElementById("sec-regions").style.display = "none";
    return;
  }
  const shown = showAllRegions ? regions : regions.slice(0, REGION_LIMIT);
  if (regions.length > REGION_LIMIT && !showAllRegions) {
    more.textContent = "Mostrar todas as " + regions.length + " regiões";
    more.style.display = "block";
  } else {
    more.style.display = "none";
  }
  el.innerHTML = shown.map(g =>
    '<div class="region-card">' +
      '<div><span class="zip">' + esc(g.zip) + "</span>" +
      (g.priority ? ' <span class="small muted">' + esc(g.priority) + "</span>" : "") +
      "</div>" +
      '<div class="name">' + esc(g.region || "fora das regiões-alvo mapeadas") + "</div>" +
      meterHtml(g.growth_score) +
      '<div class="sig-chips">' + sigChips(g.growth_signals) + "</div>" +
      '<div class="counts">' + g.viable + " viável(is) · " + g.radar + " radar · " +
      g.total + " avaliação(ões) no período</div>" +
    "</div>"
  ).join("");
}

// ---- Filtros / ordenação ----
let statusFilter = "opp";
let searchTerm = "";
let sortMode = "rank";
let minMargin = 0;

function matches(r) {
  if (statusFilter === "opp" && r.kind === "reprovado") return false;
  if ((statusFilter === "viavel" || statusFilter === "radar") && r.kind !== statusFilter) return false;
  if (minMargin > 0 && (r.margin || 0) < minMargin) return false;
  if (!searchTerm) return true;
  const hay = [r.address, r.zip_code, r.market_region, r.market_priority, r.tier, r.zoning]
    .join(" ").toLowerCase();
  return hay.includes(searchTerm);
}

function sorted(data) {
  const copy = [...data];
  if (sortMode === "recent") copy.sort((a, b) => (b.found_at || "").localeCompare(a.found_at || ""));
  else if (sortMode === "margin") copy.sort((a, b) => (b.margin || 0) - (a.margin || 0));
  else if (sortMode === "profit") copy.sort((a, b) => (b.profit || 0) - (a.profit || 0));
  else copy.sort((a, b) => rankOf(b) - rankOf(a));
  return copy;
}

let map = null, markerLayer = null, mapFitted = false;

let lastVisible = [];
let tableRendered = false;

function renderAll() {
  const visible = sorted(rows.filter(matches));
  lastVisible = visible;
  renderCards(visible);
  // A tabela completa só é montada quando o <details> é aberto — evita
  // renderizar centenas de linhas que a maioria das visitas nem vê.
  if (tableRendered) {
    renderTable(document.getElementById("tbl-all"), visible,
      "Nenhuma avaliação no período/filtro.");
  }
  // O mapa acompanha os cartões: descartadas somem dele também (a tabela
  // completa continua mostrando tudo, para auditoria).
  const mapVisible = showDismissed ? visible : visible.filter(r => !dismissed.has(r.id));
  renderMarkers(mapVisible);
  renderCompare();
}

const tblDetails = document.querySelector("details.tbl");
tblDetails.addEventListener("toggle", () => {
  if (tblDetails.open && !tableRendered) {
    tableRendered = true;
    renderTable(document.getElementById("tbl-all"), lastVisible,
      "Nenhuma avaliação no período/filtro.");
  }
});

function renderMarkers(visible) {
  if (typeof L === "undefined") {
    document.getElementById("map").innerHTML =
      '<div class="empty">Mapa indisponível (biblioteca de mapas não carregou). Os cartões e tabelas seguem funcionando.</div>';
    return;
  }
  const pts = visible.filter(r => r.lat != null && r.lng != null && (r.lat || r.lng));
  if (!map) {
    if (!pts.length) {
      document.getElementById("map").innerHTML =
        '<div class="empty">Sem coordenadas para exibir no mapa ainda.</div>';
      return;
    }
    map = L.map("map").setView([28.5384, -81.3789], 9);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 18,
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
  }
  if (!markerLayer) return;
  markerLayer.clearLayers();
  const colors = { viavel: "#0ca30c", radar: "#fab219", reprovado: "#898781" };
  pts.forEach(r => {
    const g = growthOf(r);
    const popup =
      "<b>" + esc(r.address || r.id) + "</b><br>" +
      statusLabel(r.review_status) + "<br>" +
      "Terreno: " + fmtMoney(r.land_price) + " · ARV: " + fmtMoney(r.arv) + "<br>" +
      "Lucro: " + fmtMoney(r.profit) + " (margem " + fmtPct(r.margin) + ")<br>" +
      (r.margin_stress != null ? "Margem pessimista: " + fmtPct(r.margin_stress) + "<br>" : "") +
      (g ? "Crescimento região: " + g.score.toFixed(1) + "/10<br>" : "") +
      (g && g.signals ? "Sinais: " + esc(g.signals) + "<br>" : "") +
      (r.market_region ? "Mercado: " + esc(r.market_region) + "<br>" : "") +
      (r.risk_flags ? "Atenções: " + esc(r.risk_flags) + "<br>" : "") +
      linkCell(r);
    L.circleMarker([r.lat, r.lng], {
      radius: r.kind === "viavel" ? 9 : 7,
      color: "#fcfcfb",
      weight: 2,
      fillColor: colors[r.kind],
      fillOpacity: 0.85,
    }).bindPopup(popup, { maxWidth: 380 }).addTo(markerLayer);
  });
  // Enquadra os pontos só no primeiro render: depois disso o zoom/posição
  // são do usuário, e filtrar/buscar não pode roubá-los.
  if (pts.length && !mapFitted) {
    map.fitBounds(pts.map(r => [r.lat, r.lng]), { padding: [30, 30], maxZoom: 12 });
    mapFitted = true;
  }
}

document.querySelectorAll(".chip").forEach(chip => {
  chip.setAttribute("aria-pressed", chip.classList.contains("active"));
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach(c => {
      c.classList.remove("active");
      c.setAttribute("aria-pressed", "false");
    });
    chip.classList.add("active");
    chip.setAttribute("aria-pressed", "true");
    statusFilter = chip.dataset.status;
    renderAll();
  });
});
document.getElementById("sort").addEventListener("change", e => {
  sortMode = e.target.value;
  renderAll();
});
document.getElementById("min-margin").addEventListener("change", e => {
  minMargin = parseFloat(e.target.value) || 0;
  renderAll();
});
function debounce(fn, wait) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}
document.getElementById("search").addEventListener("input", debounce(e => {
  searchTerm = e.target.value.trim().toLowerCase();
  renderAll();
}, 180));

renderRegions();
renderAll();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gera o dashboard estático em HTML.")
    parser.add_argument("--out", default=None, help="diretório de saída (padrão: site/)")
    args = parser.parse_args()
    generate_site(out_dir=args.out)
