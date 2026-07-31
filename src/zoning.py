"""Zoneamento legal e uso cadastral indicativo via GIS/Regrid.

Somente campos explicitamente configurados como zoning legal podem preencher
`listing.zoning`. DOR_UC, PA_UC, usedesc e landuse são preservados como
evidência cadastral indicativa e nunca aprovam automaticamente uma compra.

Tudo é *fail-open*: se o GIS falhar, a listagem segue para o Radar como hoje.
As fontes são dirigidas pelo config (`zoning_lookup.sources`), então dá para
trocar a URL ou adicionar GIS de county sem mexer em Python.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import Config, env
from .diagnostics import record_source_error
from .models import Listing
from .viability import resolve_county

_USER_AGENT = "orlando-land-detector/1.0 (https://github.com/gchohfi/Zillow)"

# Códigos de uso cadastral do Florida DOR. O NAL atual usa três posições
# (000..099); o formato legado tinha quatro (dois dígitos DOR + dois locais).
# Estes rótulos são evidência indicativa, nunca zoneamento legal.
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

_DOR_FIELDS = {"DORUC"}
_DEFAULT_ZONING_FIELDS = {
    "ZONING",
    "ZONINGDESCRIPTION",
    "ZONINGTYPE",
    "ZONECODE",
    "ZONEDESC",
}
_DEFAULT_CADASTRAL_FIELDS = {
    "DORUC",
    "PAUC",
    "PARUSEDESC",
    "USEDESC",
    "USECODE",
    "LANDUSE",
}
_CACHE_SCHEMA_VERSION = 2


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
    url: str,
    lat: float,
    lng: float,
    timeout: float,
    out_fields: str = "*",
    retries: int = 1,
    radius_m: float = 0,
) -> dict[str, Any] | None:
    """Consulta uma camada ArcGIS por ponto; retorna os atributos da 1ª feição.

    Pedir só os campos necessários (out_fields) é essencial em camadas
    gigantes como o cadastro estadual (~10,8 mi de parcelas): outFields=*
    força o servidor a montar a resposta completa e estoura o tempo.
    """
    params = {
        "f": "json",
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "resultRecordCount": 1,
    }
    if radius_m:
        # Buffer em metros: absorve geocodes que caem na rua em frente ao lote.
        params["distance"] = int(radius_m)
        params["units"] = "esriSRUnit_Meter"
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url, params=params, headers={"User-Agent": _USER_AGENT}, timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.Timeout as exc:
            # Camadas hospedadas "frias" costumam responder na 2ª tentativa.
            last_exc = exc
            if attempt < retries:
                time.sleep(2)
    else:
        assert last_exc is not None
        raise last_exc
    if data.get("error"):
        # Campo pedido inexistente na camada (nomes mudam entre vintages):
        # refaz com todos os campos em vez de falhar — mais lento, mas certo.
        if out_fields != "*":
            return _query_arcgis_point(
                url,
                lat,
                lng,
                timeout,
                out_fields="*",
                retries=retries,
                radius_m=radius_m,
            )
        raise RuntimeError(str(data["error"]))
    features = data.get("features") or []
    if not features:
        return None
    return features[0].get("attributes") or {}


def _query_regrid_point(
    url: str, lat: float, lng: float, token: str, timeout: float,
    radius_m: float = 0,
) -> dict[str, Any] | None:
    """Consulta a parcela no ponto via Regrid Parcels API (v2).

    Retorna o dicionário de campos da parcela (zoning, usedesc, owner etc.).
    Um raio pequeno (metros) absorve geocodes que caem na rua em frente ao
    lote — ponto exato com radius=0 não acha parcela em via pública.
    """
    params: dict[str, Any] = {"lat": lat, "lon": lng, "token": token, "limit": 1}
    if radius_m:
        params["radius"] = int(radius_m)
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    features = None
    if isinstance(data, dict):
        parcels = data.get("parcels")
        if isinstance(parcels, dict):
            features = parcels.get("features")
        if features is None:
            features = data.get("features")
    if features is None:
        # Corpo sem a lista de feições: erro da API disfarçado de 200
        # (token inválido, quota estourada etc.) — expõe em vez de engolir.
        raise RuntimeError(f"resposta inesperada da Regrid: {str(data)[:200]}")
    if not features:
        return None
    props = features[0].get("properties") or {}
    fields = props.get("fields") if isinstance(props.get("fields"), dict) else props
    return fields if isinstance(fields, dict) else None


def _field_key(field: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(field or "").upper())


def _label_from_value(
    value: str,
    prefix_map: dict[str, str],
    *,
    field: str | None = None,
) -> str | None:
    """Traduz texto ou DOR_UC sem confundir códigos locais com o padrão DOR."""
    value = str(value).strip()
    if not value:
        return None

    numeric = re.fullmatch(r"(\d+)(?:\.0+)?", value)
    if numeric:
        # Sem nome de campo, assume DOR para manter a função testável. Quando
        # o campo é conhecido, PA_UC/usecode numérico nunca é reinterpretado.
        if field is not None and _field_key(field) not in _DOR_FIELDS:
            return None
        digits = numeric.group(1)
        if len(digits) <= 2:
            dor_code = f"{int(digits):02d}"
        elif len(digits) == 3:
            number = int(digits)
            if number > 99:
                return None
            dor_code = f"{number:02d}"
        elif len(digits) == 4:
            dor_code = digits[:2]
        else:
            return None
        return prefix_map.get(dor_code)

    # Um DOR_UC textual é header/referência ou dado inválido, não descrição.
    if field is not None and _field_key(field) in _DOR_FIELDS:
        return None
    return value.lower()


def _role_fields(source: dict[str, Any], key: str, defaults: set[str]) -> list[str]:
    configured = source.get(key)
    if configured is not None:
        return [str(field) for field in configured if field]
    return [
        str(field)
        for field in source.get("fields", [])
        if field and _field_key(str(field)) in defaults
    ]


def _record_cadastral_use(
    listing: Listing,
    *,
    label: str,
    code: Any,
    field: str,
    source: str,
) -> None:
    evidence = {
        "label": label,
        "code": str(code),
        "field": field,
        "source": source,
        "status": "indicativo",
    }
    items = listing.raw.setdefault("_cadastral_use_evidence", [])
    if evidence not in items:
        items.append(evidence)
    # A ordem das fontes define a preferência. Regrid vem antes do fallback DOR.
    listing.raw.setdefault("_cadastral_use", label)
    listing.raw.setdefault("_cadastral_use_code", str(code))
    listing.raw.setdefault("_cadastral_use_field", field)
    listing.raw.setdefault("_cadastral_use_source", source)
    listing.raw.setdefault("_cadastral_use_status", "indicativo")


def _cache_metadata(listing: Listing) -> dict[str, Any]:
    return {
        "cadastral_use": listing.raw.get("_cadastral_use"),
        "cadastral_use_code": listing.raw.get("_cadastral_use_code"),
        "cadastral_use_field": listing.raw.get("_cadastral_use_field"),
        "cadastral_use_source": listing.raw.get("_cadastral_use_source"),
        "cadastral_use_status": listing.raw.get("_cadastral_use_status"),
        "cadastral_use_evidence": listing.raw.get("_cadastral_use_evidence", []),
    }


def _restore_cached_metadata(listing: Listing, cached: dict[str, Any]) -> None:
    mapping = {
        "cadastral_use": "_cadastral_use",
        "cadastral_use_code": "_cadastral_use_code",
        "cadastral_use_field": "_cadastral_use_field",
        "cadastral_use_source": "_cadastral_use_source",
        "cadastral_use_status": "_cadastral_use_status",
        "cadastral_use_evidence": "_cadastral_use_evidence",
    }
    for cache_key, raw_key in mapping.items():
        value = cached.get(cache_key)
        if value not in (None, "", []):
            listing.raw[raw_key] = value


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
    failure_retry_days = float(section.get("failure_retry_hours", 6) or 6) / 24
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
            parcel_data = cached.get("parcel_data")
            if isinstance(parcel_data, dict):
                listing.raw.setdefault("_parcel_data", {}).update(parcel_data)
                listing.raw["_parcel_source"] = cached.get("source", "cache")
            _restore_cached_metadata(listing, cached)
            cache_is_current = cached.get("schema_version") == _CACHE_SCHEMA_VERSION
            if cache_is_current and cached.get("zoning_kind") == "legal" and cached.get("zoning"):
                return cached.get("zoning"), cached.get("note")
            # Falha recente cacheada: não martela GIS indisponível a cada
            # rodada. Cache antigo é ignorado porque pode conter DOR_UC
            # indevidamente gravado como zoning legal.
            if cache_is_current and cache.get(key, failure_retry_days) is not None:
                return None, None

        county, _ = resolve_county(listing, cfg)
        last_parcel_data: dict[str, Any] | None = None
        last_parcel_source = ""
        for source in section.get("sources", []):
            name = source.get("name", "gis")
            source_type = source.get("type", "arcgis")
            url = source.get("query_url")
            # Fontes por county (camadas menores e mais rápidas): a URL é
            # escolhida pelo county resolvido via ZIP da listagem.
            by_county = source.get("query_url_by_county") or {}
            if not url and by_county:
                url = by_county.get(county)
            if not url:
                continue
            fields = [str(f) for f in source.get("fields", []) if f]
            zoning_fields = _role_fields(source, "zoning_fields", _DEFAULT_ZONING_FIELDS)
            cadastral_fields = _role_fields(
                source, "cadastral_use_fields", _DEFAULT_CADASTRAL_FIELDS
            )
            radius_m = float(source.get("radius_m", section.get("radius_m", 0)) or 0)
            try:
                if source_type == "regrid":
                    token = env("REGRID_API_KEY")
                    if not token:
                        continue  # liga sozinho quando o secret existir
                    attrs = _query_regrid_point(
                        url, listing.lat, listing.lng, token, timeout,
                        radius_m=radius_m,
                    )
                else:
                    out_fields = ",".join(fields) if fields else "*"
                    attrs = _query_arcgis_point(
                        url, listing.lat, listing.lng, timeout,
                        out_fields=out_fields, radius_m=radius_m,
                    )
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                diagnostic = record_source_error(
                    listing,
                    source=name,
                    operation="zoning_lookup",
                    error=exc,
                )
                print(
                    "  [aviso] source_error"
                    f" source={diagnostic['source']}"
                    f" operation={diagnostic['operation']}"
                    f" error={diagnostic['error']}"
                )
                continue
            if not attrs:
                # Resposta válida mas sem parcela no ponto (água, via pública,
                # área fora da cobertura da fonte): registra para diagnóstico.
                print(f"  [aviso] GIS {name}: sem parcela no ponto")
                continue
            # Preserva os atributos da parcela para a triagem de área líquida,
            # acesso, utilities e entitlement. A lista de campos varia por
            # plano/provedor, por isso mantemos o payload sem inventar valores.
            listing.raw.setdefault("_parcel_data", {}).update(attrs)
            listing.raw["_parcel_source"] = name
            last_parcel_data = dict(listing.raw["_parcel_data"])
            last_parcel_source = name

            # Uso cadastral é apenas evidência indicativa. Nunca alimenta
            # listing.zoning nem desbloqueia aprovação automática.
            for field in cadastral_fields:
                value = attrs.get(field)
                if value in (None, ""):
                    continue
                label = _label_from_value(value, prefix_map, field=field)
                if not label:
                    continue
                _record_cadastral_use(
                    listing,
                    label=label,
                    code=value,
                    field=field,
                    source=name,
                )
                break

            # Somente campos declarados/depreendidos como zoning legal podem
            # preencher listing.zoning.
            for field in zoning_fields:
                value = attrs.get(field)
                if value in (None, ""):
                    continue
                label = str(value).strip().lower()
                if not label:
                    continue
                note = f"✓ zoning legal via GIS {name}: {label} ({field}={value})"
                owner = str(attrs.get("owner") or "").strip()
                if owner:
                    # Dono da parcela (Regrid): abre a porta do contato direto.
                    note += f" · dono: {owner}"
                cache.put(key, {
                    "schema_version": _CACHE_SCHEMA_VERSION,
                    "zoning": label,
                    "zoning_kind": "legal",
                    "note": note,
                    "parcel_data": attrs,
                    "source": name,
                    **_cache_metadata(listing),
                })
                return label, note

            # A fonte respondeu com dados úteis, mesmo sem um campo de zoning.
            # Guarda-os para due diligence e tenta a próxima fonte para zoning.
        # Nada respondeu: registra a falha para poupar as próximas rodadas.
        cache.put(key, {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "zoning": None,
            "zoning_kind": None,
            "note": None,
            "parcel_data": last_parcel_data,
            "source": last_parcel_source,
            **_cache_metadata(listing),
        })
        return None, None
    finally:
        if own_cache:
            cache.close()


def enrich_zoning(
    listing: Listing, cfg: Config, cache: ZoningCache | None = None
) -> str | None:
    """Preenche listing.zoning apenas com evidência de zoning legal."""
    had_zoning = bool(listing.zoning)
    zoning, note = lookup_zoning(listing, cfg, cache=cache)
    if zoning and not listing.zoning:
        listing.zoning = zoning
    # Com zoning já preenchido, ainda consultamos/restauramos os atributos da
    # parcela para due diligence, mas não anunciamos uma confirmação redundante.
    return None if had_zoning else note
