"""Fontes de dados de listagens de terreno.

A fonte "realtor_rapidapi" é dirigida pelo config.yaml: você descreve o host,
o endpoint, os parâmetros e o mapeamento de campos da API que assinou no RapidAPI,
e o código se adapta — sem necessidade de editar Python para trocar de provedor.

A fonte "rentcast" usa a API oficial da RentCast para listagens à venda.

Para Fase 2/3 (Regrid, ATTOM, RESO/MLS), crie uma classe que herde de `DataSource`
e implemente `fetch_new_land_listings`.
"""

from __future__ import annotations

import abc
import time
from typing import Any

import requests

from .config import Config, env
from .models import Listing


class DataSource(abc.ABC):
    """Interface comum de qualquer fonte de listagens."""

    @abc.abstractmethod
    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        """Retorna as listagens de terreno mais recentes da área de busca."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
#  Utilitários de navegação no JSON (caminhos com pontos, com fallbacks)
# --------------------------------------------------------------------------- #
def dig(obj: Any, path: str) -> Any:
    """Resolve um caminho 'a.b.c' dentro de dicts aninhados; None se faltar."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def first(item: dict[str, Any], paths: list[str]) -> Any:
    """Retorna o primeiro caminho que resolver para um valor não-nulo."""
    for p in paths:
        val = dig(item, p)
        if val not in (None, ""):
            return val
    return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_list_of_dicts(obj: Any) -> list[dict[str, Any]]:
    """Finds a likely listings array when the API response shape changes."""
    if isinstance(obj, list) and all(isinstance(item, dict) for item in obj):
        return obj
    if isinstance(obj, dict):
        for value in obj.values():
            found = _first_list_of_dicts(value)
            if found:
                return found
    return []


# --------------------------------------------------------------------------- #
#  Fonte mock — roda sem chave, para testar o pipeline
# --------------------------------------------------------------------------- #
class MockDataSource(DataSource):
    """Fonte de exemplo — roda sem chave nenhuma, para testar o pipeline."""

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        return [
            Listing(
                id="mock-001", price=95_000, lat=28.4100, lng=-81.5000,
                address="Lot 12, Winter Garden, FL", lot_size_sqft=10_000,
                zoning="residential", listing_date="2026-06-26",
                url="https://example.com/mock-001", source="mock",
            ),
            Listing(
                id="mock-002", price=240_000, lat=28.6000, lng=-81.2000,
                address="Lot 7, Oviedo, FL", lot_size_sqft=8_000,
                zoning="residential", listing_date="2026-06-26",
                url="https://example.com/mock-002", source="mock",
            ),
            Listing(
                id="mock-003", price=70_000, lat=27.9659, lng=-82.8001,
                address="Lot 3, Clearwater, FL", lot_size_sqft=6_500,
                zoning="residential", listing_date="2026-06-26",
                url="https://example.com/mock-003", source="mock",
            ),
            Listing(
                id="mock-004", price=110_000, lat=28.3000, lng=-81.4000,
                address="Lot 22, Kissimmee, FL", lot_size_sqft=12_000,
                zoning="commercial", listing_date="2026-06-26",
                url="https://example.com/mock-004", source="mock",
            ),
        ]


