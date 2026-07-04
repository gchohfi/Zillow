"""Carrega configuração do config.yaml e variáveis de ambiente do .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv é opcional em tempo de execução
    pass


@dataclass
class Config:
    """Configuração tipada do sistema, lida de config.yaml."""

    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        path = Path(path)
        if not path.exists():
            # Permite rodar a partir da raiz do projeto ou de dentro de src/
            alt = Path(__file__).resolve().parent.parent / "config.yaml"
            path = alt if alt.exists() else path
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(raw=data)

    # --- Atalhos de acesso ---
    @property
    def search(self) -> dict[str, Any]:
        return self.raw["search"]

    @property
    def build(self) -> dict[str, Any]:
        return self.raw["build"]

    @property
    def costs(self) -> dict[str, Any]:
        return self.raw["costs"]

    @property
    def rules(self) -> dict[str, Any]:
        return self.raw["rules"]

    @property
    def db_path(self) -> str:
        return self.raw.get("storage", {}).get("db_path", "seen_listings.db")


def env(key: str, default: str | None = None) -> str | None:
    """Lê uma variável de ambiente (vinda do .env ou do ambiente)."""
    value = os.getenv(key, default)
    return value if value else default


# Campos percentuais que precisam estar entre 0 e 1 (frações, não %).
_PCT_FIELDS = (
    "soft_cost_pct",
    "purchase_closing_pct",
    "contingency_pct",
    "carrying_cost_annual_pct",
    "carrying_cost_pct",
    "selling_cost_pct",
)


def validate_config(cfg: "Config") -> list[str]:
    """Valida o config.yaml e retorna a lista de problemas (vazia = ok).

    Falha rápida com mensagem clara é melhor que um erro estranho no meio
    da rodada — especialmente porque os parâmetros são editados à mão.
    """
    errors: list[str] = []
    raw = cfg.raw or {}

    def _number(section: str, key: str, minimum: float | None = None,
                maximum: float | None = None, required: bool = True) -> None:
        data = raw.get(section)
        if not isinstance(data, dict):
            if required:
                errors.append(f"seção '{section}' ausente ou inválida")
            return
        value = data.get(key)
        if value is None:
            if required:
                errors.append(f"'{section}.{key}' ausente")
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors.append(f"'{section}.{key}' deve ser numérico (veio {value!r})")
            return
        if minimum is not None and number < minimum:
            errors.append(f"'{section}.{key}' deve ser ≥ {minimum} (veio {number})")
        if maximum is not None and number > maximum:
            errors.append(f"'{section}.{key}' deve ser ≤ {maximum} (veio {number})")

    _number("search", "center_lat", -90, 90)
    _number("search", "center_lng", -180, 180)
    _number("search", "radius_km", 1)
    _number("build", "living_area_sqft", 1)
    _number("build", "construction_cost_per_sqft", 1)
    _number("build", "resale_price_per_sqft", 1)
    _number("rules", "target_margin", 0, 1)
    _number("rules", "max_land_to_total_investment_pct", 0, 1)

    costs = raw.get("costs")
    if isinstance(costs, dict):
        for field in _PCT_FIELDS:
            if field in costs:
                _number("costs", field, 0, 1, required=False)
    else:
        errors.append("seção 'costs' ausente ou inválida")

    for index, tier in enumerate(raw.get("tiers") or []):
        if not isinstance(tier, dict):
            errors.append(f"tiers[{index}] deve ser um mapa")
            continue
        tier_costs = tier.get("costs") or {}
        for field in _PCT_FIELDS:
            if field in tier_costs:
                try:
                    number = float(tier_costs[field])
                except (TypeError, ValueError):
                    errors.append(f"tiers[{index}].costs.{field} deve ser numérico")
                    continue
                if not 0 <= number <= 1:
                    errors.append(
                        f"tiers[{index}].costs.{field} deve estar entre 0 e 1 (veio {number})"
                    )

    return errors
