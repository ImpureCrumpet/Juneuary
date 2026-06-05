"""Fetch daily weather + air quality from Open-Meteo and persist + classify.

Idempotent: re-fetching the same date REPLACES the row (and re-classifies it
with the current rules).

Usage:
  uv run scripts/fetch_weather.py --city seattle --days 14
  uv run scripts/fetch_weather.py --all --days 7
  uv run scripts/fetch_weather.py --city seattle --start 2026-05-20 --end 2026-06-04

Open-Meteo is free and key-less. We use:
  - api.open-meteo.com/v1/forecast       (current + past_days + forecast)
  - air-quality-api.open-meteo.com/v1/   (PM2.5, AQI; recent days only)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "microseasons.db"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import solar              # noqa: E402
import classify           # noqa: E402


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

ARCHIVE_DAYS_AGO_THRESHOLD = 7    # use archive past this; forecast only for the last week
                                  # (Open-Meteo's /forecast past_days quietly returns nulls
                                  #  for dates more than ~28 days back regardless of the
                                  #  documented 92-day max. Archive has a ~5-day lag, so
                                  #  this 7-day overlap is the safe seam.)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get_json(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params, doseq=True)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full, headers={"User-Agent": "juneuary/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


_DAILY_FIELDS = ",".join([
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "snowfall_sum",
    "cloud_cover_mean",
    "sunshine_duration",
])


def _base_weather_params(lat: float, lng: float) -> dict:
    return {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lng:.4f}",
        "daily": _DAILY_FIELDS,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
    }


def _fetch_archive(lat: float, lng: float, start: date, end: date) -> dict:
    params = _base_weather_params(lat, lng) | {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    return _get_json(ARCHIVE_URL, params)


def _fetch_forecast(lat: float, lng: float, start: date, end: date) -> dict:
    today = date.today()
    past_days = max(0, (today - start).days)
    forecast_days = max(0, (end - today).days + 1)
    params = _base_weather_params(lat, lng) | {
        "past_days": min(past_days, 92),
        "forecast_days": max(1, min(forecast_days, 16)),
    }
    return _get_json(FORECAST_URL, params)


def _merge_daily(a: dict, b: dict) -> dict:
    """Merge two Open-Meteo daily responses, deduping by date (later wins)."""
    out = {**a, "daily": {}}
    keys = set()
    for d in (a, b):
        for k in (d.get("daily") or {}).keys():
            keys.add(k)
    merged: dict[str, dict[str, object]] = {}
    for src in (a, b):
        sd = src.get("daily") or {}
        times = sd.get("time") or []
        for i, ts in enumerate(times):
            row = merged.setdefault(ts, {"time": ts})
            for k in keys:
                if k == "time":
                    continue
                arr = sd.get(k)
                if arr and i < len(arr) and arr[i] is not None:
                    row[k] = arr[i]
    ordered_dates = sorted(merged.keys())
    out["daily"] = {"time": ordered_dates}
    for k in keys:
        if k == "time":
            continue
        out["daily"][k] = [merged[d].get(k) for d in ordered_dates]
    return out


def fetch_weather(lat: float, lng: float, start: date, end: date) -> dict:
    """Daily weather for [start, end] inclusive.

    Routes intelligently between Open-Meteo's archive (ERA5, ~5-day delay)
    and forecast (current + past 92 days) endpoints. For ranges that cross
    the boundary we make two calls and merge — still cheap (2 calls, not
    one-per-day) and friendly to the free-tier limits.
    """
    today = date.today()
    cutoff = today - timedelta(days=ARCHIVE_DAYS_AGO_THRESHOLD)
    if end <= cutoff:
        return _fetch_archive(lat, lng, start, end)
    if start >= cutoff:
        return _fetch_forecast(lat, lng, start, end)
    archive_part = _fetch_archive(lat, lng, start, cutoff - timedelta(days=1))
    forecast_part = _fetch_forecast(lat, lng, cutoff, end)
    return _merge_daily(archive_part, forecast_part)


def fetch_air_quality(lat: float, lng: float, start: date, end: date) -> dict | None:
    """Daily-mean PM2.5 + US AQI for [start, end] inclusive. May 404 for old dates."""
    today = date.today()
    past_days = max(0, (today - start).days)
    forecast_days = max(0, (end - today).days + 1)
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lng:.4f}",
        "hourly": "pm2_5,us_aqi",
        "timezone": "auto",
        "past_days": min(past_days, 92),
        "forecast_days": max(1, min(forecast_days, 7)),
    }
    try:
        return _get_json(AQ_URL, params)
    except Exception as e:
        print(f"  air-quality fetch failed ({e}); proceeding without smoke data",
              file=sys.stderr)
        return None


def daily_aq_summary(aq: dict | None) -> dict[str, tuple[float | None, float | None]]:
    """Reduce hourly PM2.5/AQI to per-day max (worst hour of the day)."""
    out: dict[str, tuple[float | None, float | None]] = {}
    if not aq or "hourly" not in aq:
        return out
    times = aq["hourly"].get("time") or []
    pm = aq["hourly"].get("pm2_5") or []
    aqi = aq["hourly"].get("us_aqi") or []
    for i, ts in enumerate(times):
        d = ts.split("T", 1)[0]
        pm_v = pm[i] if i < len(pm) else None
        aqi_v = aqi[i] if i < len(aqi) else None
        cur = out.get(d, (None, None))
        new_pm = pm_v if (cur[0] is None or (pm_v is not None and pm_v > cur[0])) else cur[0]
        new_aq = aqi_v if (cur[1] is None or (aqi_v is not None and aqi_v > cur[1])) else cur[1]
        out[d] = (new_pm, new_aq)
    return out


# ---------------------------------------------------------------------------
# Persistence + classification
# ---------------------------------------------------------------------------

def open_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        sys.exit(f"DB not found at {DB_PATH}. Run scripts/build_db.py first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _prior_overcast_streak(conn, city_id: int, before_date: str,
                           threshold_pct: float = classify.OVERCAST_CLOUD_PCT) -> int:
    """Count consecutive overcast days strictly before `before_date`."""
    cur = conn.execute(
        "SELECT observed_date, cloud_cover_mean_pct FROM observations "
        "WHERE city_id = ? AND observed_date < ? "
        "ORDER BY observed_date DESC LIMIT 60",
        [city_id, before_date],
    )
    streak = 0
    expected = datetime.fromisoformat(before_date).date() - timedelta(days=1)
    for r in cur:
        d = datetime.fromisoformat(r["observed_date"]).date()
        if d != expected:
            break  # gap in observations
        if r["cloud_cover_mean_pct"] is None or r["cloud_cover_mean_pct"] < threshold_pct:
            break
        streak += 1
        expected -= timedelta(days=1)
    return streak


def upsert_observation(conn, city_id: int, day: dict, aq_day: tuple, lat: float) -> int:
    """Insert/replace one day. Returns observation id."""
    d_iso = day["date"]
    d = datetime.fromisoformat(d_iso).date()
    pm25, aqi = aq_day
    smoke = bool(pm25 is not None and pm25 >= classify.SMOKE_PM25_UG_M3)
    solar_max = solar.max_solar_elevation_deg(lat, d)

    conn.execute(
        "DELETE FROM observations WHERE city_id = ? AND observed_date = ? AND source = 'open_meteo'",
        [city_id, d_iso],
    )
    cur = conn.execute(
        """
        INSERT INTO observations (
            city_id, observed_date, source,
            temp_high_f, temp_low_f, temp_mean_f,
            precip_in, snow_in, cloud_cover_mean_pct, sun_hours,
            smoke, pm25_ug_m3, aqi_us,
            solar_elevation_max_deg, raw_json
        ) VALUES (
            :city_id, :d, 'open_meteo',
            :hi, :lo, :mean, :precip, :snow, :cloud, :sun,
            :smoke, :pm, :aqi, :selev, :raw
        )
        """,
        {
            "city_id": city_id, "d": d_iso,
            "hi": day.get("temp_high_f"),
            "lo": day.get("temp_low_f"),
            "mean": day.get("temp_mean_f"),
            "precip": day.get("precip_in") or 0.0,
            "snow": day.get("snow_in") or 0.0,
            "cloud": day.get("cloud_cover_mean_pct"),
            "sun": day.get("sun_hours"),
            "smoke": 1 if smoke else 0,
            "pm": pm25, "aqi": aqi,
            "selev": solar_max,
            "raw": json.dumps(day, ensure_ascii=False),
        },
    )
    return cur.lastrowid


def classify_and_record(conn, city_slug: str, lat: float, observation_id: int) -> classify.ClassifyResult:
    obs_row = conn.execute("SELECT * FROM observations WHERE id = ?", [observation_id]).fetchone()
    d = datetime.fromisoformat(obs_row["observed_date"]).date()
    prior_overcast = _prior_overcast_streak(conn, obs_row["city_id"], obs_row["observed_date"])

    inp = classify.ObservationIn(
        city_slug=city_slug,
        month=d.month,
        temp_high_f=obs_row["temp_high_f"] if obs_row["temp_high_f"] is not None else 0.0,
        temp_low_f=obs_row["temp_low_f"],
        precip_in=obs_row["precip_in"] or 0.0,
        snow_in=obs_row["snow_in"] or 0.0,
        cloud_cover_mean_pct=obs_row["cloud_cover_mean_pct"],
        smoke=bool(obs_row["smoke"]),
        pm25_ug_m3=obs_row["pm25_ug_m3"],
        solar_elevation_max_deg=obs_row["solar_elevation_max_deg"],
        prior_overcast_days=prior_overcast,
    )
    result = classify.classify_observation(conn, inp)

    # Persist aberration flag on the observation row itself.
    conn.execute(
        "UPDATE observations SET is_aberration = ?, aberration_reason = ? WHERE id = ?",
        [1 if result.is_aberration else 0,
         result.aberration_reason or None,
         observation_id],
    )

    conn.execute("DELETE FROM observation_microseasons WHERE observation_id = ?", [observation_id])
    for tier_name, matches in (("primary", result.primary),
                               ("secondary", result.secondary),
                               ("triggered", result.triggered)):
        for m in matches:
            conn.execute(
                "INSERT OR IGNORE INTO observation_microseasons "
                "(observation_id, occurrence_id, tier, confidence, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                [observation_id, m.occurrence_id, tier_name, m.confidence, m.reason],
            )
    return result


# ---------------------------------------------------------------------------
# Open-Meteo response normalization
# ---------------------------------------------------------------------------

def normalize_daily(weather: dict) -> list[dict]:
    """Turn Open-Meteo's column-of-arrays into a list of per-day dicts."""
    daily = weather.get("daily") or {}
    times = daily.get("time") or []
    fields = {
        "temperature_2m_max": "temp_high_f",
        "temperature_2m_min": "temp_low_f",
        "temperature_2m_mean": "temp_mean_f",
        "precipitation_sum": "precip_in",
        "snowfall_sum": "snow_in",
        "cloud_cover_mean": "cloud_cover_mean_pct",
        "sunshine_duration": "sun_seconds_raw",   # convert below
    }
    out: list[dict] = []
    for i, ts in enumerate(times):
        row = {"date": ts}
        for src, dst in fields.items():
            arr = daily.get(src)
            row[dst] = arr[i] if arr and i < len(arr) else None
        if row.get("sun_seconds_raw") is not None:
            row["sun_hours"] = row["sun_seconds_raw"] / 3600.0
        row.pop("sun_seconds_raw", None)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cities_to_fetch(conn, args) -> list[sqlite3.Row]:
    if args.all:
        return list(conn.execute("SELECT * FROM cities ORDER BY slug"))
    if args.city:
        rows = list(conn.execute("SELECT * FROM cities WHERE slug = ?", [args.city]))
        if not rows:
            sys.exit(f"unknown city: {args.city}")
        return rows
    sys.exit("specify --city <slug> or --all")


