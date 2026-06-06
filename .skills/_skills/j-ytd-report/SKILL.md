---
name: j-ytd-report
description: "Generate the combined YTD microseasons report — summary, numbers, monthly story, and season timeline."
triggers:
  - ytd report
  - generate report
  - microseason report
  - narrative report
  - season timeline
  - write up the year
  - seattle report
dependencies:
  - j-weather-sync
  - j-report-review
version: "2.0.0"
---

# YTD Report (combined)

## When to use this skill

Load when the user wants a **single** year-to-date microseasons report: narrative
summary up front, stats table, monthly story, biweekly season timeline with
commentary, series progression, triggered events, and notable days.

There is no separate tabular vs narrative output — one file covers both.

## Prerequisites

1. **j-weather-sync** — observations in `db/microseasons.db` for the city and period.
2. **j-report-review** — verify DB matches live Open-Meteo (especially forecast-era dates).

```bash
uv sync
uv run scripts/build_db.py   # if DB missing
```

## Generate

```bash
uv run scripts/report.py --city seattle
uv run scripts/report.py --city seattle_neighborhood --year 2019
uv run scripts/report.py --city seattle --through 2026-06-05
uv run scripts/report.py --city seattle --out reports/custom.md
```

Default output: `reports/<city>_<year>_ytd.md` (gitignored except `reports/.gitkeep`).

## Report structure (in order)

| Section | Content |
|---------|---------|
| **YTD Summary** | Auto headline, classification stats, spring-series arc |
| **The numbers** | YTD precip/snow/freeze/heat table vs normals |
| **Monthly story** | One bullet per month with narrative tags (wet, snow, mild, etc.) |
| **Season timeline** | ~Biweekly chapters: weather, dominant series, triggered events, lived-experience note |
| **Series progression** | Winter → spring → summer → fall slot chronology |
| **Triggered events** | Full table (Find Bananas, Paralyzing Snow, Photon Fraud, …) |
| **Notable days** | Top-5 hot / cold / wet |
| **Method** | Data sources and caveats |

## Cities

| Slug | Location |
|------|----------|
| `seattle` | City center (47.61°N, -122.33°W) |
| `seattle_neighborhood` | NEIGHBORHOOD / ZIP NNNNN (47.NN°N, -122.NN°W) |

Add more in `data/cities.yaml` + `data/cities/<slug>.yaml`, then `build_db.py`.

## Interpretation notes (include when relevant)

- Primary microseason counts **overlap** — multiple primaries per day is normal.
- "Days with a primary" may be &lt;100% — warm outliers can be unclassified.
- **Find Bananas / Paralyzing Snow** appear under **Triggered events**, not the season timeline title — check that section for snow weeks.
- Partial months (YTD in June) — precip vs full-month normal is apples/oranges.

## Examples

- "Report for Seattle 2019 in NNNNN" → sync 2019, verify OM, `report.py --city seattle_neighborhood --year 2019`
- "Write up the year's false springs" → same report; read Monthly story + Season timeline
