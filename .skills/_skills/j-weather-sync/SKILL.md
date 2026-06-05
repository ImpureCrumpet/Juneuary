---
name: j-weather-sync
description: "Fetch Open-Meteo observations into the SQLite DB and re-classify for a city and date range."
triggers:
  - fetch weather
  - sync weather
  - open-meteo
  - backfill observations
  - refresh forecast days
  - update microseasons db
dependencies: []
version: "1.0.0"
---

# Weather Sync (Open-Meteo → DB)

## When to use this skill

Load when observations need to be fetched, backfilled, or refreshed before
reports, queries, or accuracy reviews. The local DB is a cache — it drifts
from Open-Meteo when forecast-era rows age without a re-fetch.

## Prerequisites

```bash
uv sync
uv run scripts/build_db.py   # if db/microseasons.db is missing
```

## Instructions

### 1. Choose the date range

- **YTD through today:** `--start YYYY-01-01 --end $(date +%Y-%m-%d)`
- **Recent top-up:** `--days 14` (default)
- **Explicit window:** `--start YYYY-MM-DD --end YYYY-MM-DD`

### 2. Fetch and classify

```bash
# Backfill without re-pulling dates already stored
uv run scripts/fetch_weather.py --city seattle --start 2026-01-01 --end 2026-06-05 --skip-existing

# Force refresh a stale window (omit --skip-existing)
uv run scripts/fetch_weather.py --city seattle --start 2026-05-01 --end 2026-06-05

# All cities
uv run scripts/fetch_weather.py --all --days 7
```

Each city costs **2 Open-Meteo calls** per fetch window (weather + air quality),
routed across `archive-api.open-meteo.com` (ERA5, ~5-day lag) and
`api.open-meteo.com/v1/forecast` (recent days). See `ARCHIVE_DAYS_AGO_THRESHOLD`
in `scripts/fetch_weather.py`.

### 3. Know the seam

Dates within the last ~7 days use the **forecast** endpoint. Dates older than
that use **ERA5 archive**. Re-fetch recent weeks before publishing reports —
forecast-era highs can drift several degrees after the fact.

### 4. Verify row count

```bash
uv run scripts/query.py --city seattle anomaly   # quick sanity check
```

Or query SQLite directly:

```sql
SELECT COUNT(*) FROM observations
WHERE city_id = (SELECT id FROM cities WHERE slug = 'seattle')
  AND observed_date BETWEEN '2026-01-01' AND '2026-06-05';
```

Expected day count = `(end - start).days + 1`.

## What gets stored

Per observation: high/low/mean temp (°F), precip (in), snow (in), cloud cover,
sun hours, PM2.5/AQI/smoke flag, computed `solar_elevation_max_deg`, plus
`observation_microseasons` rows from `classify.py`.

## Examples

- "Backfill Seattle YTD" → `fetch_weather.py --city seattle --start 2026-01-01 --end <today> --skip-existing`
- "Refresh May before the report" → re-fetch May–June **without** `--skip-existing`
