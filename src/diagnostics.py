"""Diagnósticos estruturados de falhas em fontes externas."""

from __future__ import annotations

from typing import Any

from .models import Listing


def record_source_error(
    listing: Listing,
    *,
    source: str,
    operation: str,
    error: BaseException,
) -> dict[str, str]:
    """Registra uma falha de forma estável e contável no payload da listagem."""
    entry = {
        "source": str(source),
        "operation": str(operation),
        "error": type(error).__name__,
    }
    errors = listing.raw.setdefault("_source_errors", [])
    if entry not in errors:
        errors.append(entry)
    return entry


def source_error_flags(listing: Listing) -> list[str]:
    """Converte diagnósticos estruturados em flags persistidas no CSV."""
    flags: list[str] = []
    errors: Any = listing.raw.get("_source_errors", [])
    if not isinstance(errors, list):
        return flags
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or "unknown")
        operation = str(entry.get("operation") or "unknown")
        error = str(entry.get("error") or "UnknownError")
        flags.append(
            f"source_error|source={source}|operation={operation}|error={error}"
        )
    return flags
