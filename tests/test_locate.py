"""Tests for arbitrary-location resolution and the point-based state builder."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from juneuary.locate import nearest_catalog_city
from juneuary.predict import build_state_for_point

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


def _catalog_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Two catalog cities + one child (must never be chosen to borrow from).
    conn.execute("INSERT INTO cities (id,slug,name,latitude,longitude) "
                 "VALUES (1,'seattle','Seattle',47.6,-122.3)")
    conn.execute("INSERT INTO cities (id,slug,name,latitude,longitude) "
                 "VALUES (2,'san_francisco','San Francisco',37.77,-122.42)")
    conn.execute("INSERT INTO cities (id,slug,name,latitude,longitude,parent_city_id) "
                 "VALUES (3,'sf_sunset','SF Sunset',37.75,-122.49,2)")
    conn.execute("INSERT INTO series (id,key,name) VALUES (1,'winter','Winter')")
    conn.execute(
        "INSERT INTO microseasons (id,canonical_name,slug,category,series_id,"
        "series_order,series_label) VALUES "
        "(10,'Winter','winter','series',1,1,'winter1')"
    )
    conn.execute(
        "INSERT INTO microseason_occurrences (id,microseason_id,city_id,"
        "typical_start_month,typical_end_month,temp_max_f) VALUES (100,10,2,12,3,60)"
    )
    conn.execute(
        "INSERT INTO city_climate_normals (city_id,month,temp_max_avg_f,"
        "temp_min_avg_f,precip_total_in) VALUES (2,2,58,46,4.0)"
    )
    conn.commit()
    return conn


def _fake_forecast(lat, lng, start, end):
    return [
        {"date": "2026-02-10", "temp_high_f": 55, "temp_low_f": 47,
         "precip_in": 0.2, "snow_in": 0.0, "cloud_cover_mean_pct": 85},
        {"date": "2026-02-11", "temp_high_f": 57, "temp_low_f": 48,
         "precip_in": 0.0, "snow_in": 0.0, "cloud_cover_mean_pct": 40},
    ]


def test_nearest_catalog_city_picks_closest_owner():
    conn = _catalog_db()
    # A point near San Jose should snap to San Francisco, not Seattle, and
    # never to the child grid city.
    near = nearest_catalog_city(conn, 37.34, -121.89)
    assert near.slug == "san_francisco"


def test_nearest_catalog_city_ignores_child_cities():
    conn = _catalog_db()
    # Exactly on the child's coords still resolves to a catalog OWNER.
    near = nearest_catalog_city(conn, 37.75, -122.49)
    assert near.slug in ("san_francisco", "seattle")
    assert near.slug != "sf_sunset"


def test_build_state_for_point_borrows_catalog():
    conn = _catalog_db()
    state = build_state_for_point(
        conn, 37.34, -121.89, label="San Jose", days=2,
        weather_fetcher=_fake_forecast, aq_fetcher=None,
        today=date(2026, 2, 10),
    )
    assert state is not None
    assert state.location.source == "latlng"
    assert state.location.catalog_slug == "san_francisco"
    assert state.location.name == "San Jose"
    assert state.as_of == "2026-02-10"
    # current is today; the remaining day is forecast
    assert state.current.date == "2026-02-10"
    assert len(state.forecast) == 1
    assert "Winter" in [v.canonical_name for v in state.current.primary]
