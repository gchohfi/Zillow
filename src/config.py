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
