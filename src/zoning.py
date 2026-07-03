"""Confirmação de zoneamento/uso do solo via GIS público (consulta por ponto).

Objetivo: destravar o Radar. Quando a listagem vem sem zoneamento, o sistema
consulta camadas ArcGIS públicas (por padrão as parcelas estaduais da Flórida,
com os códigos de uso DOR padronizados) e preenche `listing.zoning` antes da
avaliação. Com o zoneamento confirmado, a própria regra existente decide:
residencial → oportunidade viável; comercial/industrial/conservação → reprovada.

Tudo é *fail-open*: se o GIS falhar, a listagem segue para o Radar como hoje.
As fontes são dirigidas pelo config (`zoning_lookup.sources`), então dá para
trocar a URL ou adicionar GIS de county sem mexer em Python.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .models import Listing

_USER_AGENT = "orlando-land-detector/1.0 (https://github.com/gchohfi/Zillow)"

# Códigos de uso do solo do Florida DOR (dois primeiros dígitos), padronizados
# no estado inteiro. O rótulo alimenta as regras de zoneamento existentes.
_DOR_PREFIX_LABELS = {
    "00": "vacant residential",
    "01": "single family residential",
    "02": "mobile home residential",
    "03": "multi-family residential",
    "04": "residential condominium",
    "05": "residential cooperative",
    "06": "retirement home residential",
    "07": "misc residential",
    "08": "multi-family residential",
    "10": "vacant commercial",
    "11": "commercial",
    "12": "commercial",
    "13": "commercial",
    "14": "commercial",
    "15": "commercial",
    "16": "commercial",
    "17": "commercial office",
    "18": "commercial office",
    "19": "commercial",
    "20": "commercial",
    "21": "commercial",
    "22": "commercial",
    "23": "commercial",
    "25": "commercial",
    "26": "commercial",
    "27": "commercial",
    "28": "commercial",
    "29": "commercial",
    "30": "commercial",
    "32": "commercial",
    "33": "commercial",
    "34": "commercial",
    "35": "commercial",
    "38": "commercial",
    "39": "commercial",
    "40": "vacant industrial",
    "41": "industrial",
    "42": "industrial",
    "43": "industrial",
    "44": "industrial",
    "45": "industrial",
    "46": "industrial",
    "47": "industrial",
    "48": "industrial warehouse",
    "49": "industrial",
    "50": "agricultural",
    "51": "agricultural",
    "52": "agricultural",
    "53": "agricultural",
    "54": "agricultural",
    "55": "agricultural",
    "56": "agricultural",
    "57": "agricultural",
    "58": "agricultural",
    "59": "agricultural",
    "60": "agricultural",
    "61": "agricultural",
    "62": "agricultural",
    "63": "agricultural",
    "64": "agricultural",
    "65": "agricultural",
    "66": "agricultural",
    "67": "agricultural",
    "68": "agricultural",
    "69": "agricultural",
    "70": "vacant institutional",
    "71": "institutional",
    "72": "institutional",
    "73": "institutional",
    "74": "institutional",
    "75": "institutional",
    "76": "institutional",
    "77": "institutional",
    "78": "institutional",
    "79": "institutional",
    "80": "government",
    "81": "government",
    "82": "conservation",
    "83": "government",
    "84": "government",
    "85": "government",
    "86": "government",
    "87": "conservation",
    "88": "government",
    "89": "government",
    "90": "utility",
    "91": "utility",
    "92": "industrial mining",
    "93": "subsurface rights",
    "94": "right-of-way",
    "95": "wetland/water",
    "96": "wetland sewage",
    "97": "outdoor recreational",
    "98": "utility centrally assessed",
    "99": "non-agricultural acreage",
}


class ZoningCache:
    """Cache por coordenada (arredondada) em SQLite, compartilhado entre rodadas."""

    def __init__(self, db_path: str = "region_signals.db"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS zoning_cache (
                key        TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload    TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    @staticmethod
    def key_for(lat: float, lng: float) -> str:
        return f"{lat:.5f},{lng:.5f}"

    def get(self, key: str, max_age_days: float) -> dict | None:
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM zoning_cache WHERE key = ?", (key,)
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

    def put(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO zoning_cache (key, fetched_at, payload) VALUES (?, ?, ?)",
            (key, datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _query_arcgis_point(
    url: str, lat: float, lng: float, timeout: float
) -> dict[str, Any] | None:
    """Consulta uma camada ArcGIS por ponto; retorna os atributos da 1ª feição."""
    params = {
        "f": "json",
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "resultRecordCount": 1,
    }
    resp = requests.get(
        url, params=params, headers={"User-Agent": _USER_AGENT}, timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    features = data.get("features") or []
    if not features:
        return None
    return features[0].get("attributes") or {}


def _label_from_value(value: str, prefix_map: dict[str, str]) -> str | None:
    """Traduz o valor do GIS num rótulo de zoneamento legível.

    Valores textuais ("VACANT RESIDENTIAL") passam direto; códigos numéricos
    (DOR use codes) são mapeados pelos dois primeiros dígitos.
    """
    value = str(value).strip()
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits and digits == value.replace(".", ""):
        prefix = digits[:2].zfill(2) if len(digits) >= 2 else digits.zfill(2)
        return prefix_map.get(prefix)
    return value.lower()


def lookup_zoning(
    listing: Listing, cfg: Config, cache: ZoningCache | None = None
) -> tuple[str | None, str | None]:
    """Retorna (zoneamento, nota de proveniência) ou (None, None)."""
    section = cfg.raw.get("zoning_lookup", {})
    if not section.get("enabled", False):
        return None, None
    if not listing.lat or not listing.lng:
        return None, None

    timeout = float(section.get("timeout_seconds", 15))
    max_age_days = float(section.get("cache_days", 90) or 90)
    prefix_map = dict(_DOR_PREFIX_LABELS)
    prefix_map.update({
        str(k).zfill(2): str(v)
        for k, v in (section.get("value_prefix_map") or {}).items()
    })

    own_cache = cache is None
    cache = cache or ZoningCache(section.get("cache_db", "region_signals.db"))
    try:
        key = ZoningCache.key_for(listing.lat, listing.lng)
        cached = cache.get(key, max_age_days)
        if cached is not None:
            return cached.get("zoning"), cached.get("note")

        for source in section.get("sources", []):
            name = source.get("name", "gis")
            url = source.get("query_url")
            if not url:
                continue
            try:
                attrs = _query_arcgis_point(url, listing.lat, listing.lng, timeout)
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                print(f"  [aviso] GIS {name} falhou: {type(exc).__name__}")
                continue
            if not attrs:
                continue
            for field in source.get("fields", []):
                value = attrs.get(field)
                if value in (None, ""):
                    continue
                label = _label_from_value(value, prefix_map)
                if not label:
                    continue
                note = f"✓ uso do solo via GIS {name}: {label} ({field}={value})"
                cache.put(key, {"zoning": label, "note": note})
                return label, note

        return None, None
    finally:
        if own_cache:
            cache.close()


def enrich_zoning(
    listing: Listing, cfg: Config, cache: ZoningCache | None = None
) -> str | None:
    """Preenche listing.zoning quando ausente; retorna a nota de proveniência."""
    if listing.zoning:
        return None
    zoning, note = lookup_zoning(listing, cfg, cache=cache)
    if zoning:
        listing.zoning = zoning
    return note
