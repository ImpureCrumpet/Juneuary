# Juneuary

A codified taxonomy of microseasons — the lying, recursive,
climate-change-warped weather phases locals actually live by.

Seeded with Seattle and San Francisco; the data model is built to expand to
peer cities without duplicating shared concepts (Spider Season, Smogust,
Hell's Front Porch are one row each globally).

Juneuary is the **engine**: the catalog/DB, the classification + forecast
logic, and a small JSON **API** that is the single front door for classified
data. Presentation layers (the markdown YTD report, a future display app) are
pure API consumers and live elsewhere — the report generator lives on the
**`report-builder`** branch.

## Stack

- **Data layer**: SQLite, generated from YAML source-of-truth files.
- **Engine + API**: Python 3.12 via `uv`; `src/juneuary/` package + a
  zero-dependency stdlib HTTP API. The render-model contract is in `contract/`.
- **Agent skills**: [skills-harness](https://github.com/Gargoyle-Apps/skills-harness) vendored at `.skills-harness/` (git subtree); project skills under `.skills/_skills/j-*`.
- **Frontend (planned)**: Node 24 + pnpm (framework TBD), over the API.

## Project layout

```
data/
  cities.yaml                 city metadata (one row per city; child grids reference parent_slug)
  series.yaml                 named series (winter, spring, fall, ...)
  microseasons.yaml           GLOBAL CONCEPTS (city-independent)
  precipitation.yaml          rain intensity scale + named patterns
  presentation.yaml           display metadata (emoji/color/glyph) per concept
  cities/
    seattle.yaml              per-city: occurrences + overlaps + patterns + normals
    san_francisco.yaml        per-city: occurrences + overlaps + patterns + normals
    # Neighborhood / grid-cell children live in the gitignored
    # data/cities.local.yaml (see data/cities.local.example.yaml) and
    # inherit catalog + normals via parent_slug.
db/
  schema.sql                  SQLite schema (the DDL is the spec)
  microseasons.db             generated; gitignored
src/juneuary/                 engine package (importable, runtime-agnostic)
  presentation.py             emoji/color/glyph lookups from presentation.yaml
  state.py                    MicroseasonState DTO + DB builders
  predict.py                  fetch+classify a date range (archive/forecast)
  locate.py                   nearest-catalog resolution for arbitrary lat/lng
  serve.py                    stdlib HTTP API (/v1/*)
scripts/
  build_db.py                 YAML -> SQLite (idempotent)
  query.py                    inspection CLI (propose, active, last-seen, ...)
  fetch_weather.py            Open-Meteo client: fetch + classify + persist
  classify.py                 shared classifier (primary/secondary/triggered)
  solar.py                    solar geometry (declination + max elevation)
  serve.py                    launch the JSON API
  state.py                    dump a MicroseasonState as JSON (CLI)
contract/                     versioned render-model contract (JSON Schema + example)
.skills/                      agent skills (harness + j-* project skills)
.skills-harness/              vendored skills-harness kit (git subtree)
```

> The markdown YTD report (`scripts/report.py`, the per-city `narrative:`
> templates, and `reports/`) lives on the **`report-builder`** branch, where it
> consumes this API instead of the DB.

## Agent skills

Vendored from [Gargoyle-Apps/skills-harness](https://github.com/Gargoyle-Apps/skills-harness) via git subtree. Cursor loads the harness from `AGENTS.md`; the index is `.skills/_index.md`.

| Skill | Purpose |
|-------|---------|
| `j-weather-sync` | Fetch Open-Meteo → SQLite, re-classify |

Update the kit: `git subtree pull --prefix=.skills-harness skills-harness main --squash` (see **harness-subtree** skill).

Report-specific skills (`j-ytd-report`, `j-report-review`) live on the **`report-builder`** branch alongside the report generator.

Use `seattle` for city-center coords; add neighborhood-level grid cells to a gitignored `data/cities.local.yaml` (see `data/cities.local.example.yaml`).

## HTTP API

A zero-dependency stdlib server exposes the classification engine. It is the
single front door — consumers never touch the DB or Open-Meteo directly.

```bash
uv run scripts/serve.py            # http://127.0.0.1:8787
```

| Route | Returns |
|-------|---------|
| `GET /v1/health` | liveness + schema version |
| `GET /v1/presentation` | emoji/color/glyph maps |
| `GET /v1/state?city=&date=` | a day's `MicroseasonState` from stored observations |
| `GET /v1/forecast?city=&days=` | current state + a forecast window |
| `GET /v1/days?city=\|lat=&lng=&start=&end=` | a classified range — fetches Open-Meteo (archive/forecast) and classifies internally |
| `GET /v1/normals?city=` | monthly climate normals |

The response shape is versioned (`SCHEMA_VERSION`) and documented in
`contract/state.schema.json` with a worked example in
`contract/example_state.json`. Arbitrary `lat`/`lng` borrow the nearest
catalog city; child cities expose their parent via `catalog_slug`.

## Quick start

```bash
uv sync
uv run scripts/build_db.py

# Cross-city inspection
uv run scripts/query.py concepts            # which concepts are shared vs city-unique
uv run scripts/query.py cities              # cities + occurrence counts
uv run scripts/query.py compare "Spider Season"   # one concept across all its cities

# Per-city slices
uv run scripts/query.py --city seattle calendar
uv run scripts/query.py --city san_francisco all
uv run scripts/query.py --city san_francisco overlaps
uv run scripts/query.py --city san_francisco rain   # intensities + SF-scoped patterns

# Climate normals and anomaly view
uv run scripts/query.py --city seattle normals      # 12-month baseline
uv run scripts/query.py --city seattle anomaly      # each microseason's delta vs normal

# Classify hypothetical conditions
uv run scripts/query.py --city seattle propose 2 64 42                                  # Feb 64°F -> Fool's Spring (+14°F)
uv run scripts/query.py --city seattle propose 2 64 42 --cloud 25 --prior-overcast 15   # Fool's Spring + Praise the Sun + Photon Fraud
uv run scripts/query.py --city seattle propose 8 80 60 --smoke                          # Smogust + Choking Smoke
uv run scripts/query.py --city seattle propose 1 31 22 --snow 1.0                       # Find Bananas + Paralyzing Snow
uv run scripts/query.py --city san_francisco propose 3 85 60                            # SF heat anomaly -> propose new

# Live data: fetch from Open-Meteo, classify, store
uv run scripts/fetch_weather.py --all --days 14 --skip-existing            # both cities, last 14 days; skip days already on file
uv run scripts/fetch_weather.py --city seattle --days 30 --skip-existing   # Seattle, last 30 days
uv run scripts/fetch_weather.py --city seattle --start 2026-04-01 --end 2026-04-30 --skip-existing

# Sequence tracking against fetched observations
uv run scripts/query.py --city seattle active           # most recent day's classification
uv run scripts/query.py --city seattle last-seen        # per-microseason last-seen date (filters out aberrations)
uv run scripts/query.py --city seattle last-seen all    # include transient/aberration matches
uv run scripts/query.py --city seattle aberrations      # statistical-outlier days that don't define microseasons

# Misc
uv run scripts/query.py series              # series ordering
uv run scripts/query.py find faux           # search names + aliases
```

### Anomaly model

Every microseason is implicitly defined as a deviation from what's normally
true here for this time of year. The data layer makes this explicit:

- `city_climate_normals` holds 12 monthly rows per city (NOAA-style 30-year
  averages).
- `v_occurrence_vs_normals` exposes `high_anomaly_f` / `low_anomaly_f` for
  every microseason — Fool's Spring in Seattle is `+12°F` over Feb normal
  high; Juneuary is `-6°F`; Hell's Front Porch is `+38°F`.

This is what makes microseasons portable across cities: the same observed
temperature can be Fool's Spring in Seattle and just February in San
Francisco. The model resolves that via city-specific normals, not via
hardcoded temperature ranges.

### Three-tier classification

Every observation gets classified into up to three independent tiers — this
is what makes **Constants a secondary forecast** instead of competing with
the weather-of-the-day:

| tier | what's in it | examples |
| --- | --- | --- |
| **primary** | The weather classification(s) for this day. | Fool's Spring, Juneuary, Actual Spring, Hell's Front Porch |
| **triggered** | Signal-driven events that fired today. | Praise the Sun, Photon Fraud, Find Bananas, Smogust, Choking Smoke, Welcome Drizzle |
| **secondary** | Background traits currently in their typical window. | Karl the Fog, Spider Season, Convergence Zones |

A day might be (PRIMARY: Actual Spring, Juneuary) + (TRIGGERED: Praise the
Sun) + (SECONDARY: Convergence Zones) all at once.

### Live data: Open-Meteo + solar elevation + first-sun events

`scripts/fetch_weather.py` pulls daily weather + PM2.5 air-quality from
Open-Meteo (free, no API key), computes max solar elevation from
`scripts/solar.py`, persists each day to the `observations` table, and runs
the shared classifier to populate `observation_microseasons`. Re-running for
the same date REPLACES the row (idempotent).

```
$ uv run scripts/fetch_weather.py --all --days 14
[seattle] ...
  2026-06-04  hi 65/lo 54°F cloud 86%      PRIMARY: Actual Spring, Juneuary  secondary: Convergence Zones
  2026-06-05  hi 59/lo 50°F cloud 58%      PRIMARY: Actual Spring, Juneuary  secondary: Convergence Zones
```

Then:

```
$ uv run scripts/query.py --city seattle last-seen

  microseason                tier        last seen     first seen    days
  Actual Spring  [spring3]   primary     2026-06-05    2026-05-23    10
  Convergence Zones          secondary   2026-06-05    2026-05-23    14
  Juneuary                   primary     2026-06-05    2026-06-04    2
  Flowering Wet              primary     2026-05-30    2026-05-23    5
```

### First-sun events (strict tolerances)

Praise the Sun and Glorious Sun fire from observation HISTORY, not from
date alone — that's the only way to keep them honest in Seattle:

| | Seattle | San Francisco |
| --- | --- | --- |
| **Praise the Sun**: today cloud ≤ X% | 25% | 20% |
| **Praise the Sun**: prior consecutive overcast days ≥ N | 14 | 7 |
| **Glorious Sun**: above PLUS high ≥ X°F | 62°F | 65°F |
| **Glorious Sun**: AND solar elev ≥ X° | 35° | 35° |

A day where cloud is ≤80% is "overcast" for the purposes of the prior-day
streak. Thresholds live in `scripts/classify.py:FIRST_SUN_THRESHOLDS` and
can be moved into data later.

### Photon Fraud (sun without vitamin D)

Triggered by solar geometry, not date. Fires when max solar elevation at
solar noon ≤ 30° AND cloud cover ≤ 60% (so the sun is actually visible).

| latitude | dates Photon Fraud is geometrically possible |
| --- | --- |
| Seattle (47.6°N) | mid-Oct → mid-Feb |
| San Francisco (37.8°N) | a few weeks around winter solstice only |

This is why the same concept fires routinely in Seattle and almost never in
SF — the model captures this automatically via lat-based math.

### Aberration handling — one freak day doesn't scuttle the system

A single 100°F day in Seattle in late June is real weather, but it's a
fluke; we don't want it to (a) propose a new microseason that never
recurs, (b) become an "official" last-seen entry for Hell's Front Porch,
or (c) train an automated downstream consumer to expect it again.

When the classifier sees an observation more than `±20°F` from the
monthly normal — or wildfire smoke in deep winter, or snow in summer —
it marks the observation as an **aberration**:

- `observations.is_aberration = 1` is persisted in the DB.
- Primary matches get confidence downgraded to `0.2` (transient).
- The "propose new microseason" block is **suppressed** and replaced
  with an aberration note telling you to wait for recurrence before
  codifying.
- `last-seen` excludes transient + aberration matches by default
  (`last-seen all` opts back in).

Demonstrated against the real 2021 PNW heat dome:

```
$ uv run scripts/fetch_weather.py --city seattle --start 2021-06-25 --end 2021-06-30
  2021-06-25  hi 84/lo 61°F  PRIMARY: Actual Spring  secondary: Convergence Zones
  2021-06-26  hi 94/lo 64°F  secondary: Convergence Zones [ABERRATION]
  2021-06-27  hi 94/lo 68°F  secondary: Convergence Zones [ABERRATION]
  2021-06-28  hi 100/lo 70°F secondary: Convergence Zones [ABERRATION]
  2021-06-29  hi 91/lo 65°F  secondary: Convergence Zones    (+20°F, just under threshold)
  2021-06-30  hi 82/lo 62°F  secondary: Convergence Zones

$ uv run scripts/query.py --city seattle aberrations
  2021-06-28    hi 100°F lo 70°F   high +29°F vs normal (threshold ±20°F)
  2021-06-27    hi 94°F lo 68°F    high +23°F vs normal (threshold ±20°F)
  2021-06-26    hi 94°F lo 64°F    high +23°F vs normal (threshold ±20°F)
```

The heat dome days never appeared as `last-seen: Hell's Front Porch` —
which is what you'd want. They live cleanly in the aberrations log for
analysis. If/when the same anomaly recurs in a future year, that's the
signal to codify a new concept.

Tuning knobs in `scripts/classify.py`:
- `ABERRATION_ANOMALY_F = 20.0` — how far from normal counts as aberrant.
- `ABERRATION_PRIMARY_CONFIDENCE = 0.2` — confidence assigned to primary
  matches on aberration days.

### `propose` — manual classification + new-concept suggestions

`propose` takes hypothetical inputs and runs the same classifier as
`fetch_weather`:

```
$ uv run scripts/query.py --city seattle propose 2 64 42 --cloud 25 --prior-overcast 15

PRIMARY (weather classification):
  - Fool's Spring [spring1]  (series)
      high 64°F in 42–62°F range
TRIGGERED (signal-driven events):
  - Praise the Sun [first_sun_any]  (triggered_event)
      ≤25% cloud after ≥14 prior overcast days
  - Photon Fraud [low_sun_useless]  (sun_phenomenon)
      solar elevation 29.1° ≤ 30° with sun visible
SECONDARY (background traits active):
  - Convergence Zones  (constant)

Worth considering a new microseason concept:
  • warm anomaly (+14°F over normal high)
```

Matching rules (executed in `classify.py`):
1. **Constants** → secondary tier if their month window includes today.
2. **Photon Fraud** → triggered if solar elevation ≤ 30° AND sun visible.
3. **Signal-gated concepts** (Smogust, Smoketember, Choking Smoke; Find
   Bananas, Paralyzing Snow; Welcome Drizzle) → triggered if signal +
   in-window.
4. **First-sun events** (Praise/Glorious Sun) → triggered if strict
   tolerances above are all met.
5. **Other weather concepts** → primary if temperature fits (±3°F slack)
   AND in-window; "out-of-window-but-fits" listed separately.
6. If observation is ≥10°F off normal or has a disaster signal: also
   suggest defining a new concept.

## Data model

The model splits "what is this microseason?" from "how does it manifest here?"

```
microseasons           ← CONCEPT (global). Name, joke, category, series.
microseason_aliases    ← Global (Smaugust → Smogust).
microseason_occurrences ← PER CITY. Timing, temps, conditions, triggers,
                          climate sensitivity, local-flavor description.
microseason_overlaps   ← PER CITY. Pairs of occurrences that co-occur there.
series                 ← Global (spring/winter/summer/fall/...).
cities                 ← Cities scoped by the dataset.
city_climate_normals   ← PER CITY x MONTH. 30-year baselines (NOAA-style):
                          temp_max/min/mean, precip, snow, sun%. The "what's
                          normally true here" that every microseason is
                          implicitly defined AGAINST.
precipitation_types    ← Global (intensities + patterns).
precipitation_pattern_cities ← Patterns scope per city (Convergence Zone:
                               Seattle only; Diablo Winds: SF only;
                               Pineapple Express: both).
```

Two views are pre-built:
- `v_city_microseasons` flattens occurrence + concept + series into one row.
- `v_occurrence_vs_normals` joins each occurrence to its start-month normals
  and exposes `high_anomaly_f` / `low_anomaly_f` directly.

A convenience view `v_city_microseasons` flattens occurrences + concepts + series
into the "as-if pre-refactor" shape, for easy querying.

### Why this split?

- **Spider Season** is one concept; Seattle's window is Aug 15 – Oct 31, SF's is
  Sep 1 – Nov 15. Same joke, different timing.
- **Hell's Front Porch** is one concept; Seattle's trigger involves `850mb temps`,
  SF's involves `diablo_winds`. Same vibe, different mechanism.
- **Smogust / Smoketember / Choking Smoke** are West-Coast-wide concepts; each
  city carries its own occurrence row.
- **Juneuary** is a Seattle concept (so far); **June Gloom**, **May Gray**,
  **Fogust**, **Karl the Fog** are SF concepts. Each lives in the global
  catalog and just has one occurrence — adding them to another city later is
  one YAML entry.

### Microseason categories

| category           | meaning                                                              |
| ------------------ | -------------------------------------------------------------------- |
| `calendar`         | Predictable date window every year (Juneuary, The Long Dark)         |
| `series`           | Member of an ordered/alternating series (Fool's Spring = spring1)    |
| `triggered_event`  | Fires when conditions cross thresholds (Hell's Front Porch)          |
| `constant`         | Recurring trait, not really a season (Spider Season, Karl the Fog)   |
| `climate_disaster` | Wildfire smoke etc., compounded by climate change                    |
| `sun_phenomenon`   | "Useless sun" — out, but solar elevation too low for vitamin D       |

### Series (criterion 1.1)

- `spring`: `spring1` (Fool's Spring) → `spring2` (Spring of Deception) → `spring2_5` (The Pollening) → `spring3` (Actual Spring)
- `winter`: `winter1` (Winter) → `winter2` (Second Winter) → `winter3` (Third Winter), alternating with `spring`
- `fall`:   `fall1` (False Fall) → `fall2` (Second Summer) → `fall3` (Actual Fall)
- `summer`: `summer1` (Summer)
- `first_sun`: `first_sun_any` (Praise the Sun) → `first_sun_good` (Glorious Sun)
- `low_sun`: useless-sun phenomena (Photon Fraud + 4 aliases)

A city decides which series members it observes. SF currently has none of the
spring fakeouts because there's no proper winter to be relieved from.

### Concept vs. occurrence — what lives where?

| Lives on **concept** (`microseasons.yaml`) | Lives on **occurrence** (`cities/<slug>.yaml`) |
| --- | --- |
| `canonical_name`, `slug`, `aliases`            | `typical_start_*` / `typical_end_*` / `typical_duration_days` |
| `category`                                     | `temp_min_f` / `temp_max_f` |
| `series`, `series_order`, `series_label`       | `conditions`, `triggers`, `climate_drivers` |
| `description` (universal vibe/joke)            | `is_nonlinear`, `can_be_skipped`, `can_be_amplified` |
| `notes` (concept-level commentary)             | `local_name` (optional rename), `local_description` (local flavor) |

### Adding a new city

**Independent city** (its own catalog):

1. Add a row to `data/cities.yaml`.
2. Create `data/cities/<slug>.yaml` with `occurrences:`, `overlaps:`,
   `precipitation_patterns:`, and ideally `climate_normals:`. (Report narrative
   templates, if any, live on the `report-builder` branch.)
3. If you need a brand-new concept that doesn't already exist (a city-unique
   microseason), add it to `data/microseasons.yaml` as a concept first, then
   give it an occurrence in your new city file.
4. `uv run scripts/build_db.py`.

**Sibling city / grid cell** (shares an existing city's catalog):

Neighborhood-level entries (grid cells, ZIPs, blocks) belong in a
**gitignored** `data/cities.local.yaml` so they never get committed.
See `data/cities.local.example.yaml` for the schema. The example boils
down to one block:

```yaml
- slug: seattle_neighborhood
  name: "Seattle, WA (neighborhood)"
  latitude:  47.6XXX
  longitude: -122.3XXX
  parent_slug: seattle    # inherits catalog + normals + narrative voice
```

`scripts/build_db.py` merges `cities.local.yaml` on top of `cities.yaml`
automatically. No per-city YAML required. Occurrences and climate normals
resolve through `v_catalog_city` at query time (and the API surfaces the
parent via `catalog_slug` so consumers can inherit parent-owned resources).
Observations are still scoped to the child (independent grid cell), so
anomaly + last-seen data is local even when the catalog isn't. Optional
per-grid normals override: drop a `data/cities/<slug>.local.yaml` with
just `climate_normals:` (also gitignored).

The loader rejects occurrences that reference unknown concepts, child
cities that try to define their own occurrences/overlaps, and warns on
overlap pairs whose concepts have no occurrence in that city.

## Current dataset

- 2 public cities (Seattle, San Francisco placeholder); any number of
  local sibling/grid entries via gitignored `data/cities.local.yaml`.
- 38 concepts, 8 shared between Seattle and San Francisco.
- 45 occurrences (31 Seattle + 14 San Francisco); local children
  inherit their parent's via `parent_slug`.
- 32 overlap pairs.
- 15 precipitation types (10 universal intensities + 5 patterns).
- 7 pattern↔city links.
- 24 monthly climate-normal rows (12 × 2 cities, NOAA 1991–2020 approximated);
  local children inherit their parent's.
- Observations and classifications stream in from Open-Meteo via
  `scripts/fetch_weather.py` — no API key needed.

## Editorial decisions worth your review

- **Faux Spring / False Spring / Fool's Spring** → one concept with two aliases.
- **Juneuary vs. June Gloom** → modeled as **distinct concepts**. Same cool-June
  vibe but different mechanisms (generalized cool June vs. specifically
  marine-layer fog) and different cultural meaning. Easy to merge into one
  concept with city-specific names if you prefer.
- **Photon Fraud / The Empty Bright / SAD Sun / Solar Deficiency / Bright Nothing**
  → five aliases of one concept.
- **Autumn → alias of Actual Fall.**
- **Indian Summer** added as its own concept (used by SF; "Second Summer" in
  Seattle remains a separate concept because the Seattle term is doing
  series-step work alongside False Fall and Actual Fall).
- **The Pollening** stays inside the spring series as `spring2_5`.
- **Convergence Zone** appears both as a `constant` microseason (Seattle only)
  and as a `pattern` in precipitation (scoped to Seattle).

## Next up

- Add a non-West-Coast city (NYC / Boston / Chicago) to stress-test the
  model with hurricanes, polar vortex, real winter, and humid summers.
- Move first-sun thresholds + signal-gate parameters out of `classify.py`
  and into per-city YAML (mirror the data-driven `presentation.yaml` pattern).
- Per-grid climate-normal overrides for sibling cities — children
  currently inherit the parent's official-airport normals, which can be
  several degrees off in micro-climates.
- Small Node/pnpm frontend (framework TBD) over the SQLite DB. Now that
  `observations` + `v_microseason_last_seen` are populated, a calendar
  view + sequence timeline is straightforward.
- Cron / scheduled job to call `fetch_weather.py --all --days 2 --skip-existing` daily.
