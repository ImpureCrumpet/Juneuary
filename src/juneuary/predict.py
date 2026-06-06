"""Forecast / prediction path.

The classifier (`scripts/classify.py`) is already runtime-agnostic: it scores
an `ObservationIn` regardless of whether the day is observed or forecast. So
prediction is mostly orchestration — fetch forward days, classify each, and
emit the same `DayState` DTO the rest of the contract uses.

Forecast days are computed on request and NOT persisted, so they never
contaminate the observations table (which is the historical record). The
weather fetch is injectable so this module is testable without network.

`classify` / `solar` / `fetch_weather` live in scripts/ as the shared engine
libs; we reuse them via the same path bootstrap the other scripts use rather
than duplicating logic.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import SCHEMA_VERSION
from .locate import nearest_catalog_city
from .state import DayState, Location, MicroseasonState, MicroseasonView

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import classify        # noqa: E402  (shared engine lib in scripts/)
import solar           # noqa: E402

# Type aliases for the injectable fetchers.
WeatherFetcher = Callable[[float, float, date, date], list[dict]]
AQFetcher = Callable[[float, float, date, date], dict]


# ---------------------------------------------------------------------------
# Default (live) fetchers — thin wrappers over fetch_weather.py
# ---------------------------------------------------------------------------

def _default_weather_fetcher(lat: float, lng: float, start: date, end: date) -> list[dict]:
    import fetch_weather                                          # noqa: E402
    raw = fetch_weather.fetch_weather(lat, lng, start, end)
    days = fetch_weather.normalize_daily(raw)
    return [d for d in days if start.isoformat() <= d["date"] <= end.isoformat()]


def _default_aq_fetcher(lat: float, lng: float, start: date, end: date) -> dict:
    import fetch_weather                                          # noqa: E402
    aq = fetch_weather.fetch_air_quality(lat, lng, start, end)
    return fetch_weather.daily_aq_summary(aq)


# ---------------------------------------------------------------------------
# Classification of a single forecast day
# ---------------------------------------------------------------------------

def _day_state_from_classify(
    observed_date: str,
    day: dict,
    result: "classify.ClassifyResult",
    is_forecast: bool,
) -> DayState:
    ds = DayState(
        date=observed_date,
        is_forecast=is_forecast,
        temp_high_f=day.get("temp_high_f"),
        temp_low_f=day.get("temp_low_f"),
        precip_in=day.get("precip_in"),
        snow_in=day.get("snow_in"),
        is_aberration=result.is_aberration,
        aberration_reason=result.aberration_reason,
        normal_high_f=result.anomaly.normal_high_f,
        normal_low_f=result.anomaly.normal_low_f,
        normal_precip_in=result.anomaly.normal_precip_in,
        high_anomaly_f=result.anomaly.high_anomaly_f,
        low_anomaly_f=result.anomaly.low_anomaly_f,
    )
    for tier, matches in (("primary", result.primary),
                          ("secondary", result.secondary),
                          ("triggered", result.triggered)):
        for m in matches:
            ds_list = getattr(ds, tier)
            from .presentation import presentation_for
            p = presentation_for(m.canonical_name)
            ds_list.append(MicroseasonView(
                canonical_name=m.canonical_name,
                display_name=m.display_name,
                category=m.category,
                tier=tier,
                confidence=m.confidence,
                reason=m.reason,
                emoji=p.emoji, color=p.color, glyph=p.glyph,
            ))
    return ds


def classify_range(
    conn: sqlite3.Connection,
    city_slug: str,
    lat: float,
    lng: float,
    start: date,
    end: date,
    is_forecast: bool | None = None,
    weather_fetcher: WeatherFetcher = _default_weather_fetcher,
    aq_fetcher: AQFetcher | None = _default_aq_fetcher,
) -> list[DayState]:
    """Fetch + classify every day in [start, end] and return DayStates.

    Works for past ranges (the default fetcher routes to the ERA5 archive) and
    future ranges (forecast) alike, so it backs both /v1/days (history) and the
    forecast path. `is_forecast`:
      - True/False : stamp every day accordingly.
      - None       : decide per day (date > today => forecast).

    The prior-overcast streak (needed for first-sun events) is seeded from the
    DB history before `start`, then walked forward across the window.
    """
    days = sorted(weather_fetcher(lat, lng, start, end), key=lambda d: d["date"])
    if not days:
        return []
    today = date.today()

    aq_by_day: dict = {}
    if aq_fetcher is not None:
        try:
            aq_by_day = aq_fetcher(lat, lng, start, end)
        except Exception:                                        # noqa: BLE001
            aq_by_day = {}

    city_row = conn.execute(
        "SELECT id FROM cities WHERE slug = ?", [city_slug]
    ).fetchone()
    streak = 0
    if city_row is not None:
        try:
            import fetch_weather                                  # noqa: E402
            streak = fetch_weather._prior_overcast_streak(
                conn, city_row["id"], days[0]["date"]
            )
        except Exception:                                        # noqa: BLE001
            streak = 0

    out: list[DayState] = []
    for day in days:
        d = datetime.fromisoformat(day["date"]).date()
        pm25, _aqi = aq_by_day.get(day["date"], (None, None))
        smoke = bool(pm25 is not None and pm25 >= classify.SMOKE_PM25_UG_M3)
        cloud = day.get("cloud_cover_mean_pct")

        inp = classify.ObservationIn(
            city_slug=city_slug,
            month=d.month,
            temp_high_f=day.get("temp_high_f") if day.get("temp_high_f") is not None else 0.0,
            temp_low_f=day.get("temp_low_f"),
            precip_in=day.get("precip_in") or 0.0,
            snow_in=day.get("snow_in") or 0.0,
            cloud_cover_mean_pct=cloud,
            smoke=smoke,
            pm25_ug_m3=pm25,
            solar_elevation_max_deg=solar.max_solar_elevation_deg(lat, d),
            prior_overcast_days=streak,
        )
        result = classify.classify_observation(conn, inp)
        fc = is_forecast if is_forecast is not None else (d > today)
        out.append(_day_state_from_classify(day["date"], day, result, fc))

        # Walk the streak forward for the next iteration.
        if cloud is not None and cloud >= classify.OVERCAST_CLOUD_PCT:
            streak += 1
        else:
            streak = 0
    return out


def forecast_day_states(
    conn: sqlite3.Connection,
    city_slug: str,
    lat: float,
    lng: float,
    start: date,
    end: date,
    weather_fetcher: WeatherFetcher = _default_weather_fetcher,
    aq_fetcher: AQFetcher | None = _default_aq_fetcher,
) -> list[DayState]:
    """Classify [start, end] as forecast days (every day stamped is_forecast)."""
    return classify_range(
        conn, city_slug, lat, lng, start, end,
        is_forecast=True,
        weather_fetcher=weather_fetcher, aq_fetcher=aq_fetcher,
    )


def build_days_payload(
    conn: sqlite3.Connection,
    start: date,
    end: date,
    city: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    weather_fetcher: WeatherFetcher | None = None,
    aq_fetcher: AQFetcher | None = None,
) -> dict | None:
    """/v1/days payload: fetch Open-Meteo for [start, end], classify each day,
    return the list of DayStates plus the resolved location.

    Pass either `city` (catalog/child slug) or `lat`+`lng` (borrows nearest
    catalog). Fetchers default to the live Open-Meteo wrappers; inject fakes in
    tests.
    """
    conn.row_factory = sqlite3.Row
    wf = weather_fetcher or _default_weather_fetcher
    af = aq_fetcher if aq_fetcher is not None else _default_aq_fetcher

    if city:
        row = conn.execute(
            "SELECT slug, name, latitude, longitude FROM cities WHERE slug = ?",
            [city],
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown city: {city}")
        slug, name = row["slug"], row["name"]
        use_lat, use_lng = row["latitude"], row["longitude"]
        location = Location(slug, name, use_lat, use_lng, source="catalog")
    elif lat is not None and lng is not None:
        nearest = nearest_catalog_city(conn, lat, lng)
        if nearest is None:
            raise ValueError("no catalog cities available to borrow a catalog from")
        slug = nearest.slug
        use_lat, use_lng = lat, lng
        location = Location(slug, f"{lat:.3f}, {lng:.3f}", lat, lng,
                            source="latlng", catalog_slug=nearest.slug)
    else:
        raise ValueError("provide city or lat+lng")

    if use_lat is None or use_lng is None:
        raise ValueError(f"{slug} has no coordinates")

    days = classify_range(
        conn, slug, use_lat, use_lng, start, end,
        is_forecast=None, weather_fetcher=wf, aq_fetcher=af,
    )
    from dataclasses import asdict
    return {
        "schema_version": SCHEMA_VERSION,
        "location": asdict(location),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": [asdict(d) for d in days],
    }


def attach_forecast(
    conn: sqlite3.Connection,
    state: MicroseasonState,
    days: int = 7,
    weather_fetcher: WeatherFetcher = _default_weather_fetcher,
    aq_fetcher: AQFetcher | None = _default_aq_fetcher,
) -> MicroseasonState:
    """Populate `state.forecast` with the next `days` days (today onward)."""
    if state.location.latitude is None or state.location.longitude is None:
        return state
    days = max(1, min(days, 16))                                 # Open-Meteo cap
    start = date.today()
    end = start + timedelta(days=days - 1)
    # When the location borrows a catalog (arbitrary point), classify against
    # that catalog's slug; otherwise the location's own slug.
    catalog_slug = state.location.catalog_slug or state.location.slug
    state.forecast = forecast_day_states(
        conn, catalog_slug,
        state.location.latitude, state.location.longitude,
        start, end,
        weather_fetcher=weather_fetcher, aq_fetcher=aq_fetcher,
    )
    return state


def build_state_for_point(
    conn: sqlite3.Connection,
    lat: float,
    lng: float,
    label: str | None = None,
    days: int = 7,
    weather_fetcher: WeatherFetcher = _default_weather_fetcher,
    aq_fetcher: AQFetcher | None = _default_aq_fetcher,
    today: date | None = None,
) -> MicroseasonState | None:
    """Render-model for an arbitrary lat/lng (no catalog city, no stored
    observations). Borrows the nearest catalog city's vocabulary/normals and
    computes a live nowcast: `current` is today, `forecast` is the days after.
    """
    conn.row_factory = sqlite3.Row
    nearest = nearest_catalog_city(conn, lat, lng)
    if nearest is None:
        raise ValueError("no catalog cities available to borrow a catalog from")

    today = today or date.today()
    span = max(1, min(days, 16))
    end = today + timedelta(days=span - 1)
    states = forecast_day_states(
        conn, nearest.slug, lat, lng, today, end,
        weather_fetcher=weather_fetcher, aq_fetcher=aq_fetcher,
    )
    if not states:
        return None

    current = states[0]
    forecast = states[1:]
    return MicroseasonState(
        schema_version=SCHEMA_VERSION,
        location=Location(
            slug=nearest.slug,
            name=label or f"{lat:.3f}, {lng:.3f}",
            latitude=lat,
            longitude=lng,
            source="latlng",
            catalog_slug=nearest.slug,
        ),
        as_of=current.date,
        current=current,
        forecast=forecast,
    )
