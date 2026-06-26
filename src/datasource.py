"""Fontes de dados de listagens de terreno.

A arquitetura é plugável: para usar Regrid, ATTOM ou um feed RESO/MLS na Fase 2/3,
crie uma nova classe que herde de `DataSource` e implemente `fetch_new_land_listings`.
"""

from __future__ import annotations

import abc
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


class MockDataSource(DataSource):
    """Fonte de exemplo — roda sem chave nenhuma, para testar o pipeline."""

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        # Alguns terrenos fictícios dentro e fora do raio, com perfis variados.
        return [
            Listing(
                id="mock-001",
                price=95_000,                 # bom: terreno barato p/ ARV alto
                lat=28.4100, lng=-81.5000,     # ~15 km de Orlando
                address="Lot 12, Winter Garden, FL",
                lot_size_sqft=10_000,
                zoning="residential",
                listing_date="2026-06-26",
                url="https://example.com/mock-001",
                source="mock",
            ),
            Listing(
                id="mock-002",
                price=240_000,                # caro demais p/ ARV → reprova
                lat=28.6000, lng=-81.2000,
                address="Lot 7, Oviedo, FL",
                lot_size_sqft=8_000,
                zoning="residential",
                listing_date="2026-06-26",
                url="https://example.com/mock-002",
                source="mock",
            ),
            Listing(
                id="mock-003",
                price=70_000,
                lat=27.9659, lng=-82.8001,     # Clearwater, ~160 km → fora do raio
                address="Lot 3, Clearwater, FL",
                lot_size_sqft=6_500,
                zoning="residential",
                listing_date="2026-06-26",
                url="https://example.com/mock-003",
                source="mock",
            ),
            Listing(
                id="mock-004",
                price=110_000,
                lat=28.3000, lng=-81.4000,     # dentro do raio
                address="Lot 22, Kissimmee, FL",
                lot_size_sqft=12_000,
                zoning="commercial",           # zoneamento não residencial → reprova se regra ligada
                listing_date="2026-06-26",
                url="https://example.com/mock-004",
                source="mock",
            ),
        ]


class RealtorRapidAPISource(DataSource):
    """Fase 1: listagens da Realtor.com via RapidAPI.

    Os endpoints variam conforme a API que você assinar no RapidAPI. O método
    `_search` abaixo já monta a chamada; ajuste `path` e os parâmetros conforme
    a documentação da API escolhida, e `_parse` conforme o formato da resposta.
    """

    def __init__(self) -> None:
        self.key = env("RAPIDAPI_KEY")
        self.host = env("RAPIDAPI_HOST", "us-real-estate.p.rapidapi.com")
        if not self.key:
            raise RuntimeError(
                "RAPIDAPI_KEY não configurada. Use --mock para testar sem chave, "
                "ou preencha o .env."
            )

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        search = cfg.search
        raw_items = self._search(
            lat=search["center_lat"],
            lng=search["center_lng"],
            radius_km=search["radius_km"],
        )
        return [self._parse(item) for item in raw_items]

    def _search(self, lat: float, lng: float, radius_km: float) -> list[dict[str, Any]]:
        radius_miles = radius_km / 1.60934
        url = f"https://{self.host}/v2/for-sale-by-location"  # AJUSTE conforme a API
        params = {
            "lat": lat,
            "lng": lng,
            "radius": round(radius_miles, 1),
            "property_type": "land",
            "sort": "newest",
            "limit": 50,
        }
        headers = {"X-RapidAPI-Key": self.key, "X-RapidAPI-Host": self.host}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # AJUSTE conforme o caminho dos resultados na resposta da sua API:
        return data.get("data", {}).get("results", []) or data.get("results", [])

    def _parse(self, item: dict[str, Any]) -> Listing:
        # AJUSTE os nomes dos campos conforme o JSON da sua API.
        loc = item.get("location", {}).get("address", {}) or {}
        coord = (item.get("location", {}).get("address", {}) or {}).get("coordinate", {}) or {}
        return Listing(
            id=str(item.get("property_id") or item.get("listing_id") or item.get("id")),
            price=float(item.get("list_price") or 0),
            lat=float(coord.get("lat") or 0),
            lng=float(coord.get("lon") or coord.get("lng") or 0),
            address=loc.get("line", "") or item.get("address", ""),
            lot_size_sqft=_safe_float(item.get("lot_size", {}).get("size")),
            zoning=item.get("zoning"),
            listing_date=item.get("list_date"),
            url=item.get("href", "") or item.get("rdc_web_url", ""),
            source="realtor-rapidapi",
            raw=item,
        )


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_source(use_mock: bool) -> DataSource:
    """Fábrica: escolhe a fonte de dados conforme o modo."""
    return MockDataSource() if use_mock else RealtorRapidAPISource()
