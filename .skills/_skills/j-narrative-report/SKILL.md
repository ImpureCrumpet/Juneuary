---
name: j-narrative-report
description: "Write a human narrative YTD report with season timeline and lived-experience commentary."
triggers:
  - narrative report
  - season timeline
  - commentary report
  - write up the year
  - microseason story
dependencies:
  - j-weather-sync
  - j-report-review
version: "1.0.0"
---

# Narrative YTD Report

## When to use this skill

Load when the user wants a **human-facing** write-up: YTD summary in plain
language, a chronological season timeline with commentary, and alignment with
how the year *felt* locally (mild winter, false springs, etc.) — not just tables.

Output: `reports/<city>_<year>_ytd_narrative.md`

## Instructions

### 1. Sync and verify (required)

Follow **j-weather-sync** to refresh recent forecast-era days.

Follow **j-report-review** to confirm DB matches live Open-Meteo. Fix any drift
before writing narrative numbers.

### 2. Gather facts from Open-Meteo (source of truth for temps/precip)

Compute from a live fetch or verified DB:

- Monthly avg high/low, precip vs `city_climate_normals`
- YTD totals: precip, snow, days below 32°F, days ≥ 60°F / ≥ 70°F
- Coldest low, hottest high with dates
- Warm spells (3+ consecutive days ≥ 55°F)
- Snow days (≥ 0.1 in)

Use `scripts/fetch_weather.py`'s `fetch_weather()` for the live comparison.

### 3. Gather microseason arc from DB

```bash
uv run scripts/report.py --city seattle --through <end>   # reference tables
uv run scripts/query.py --city seattle all                # optional detail
```

Identify:

- **Series progression:** Winter → Fool's Spring → Second Winter → Spring of
  Deception → Third Winter → Actual Spring → Juneuary
- **Triggered events:** snow days, Photon Fraud runs
- **Biweekly or thematic chapters** for the timeline (not one row per day)

### 4. Write the narrative structure

```markdown
# <City> — <Year> YTD Narrative Report

**Generated:** <today>
**Period:** <start> → <end>
**Weather source:** Open-Meteo ERA5 + forecast
**Normals:** NOAA NCEI 1991–2020 (from city YAML)

## YTD Summary
- Headline sentence (how the year felt)
- Key numbers table (observed vs normal)
- Monthly temperature story (1–2 sentences each)
- False springs inventory (which lies fired, when)
- "What matched lived experience" checklist

## Season Timeline
### <date range> · <dominant microseason>
**Weather:** stats
**Series:** slot label
> *Lived experience:* commentary

(repeat per chapter)

## Data integrity note
- OM verification status, stale-forecast caveat, ERA5 vs station disclaimer

## Quick reference — triggered events YTD
```

### 5. Commentary guidelines

- Lead with **felt experience**, support with numbers.
- Call out **false springs explicitly** — Feb tease, Mar wet deception, Apr
  whiplash — when the data supports it.
- Note when **mild = warm lows**, not necessarily warm highs (PNW pattern).
- Flag **partial months** (e.g. June day 5 vs full-month normal).
- Distinguish **wet March** from **cold March** when precip and temp diverge.
- End timeline chapters with a blockquote `> *Lived experience:* ...`

### 6. Do not

- Copy the tabular report verbatim — cross-link to `reports/<city>_<year>_ytd.md`.
- Quote DB numbers without OM verification on forecast-era dates.
- Invent microseason labels for days the classifier left unclassified — say
  "warm outlier" or cite the hottest days in Notable Days instead.

## Examples

- "Write up Seattle's mild winter and false springs" → narrative report with
  Feb snow, Mar soak, Apr 15 snow, May heat release
- "New narrative version of the Seattle report" → `reports/seattle_2026_ytd_narrative.md`
