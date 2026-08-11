"""Orquestrador: busca → geofiltro → novidade → viabilidade → alerta."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, env, validate_config
from .availability import check_availability
from .arv import enrich_arv
from .datasource import get_source
from .diagnostics import source_error_flags
from .due_diligence import assess_due_diligence
from .geo import within_radius
from .notifier import notify, notify_radar, send_message, send_whatsapp_status
from .red_flags import apply_red_flags, mark_flood_zone
from .rental import apply_rental_analysis, enrich_rent
from .region_signals import SignalsCache, get_region_signals, prefetch_config_zips
from .reporter import append_evaluations, append_results
from .review import classify_review_status, is_radar_candidate
from .search_spec import apply_search_spec
from .storage import SeenStore
from .viability import evaluate
from .zoning import ZoningCache, enrich_zoning


@dataclass(frozen=True)
class RunOutcome:
    status: str
    source_status: str
    source_captured_at: str
    total: int = 0


def _source_outcome(source: object) -> tuple[str, str, list[str]]:
    outcome = getattr(source, "outcome", None)
    errors = list(getattr(source, "errors", []) or [])
    status = getattr(outcome, "status", None) or ("failed" if errors else "healthy")
    captured_at = getattr(outcome, "captured_at", None) or datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")
    diagnostics = list(getattr(outcome, "diagnostics", []) or errors)
    return status, captured_at, diagnostics[:5]


def _write_run_status(
    cfg: Config,
    *,
    source_name: str,
    source_status: str,
    source_captured_at: str,
    diagnostics: list[str],
    stage: str,
    total: int,
    source_metrics: dict | None = None,
) -> None:
    path = cfg.raw.get("output", {}).get("run_status_path", "scan_status.json")
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source_name,
        "source_result": source_status,
        "source_captured_at": source_captured_at,
        "diagnostics": diagnostics,
        "stage": stage,
        "listings_returned": total,
        "source_metrics": source_metrics or {},
        "status_updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _close_resources(
    store: SeenStore,
    signals_cache: SignalsCache | None,
    zoning_cache: ZoningCache | None,
) -> None:
    if signals_cache is not None:
        signals_cache.close()
    if zoning_cache is not None:
        zoning_cache.close()
    store.close()


def _format_run_summary(
    *,
    source_name: str,
    radius_km: float,
    total: int,
    out_of_radius: int,
    already_seen: int,
    unavailable: int,
    not_viable: int,
    failed: int,
    viable_new: int,
    radar: int = 0,
    dashboard_url: str | None = None,
    source_metrics: dict | None = None,
) -> str:
    status = "Sem oportunidade viável nova nesta rodada."
    if viable_new:
        status = "Oportunidades viáveis foram enviadas em mensagens separadas."
    elif radar:
        status = "Sem oportunidade aprovada; há candidatos no Radar para revisão manual."
    lines = [
        "[Orlando Land] Resumo da rodada",
        status,
        f"Fonte: {source_name}",
        f"Raio: {radius_km} km de Orlando",
        f"Listagens encontradas: {total}",
        f"Viáveis novas: {viable_new}",
        f"Radar/revisão: {radar}",
        f"Já vistas: {already_seen}",
        f"Reprovadas: {not_viable}",
        f"Indisponíveis/antigas: {unavailable}",
        f"Fora do raio: {out_of_radius}",
        f"Falhas: {failed}",
    ]
    source_metrics = source_metrics or {}
    if "credits_consumed" in source_metrics:
        lines.append(f"Créditos consumidos: {source_metrics['credits_consumed']}")
    if "credit_balance_after" in source_metrics:
        lines.append(f"Saldo de créditos: {source_metrics['credit_balance_after']}")
    if source_metrics.get("max_items_allowed") == 0:
        lines.append("Saldo baixo — scan pausado pelo orçamento configurado.")
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    return "\n".join(lines)


def run(use_mock: bool = False, dry_run: bool = False) -> RunOutcome:
    cfg = Config.load()
    config_errors = validate_config(cfg)
    if config_errors:
        print("[config] config.yaml inválido; corrija antes de rodar:")
        for error in config_errors:
            print(f"  - {error}")
        return RunOutcome("failed", "failed", datetime.now(timezone.utc).isoformat())
    try:
        source = get_source(cfg, use_mock)
    except RuntimeError as exc:
        print(f"[config] {exc}")
        return RunOutcome("failed", "failed", datetime.now(timezone.utc).isoformat())
    store = SeenStore(":memory:" if use_mock or dry_run else cfg.db_path)

    search = cfg.search
    center_lat, center_lng = search["center_lat"], search["center_lng"]
    radius_km = search["radius_km"]

    print(f"Buscando terrenos num raio de {radius_km} km de Orlando "
          f"({'mock' if use_mock else source.__class__.__name__})...")

    listings = source.fetch_new_land_listings(cfg)
    print(f"  {len(listings)} listagem(ns) retornada(s) pela fonte.")
    source_status, source_captured_at, source_diagnostics = _source_outcome(source)
    source_name = "mock" if use_mock else source.__class__.__name__
    source_metrics = dict(getattr(source, "metrics", {}) or {})

    def record_runtime_failure(code: str) -> None:
        if not dry_run and not use_mock:
            _write_run_status(
                cfg,
                source_name=source_name,
                source_status=source_status,
                source_captured_at=source_captured_at,
                diagnostics=[*source_diagnostics, code][:5],
                stage="failed",
                total=len(listings),
                source_metrics=source_metrics,
            )

    if not dry_run and not use_mock:
        _write_run_status(
            cfg,
            source_name=source_name,
            source_status=source_status,
            source_captured_at=source_captured_at,
            diagnostics=source_diagnostics,
            stage="failed" if source_status == "failed" else "fetched",
            total=len(listings),
            source_metrics=source_metrics,
        )
    if source_status == "failed":
        send_message(
            "[Orlando Land] Falha na fonte de dados",
            "A fonte principal falhou nesta rodada. O resultado nao representa zero listagens.\n\n"
            + "\n".join(f"- {err}" for err in source_diagnostics[:3]),
            dry_run=dry_run,
            delivery_store=store,
        )
        store.close()
        return RunOutcome("failed", source_status, source_captured_at, len(listings))

    viable_new = []
    radar_candidates = []
    evaluated_results = []
    reserved_keys: set[str] = set()
    n_out_of_radius = n_already_seen = n_unavailable = n_not_viable = n_failed = 0

    signals_cfg = cfg.raw.get("region_signals", {})
    signals_cache = None
    if signals_cfg.get("enabled", False) and not use_mock and not dry_run:
        signals_cache = SignalsCache(signals_cfg.get("cache_db", "region_signals.db"))

    zoning_cfg = cfg.raw.get("zoning_lookup", {})
    zoning_cache = None
    n_zoning_confirmed = 0
    if zoning_cfg.get("enabled", False) and not use_mock and not dry_run:
        zoning_cache = ZoningCache(zoning_cfg.get("cache_db", "region_signals.db"))

    for listing in listings:
        inside, dist = within_radius(
            center_lat, center_lng, listing.lat, listing.lng, radius_km
        )
        listing.distance_km = dist
        if not inside:
            n_out_of_radius += 1
            continue

        key = SeenStore.key_for(listing)
        if key in reserved_keys or not store.is_new(listing):
            n_already_seen += 1
            continue
        reserved_keys.add(key)
        store.record_stage(listing, "fetched")

        availability_reasons = []
        if not use_mock:
            is_available, availability_reasons = check_availability(listing, cfg)
            if not is_available:
                n_unavailable += 1
                continue

        if zoning_cache is not None:
            had_zoning = bool(listing.zoning)
            zoning_note = enrich_zoning(listing, cfg, cache=zoning_cache)
            if zoning_note:
                availability_reasons.append(zoning_note)
            if zoning_note and not had_zoning and listing.zoning:
                n_zoning_confirmed += 1

        flood = None
        if not use_mock:
            enrich_arv(listing, cfg)
            # Zona FEMA antes da avaliação: alto risco encarece o seguro
            # do carrego dentro do próprio motor de viabilidade.
            flood = mark_flood_zone(listing, cfg)

        try:
            result = evaluate(listing, cfg)
        except Exception as exc:  # noqa: BLE001
            n_failed += 1
            store.record_stage(listing, "failed", error=type(exc).__name__)
            print(
                f"  [aviso] listagem {listing.id or '(sem id)'} nao avaliada: "
                f"{type(exc).__name__}"
            )
            continue
        result.reasons.extend(availability_reasons)
        if flood is not None:
            apply_red_flags(result, cfg, flood=flood)
        for flag in source_error_flags(listing):
            if flag not in result.risk_flags:
                result.risk_flags.append(flag)
            reason = f"⚠ {flag}"
            if reason not in result.reasons:
                result.reasons.append(reason)
        assess_due_diligence(result, cfg)
        classify_review_status(result, cfg)
        apply_search_spec(result, cfg)
        if signals_cache is not None and result.review_status != "reprovado":
            signals = get_region_signals(
                result.zip_code, listing.lat, listing.lng, cfg, cache=signals_cache
            )
            if signals:
                result.growth_score = signals.get("score")
                result.growth_signals = signals
        # Lente de renda só para o que vira alerta/radar: poupa a cota da
        # RentCast (1 chamada extra por candidato, não por listagem).
        if not use_mock and result.review_status != "reprovado":
            enrich_rent(listing, cfg)
            apply_rental_analysis(result, cfg)
        evaluated_results.append(result)
        store.record_stage(listing, "evaluated")

        if result.is_viable:
            viable_new.append(result)
        elif is_radar_candidate(result):
            radar_candidates.append(result)
        else:
            n_not_viable += 1

    print(f"  fora do raio: {n_out_of_radius} | já vistos: {n_already_seen} | "
          f"indisponíveis/provavelmente antigas: {n_unavailable} | "
          f"radar: {len(radar_candidates)} | reprovadas: {n_not_viable} | falhas: {n_failed} | "
          f"viáveis NOVOS: {len(viable_new)}")
    if zoning_cache is not None:
        print(f"  [zoning] zoning legal confirmado via GIS: {n_zoning_confirmed}")

    rejected_results = [
        result
        for result in evaluated_results
        if not result.is_viable and result not in radar_candidates
    ]

    # Dry-run não grava banco/CSV; em execução real, outputs obrigatórios vêm
    # antes de qualquer confirmação em seen_listings.
    csv_path = cfg.raw.get("output", {}).get("csv_path")
    evaluations_csv_path = cfg.raw.get("output", {}).get("evaluations_csv_path")
    if not dry_run:
        try:
            if evaluations_csv_path and evaluated_results:
                append_evaluations(evaluated_results, evaluations_csv_path, cfg=cfg)
            if csv_path and viable_new:
                append_results(viable_new, csv_path, cfg=cfg)
            for result in evaluated_results:
                store.record_stage(result.listing, "outputs_written")
            for result in rejected_results:
                store.mark_seen(result.listing)
        except Exception as exc:
            for result in evaluated_results:
                store.record_stage(result.listing, "failed", error=type(exc).__name__)
            record_runtime_failure(f"persistence:{type(exc).__name__}")
            _close_resources(store, signals_cache, zoning_cache)
            raise

    if notify(viable_new, dry_run=dry_run, delivery_store=store) is False:
        for result in viable_new:
            store.record_stage(result.listing, "failed", error="required_channel_failed")
        record_runtime_failure("notification:required_channel_failed")
        _close_resources(store, signals_cache, zoning_cache)
        raise RuntimeError("required notification channel failed")
    if not dry_run:
        for result in viable_new:
            store.record_stage(result.listing, "alerted")
            store.mark_seen(result.listing)

    radar_cfg = cfg.raw.get("radar", {})
    if radar_cfg.get("enabled", False) and radar_cfg.get("send_whatsapp", True):
        radar_ok = notify_radar(
            radar_candidates,
            dry_run=dry_run,
            max_messages=int(radar_cfg.get("max_candidates", 10) or 10),
            delivery_store=store,
        )
        if radar_ok is False:
            for result in radar_candidates:
                store.record_stage(result.listing, "failed", error="required_channel_failed")
            record_runtime_failure("radar_notification:required_channel_failed")
            _close_resources(store, signals_cache, zoning_cache)
            raise RuntimeError("required radar notification channel failed")
        if not dry_run:
            for result in radar_candidates:
                store.record_stage(result.listing, "alerted")
                store.mark_seen(result.listing)
    elif not dry_run:
        for result in radar_candidates:
            store.mark_seen(result.listing)
    if cfg.raw.get("notifications", {}).get("whatsapp_run_summary", {}).get("enabled", False):
        summary = _format_run_summary(
            source_name="mock" if use_mock else source.__class__.__name__,
            radius_km=radius_km,
            total=len(listings),
            out_of_radius=n_out_of_radius,
            already_seen=n_already_seen,
            unavailable=n_unavailable,
            not_viable=n_not_viable,
            radar=len(radar_candidates),
            failed=n_failed,
            viable_new=len(viable_new),
            dashboard_url=env("DASHBOARD_URL"),
            source_metrics=source_metrics,
        )
        if send_whatsapp_status(
            summary,
            dry_run=dry_run,
            delivery_store=store,
        ) is False:
            record_runtime_failure("run_summary:required_channel_failed")
            _close_resources(store, signals_cache, zoning_cache)
            raise RuntimeError("required run-summary channel failed")

    # Depois dos alertas (para não atrasá-los), completa os sinais das
    # regiões-alvo que ainda não estão em cache — alimenta o dashboard.
    if signals_cache is not None:
        try:
            prefetch_config_zips(cfg, cache=signals_cache)
        except Exception as exc:  # noqa: BLE001
            print(f"  [aviso] pre-carga de sinais falhou: {type(exc).__name__}")
    _close_resources(store, signals_cache, zoning_cache)
    final_status = source_status if source_status != "healthy" else (
        "degraded" if n_failed else "healthy"
    )
    if not dry_run and not use_mock:
        _write_run_status(
            cfg,
            source_name=source_name,
            source_status=source_status,
            source_captured_at=source_captured_at,
            diagnostics=source_diagnostics,
            stage="completed" if final_status == "healthy" else "failed",
            total=len(listings),
            source_metrics=source_metrics,
        )
    return RunOutcome(final_status, source_status, source_captured_at, len(listings))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detector de oportunidades de terreno (spec build) perto de Orlando."
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="usa dados de exemplo, sem precisar de chave de API",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="somente mostra no console; não grava banco/CSV nem envia alertas",
    )
    args = parser.parse_args()
    outcome = run(use_mock=args.mock, dry_run=args.dry_run)
    if outcome.status != "healthy":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
