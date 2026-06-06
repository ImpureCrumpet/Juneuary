---
name: j-report-review
description: "Verify report numbers against a live Open-Meteo fetch, not just the local DB."
triggers:
  - review report
  - check report accuracy
  - verify against open-meteo
  - report code review
  - is the report right
version: "2.0.0"
---

# Report Accuracy Review

> **Branch:** lives on `report-builder` alongside `scripts/report.py`.

## When to use this skill

Load when the user asks whether a report is **accurate**, **correct**, or
**matches reality**.

**Accuracy means matching Open-Meteo**, not matching a previous report export.
Note the report now pulls its data live through the API's `/v1/days` (which
fetches Open-Meteo itself), so a freshly built report reflects current
Open-Meteo — the review is mostly checking that the rendered numbers agree with
an independent fetch and that the narrative claims hold.

## Instructions

### 1. Identify the report window

From the report header or user: city slug, start date, end date.

### 2. Live-fetch Open-Meteo

```python
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, "scripts")
from fetch_weather import fetch_weather

lat, lng = 47.6062, -122.3321  # or read from cities table
wx = fetch_weather(lat, lng, date(2026, 1, 1), date(2026, 6, 5))
```

Or shell:

```bash
uv run scripts/fetch_weather.py --city seattle --start 2026-05-01 --end 2026-06-05
```

### 3. Compare OM vs DB per day

Flag when any of:

| Field | Tolerance |
|-------|-----------|
| High / low temp | > 0.25°F |
| Precip | > 0.02 in |
| Snow | > 0.02 in |

```python
# Pseudocode loop over daily['time']
# Compare temperature_2m_max/min, precipitation_sum, snowfall_sum
# against observations.temp_high_f, temp_low_f, precip_in, snow_in
```

### 4. If drift found

Because the report fetches live via `/v1/days`, simply **rebuild the report**
(`uv run scripts/report.py ...`) to pick up the latest Open-Meteo data, then
re-diff. Forecast-era days (the most recent ~week) can shift between runs;
document that caveat for any report covering them. Jan–Apr archive data is
usually stable. (DB staleness only affects `/v1/state` and `/v1/forecast`,
which read stored observations — not the report.)

### 5. Verify monthly aggregates against OM (not report rounding)

Compute monthly avg high/low and precip sums from OM daily arrays. Compare to
report's "Monthly Summary vs Normals" — allow ±1°F display rounding.

### 6. Review report.py logic (code review checklist)

| Check | Issue if wrong |
|-------|----------------|
| YTD Summary primary % | Counts days with any primary; overlaps normal |
| Season timeline vs triggered | Snow weeks — Find Bananas / Paralyzing Snow live in **Triggered events** table |
| Missing primary days | Warm outliers (May 80°F+) may be unclassified |
| Partial month normals | YTD in June — monthly story flags short months |
| Stale DB | Forecast-era temps off by several °F |

### 7. Cross-check narrative claims

For each qualitative claim ("mild winter", "false spring", "wet March"):

- Mild winter → few freeze lows, positive low-temp anomaly vs normals
- False spring → warm spell followed by cold/snow within 2 weeks
- Wet March → monthly precip >> normal, not necessarily cold highs

### 8. Deliverable format

```markdown
## Verdict
[Accurate against OM / Partially stale / Wrong]

## OM vs DB
- N days compared, M diffs
- List material diffs or "0 diffs after refresh"

## Report logic issues
- ...

## Narrative alignment
- User memory vs data: ...
```

## Examples

- "Is the Seattle report accurate?" → live OM fetch, diff, refresh if needed
- "Code review the report" → logic checklist + OM verification
