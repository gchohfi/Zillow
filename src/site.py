"""Gera o dashboard estático (site/index.html) a partir dos CSVs.

Pensado para rodar logo após a varredura (local ou GitHub Actions) e ser
publicado no GitHub Pages, para a empresa acompanhar as oportunidades por link.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config

MAX_EMBEDDED_ROWS = 1000

_ROW_FIELDS = (
    "found_at",
    "review_status",
    "review_reason",
    "is_viable",
    "tier",
    "zip_code",
    "market_priority",
    "market_region",
    "market_strategies",
    "risk_flags",
    "growth_score",
    "growth_signals",
    "address",
    "lat",
    "lng",
    "distance_km",
    "land_price",
    "arv",
    "arv_source",
    "total_cost",
    "profit",
    "margin",
    "land_to_total_investment",
    "zoning",
    "url",
    "id",
)

_FLOAT_FIELDS = {
    "lat", "lng", "distance_km", "land_price", "arv", "total_cost",
    "profit", "margin", "land_to_total_investment", "growth_score",
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
        "regions": _aggregate_regions(embedded),
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
  .wrap { max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
  header h1 { font-size: 22px; margin: 0 0 4px; }
  header p { margin: 0; color: var(--text-secondary); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 20px 0; }
  .tile {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }
  .tile .label { color: var(--text-secondary); font-size: 12px; }
  .tile .value { font-size: 28px; font-weight: 600; margin-top: 2px; }
  .tile .sub { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0 16px; }
  .chip {
    border: 1px solid var(--border);
    background: var(--surface-1);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 13px;
  }
  .chip.active { border-color: var(--accent); color: var(--text-primary); font-weight: 600; }
  #search {
    flex: 1 1 220px;
    max-width: 340px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    color: var(--text-primary);
  }
  section { margin-top: 28px; }
  section h2 { font-size: 16px; margin: 0 0 8px; }
  section .hint { color: var(--text-muted); font-size: 12px; margin: 0 0 10px; }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  #map { height: 480px; }
  .table-scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; min-width: 900px; }
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
  .badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; white-space: nowrap; }
  .badge .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .badge.viavel .dot { background: var(--status-good); }
  .badge.viavel { color: var(--status-good-text); font-weight: 600; }
  .badge.radar .dot { background: var(--status-warning); }
  .badge.radar { color: var(--status-warning-text); font-weight: 600; }
  .badge.reprovado .dot { background: var(--status-muted); }
  .badge.reprovado { color: var(--text-muted); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .links a { margin-right: 8px; white-space: nowrap; }
  .muted { color: var(--text-muted); }
  .small { font-size: 12px; }
  .empty { padding: 24px; color: var(--text-muted); text-align: center; }
  .regions { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
  .region-card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .region-card .zip { font-size: 16px; font-weight: 700; }
  .region-card .name { color: var(--text-secondary); font-size: 12px; min-height: 30px; }
  .meter-row { display: flex; align-items: center; gap: 8px; }
  .meter { flex: 1; height: 8px; border-radius: 4px; background: var(--meter-track); overflow: hidden; }
  .meter > span { display: block; height: 100%; border-radius: 4px; background: var(--meter-fill); }
  .meter-value { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .sig-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .sig-chip {
    background: var(--chip-bg);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .region-card .counts { color: var(--text-muted); font-size: 12px; margin-top: auto; }
  .growth-cell { min-width: 110px; }
  .growth-cell .meter { height: 6px; }
  footer { margin-top: 32px; color: var(--text-muted); font-size: 12px; }
  footer a { margin-right: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Orlando Land Detector</h1>
    <p>Oportunidades de terreno para spec build num raio de 80&nbsp;km de Orlando ·
       atualizado <span id="updated">—</span></p>
  </header>

  <div class="tiles">
    <div class="tile"><div class="label">Oportunidades viáveis</div><div class="value" id="kpi-viable">0</div><div class="sub" id="kpi-window"></div></div>
    <div class="tile"><div class="label">Radar (revisar)</div><div class="value" id="kpi-radar">0</div><div class="sub">números bons, falta diligência</div></div>
    <div class="tile"><div class="label">Avaliações</div><div class="value" id="kpi-total">0</div><div class="sub">tudo que o robô analisou</div></div>
    <div class="tile"><div class="label">Maior margem</div><div class="value" id="kpi-margin">—</div><div class="sub" id="kpi-margin-addr"></div></div>
  </div>

  <div class="controls">
    <button class="chip active" data-status="all">Tudo</button>
    <button class="chip" data-status="viavel">✓ Viáveis</button>
    <button class="chip" data-status="radar">⚠ Radar</button>
    <button class="chip" data-status="reprovado">Reprovadas</button>
    <input id="search" type="search" placeholder="Filtrar por endereço, ZIP, região…">
  </div>

  <section id="sec-regions">
    <h2>Crescimento por região</h2>
    <p class="hint">Sinais estudados para identificar valorização: escolas e comércio próximos (OpenStreetMap)
       e crescimento de população e renda em 5 anos (US Census). Score 0–10 por ZIP com avaliação recente.</p>
    <div class="regions" id="region-cards"></div>
  </section>

  <section>
    <h2>Mapa</h2>
    <p class="hint">Verde = viável · Âmbar = radar (revisar) · Cinza = reprovada. Clique no ponto para detalhes.</p>
    <div class="card"><div id="map"></div></div>
  </section>

  <section>
    <h2>Oportunidades viáveis</h2>
    <p class="hint">Passaram em todos os filtros automáticos (margem, terreno/investimento, zoneamento, disponibilidade).</p>
    <div class="card table-scroll"><table id="tbl-viable"></table></div>
  </section>

  <section>
    <h2>Radar — conferir antes de ofertar</h2>
    <p class="hint">Números aprovados, mas com pendência de diligência (zoneamento, análise manual do segmento).</p>
    <div class="card table-scroll"><table id="tbl-radar"></table></div>
  </section>

  <section>
    <h2>Todas as avaliações</h2>
    <p class="hint" id="all-hint"></p>
    <div class="card table-scroll"><table id="tbl-all"></table></div>
  </section>

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
const statusKind = s => s === "viavel" ? "viavel" : (s || "").startsWith("radar_") ? "radar" : "reprovado";
const statusLabel = s => ({
  viavel: "✓ Viável",
  radar_zoneamento_pendente: "⚠ Radar: zoneamento",
  radar_analise_manual: "⚠ Radar: análise manual",
}[s] || (statusKind(s) === "radar" ? "⚠ Radar" : "Reprovada"));

const rows = DATA.rows.map(r => ({ ...r, kind: statusKind(r.review_status) }));

document.getElementById("updated").textContent = fmtDate(DATA.generated_at);
document.getElementById("kpi-window").textContent = "últimos " + Math.round(DATA.period_days) + " dias";

const viable = rows.filter(r => r.kind === "viavel");
const radar = rows.filter(r => r.kind === "radar");
document.getElementById("kpi-viable").textContent = viable.length;
document.getElementById("kpi-radar").textContent = radar.length;
document.getElementById("kpi-total").textContent = DATA.total_rows;
const candidates = viable.length ? viable : radar;
const best = candidates.reduce((a, r) => (r.margin != null && (!a || r.margin > a.margin)) ? r : a, null);
if (best) {
  document.getElementById("kpi-margin").textContent = fmtPct(best.margin);
  document.getElementById("kpi-margin-addr").textContent = best.address || "";
}
document.getElementById("all-hint").textContent =
  "Mostrando " + rows.length + " de " + DATA.total_rows + " avaliações dos últimos " +
  Math.round(DATA.period_days) + " dias.";

function linkCell(r) {
  const links = [];
  if (r.url) links.push('<a href="' + r.url + '" target="_blank" rel="noopener">Anúncio</a>');
  if (r.address) {
    const q = encodeURIComponent(r.address);
    links.push('<a href="https://www.google.com/maps/search/?api=1&query=' + q + '" target="_blank" rel="noopener">Maps</a>');
    links.push('<a href="https://www.zillow.com/homes/' + q + '_rb/" target="_blank" rel="noopener">Zillow</a>');
    links.push('<a href="https://www.realtor.com/realestateandhomes-search/' + q + '" target="_blank" rel="noopener">Realtor</a>');
  } else if (r.lat != null && r.lng != null) {
    links.push('<a href="https://www.google.com/maps/search/?api=1&query=' + r.lat + ',' + r.lng + '" target="_blank" rel="noopener">Maps</a>');
  }
  return links.join(" ");
}

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
  if (r.growth_score == null) return '<span class="muted small">n/d</span>';
  return '<div class="growth-cell" title="' + esc(r.growth_signals) + '">' +
    meterHtml(r.growth_score) + "</div>";
}

function renderRegions() {
  const el = document.getElementById("region-cards");
  const regions = (DATA.regions || []).filter(g => g.growth_score != null);
  if (!regions.length) {
    document.getElementById("sec-regions").style.display = "none";
    return;
  }
  el.innerHTML = regions.map(g =>
    '<div class="region-card">' +
      '<div><span class="zip">' + esc(g.zip) + "</span>" +
      (g.priority ? ' <span class="badge radar" style="color:var(--text-muted)">' + esc(g.priority) + "</span>" : "") +
      "</div>" +
      '<div class="name">' + esc(g.region || "fora das regiões-alvo mapeadas") + "</div>" +
      meterHtml(g.growth_score) +
      '<div class="sig-chips">' + sigChips(g.growth_signals) + "</div>" +
      '<div class="counts">' + g.viable + " viável(is) · " + g.radar + " radar · " +
      g.total + " avaliação(ões) no período</div>" +
    "</div>"
  ).join("");
}

function badge(r) {
  const kind = r.kind;
  return '<span class="badge ' + kind + '"><span class="dot"></span>' + statusLabel(r.review_status) + '</span>';
}

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

let statusFilter = "all";
let searchTerm = "";

function matches(r) {
  if (statusFilter !== "all" && r.kind !== statusFilter) return false;
  if (!searchTerm) return true;
  const hay = [r.address, r.zip_code, r.market_region, r.market_priority, r.tier, r.zoning]
    .join(" ").toLowerCase();
  return hay.includes(searchTerm);
}

let map = null, markerLayer = null;

function renderAll() {
  const visible = rows.filter(matches);
  renderTable(document.getElementById("tbl-viable"),
    visible.filter(r => r.kind === "viavel"), "Nenhuma oportunidade viável no período/filtro.");
  renderTable(document.getElementById("tbl-radar"),
    visible.filter(r => r.kind === "radar"), "Nenhum candidato no radar para o filtro atual.");
  renderTable(document.getElementById("tbl-all"), visible, "Nenhuma avaliação no período/filtro.");
  renderMarkers(visible);
}

function renderMarkers(visible) {
  if (typeof L === "undefined") {
    document.getElementById("map").innerHTML =
      '<div class="empty">Mapa indisponível (biblioteca de mapas não carregou). As tabelas abaixo seguem funcionando.</div>';
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
    const popup =
      "<b>" + esc(r.address || r.id) + "</b><br>" +
      statusLabel(r.review_status) + "<br>" +
      "Terreno: " + fmtMoney(r.land_price) + " · ARV: " + fmtMoney(r.arv) + "<br>" +
      "Lucro: " + fmtMoney(r.profit) + " (margem " + fmtPct(r.margin) + ")<br>" +
      (r.growth_score != null ? "Crescimento região: " + r.growth_score.toFixed(1) + "/10<br>" : "") +
      (r.growth_signals ? "Sinais: " + esc(r.growth_signals) + "<br>" : "") +
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
  if (pts.length) map.fitBounds(pts.map(r => [r.lat, r.lng]), { padding: [30, 30], maxZoom: 12 });
}

document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    statusFilter = chip.dataset.status;
    renderAll();
  });
});
document.getElementById("search").addEventListener("input", e => {
  searchTerm = e.target.value.trim().toLowerCase();
  renderAll();
});

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
