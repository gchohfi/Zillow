"""Memorando de decisão por oportunidade (2 páginas, gerado do CSV).

Formato do comitê de investimento: resumo do ativo, tese, investimento,
retornos-base (spec build + renda), cenário pessimista, sensibilidade,
riscos e recomendação objetiva (comprar / negociar / descartar). Gerado
no build do site para cada oportunidade viável ou em radar da janela.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone


def memo_slug(listing_id: str) -> str:
    """Nome de arquivo estável e seguro a partir do id da listagem."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(listing_id)).strip("-")
    return slug or "sem-id"


def _money(value: object) -> str:
    try:
        return f"US$ {float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/d"


def _pct(value: object) -> str:
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "n/d"


def _recommendation(status: str, risk_flags: str) -> tuple[str, str, str]:
    """(veredito, classe css, justificativa curta)."""
    if status == "viavel":
        return (
            "COMPRAR (condicionado à diligência)",
            "buy",
            "Retorno acima do alvo com riscos mapeados. Confirmar em campo os "
            "itens de atenção antes de ofertar.",
        )
    if status == "radar_desenvolvimento":
        return (
            "ESTUDAR COMO DESENVOLVIMENTO",
            "hold",
            "Lote grande: a fórmula de casa única NÃO se aplica. O valor está "
            "no potencial de múltiplas unidades ou land banking — analise por "
            "preço/acre, densidade permitida e custo de infraestrutura.",
        )
    if status.startswith("radar"):
        return (
            "NEGOCIAR / VERIFICAR",
            "hold",
            "Números interessantes, mas há pendência que impede aprovação "
            "automática. Resolver as condições abaixo ou usar como alavanca "
            "de negociação no preço.",
        )
    return (
        "DESCARTAR",
        "pass",
        "Retorno insuficiente ou dependente de premissa frágil no cenário atual.",
    )


