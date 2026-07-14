"""Lente de renda (buy & hold): aluguel real → NOI, cap rate, DSCR.

Complementa o motor de spec build com a análise de renda recorrente:
quanto o imóvel construído renderia se, em vez de vendido, fosse
alugado. Usa o rent AVM da RentCast (mesma chave do ARV) e premissas
de `config.yaml → rental`. É uma camada INFORMATIVA — não muda a
aprovação/reprovação do spec build; alimenta decisão nas regiões cuja
tese é SFR rental/BTR.
"""

from __future__ import annotations

from typing import Any

import requests

from .config import Config, env
from .models import Listing, ViabilityResult
from .viability import resolve_parameters


def _first_number(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def enrich_rent(listing: Listing, cfg: Config) -> None:
    """Anexa o aluguel mensal estimado (casa pronta hipotética) à listagem."""
    rental_cfg = cfg.raw.get("rental", {})
    if not rental_cfg.get("enabled", False):
        return
    if listing.rent_estimate:
        return
    key = env("RENTCAST_API_KEY")
    if not key:
        return

    _, build, _, _ = resolve_parameters(listing, cfg)
    params: dict[str, Any] = {
        "propertyType": rental_cfg.get("property_type", "Single Family"),
        "squareFootage": int(float(build["living_area_sqft"])),
        "maxRadius": rental_cfg.get("max_radius_miles", 2),
        "daysOld": rental_cfg.get("days_old", 180),
        "compCount": rental_cfg.get("comp_count", 10),
    }
    if listing.address:
        params["address"] = listing.address
    else:
        params["latitude"] = listing.lat
        params["longitude"] = listing.lng

    url = (
        cfg.raw.get("datasource", {})
        .get("rentcast", {})
        .get("base_url", "https://api.rentcast.io/v1")
        .rstrip("/")
        + rental_cfg.get("path", "/avm/rent/long-term")
    )
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json", "X-Api-Key": key},
            timeout=float(rental_cfg.get("timeout_seconds", 20)),
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  [aviso] rent AVM falhou para {listing.id or listing.address}: {type(exc).__name__}")
        return
    if not isinstance(data, dict):
        return

    value = _first_number(data, ["rent", "rentEstimate", "price", "estimate", "value"])
    comps = data.get("comparables") or data.get("comps") or []
    min_comps = int(rental_cfg.get("min_comps", 3) or 0)
    if not value or (isinstance(comps, list) and len(comps) < min_comps):
        print(
            f"  [aviso] rent AVM insuficiente para {listing.id or listing.address}: "
            f"aluguel={value or 'n/d'} comps={len(comps) if isinstance(comps, list) else 0}"
        )
        return

    listing.rent_estimate = value
    listing.rent_source = "rentcast_rent_avm"
    listing.rent_comps_count = len(comps) if isinstance(comps, list) else None


def _annual_debt_service(loan: float, rate: float, years: float) -> float:
    """Prestação anual de um financiamento amortizado (tabela Price)."""
    if loan <= 0 or years <= 0:
        return 0.0
    n = years * 12
    if rate <= 0:
        return loan / years
    r = rate / 12
    monthly = loan * r / (1 - (1 + r) ** -n)
    return monthly * 12


def apply_rental_analysis(result: ViabilityResult, cfg: Config) -> None:
    """Calcula NOI, cap rate, DSCR e cash-on-cash quando há aluguel estimado."""
    rental_cfg = cfg.raw.get("rental", {})
    if not rental_cfg.get("enabled", False):
        return
    rent = result.listing.rent_estimate
    if not rent:
        return

    # Base de investimento buy & hold: tudo, menos o custo de VENDA
    # (comissão/closing da saída), que só existe no spec build.
    basis = max(result.total_cost - result.selling_cost, 0.0)
    if basis <= 0:
        return

    gross = float(rent) * 12
    vacancy = float(rental_cfg.get("vacancy_pct", 0.08) or 0)
    effective = gross * (1 - vacancy)

    property_tax = float(rental_cfg.get("property_tax_pct", 0.011) or 0) * result.arv
    insurance = float(rental_cfg.get("insurance_annual", 2800) or 0)
    if result.flood_high_risk:
        insurance += float(
            cfg.raw.get("red_flags", {}).get("flood", {})
            .get("insurance_surcharge_annual", 0) or 0
        )
    hoa = float(rental_cfg.get("hoa_monthly", 0) or 0) * 12
    pct_of_income = (
        float(rental_cfg.get("maintenance_pct", 0.08) or 0)
        + float(rental_cfg.get("management_pct", 0.08) or 0)
        + float(rental_cfg.get("reserves_pct", 0.05) or 0)
    ) * effective

    noi = effective - property_tax - insurance - hoa - pct_of_income
    cap_rate = noi / basis

    fin = rental_cfg.get("financing", {}) or {}
    down_pct = float(fin.get("down_payment_pct", 0.25) or 0)
    loan = basis * (1 - down_pct)
    debt_service = _annual_debt_service(
        loan, float(fin.get("interest_rate", 0.07) or 0),
        float(fin.get("amort_years", 30) or 30),
    )
    dscr = (noi / debt_service) if debt_service else None
    equity = basis * down_pct
    cash_on_cash = ((noi - debt_service) / equity) if equity else None

    result.rent_monthly = float(rent)
    result.noi_annual = noi
    result.cap_rate = cap_rate
    result.dscr = dscr
    result.cash_on_cash = cash_on_cash

    line = (
        f"• renda (buy & hold): aluguel US$ {rent:,.0f}/mês → "
        f"NOI US$ {noi:,.0f}/ano, cap {cap_rate:.1%}"
    )
    if dscr is not None:
        line += f", DSCR {dscr:.2f}"
    if cash_on_cash is not None:
        line += f", cash-on-cash {cash_on_cash:.1%}"
    result.reasons.append(line)

    min_dscr = float(rental_cfg.get("min_dscr_warn", 1.2) or 0)
    if dscr is not None and min_dscr and dscr < min_dscr:
        flag = f"DSCR {dscr:.2f} < {min_dscr:.2f} na tese de renda (dívida aperta o fluxo)"
        result.reasons.append(f"⚠ {flag}")
        if flag not in result.risk_flags:
            result.risk_flags.append(flag)
