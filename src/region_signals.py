"""Sinais de crescimento da região: escolas, comércio, população e renda.

Fontes públicas e gratuitas, sem chave de API:
- OpenStreetMap Overpass: escolas e comércio num raio da oportunidade
- US Census ACS 5 anos (por ZCTA/ZIP): crescimento de população e renda

Tudo é *fail-open*: falha de API nunca bloqueia alerta, só deixa os sinais
vazios. Resultados ficam em cache SQLite por ZIP (os sinais mudam devagar),
então o custo por rodada é de poucas chamadas.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import Config

# Sentinelas do Census para "sem dado" (ex.: -666666666).
_CENSUS_MISSING_THRESHOLD = -100_000


class SignalsCache:
    """Cache simples por ZIP em SQLite (compartilhado entre rodadas)."""

    def __init__(self, db_path: str = "region_signals.db"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS region_signals (
                zip        TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload    TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get(self, zip_code: str, max_age_days: float) -> dict | None:
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM region_signals WHERE zip = ?",
            (zip_code,),
        ).fetchone()
        if not row:
            return None
        try:
            fetched = datetime.fromisoformat(row[0])
        except ValueError:
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > timedelta(days=max_age_days):
            return None
        try:
            return json.loads(row[1])
        except json.JSONDecodeError:
            return None

    def put(self, zip_code: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO region_signals (zip, fetched_at, payload) VALUES (?, ?, ?)",
            (zip_code, datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _fetch_overpass_counts(
    lat: float, lng: float, radius_m: int, cfg: dict[str, Any]
) -> tuple[int | None, int | None]:
    """Conta escolas e pontos de comércio num raio (OpenStreetMap)."""
    url = cfg.get("overpass_url", "https://overpass-api.de/api/interpreter")
    timeout = float(cfg.get("timeout_seconds", 25))
    query = f"""
[out:json][timeout:{int(timeout)}];
nwr["amenity"~"^(school|kindergarten|college|university)$"](around:{radius_m},{lat},{lng});
out count;
(
  nwr["shop"](around:{radius_m},{lat},{lng});
  nwr["amenity"~"^(restaurant|cafe|fast_food|supermarket|bank|pharmacy|marketplace)$"](around:{radius_m},{lat},{lng});
);
out count;
"""
    resp = requests.post(url, data={"data": query}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    counts = [
        int(el.get("tags", {}).get("total", 0))
        for el in data.get("elements", [])
        if el.get("type") == "count"
    ]
    if len(counts) < 2:
        return None, None
    return counts[0], counts[1]


def _fetch_census_acs(zip_code: str, year: int, cfg: dict[str, Any]) -> tuple[float | None, float | None]:
    """Retorna (população, renda mediana) do ACS 5 anos para o ZIP/ZCTA."""
    base = cfg.get("census_url", "https://api.census.gov/data")
    timeout = float(cfg.get("timeout_seconds", 25))
    url = f"{base}/{year}/acs/acs5"
    resp = requests.get(
        url,
        params={
            "get": "B01003_001E,B19013_001E",
            "for": f"zip code tabulation area:{zip_code}",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or len(data) < 2:
        return None, None

    def _clean(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > _CENSUS_MISSING_THRESHOLD and number > 0 else None

    return _clean(data[1][0]), _clean(data[1][1])


def _growth_pct(base: float | None, latest: float | None) -> float | None:
    if not base or latest is None:
        return None
    return (latest - base) / base


def compute_score(signals: dict[str, Any]) -> float | None:
    """Score 0-10 a partir dos sinais disponíveis (renormaliza os ausentes).

    Referências de teto (valem 100% do componente):
    escolas ≥6 · comércio ≥30 · população +10% em 5 anos · renda +30% em 5 anos.
    """
    components: list[float] = []
    if signals.get("schools") is not None:
        components.append(min(signals["schools"] / 6.0, 1.0))
    if signals.get("commerce") is not None:
        components.append(min(signals["commerce"] / 30.0, 1.0))
    if signals.get("pop_growth_pct") is not None:
        components.append(max(0.0, min(signals["pop_growth_pct"] / 0.10, 1.0)))
    if signals.get("income_growth_pct") is not None:
        components.append(max(0.0, min(signals["income_growth_pct"] / 0.30, 1.0)))
    if not components:
        return None
    return round(10.0 * sum(components) / len(components), 1)


def build_summary(signals: dict[str, Any], radius_km: float) -> list[str]:
    """Frases curtas dos sinais, para WhatsApp/CSV/dashboard."""
    parts: list[str] = []
    if signals.get("schools") is not None:
        parts.append(f"{signals['schools']} escolas em {radius_km:.0f} km")
    if signals.get("commerce") is not None:
        parts.append(f"{signals['commerce']} comercios em {radius_km:.0f} km")
    if signals.get("pop_growth_pct") is not None:
        parts.append(f"populacao {signals['pop_growth_pct']:+.1%} em 5 anos")
    if signals.get("income_growth_pct") is not None:
        parts.append(f"renda {signals['income_growth_pct']:+.1%} em 5 anos")
    return parts


def get_region_signals(
    zip_code: str | None,
    lat: float,
    lng: float,
    cfg: Config,
    cache: SignalsCache | None = None,
) -> dict[str, Any] | None:
    """Sinais de crescimento para um ZIP; usa cache e falha aberto."""
    section = cfg.raw.get("region_signals", {})
    if not section.get("enabled", False):
        return None
    if not zip_code:
        return None

    max_age_days = float(section.get("cache_days", 30) or 30)
    own_cache = cache is None
    cache = cache or SignalsCache(section.get("cache_db", "region_signals.db"))
    try:
        cached = cache.get(zip_code, max_age_days)
        if cached is not None:
            return cached

        radius_km = float(section.get("radius_km", 3) or 3)
        signals: dict[str, Any] = {
            "zip": zip_code,
            "radius_km": radius_km,
            "schools": None,
            "commerce": None,
            "pop_growth_pct": None,
            "income_growth_pct": None,
        }

        if lat and lng:
            try:
                schools, commerce = _fetch_overpass_counts(
                    lat, lng, int(radius_km * 1000), section
                )
                signals["schools"] = schools
                signals["commerce"] = commerce
            except (requests.RequestException, ValueError) as exc:
                print(f"  [aviso] Overpass falhou para ZIP {zip_code}: {type(exc).__name__}")

        latest_year = int(section.get("census_latest_year", 2023))
        base_year = int(section.get("census_base_year", 2018))
        try:
            pop_latest, income_latest = _fetch_census_acs(zip_code, latest_year, section)
            pop_base, income_base = _fetch_census_acs(zip_code, base_year, section)
            signals["pop_growth_pct"] = _growth_pct(pop_base, pop_latest)
            signals["income_growth_pct"] = _growth_pct(income_base, income_latest)
            signals["pop_latest"] = pop_latest
        except (requests.RequestException, ValueError) as exc:
            print(f"  [aviso] Census falhou para ZIP {zip_code}: {type(exc).__name__}")

        signals["score"] = compute_score(signals)
        signals["summary"] = build_summary(signals, radius_km)

        # Guarda mesmo parcial: evita repetir chamadas com falha a cada rodada.
        cache.put(zip_code, signals)
        return signals
    finally:
        if own_cache:
            cache.close()