def resolve_date_range(args) -> tuple[date, date]:
    if args.start or args.end:
        if not (args.start and args.end):
            sys.exit("--start and --end must be used together")
        return (datetime.fromisoformat(args.start).date(),
                datetime.fromisoformat(args.end).date())
    today = date.today()
    days = args.days or 7
    return today - timedelta(days=days - 1), today


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", help="city slug (e.g. seattle)")
    p.add_argument("--all", action="store_true", help="fetch all cities")
    p.add_argument("--days", type=int, default=7,
                   help="how many days back from today (default 7)")
    p.add_argument("--start", help="ISO start date (YYYY-MM-DD)")
    p.add_argument("--end", help="ISO end date (YYYY-MM-DD)")
    p.add_argument("--no-classify", action="store_true",
                   help="store observations but skip classification")
    p.add_argument("--skip-existing", action="store_true",
                   help="don't refetch dates already in observations (cheaper on API)")
    args = p.parse_args()

    conn = open_db()
    start, end = resolve_date_range(args)
    cities = cities_to_fetch(conn, args)

    print(f"Fetching {start.isoformat()} → {end.isoformat()} for {len(cities)} city/cities")

    total_obs = total_class = total_skipped = 0
    for city in cities:
        print(f"\n[{city['slug']}] {city['name']} ({city['latitude']}, {city['longitude']})")

        # Decide which dates actually need fetching.
        existing: set[str] = set()
        if args.skip_existing:
            for r in conn.execute(
                "SELECT observed_date FROM observations "
                "WHERE city_id = ? AND observed_date BETWEEN ? AND ?",
                [city["id"], start.isoformat(), end.isoformat()],
            ):
                existing.add(r[0])
            wanted = {(start + timedelta(days=i)).isoformat()
                      for i in range((end - start).days + 1)}
            missing = sorted(wanted - existing)
            if not missing:
                print(f"  all {len(wanted)} days already on file; nothing to fetch.")
                continue
            fetch_start = date.fromisoformat(missing[0])
            fetch_end = date.fromisoformat(missing[-1])
            print(f"  {len(existing)} of {len(wanted)} days on file; "
                  f"fetching {len(missing)} missing days "
                  f"({fetch_start} → {fetch_end}).")
        else:
            fetch_start, fetch_end = start, end

        weather = fetch_weather(city["latitude"], city["longitude"], fetch_start, fetch_end)
        aq = fetch_air_quality(city["latitude"], city["longitude"], fetch_start, fetch_end)
        aq_by_day = daily_aq_summary(aq)

        days = normalize_daily(weather)
        days = [d for d in days if fetch_start.isoformat() <= d["date"] <= fetch_end.isoformat()]
        if args.skip_existing:
            days = [d for d in days if d["date"] not in existing]
            total_skipped += len(existing & {d["date"] for d in normalize_daily(weather)})
        days.sort(key=lambda d: d["date"])

        for day in days:
            aq_day = aq_by_day.get(day["date"], (None, None))
            obs_id = upsert_observation(conn, city["id"], day, aq_day, city["latitude"])
            total_obs += 1
            if not args.no_classify:
                result = classify_and_record(conn, city["slug"], city["latitude"], obs_id)
                total_class += 1
                _print_day_summary(day, result)
        conn.commit()

    summary = f"\nWrote {total_obs} observations; classified {total_class}."
    if args.skip_existing:
        summary += f" Skipped {total_skipped} already on file."
    print(summary)
    return 0


def _print_day_summary(day: dict, result: classify.ClassifyResult) -> None:
    bits = []
    hi = day.get("temp_high_f")
    lo = day.get("temp_low_f")
    if hi is not None and lo is not None:
        bits.append(f"hi {hi:.0f}/lo {lo:.0f}°F")
    if day.get("cloud_cover_mean_pct") is not None:
        bits.append(f"cloud {day['cloud_cover_mean_pct']:.0f}%")
    if (day.get("precip_in") or 0) > 0:
        bits.append(f"precip {day['precip_in']:.2f}\"")
    if (day.get("snow_in") or 0) > 0:
        bits.append(f"snow {day['snow_in']:.2f}\"")
    tag = lambda label, ms: f"{label}: {', '.join(m.display_name for m in ms)}" if ms else ""
    chunks = [t for t in (
        tag("PRIMARY", result.primary),
        tag("triggered", result.triggered),
        tag("secondary", result.secondary),
    ) if t]
    aberration = " [ABERRATION]" if result.is_aberration else ""
    print(f"  {day['date']}  {' '.join(bits):<40}  "
          + ("  ".join(chunks) or "(no matches)") + aberration)


if __name__ == "__main__":
    raise SystemExit(main())
