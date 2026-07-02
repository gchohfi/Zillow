"""Orquestrador: busca → geofiltro → novidade → viabilidade → alerta."""

from __future__ import annotations

import argparse

from .config import Config, env
from .availability import check_availability
from .arv import enrich_arv
from .datasource import get_source
from .geo import within_radius
from .notifier import notify, notify_radar, send_message, send_whatsapp_status
from .red_flags import apply_red_flags
from .reporter import append_evaluations, append_results
from .review import classify_review_status, is_radar_candidate
from .storage import SeenStore
from .viability import evaluate


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
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    return "\n".join(lines)


def run(use_mock: bool = False, dry_run: bool = False) -> None:
    cfg = Config.load()
    try:
        source = get_source(cfg, use_mock)
    except RuntimeError as exc:
        print(f"[config] {exc}")
        return
    store = SeenStore(":memory:" if use_mock else cfg.db_path)

    search = cfg.search
    center_lat, center_lng = search["center_lat"], search["center_lng"]
    radius_km = search["radius_km"]

    print(f"Buscando terrenos num raio de {radius_km} km de Orlando "
          f"({'mock' if use_mock else source.__class__.__name__})...")

    listings = source.fetch_new_land_listings(cfg)
    print(f"  {len(listings)} listagem(ns) retornada(s) pela fonte.")
    source_errors = getattr(source, "errors", [])
    if not listings and source_errors:
        send_message(
            "[Orlando Land] Falha na fonte de dados",
            "A RentCast nao retornou listagens nesta rodada.\n\n"
            + "\n".join(f"- {err}" for err in source_errors[:3]),
            dry_run=dry_run,
        )
        store.close()
        return

    viable_new = []
    radar_candidates = []
    evaluated_results = []
    n_out_of_radius = n_already_seen = n_unavailable = n_not_viable = n_failed = 0

    for listing in listings:
        inside, dist = within_radius(
            center_lat, center_lng, listing.lat, listing.lng, radius_km
        )
        listing.distance_km = dist
        if not inside:
            n_out_of_radius += 1
            continue

        if not store.is_new(listing):
            n_already_seen += 1
            continue

        availability_reasons = []
        if not use_mock:
            is_available, availability_reasons = check_availability(listing, cfg)
            if not is_available:
                n_unavailable += 1
                continue

        if not use_mock:
            enrich_arv(listing, cfg)

        try:
            result = evaluate(listing, cfg)
        except Exception as exc:  # noqa: BLE001
            n_failed += 1
            print(f"  [aviso] listagem {listing.id or '(sem id)'} nao avaliada: {exc}")
            continue
        result.reasons.extend(availability_reasons)
        if not use_mock:
            apply_red_flags(result, cfg)
        classify_review_status(result, cfg)
        evaluated_results.append(result)

        store.mark_seen(listing)   # marca como visto somente depois da avaliação
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

    # Grava as oportunidades viáveis na planilha CSV.
    csv_path = cfg.raw.get("output", {}).get("csv_path")
    if csv_path and viable_new:
        append_results(viable_new, csv_path)
    evaluations_csv_path = cfg.raw.get("output", {}).get("evaluations_csv_path")
    if evaluations_csv_path and evaluated_results:
        append_evaluations(evaluated_results, evaluations_csv_path)

    notify(viable_new, dry_run=dry_run)
    radar_cfg = cfg.raw.get("radar", {})
    if radar_cfg.get("enabled", False) and radar_cfg.get("send_whatsapp", True):
        notify_radar(
            radar_candidates,
            dry_run=dry_run,
            max_messages=int(radar_cfg.get("max_candidates", 10) or 10),
        )
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
        )
        send_whatsapp_status(summary, dry_run=dry_run)

    store.close()


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
        help="mostra no console mas não envia alertas externos",
    )
    args = parser.parse_args()
    run(use_mock=args.mock, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