# --------------------------------------------------------------------------- #
#  Fonte Realtor/RapidAPI dirigida por config (Fase 1)
# --------------------------------------------------------------------------- #
class RealtorRapidAPISource(DataSource):
    """Listagens via RapidAPI, configurável pelo bloco `datasource.rapidapi`."""

    def __init__(self, ds_cfg: dict[str, Any]) -> None:
        self.cfg = ds_cfg.get("rapidapi", {})
        self.key = env("RAPIDAPI_KEY")
        self.host = self.cfg.get("host") or env("RAPIDAPI_HOST")
        if not self.key:
            raise RuntimeError(
                "RAPIDAPI_KEY não configurada. Use --mock para testar sem chave, "
                "ou preencha o .env."
            )

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        search = cfg.search
        radius_km = float(search["radius_km"])
        ctx = {
            "lat": search["center_lat"],
            "lng": search["center_lng"],
            "radius_km": round(radius_km, 1),
            "radius_miles": round(radius_km / 1.60934, 1),
        }
        fields = self.cfg.get("fields", {})

        # Busca em cada CEP (multi-CEP cobre os ~180 km); junta e deduplica.
        params_base = self.cfg.get("params", {})
        zip_param = self.cfg.get("zip_param", "postal_code")
        postal_codes = self.cfg.get("postal_codes") or [
            params_base.get(zip_param) or params_base.get("postal_code")
        ]

        by_id: dict[str, Listing] = {}
        for zip_code in [z for z in postal_codes if z]:
            params = dict(params_base)
            params[zip_param] = zip_code
            if zip_param != "postal_code":
                params.pop("postal_code", None)
            try:
                raw_items = self._request(ctx, params)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 403:
                    print("  [erro] RapidAPI recusou a chamada: sua conta nao esta assinada nesta API.")
                    break
                if status == 429:
                    print("  [erro] RapidAPI recusou a chamada: limite de requisicoes atingido.")
                    break
                print(f"  [aviso] falha ao buscar CEP {zip_code}: {exc}")
                continue
            except requests.RequestException as exc:
                print(f"  [aviso] falha ao buscar CEP {zip_code}: {exc}")
                continue
            for item in raw_items:
                listing = self._parse(item, fields)
                if listing.id and listing.id not in by_id:
                    by_id[listing.id] = listing
            print(f"  CEP {zip_code}: {len(raw_items)} listagem(ns)")

        return list(by_id.values())

    def _request(self, ctx: dict[str, Any], params_in: dict[str, Any]) -> list[dict[str, Any]]:
        method = (self.cfg.get("method") or "GET").upper()
        url = self.cfg.get("base_url", f"https://{self.host}").rstrip("/") + \
            self.cfg.get("search_path", "")
        params = _fill(params_in, ctx)
        headers = {"X-RapidAPI-Key": self.key, "X-RapidAPI-Host": self.host}

        if method == "POST":
            resp = requests.post(url, json=params, headers=headers, timeout=30)
        else:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for path in self.cfg.get("results_paths", ["results", "data"]):
            found = dig(data, path)
            if isinstance(found, list):
                return found
        # Último recurso: se a própria resposta já for uma lista.
        return data if isinstance(data, list) else _first_list_of_dicts(data)

    def _parse(self, item: dict[str, Any], fields: dict[str, list[str]]) -> Listing:
        return Listing(
            id=str(first(item, fields.get("id", [])) or ""),
            price=_safe_float(first(item, fields.get("price", []))) or 0.0,
            lat=_safe_float(first(item, fields.get("lat", []))) or 0.0,
            lng=_safe_float(first(item, fields.get("lng", []))) or 0.0,
            address=str(first(item, fields.get("address", [])) or ""),
            lot_size_sqft=_safe_float(first(item, fields.get("lot_size_sqft", []))),
            property_type=str(first(item, fields.get("property_type", [])) or "land"),
            zoning=first(item, fields.get("zoning", [])),
            listing_date=first(item, fields.get("listing_date", [])),
            url=str(first(item, fields.get("url", [])) or ""),
            source="realtor-rapidapi",
            raw=item,
        )


