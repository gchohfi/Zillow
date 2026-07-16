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
    "arv",
    "arv_source",
    "total_cost",
    "profit",
    "margin",
    "margin_stress",
    "land_to_total_investment",
    "zoning",
    "url",
    "id",
)

_FLOAT_FIELDS = {
    "lat", "lng", "distance_km", "land_price", "lot_size_sqft",
    "lot_size_acres", "price_per_acre", "arv", "total_cost",
    "profit", "margin", "margin_stress", "land_to_total_investment",
    "growth_score", "market_score",
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

    # Publica também os CSVs para download direto pelo link do dashboard.
    output_cfg = cfg.raw.get("output", {})
    for key in ("csv_path", "evaluations_csv_path"):
        path = output_cfg.get(key)
        if path and os.path.exists(path):
            shutil.copy(path, out / Path(path).name)

    print(f"[site] dashboard gerado em {index} ({payload['total_rows']} avaliações, "
          f"últimos {payload['period_days']:.0f} dias)")
    return index


_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orlando Land Detector — Oportunidades</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  :root {
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --grid: #e1e0d9;
    --border: rgba(11,11,11,0.10);
    --status-good: #0ca30c;
    --status-good-text: #006300;
    --status-warning: #fab219;
    --status-warning-text: #7a5200;
    --status-muted: #898781;
    --accent: #2a78d6;
    --accent-wash: rgba(42,120,214,0.10);
    --meter-track: #cde2fb;
    --meter-fill: #2a78d6;
    --chip-bg: #f0efec;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --grid: #2c2c2a;
      --border: rgba(255,255,255,0.10);
      --status-good-text: #0ca30c;
      --status-warning-text: #fab219;
      --accent: #3987e5;
      --accent-wash: rgba(57,135,229,0.16);
      --meter-track: #184f95;
      --meter-fill: #6da7ec;
      --chip-bg: #2c2c2a;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.45;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 20px 16px 48px; }
  header h1 { font-size: 20px; margin: 0 0 2px; }
  header p { margin: 0; color: var(--text-secondary); font-size: 13px; }
  .banner-new {
    display: none;
    margin: 12px 0 0;
    padding: 10px 14px;
    border-radius: 10px;
    background: var(--accent-wash);
    border: 1px solid var(--accent);
    color: var(--text-primary);
    font-weight: 600;
    font-size: 14px;
  }
  .kpis { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
  .kpi {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 14px;
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .kpi .value { font-size: 20px; font-weight: 700; }
  .kpi .label { color: var(--text-secondary); font-size: 12px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0 16px; }
  .chip {
    border: 1px solid var(--border);
    background: var(--surface-1);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 10px 16px;
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    cursor: pointer;
    font-size: 13px;
  }
  .chip.active { border-color: var(--accent); color: var(--text-primary); font-weight: 600; }
  select#sort, select#min-margin, #search {
    padding: 10px 12px;
    min-height: 44px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    color: var(--text-primary);
    font-size: 13px;
  }
  #search { flex: 1 1 180px; max-width: 300px; }
  .chip:focus-visible, .show-more:focus-visible, #search:focus-visible,
  select:focus-visible, .opp-star:focus-visible, .opp-dismiss:focus-visible,
  summary:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  section { margin-top: 26px; }
  section h2 { font-size: 15px; margin: 0 0 6px; }
  section .hint { color: var(--text-muted); font-size: 12px; margin: 0 0 10px; }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }

  /* ---- Feed de oportunidades (herói) ---- */
  .opps { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 12px; }
  .opp {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .opp.viavel { border-left: 4px solid var(--status-good); }
  .opp.radar { border-left: 4px solid var(--status-warning); }
  .opp-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .opp-head .when { margin-left: auto; color: var(--text-muted); font-size: 12px; white-space: nowrap; }
  .tag-new {
    background: var(--accent);
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    border-radius: 999px;
    padding: 2px 8px;
    letter-spacing: 0.4px;
  }
  .opp-title { font-size: 15px; font-weight: 700; line-height: 1.3; }
  .opp-sub { color: var(--text-secondary); font-size: 12px; }
  .opp-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  .stat .l { color: var(--text-muted); font-size: 11px; }
  .stat .v { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .opp-alert { font-size: 12px; color: var(--status-warning-text); }
  .opp-alert.ok { color: var(--status-good-text); }
  .opp-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: auto; padding-top: 4px; border-top: 1px solid var(--grid); }
  .opp-actions a {
    font-size: 13px; font-weight: 600;
    padding: 6px 4px; min-height: 40px;
    display: inline-flex; align-items: center;
  }
  .opp-group {
    font-size: 13px; font-weight: 700; color: var(--text-secondary);
    margin: 18px 0 8px; text-transform: uppercase; letter-spacing: 0.3px;
  }
  .opp-group:first-child { margin-top: 0; }
  .opp-group .count { color: var(--text-muted); font-weight: 500; text-transform: none; }
  .opp-star, .opp-dismiss {
    border: none; background: none; cursor: pointer;
    font-size: 16px; color: var(--text-muted);
    min-width: 36px; min-height: 36px;
    display: inline-flex; align-items: center; justify-content: center;
  }
  .opp-star:hover, .opp-dismiss:hover { color: var(--accent); }
  .opp-star.on { color: var(--status-warning); }
  .opp.starred { border-color: var(--accent); }
  .opp-diligence { margin-top: 2px; }
  .opp-diligence summary {
    cursor: pointer; font-size: 12px; font-weight: 600;
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
    margin-top: 10px; font-size: 13px; color: var(--text-muted);
    background: none; border: none; cursor: pointer; padding: 8px 4px;
  }
  .dismissed-note:hover { color: var(--accent); }
  .show-more {
    margin-top: 12px;
    width: 100%;
    padding: 9px;
    border: 1px dashed var(--border);
    border-radius: 10px;
    background: none;
    color: var(--accent);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }

  .badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; white-space: nowrap; }
  .badge .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .badge.viavel .dot { background: var(--status-good); }
  .badge.viavel { color: var(--status-good-text); font-weight: 600; }
  .badge.radar .dot { background: var(--status-warning); }
  .badge.radar { color: var(--status-warning-text); font-weight: 600; }
  .badge.reprovado .dot { background: var(--status-muted); }
  .badge.reprovado { color: var(--text-muted); }

  #map { height: 380px; }
  .regions { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
  .region-card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .region-card .zip { font-size: 15px; font-weight: 700; }
  .region-card .name { color: var(--text-secondary); font-size: 12px; min-height: 28px; }
  .meter-row { display: flex; align-items: center; gap: 8px; }
  .meter { flex: 1; height: 8px; border-radius: 4px; background: var(--meter-track); overflow: hidden; }
  .meter > span { display: block; height: 100%; border-radius: 4px; background: var(--meter-fill); }
  .meter-value { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .sig-chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .sig-chip {
    background: var(--chip-bg);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 11.5px;
    white-space: nowrap;
  }
  .region-card .counts { color: var(--text-muted); font-size: 12px; margin-top: auto; }

  details.tbl { margin-top: 26px; }
  details.tbl > summary {
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 4px;
    color: var(--text-secondary);
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
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .links a { margin-right: 8px; white-space: nowrap; }
  .muted { color: var(--text-muted); }
  .small { font-size: 12px; }
  .empty { padding: 24px; color: var(--text-muted); text-align: center; }
  .growth-cell { min-width: 110px; }
  .growth-cell .meter { height: 6px; }
  footer { margin-top: 32px; color: var(--text-muted); font-size: 12px; }
  footer a { margin-right: 12px; }
  @media (max-width: 480px) {
    .opp-stats { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 600px) {
    .kpis, .controls {
      flex-wrap: nowrap;
      overflow-x: auto;
      scroll-snap-type: x proximity;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 4px;
    }
    .kpi, .chip { scroll-snap-align: start; flex: 0 0 auto; }
    #search { min-width: 200px; max-width: none; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Orlando Land Detector</h1>
    <p>Terrenos para spec build · raio de 80 km de Orlando · atualizado <span id="updated">—</span></p>
    <div class="banner-new" id="banner-new"></div>
  </header>

  <div class="kpis">
    <div class="kpi"><span class="value" id="kpi-new24">0</span><span class="label">novas em 24h</span></div>
    <div class="kpi"><span class="value" id="kpi-viable">0</span><span class="label">viáveis</span></div>
    <div class="kpi"><span class="value" id="kpi-radar">0</span><span class="label">no radar</span></div>
    <div class="kpi"><span class="value" id="kpi-margin">—</span><span class="label">maior margem</span></div>
    <div class="kpi"><span class="value" id="kpi-total">0</span><span class="label" id="kpi-total-label">avaliadas</span></div>
  </div>

  <div class="controls">
    <button class="chip active" data-status="opp">Oportunidades</button>
    <button class="chip" data-status="viavel">✓ Viáveis</button>
    <button class="chip" data-status="radar">⚠ Radar</button>
    <button class="chip" data-status="all">Tudo</button>
    <select id="sort">
      <option value="rank">Ordenar: recomendado</option>
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
    <input id="search" type="search" placeholder="Endereço, ZIP, região…">
  </div>

  <section>
    <h2>Oportunidades em aberto</h2>
    <p class="hint">Viáveis passaram em todos os filtros; Radar tem números bons com uma pendência de diligência. Reprovadas ficam na tabela completa no fim da página.</p>
    <div id="opp-cards"></div>
    <button class="show-more" id="show-more" style="display:none"></button>
    <button class="dismissed-note" id="dismissed-note" style="display:none"></button>
  </section>

  <section>
    <h2>Mapa</h2>
    <p class="hint">Verde = viável · Âmbar = radar · Cinza = reprovada. Clique no ponto para detalhes.</p>
    <div class="card"><div id="map"></div></div>
  </section>

  <section id="sec-regions">
    <h2>Crescimento por região</h2>
    <p class="hint">Sinais de valorização: escolas e comércio próximos (OpenStreetMap), população e renda em 5 anos (US Census). Score 0–10 por ZIP.</p>
    <div class="regions" id="region-cards"></div>
    <button class="show-more" id="show-more-regions" style="display:none"></button>
  </section>

  <details class="tbl">
    <summary>Tabela completa (todas as avaliações do período, inclusive reprovadas)</summary>
    <div class="card table-scroll"><table id="tbl-all"></table></div>
  </details>

  <footer>
    <a href="opportunities.csv" download>Baixar oportunidades (CSV)</a>
    <a href="evaluations.csv" download>Baixar avaliações (CSV)</a>
    <span>Gerado automaticamente pelo Orlando Land Detector. Valores em USD; estimativas — não é recomendação de investimento.</span>
  </footer>
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
  viavel: "✓ Viável",
  radar_zoneamento_pendente: "⚠ Radar: zoneamento",
  radar_analise_manual: "⚠ Radar: análise manual",
}[s] || (statusKind(s) === "radar" ? "⚠ Radar" : "Reprovada"));

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
  return base + q + (isNew(r) ? 0.3 : 0);
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
      b.textContent = "\\u{1F514} " + fresh.length + " nova(s) oportunidade(s) desde a sua última visita";
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
  return links;
}
const linkCell = r => linkParts(r).map(([t, u]) =>
  '<a href="' + u + '" target="_blank" rel="noopener">' + t + "</a>").join(" ");

const esc = s => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const SIG_ICONS = [
  [/escola/i, "\\u{1F3EB}"],
  [/comercio/i, "\\u{1F6D2}"],
  [/populacao/i, "\\u{1F465}"],
  [/renda/i, "\\u{1F4B0}"],
];
function sigChips(signals) {
  if (!signals) return "";
  return signals.split(";").map(s => s.trim()).filter(Boolean).map(s => {
    const icon = (SIG_ICONS.find(([re]) => re.test(s)) || [null, ""])[1];
    return '<span class="sig-chip">' + icon + " " + esc(s) + "</span>";
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
    : '<div class="opp-alert">' + "\\u26A0 " + esc(r.review_reason || "revisar diligência") + "</div>";
  const g = growthOf(r);
  const growth = g
    ? '<div class="stat" title="' + esc(g.signals) + '"><div class="l">região \\u2191</div><div class="v">' + g.score.toFixed(1) + "/10</div></div>"
    : '<div class="stat"><div class="l">região \\u2191</div><div class="v muted">n/d</div></div>';
  const isStarred = starred.has(r.id);
  const isDismissed = dismissed.has(r.id);
  const isDevelopment = r.review_status === "radar_desenvolvimento";
  const thesisStats = isDevelopment
    ? '<div class="stat"><div class="l">área</div><div class="v">' +
        (r.lot_size_acres == null ? "n/d" : Number(r.lot_size_acres).toFixed(1) + " acres") + "</div></div>" +
      '<div class="stat"><div class="l">preço/acre</div><div class="v">' + fmtMoney(r.price_per_acre) + "</div></div>"
    : '<div class="stat"><div class="l">lucro est.</div><div class="v">' + fmtMoney(r.profit) + "</div></div>" +
      '<div class="stat"><div class="l">margem</div><div class="v">' + fmtPct(r.margin) +
        (r.margin_stress != null ? '</div><div class="small muted">pess. ' + fmtPct(r.margin_stress) + "</div>" : "</div>") + "</div>";
  return '<article class="opp ' + r.kind + (isStarred ? " starred" : "") + '">' +
    '<div class="opp-head">' + badge(r) +
      (isNew(r) ? '<span class="tag-new">NOVA</span>' : "") +
      '<span class="when">' + fmtAgo(r.found_at) + "</span>" +
      '<button class="opp-star' + (isStarred ? " on" : "") + '" data-id="' + esc(r.id) +
        '" title="' + (isStarred ? "Deixar de acompanhar" : "Acompanhar") + '" aria-pressed="' + isStarred + '">' +
        (isStarred ? "\\u2605" : "\\u2606") + "</button>" +
      '<button class="opp-dismiss" data-id="' + esc(r.id) +
        '" title="' + (isDismissed ? "Restaurar" : "Descartar") + '">' +
        (isDismissed ? "\\u21BA" : "\\u2715") + "</button>" +
    "</div>" +
    '<div><div class="opp-title">' + esc(r.address || r.id) + "</div>" +
    '<div class="opp-sub">' + esc(r.market_region || "fora das regiões-alvo") +
      (r.zip_code ? " · ZIP " + esc(r.zip_code) : "") +
      (r.tier ? " · " + esc(r.tier) : "") +
      (r.distance_km != null ? " · " + fmtKm(r.distance_km) : "") + "</div></div>" +
    '<div class="opp-stats">' +
      '<div class="stat"><div class="l">terreno</div><div class="v">' + fmtMoney(r.land_price) + "</div></div>" +
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
    section("\\u2713 Prontas para oferta", ready) +
    section("\\u26A0 Em diligência", pending);

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
  { h: "Mercado", c: r => esc(r.market_priority) +
      (r.market_region ? '<div class="small muted">' + esc(r.market_region) + "</div>" : "") },
  { h: "Segmento", c: r => esc(r.tier) || '<span class="muted">n/d</span>' },
  { h: "Terreno", c: r => fmtMoney(r.land_price), num: true },
  { h: "Área", c: r => r.lot_size_acres == null ? '<span class="muted">n/d</span>' : Number(r.lot_size_acres).toFixed(2) + " ac", num: true },
  { h: "Preço/acre", c: r => fmtMoney(r.price_per_acre), num: true },
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
