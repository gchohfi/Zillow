"""Orquestrador: busca → geofiltro → novidade → viabilidade → alerta."""

from __future__ import annotations

import argparse

from .config import Config
from .datasource import get_source
from .geo import within_radius
from .storage import SeenStore
from .viability import evaluate


def run(use_mock: bool = False, dry_run: bool = False) -> None:
    cfg = Config.load()
    source = get_source(use_mock)
    store = SeenStore(cfg.db_path)

    search = cfg.search
    center_lat, center_lng = search["center_lat"], search["center_lng"]
    radius_km = search["radius_km"]

    print(f"Buscando terrenos num raio de {radius_km} km de Orlando "
          f"({'mock' if use_mock else source.__class__.__name__})...")

    listings = source.fetch_new_land_listings(cfg)
    print(f"  {len(listings)} listagem(ns) retornada(s) pela fonte.")

    viable_new = []
    n_out_of_radius = n_already_seen = n_not_viable = 0

    for listing in listings:
        inside, dist = within_radius(
            center_lat, center_lng, listing.lat, listing.lng, radius_km
        )
        listing.distance_km = dist
        if not inside:
            n_out_of_radius += 1
            continue

        if not store.is_new(listing.id):
            n_already_seen += 1
            continue
        store.mark_seen(listing)   # marca como visto (mesmo se não for viável)

        result = evaluate(listing, cfg)
        if result.is_viable:
            viable_new.append(result)
        else:
            n_not_viable += 1

    print(f"  fora do raio: {n_out_of_radius} | já vistos: {n_already_seen} | "
          f"não viáveis: {n_not_viable} | viáveis NOVOS: {len(viable_new)}")

    from .notifier import notify
    notify(viable_new, dry_run=dry_run)

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