# --------------------------------------------------------------------------- #
#  Fonte RentCast (listagens à venda)
# --------------------------------------------------------------------------- #
class RentCastSource(DataSource):
    """Listagens de terrenos via RentCast Sale Listings API."""

    def __init__(self, ds_cfg: dict[str, Any]) -> None:
        self.cfg = ds_cfg.get("rentcast", {})
        self.errors: list[str] = []
        self.key = env("RENTCAST_API_KEY")
        if not self.key:
            raise RuntimeError(
                "RENTCAST_API_KEY não configurada. Use --mock para testar sem chave, "
                "ou preencha o .env."
            )

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        search = cfg.search
        radius_km = float(search["radius_km"])
        limit = int(self.cfg.get("limit", 500))
        max_pages = int(self.cfg.get("max_pages", 1))
        points = self.cfg.get("search_points") or [
            {
                "name": "Orlando",
                "lat": search["center_lat"],
                "lng": search["center_lng"],
                "radius_miles": min(100, radius_km / 1.60934),
            }
        ]

        by_id: dict[str, Listing] = {}
        for point in points:
            name = point.get("name", "ponto")
            for page in range(max_pages):
                offset = page * limit
                try:
                    raw_items = self._request(point, limit=limit, offset=offset)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status in (401, 403):
                        msg = "RentCast recusou a chamada: confira a RENTCAST_API_KEY/plano."
                        self.errors.append(msg)
                        print(f"  [erro] {msg}")
                        return list(by_id.values())
                    if status == 429:
                        msg = "RentCast recusou a chamada: limite de requisicoes atingido."
                        self.errors.append(msg)
                        print(f"  [erro] {msg}")
                        return list(by_id.values())
                    msg = f"falha ao buscar RentCast {name}: {exc}"
                    self.errors.append(msg)
                    print(f"  [aviso] {msg}")
                    break
                except requests.RequestException as exc:
                    msg = f"falha ao buscar RentCast {name}: {exc}"
                    self.errors.append(msg)
                    print(f"  [aviso] {msg}")
                    break

                for item in raw_items:
                    listing = self._parse(item)
                    if listing.id and listing.id not in by_id:
                        by_id[listing.id] = listing
                print(f"  RentCast {name} offset {offset}: {len(raw_items)} listagem(ns)")

                if len(raw_items) < limit:
                    break

        return list(by_id.values())

    def _request(self, point: dict[str, Any], limit: int, offset: int) -> list[dict[str, Any]]:
        url = self.cfg.get("base_url", "https://api.rentcast.io/v1").rstrip("/") + \
            self.cfg.get("search_path", "/listings/sale")
        params: dict[str, Any] = {
            "latitude": point["lat"],
            "longitude": point["lng"],
            "radius": min(float(point.get("radius_miles", 100)), 100.0),
            "propertyType": self.cfg.get("property_type", "Land"),
            "status": self.cfg.get("status", "Active"),
            "limit": limit,
            "offset": offset,
        }
        optional_params = self.cfg.get("params", {})
        params.update({k: v for k, v in optional_params.items() if v not in (None, "")})
        headers = {"Accept": "application/json", "X-Api-Key": self.key}
        timeout = float(self.cfg.get("timeout_seconds", 60))
        retries = int(self.cfg.get("retries", 2))
        retry_sleep = float(self.cfg.get("retry_sleep_seconds", 3))
        last_exc: requests.RequestException | None = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                resp.raise_for_status()
                break
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status < 500:
                    raise
                last_exc = exc
            except requests.RequestException as exc:
                last_exc = exc
            if attempt < retries:
                print(f"  [aviso] RentCast tentativa {attempt + 1} falhou; tentando novamente...")
                time.sleep(retry_sleep)
        else:
            assert last_exc is not None
            raise last_exc
        data = resp.json()
        return data if isinstance(data, list) else []

    def _parse(self, item: dict[str, Any]) -> Listing:
        address = item.get("formattedAddress") or ", ".join(
            part for part in [
                item.get("addressLine1"),
                item.get("city"),
                item.get("state"),
                item.get("zipCode"),
            ]
            if part
        )
        return Listing(
            id=str(item.get("id") or item.get("mlsNumber") or ""),
            price=_safe_float(item.get("price")) or 0.0,
            lat=_safe_float(item.get("latitude")) or 0.0,
            lng=_safe_float(item.get("longitude")) or 0.0,
            address=str(address or ""),
            lot_size_sqft=_safe_float(item.get("lotSize")),
            property_type=str(item.get("propertyType") or "Land"),
            zoning=item.get("zoning"),
            listing_date=item.get("listedDate") or item.get("createdDate") or item.get("lastSeenDate"),
            url=str(item.get("listingUrl") or item.get("url") or ""),
            source="rentcast",
            raw=item,
        )


def _fill(value: Any, ctx: dict[str, Any]) -> Any:
    """Substitui placeholders {lat} {lng} {radius_km} {radius_miles} recursivamente.

    Suporta dicts e listas aninhados (corpos JSON de APIs POST).
    """
    if isinstance(value, dict):
        return {k: _fill(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ctx) for v in value]
    if isinstance(value, str) and "{" in value:
        try:
            return value.format(**ctx)
        except (KeyError, IndexError):
            return value
    return value


# --------------------------------------------------------------------------- #
#  Fábrica
# --------------------------------------------------------------------------- #
def get_source(cfg: Config, use_mock: bool = False) -> DataSource:
    """Escolhe a fonte: --mock força mock; senão usa datasource.provider do config."""
    ds_cfg = cfg.raw.get("datasource", {})
    provider = "mock" if use_mock else ds_cfg.get("provider", "mock")
    if provider == "mock":
        return MockDataSource()
    if provider == "realtor_rapidapi":
        return RealtorRapidAPISource(ds_cfg)
    if provider == "rentcast":
        return RentCastSource(ds_cfg)
    raise ValueError(f"datasource.provider desconhecido: {provider!r}")
