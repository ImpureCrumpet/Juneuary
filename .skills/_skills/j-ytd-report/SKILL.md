---
name: j-ytd-report
description: "Generate the machine-readable YTD microseasons markdown report from the local DB."
triggers:
  - ytd report
  - tabular report
  - generate report
  - microseason report
  - seattle report tables
dependencies:
  - j-weather-sync
version: "1.0.0"
---

# YTD Tabular Report

## When to use this skill

Load when the user wants the **machine-readable** year-to-date report: snapshot
counts, primary/secondary timelines, series progression, triggered events,
monthly normals table, and notable days. This report reads **only the local DB**
— run **j-weather-sync** first (and **j-report-review** if accuracy matters).

## Instructions

### 1. Ensure observations exist

```bash
uv run scripts/fetch_weather.py --city seattle --start 2026-01-01 --end <today> --skip-existing
```

### 2. Generate

```bash
uv run scripts/report.py --city seattle
uv run scripts/report.py --city seattle --through 2026-06-05
uv run scripts/report.py --city seattle --out reports/custom.md
```

Default output: `reports/<city>_<year>_ytd.md`.

### 3. Understand the output sections

| Section | Source |
|---------|--------|
| Snapshot | observation + classification counts |
| Primary / Secondary timelines | per-microseason day counts (overlapping) |
| Series progression | winter/spring/summer/fall slot chronology |
| Triggered events | signal-fired events with reasons |
| Aberrations | `is_aberration` flag from classifier |
| Monthly summary vs normals | `city_climate_normals` |
| Notable days | top-5 hot/cold/wet from observations |

### 4. Interpretation caveats (tell the user if relevant)

- **Primary day counts overlap** — a single day can carry Winter + The Dark Wet + Fool's Spring. Counts do not sum to calendar days.
- **"Days with a classification: 100%"** means every day has at least a secondary constant (e.g. Convergence Zones), not that every day has a primary microseason.
- **~10–15% of days may lack any primary** when temps fall outside all defined profiles or match only out-of-window concepts.

## Examples

- "Generate the Seattle YTD tables" → `report.py --city seattle`
- "Report through June 5" → `--through 2026-06-05`