def build_memo_html(row: dict, generated_at: str | None = None) -> str:
    """Monta o memorando em HTML a partir de uma linha normalizada do CSV."""
    status = str(row.get("review_status") or "")
    verdict, css, rationale = _recommendation(status, str(row.get("risk_flags") or ""))
    address = str(row.get("address") or row.get("id") or "(sem endereço)")
    generated = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    risk_items = [f for f in str(row.get("risk_flags") or "").split(";") if f.strip()]
    reasons = [r for r in str(row.get("reasons") or "").split(" | ") if r.strip()]
    conditions = [r for r in reasons if r.startswith(("⚠", "✗"))]
    checks = [r for r in reasons if r.startswith(("✓", "•"))]

    def li(items: list[str]) -> str:
        return "".join(f"<li>{html.escape(item.strip())}</li>" for item in items) or "<li>—</li>"

    # Lote de desenvolvimento: métricas de casa única (margem, ARV, renda,
    # sensibilidade) seriam enganosas — mostra a base de terra em vez delas.
    is_development = status == "radar_desenvolvimento"
    numbers_block = f"""
  <h2>Números-base (spec build)</h2>
  <table>
    <tr><td>Terreno (preço pedido)</td><td>{_money(row.get('land_price'))}</td></tr>
    <tr><td>Investimento total</td><td>{_money(row.get('total_cost'))}</td></tr>
    <tr><td>ARV ({html.escape(str(row.get('arv_source') or 'premissa'))})</td><td>{_money(row.get('arv'))}</td></tr>
    <tr><td>Lucro estimado</td><td>{_money(row.get('profit'))}</td></tr>
    <tr><td>Margem</td><td>{_pct(row.get('margin'))}</td></tr>
    <tr><td>Margem no pessimista</td><td>{_pct(row.get('margin_stress'))}</td></tr>
    <tr><td>Terreno / investimento</td><td>{_pct(row.get('land_to_total_investment'))}</td></tr>
    __FLOOD__
  </table>"""
    if is_development:
        acres = row.get("lot_size_acres")
        acres_txt = f"{float(acres):,.2f} acres" if acres not in (None, "") else "n/d"
        numbers_block = f"""
  <h2>Números do lote (desenvolvimento)</h2>
  <table>
    <tr><td>Preço pedido</td><td>{_money(row.get('land_price'))}</td></tr>
    <tr><td>Área</td><td>{acres_txt}</td></tr>
    <tr><td>Preço por acre</td><td>{_money(row.get('price_per_acre'))}</td></tr>
    __FLOOD__
  </table>
  <p class="meta">A conta de casa única não se aplica a este lote — próxima
  etapa: densidade permitida pelo zoneamento × preço por lote acabado na
  região, menos custo de infraestrutura (ruas, utilities, drenagem).</p>"""

    rent_block = ""
    if not is_development and row.get("rent_monthly"):
        rent_block = f"""
  <h2>Lente de renda (buy &amp; hold)</h2>
  <table>
    <tr><td>Aluguel estimado</td><td>{_money(row.get('rent_monthly'))}/mês</td></tr>
    <tr><td>NOI anual</td><td>{_money(row.get('noi_annual'))}</td></tr>
    <tr><td>Cap rate (yield on cost)</td><td>{_pct(row.get('cap_rate'))}</td></tr>
    <tr><td>DSCR</td><td>{row.get('dscr') or 'n/d'}</td></tr>
    <tr><td>Cash-on-cash</td><td>{_pct(row.get('cash_on_cash'))}</td></tr>
  </table>"""

    sensitivity = str(row.get("sensitivity_top") or "")
    sensitivity_block = (
        f"<h2>Sensibilidade — o que vigiar</h2><ul>{li(sensitivity.split(';'))}</ul>"
        if sensitivity and not is_development else ""
    )

    flood = str(row.get("flood_zone") or "")
    flood_line = (
        f"<tr><td>Zona FEMA</td><td>{html.escape(flood)}</td></tr>" if flood else ""
    )

    links = []
    if row.get("url"):
        links.append(f'<a href="{html.escape(str(row["url"]))}">Anúncio original</a>')
    if row.get("lat") and row.get("lng"):
        links.append(
            f'<a href="https://app.regrid.com/map#ll={row["lat"]},{row["lng"]}&z=17">'
            "Regrid (dono/zoneamento)</a>"
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memo — {html.escape(address)}</title>
<style>
 body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; margin: 2rem auto;
        max-width: 720px; padding: 0 1rem; color: #1a2433; line-height: 1.45; }}
 h1 {{ font-size: 1.25rem; margin-bottom: .25rem; }}
 h2 {{ font-size: .95rem; text-transform: uppercase; letter-spacing: .04em;
      color: #5a6b82; border-bottom: 1px solid #e3e8ef; padding-bottom: .25rem; margin-top: 1.6rem; }}
 table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
 td {{ padding: .3rem .4rem; border-bottom: 1px solid #eef1f5; }}
 td:last-child {{ text-align: right; font-variant-numeric: tabular-nums; }}
 ul {{ padding-left: 1.2rem; font-size: .95rem; }}
 .verdict {{ padding: .8rem 1rem; border-radius: .5rem; font-weight: 700; margin: 1rem 0; }}
 .buy {{ background: #e7f6ec; color: #156a38; }}
 .hold {{ background: #fdf3dd; color: #8a6116; }}
 .pass {{ background: #fde8e8; color: #a02929; }}
 .meta {{ color: #5a6b82; font-size: .85rem; }}
 .links a {{ margin-right: 1rem; }}
 @media print {{ body {{ margin: 0; }} }}
</style></head><body>
  <p class="meta">Memorando de decisão — Orlando Land Detector · {html.escape(generated)}</p>
  <h1>{html.escape(address)}</h1>
  <p class="meta">Segmento: {html.escape(str(row.get('tier') or 'n/d'))} ·
     Mercado: {html.escape(str(row.get('market_priority') or 'n/d'))}
     {html.escape(('- ' + str(row.get('market_region'))) if row.get('market_region') else '')} ·
     ZIP {html.escape(str(row.get('zip_code') or 'n/d'))}</p>

  <div class="verdict {css}">{verdict}</div>
  <p>{html.escape(rationale)}</p>

  <h2>Tese de investimento</h2>
  <p>{html.escape(str(row.get('market_strategies') or 'Spec build: comprar terreno, construir e vender.'))}</p>
  {numbers_block.replace('__FLOOD__', flood_line)}
  {rent_block}
  {sensitivity_block}

  <h2>Principais riscos</h2>
  <ul>{li(risk_items)}</ul>

  <h2>Condições para avançar</h2>
  <ul>{li(conditions)}</ul>

  <h2>Diligência já verificada</h2>
  <ul>{li(checks)}</ul>

  <p class="links">{' '.join(links)}</p>
</body></html>"""
