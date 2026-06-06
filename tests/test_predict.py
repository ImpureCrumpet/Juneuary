"""Tests for the forecast/prediction path (network-free via injected fetcher).

Builds a temp DB from the real schema with a minimal Seattle catalog so the
shared classifier runs for real, then feeds fabricated forecast days.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from juneuary.predict import (
    attach_forecast,
    build_days_payload,
    classify_range,
    forecast_day_states,
)
from juneuary.state import DayState, Location, MicroseasonState
from juneuary import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


def _catalog_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO cities (id,slug,name,latitude,longitude) "
                 "VALUES (1,'seattle','Seattle',47.6,-122.3)")
    conn.execute("INSERT INTO series (id,key,name) VALUES (1,'winter','Winter')")
    conn.execute(
        "INSERT INTO microseasons (id,canonical_name,slug,category,series_id,"
        "series_order,series_label) VALUES "
        "(10,'Winter','winter','series',1,1,'winter1')"
    )
    # Winter occurrence: Dec–Mar window, fires when high <= 50F.
    conn.execute(
        "INSERT INTO microseason_occurrences (id,microseason_id,city_id,"
        "typical_start_month,typical_end_month,temp_max_f) "
        "VALUES (100,10,1,12,3,50)"
    )
    conn.execute(
        "INSERT INTO city_climate_normals (city_id,month,temp_max_avg_f,"
        "temp_min_avg_f,precip_total_in) VALUES (1,2,48,37,3.5)"
    )
    conn.commit()
    return conn


def _fake_forecast(lat, lng, start, end):
    return [
        {"date": "2026-02-10", "temp_high_f": 40, "temp_low_f": 31,
         "precip_in": 0.1, "snow_in": 0.0, "cloud_cover_mean_pct": 90},
        {"date": "2026-02-11", "temp_high_f": 62, "temp_low_f": 41,
         "precip_in": 0.0, "snow_in": 0.0, "cloud_cover_mean_pct": 10},
    ]


def test_forecast_day_states_classifies_each_day():
    conn = _catalog_db()
    days = forecast_day_states(
        conn, "seattle", 47.6, -122.3,
        date(2026, 2, 10), date(2026, 2, 11),
        weather_fetcher=_fake_forecast, aq_fetcher=None,
    )
    assert len(days) == 2
    assert all(d.is_forecast for d in days)

    cold = days[0]
    assert cold.temp_high_f == 40
    assert "Winter" in [v.canonical_name for v in cold.primary]
    # decorated from presentation.yaml
    assert cold.primary[0].emoji == "❄️"

    warm = days[1]
    assert "Winter" not in [v.canonical_name for v in warm.primary]


def test_attach_forecast_populates_state():
    conn = _catalog_db()
    state = MicroseasonState(
        schema_version=SCHEMA_VERSION,
        location=Location("seattle", "Seattle", 47.6, -122.3),
        as_of="2026-02-09",
        current=DayState(date="2026-02-09"),
    )
    attach_forecast(conn, state, days=2,
                    weather_fetcher=_fake_forecast, aq_fetcher=None)
    assert len(state.forecast) == 2
    assert state.to_dict()["forecast"][0]["is_forecast"] is True


def test_attach_forecast_noop_without_latlng():
    conn = _catalog_db()
    state = MicroseasonState(
        schema_version=SCHEMA_VERSION,
        location=Location("nowhere", "Nowhere", None, None),
        as_of="2026-02-09",
        current=DayState(date="2026-02-09"),
    )
    attach_forecast(conn, state, days=2,
                    weather_fetcher=_fake_forecast, aq_fetcher=None)
    assert state.forecast == []


def test_classify_range_marks_past_days_not_forecast_and_sets_anomaly():
    conn = _catalog_db()
    days = classify_range(
        conn, "seattle", 47.6, -122.3,
        date(2026, 2, 10), date(2026, 2, 11),
        is_forecast=None,                       # decide per day; both are past
        weather_fetcher=_fake_forecast, aq_fetcher=None,
    )
    assert [d.is_forecast for d in days] == [False, False]
    # anomaly populated against the Feb normal high of 48F
    assert days[0].normal_high_f == 48
    assert days[0].high_anomaly_f == 40 - 48


def test_build_days_payload_for_city():
    conn = _catalog_db()
    payload = build_days_payload(
        conn, start=date(2026, 2, 10), end=date(2026, 2, 11),
        city="seattle",
        weather_fetcher=_fake_forecast, aq_fetcher=None,
    )
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["location"]["slug"] == "seattle"
    assert len(payload["days"]) == 2
    assert payload["days"][0]["high_anomaly_f"] == 40 - 48
