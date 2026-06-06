"""Resolve an arbitrary lat/lng to a catalog to borrow from.

A display user enters a ZIP / location (RainRain already geocodes that to a
lat/lng). Juneuary has curated catalogs only for a handful of cities, so an
arbitrary point borrows the *nearest catalog-owning city's* occurrence set and
climate normals — the same inheritance the schema already models for child
"grid" cities, just resolved on the fly instead of stored.

The borrowed catalog is the microseason vocabulary + thresholds + normals; the
weather signal and solar geometry still come from the requested point.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass


@dataclass
class NearestCity:
    slug: str
    name: str
    latitude: float
    longitude: float
    distance_km: float


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_catalog_city(
    conn: sqlite3.Connection, lat: float, lng: float
) -> NearestCity | None:
    """Closest catalog-owning city (parent_city_id IS NULL) with coordinates.

    Catalog-owning cities are the ones that actually carry occurrences and
    normals; child/grid cities inherit, so we never borrow from them directly.
    """
    rows = conn.execute(
        "SELECT slug, name, latitude, longitude FROM cities "
        "WHERE parent_city_id IS NULL "
        "AND latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    best: NearestCity | None = None
    for r in rows:
        d = _haversine_km(lat, lng, r["latitude"], r["longitude"])
        if best is None or d < best.distance_km:
            best = NearestCity(r["slug"], r["name"], r["latitude"], r["longitude"], d)
    return best
