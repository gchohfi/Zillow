"""Cálculo de distância geográfica (Haversine)."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em quilômetros entre dois pontos (lat/long em graus)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def within_radius(
    center_lat: float, center_lng: float, lat: float, lng: float, radius_km: float
) -> tuple[bool, float]:
    """Retorna (está_dentro, distância_km) em relação ao centro."""
    dist = haversine_km(center_lat, center_lng, lat, lng)
    return dist <= radius_km, dist
