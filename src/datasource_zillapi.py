"""Fonte Zillapi com limite rígido de créditos por rodada."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from .config import Config, env
from .datasource import DataSource, SourceOutcome
from .models import Listing


def _safe_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lot_size_sqft(item: dict[str, Any]) -> float | None:
    home_info = item.get("hdpData", {}).get("homeInfo", {})
    if not isinstance(home_info, dict):
        home_info = {}
    value = item.get("lotAreaValue") or home_info.get("lotAreaValue")
    unit = str(item.get("lotAreaUnit") or home_info.get("lotAreaUnit") or "").lower()
    number = _safe_float(value)
    if number:
        return number * 43_560 if "acre" in unit else number

    text = str(item.get("lotAreaString") or home_info.get("lotAreaString") or "")
    match = re.search(r"([\d,.]+)\s*(acre|acres|sq\.?\s*ft|sqft)?", text, re.I)
    if not match:
        return None
    number = _safe_float(match.group(1))
    if not number:
        return None
    return number * 43_560 if "acre" in (match.group(2) or "").lower() else number


class ZillapiSource(DataSource):
    """Busca um subconjunto diário de terrenos sem ultrapassar o orçamento."""

    def __init__(self, ds_cfg: dict[str, Any]) -> None:
        super().__init__()
        self.cfg = ds_cfg.get("zillapi", {})
        self.api_key = env("ZILLAPI_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ZILLAPI_KEY não configurada. Cadastre-a como secret; não use arquivo local."
            )
        self.base_url = str(
            self.cfg.get("base_url") or "https://api.zillapi.com/v1"
        ).rstrip("/")
        self.errors: list[str] = []
        self.metrics: dict[str, Any] = {
            "credits_consumed": 0,
            "bboxes_scanned": 0,
        }

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _balance(self) -> int:
        response = requests.get(
            f"{self.base_url}/me",
            headers=self.headers,
            timeout=float(self.cfg.get("timeout_seconds", 60)),
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        return int((data.get("credits") or {}).get("balance", 0))

    def _selected_bboxes(self) -> list[dict[str, float]]:
        bboxes = list(self.cfg.get("bboxes") or [])
        if not bboxes:
            raise RuntimeError("datasource.zillapi.bboxes precisa ter ao menos uma área")
        count = min(int(self.cfg.get("bboxes_per_run", 1)), len(bboxes))
        day_index = datetime.now(timezone.utc).date().toordinal() % len(bboxes)
        return [bboxes[(day_index + offset) % len(bboxes)] for offset in range(count)]

    def fetch_new_land_listings(self, cfg: Config) -> list[Listing]:
        reserve = int(self.cfg.get("reserve_credits", 100))
        hard_cap = min(int(self.cfg.get("max_items_per_run", 29)), 29)
        try:
            balance_before = self._balance()
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            message = f"Zillapi não informou o saldo ({type(exc).__name__})"
            self.errors.append(message)
            self._finish(succeeded=0, failed=1, diagnostics=self.errors)
            return []

        available = max(0, balance_before - reserve)
        allowance = min(hard_cap, available)
        self.metrics.update({
            "credit_balance_before": balance_before,
            "credit_floor": reserve,
            "max_items_allowed": allowance,
        })
        if allowance < 1:
            message = f"saldo baixo: {balance_before} créditos; scan pausado no piso {reserve}"
            self.errors.append(message)
            self.outcome = SourceOutcome(status="degraded", diagnostics=[message])
            return []

        selected = self._selected_bboxes()
        per_bbox = max(1, allowance // len(selected))
        remaining = allowance
        by_id: dict[str, Listing] = {}
        succeeded = failed = 0

        for index, bbox in enumerate(selected):
            max_items = remaining if index == len(selected) - 1 else min(per_bbox, remaining)
            payload = {
                "filters": {
                    "status": self.cfg.get("status", "for_sale"),
                    "bbox": {key: float(bbox[key]) for key in ("west", "south", "east", "north")},
                    "price": {
                        "min": int(self.cfg.get("min_price", 0)),
                        "max": int(self.cfg.get("max_price", 5_000_000)),
                    },
                    "homeTypes": ["lot"],
                },
                "extractionMethod": "PAGINATION",
                "maxItems": max_items,
                "async": False,
            }
            try:
                response = requests.post(
                    f"{self.base_url}/search",
                    json=payload,
                    headers=self.headers,
                    timeout=float(self.cfg.get("timeout_seconds", 60)),
                )
                response.raise_for_status()
                body = response.json()
                rows = body.get("data") or []
                if not isinstance(rows, list):
                    raise ValueError("resposta sem lista em data")
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                message = f"Zillapi recusou a busca (HTTP {status or 'desconhecido'})"
                self.errors.append(message)
                failed += 1
                if status in (401, 402, 403, 429):
                    break
                continue
            except (requests.RequestException, ValueError, TypeError) as exc:
                self.errors.append(f"Zillapi falhou ({type(exc).__name__})")
                failed += 1
                continue

            succeeded += 1
            self.metrics["bboxes_scanned"] += 1
            self.metrics["credits_consumed"] += max(1, len(rows))
            remaining = max(0, remaining - max(1, len(rows)))
            for item in rows:
                if not isinstance(item, dict):
                    continue
                listing = self._parse(item)
                if listing.id and listing.id not in by_id:
                    by_id[listing.id] = listing
            if remaining < 1:
                break

        try:
            self.metrics["credit_balance_after"] = self._balance()
        except (requests.RequestException, ValueError, TypeError, KeyError):
            self.metrics["credit_balance_after"] = max(
                0, balance_before - int(self.metrics["credits_consumed"])
            )
        self._finish(succeeded=succeeded, failed=failed, diagnostics=self.errors)
        return list(by_id.values())

    def _parse(self, item: dict[str, Any]) -> Listing:
        home_info = item.get("hdpData", {}).get("homeInfo", {})
        if not isinstance(home_info, dict):
            home_info = {}
        address_data = item.get("address") if isinstance(item.get("address"), dict) else {}
        street = item.get("addressStreet") or address_data.get("streetAddress") or ""
        city = item.get("addressCity") or address_data.get("city") or ""
        state = item.get("addressState") or address_data.get("state") or ""
        zipcode = item.get("addressZipcode") or address_data.get("zipcode") or ""
        address = ", ".join(str(part) for part in (street, city, state, zipcode) if part)
        lat_long = item.get("latLong") if isinstance(item.get("latLong"), dict) else {}
        zpid = str(item.get("zpid") or home_info.get("zpid") or "")
        detail_url = str(item.get("detailUrl") or "")
        if detail_url.startswith("/"):
            detail_url = f"https://www.zillow.com{detail_url}"
        return Listing(
            id=zpid,
            price=_safe_float(item.get("unformattedPrice") or item.get("price")) or 0.0,
            lat=_safe_float(lat_long.get("latitude") or item.get("latitude")) or 0.0,
            lng=_safe_float(lat_long.get("longitude") or item.get("longitude")) or 0.0,
            address=address,
            lot_size_sqft=_lot_size_sqft(item),
            property_type=str(item.get("homeType") or home_info.get("homeType") or "LOT"),
            listing_date=item.get("listDate") or home_info.get("datePosted"),
            url=detail_url,
            source="zillapi",
            raw={**item, "_zestimate": item.get("zestimate") or home_info.get("zestimate")},
        )
