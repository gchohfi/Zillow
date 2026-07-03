"""Sinais de crescimento da região: escolas, comércio, população e renda.

Fontes públicas e gratuitas, sem chave de API:
- OpenStreetMap Overpass: escolas e comércio num raio da oportunidade
- US Census ACS 5 anos (por ZCTA/ZIP): crescimento de população e renda

Tudo é *fail-open*: falha de API nunca bloqueia alerta, só deixa os sinais
vazios. Resultados ficam em cache SQLite por ZIP (os sinais mudam devagar),
então o custo por rodada é de poucas chamadas.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import Config

_GEOCODER_USER_AGENT = "orlando-land-detector/1.0 (https://github.com/gchohfi/Zillow)"

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
    """Conta escolas e pontos de comércio num raio (OpenStreetMap).

    Tenta espelhos em sequência: os IPs compartilhados de CI costumam ser
    limitados pelo servidor principal do Overpass.
    """
    urls = cfg.get("overpass_urls") or [
        cfg.get("overpass_url", "https://overpass-api.de/api/interpreter"),
        "https://overpass.kumi.systems/api/interpreter",
    ]
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
    last_exc: Exception | None = None
    for url in urls:
        try:
            resp = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": _GEOCODER_USER_AGENT},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            continue
        counts = [
            int(el.get("tags", {}).get("total", 0))
            for el in data.get("elements", [])
            if el.get("type") == "count"
        ]
        if len(counts) < 2:
            return None, None
        return counts[0], counts[1]
    assert last_exc is not None
    raise last_exc


def _fetch_census_acs(zip_code: str, year: int, cfg: dict[str, Any]) -> tuple[float | None, float | None]:
    """Retorna (população, renda mediana) do ACS 5 anos para o ZIP/ZCTA.

    Até o ACS 2019, o geo ZCTA é aninhado por estado e a consulta exige
    `in=state:FIPS`; a partir de 2020 o ZCTA é nacional e o `in` é rejeitado.
    """
    base = cfg.get("census_url", "https://api.census.gov/data")
    timeout = float(cfg.get("timeout_seconds", 25))
    url = f"{base}/{year}/acs/acs5"
    params: dict[str, Any] = {
        "get": "B01003_001E,B19013_001E",
        "for": f"zip code tabulation area:{zip_code}",
    }
    if year <= 2019:
        params["in"] = f"state:{cfg.get('census_state_fips', '12')}"
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    if not resp.text.strip():
        # ZCTA sem dados retorna corpo vazio (204) em alguns vintages.
        return None, None
    try:
        data = resp.json()
    except ValueError:
        return None, None
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
    failure_retry_days = float(section.get("failure_retry_hours", 6) or 6) / 24
    own_cache = cache is None
    cache = cache or SignalsCache(section.get("cache_db", "region_signals.db"))
    try:
        cached = cache.get(zip_code, max_age_days)
        if cached is not None:
            if cached.get("score") is not None:
                return cached
            # Busca anterior falhou (score vazio): tenta de novo após poucas
            # horas em vez de esperar o cache de 30 dias expirar.
            if cache.get(zip_code, failure_retry_days) is not None:
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
        pop_latest = income_latest = pop_base = income_base = None
        try:
            pop_latest, income_latest = _fetch_census_acs(zip_code, latest_year, section)
        except (requests.RequestException, ValueError) as exc:
            print(f"  [aviso] Census {latest_year} falhou para ZIP {zip_code}: {type(exc).__name__}")
        try:
            pop_base, income_base = _fetch_census_acs(zip_code, base_year, section)
        except (requests.RequestException, ValueError) as exc:
            print(f"  [aviso] Census {base_year} falhou para ZIP {zip_code}: {type(exc).__name__}")
        signals["pop_growth_pct"] = _growth_pct(pop_base, pop_latest)
        signals["income_growth_pct"] = _growth_pct(income_base, income_latest)
        signals["pop_latest"] = pop_latest

        signals["score"] = compute_score(signals)
        signals["summary"] = build_summary(signals, radius_km)

        # Guarda mesmo parcial: evita repetir chamadas com falha a cada rodada.
        cache.put(zip_code, signals)
        # Pausa educada entre ZIPs para não estourar limites das APIs públicas.
        time.sleep(float(section.get("fetch_pause_seconds", 1.0) or 0))
        return signals
    finally:
        if own_cache:
            cache.close()


def _geocode_zip(zip_code: str, section: dict[str, Any]) -> tuple[float, float] | None:
    """Centroide aproximado de um ZIP: Nominatim, com Photon como reserva.

    IPs de CI são frequentemente bloqueados pelo Nominatim; o Photon
    (também baseado em OpenStreetMap) costuma aceitar.
    """
    timeout = float(section.get("timeout_seconds", 25))
    headers = {"User-Agent": _GEOCODER_USER_AGENT}

    url = section.get("geocoder_url", "https://nominatim.openstreetmap.org/search")
    try:
        resp = requests.get(
            url,
            params={
                "postalcode": zip_code,
                "country": "us",
                "state": "florida",
                "format": "json",
                "limit": 1,
            },
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass

    photon_url = section.get("photon_url", "https://photon.komoot.io/api/")
    resp = requests.get(
        photon_url,
        params={"q": f"{zip_code} Florida USA", "limit": 1},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features") or []
    if not features:
        return None
    try:
        lng, lat = features[0]["geometry"]["coordinates"][:2]
        return float(lat), float(lng)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _zip_centroids_from_csv(cfg: Config) -> dict[str, tuple[float, float]]:
    """Centroides por ZIP a partir das avaliações já registradas (sem rede)."""
    path = cfg.raw.get("output", {}).get("evaluations_csv_path", "evaluations.csv")
    if not path or not os.path.exists(path):
        return {}
    sums: dict[str, list[float]] = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                zip_code = str(row.get("zip_code") or "").strip()
                try:
                    lat = float(row.get("lat") or "")
                    lng = float(row.get("lng") or "")
                except (TypeError, ValueError):
                    continue
                if not zip_code or not lat or not lng:
                    continue
                acc = sums.setdefault(zip_code, [0.0, 0.0, 0.0])
                acc[0] += lat
                acc[1] += lng
                acc[2] += 1
    except OSError:
        return {}
    return {z: (acc[0] / acc[2], acc[1] / acc[2]) for z, acc in sums.items() if acc[2]}


def thesis_zips(cfg: Config) -> list[str]:
    """ZIPs das regiões-alvo definidas em market_strategy.zip_groups."""
    zips: list[str] = []
    for group in cfg.raw.get("market_strategy", {}).get("zip_groups", []):
        for zip_code in group.get("zips", []):
            code = str(zip_code)
            if code not in zips:
                zips.append(code)
    return zips


def prefetch_config_zips(cfg: Config, cache: SignalsCache | None = None) -> int:
    """Pré-carrega sinais de todos os ZIPs das teses; retorna quantos buscou.

    Só consulta o que não está em cache (ou está em cache sem os dados de
    escolas/comércio, ex.: buscado antes sem coordenada). Respeita o limite
    de uso do Nominatim com uma pausa entre geocodificações.
    """
    section = cfg.raw.get("region_signals", {})
    if not section.get("enabled", False) or not section.get("prefetch_thesis_zips", False):
        return 0

    max_age_days = float(section.get("cache_days", 30) or 30)
    pause = float(section.get("prefetch_pause_seconds", 1.1))
    own_cache = cache is None
    cache = cache or SignalsCache(section.get("cache_db", "region_signals.db"))
    fetched = 0
    csv_centroids = _zip_centroids_from_csv(cfg)
    try:
        for zip_code in thesis_zips(cfg):
            cached = cache.get(zip_code, max_age_days)
            if cached is not None and cached.get("schools") is not None:
                continue
            # Coordenada local (terrenos já vistos no ZIP) evita geocodificar.
            coords = csv_centroids.get(zip_code)
            if coords is None:
                try:
                    coords = _geocode_zip(zip_code, section)
                except (requests.RequestException, ValueError) as exc:
                    print(f"  [aviso] geocodificacao falhou para ZIP {zip_code}: {type(exc).__name__}")
                    coords = None
                time.sleep(pause)
            if coords is None:
                continue
            if cached is not None:
                # Cache parcial (sem Overpass): remove para refazer completo.
                cache.conn.execute("DELETE FROM region_signals WHERE zip = ?", (zip_code,))
                cache.conn.commit()
            signals = get_region_signals(zip_code, coords[0], coords[1], cfg, cache=cache)
            if signals is not None:
                fetched += 1
            time.sleep(pause)
        if fetched:
            print(f"  [sinais] pre-carregados {fetched} ZIP(s) das regioes-alvo")
        return fetched
    finally:
        if own_cache:
            cache.close()


def cached_signals_for_zips(
    zips: list[str], cfg: Config, cache: SignalsCache | None = None
) -> dict[str, dict[str, Any]]:
    """Lê do cache (sem rede) os sinais disponíveis para uma lista de ZIPs."""
    section = cfg.raw.get("region_signals", {})
    if not section.get("enabled", False):
        return {}
    max_age_days = float(section.get("cache_days", 30) or 30)
    own_cache = cache is None
    try:
        cache = cache or SignalsCache(section.get("cache_db", "region_signals.db"))
    except sqlite3.Error:
        return {}
    try:
        result: dict[str, dict[str, Any]] = {}
        for zip_code in zips:
            cached = cache.get(str(zip_code), max_age_days)
            if cached is not None:
                result[str(zip_code)] = cached
        return result
    finally:
        if own_cache:
            cache.close()
