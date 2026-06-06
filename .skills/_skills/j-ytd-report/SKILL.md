---
name: j-ytd-report
description: "Generate the YTD microseasons report — vernacular narrative with text-passable emoji, numbers, monthly story, and season timeline."
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
version: "2.3.0"
---

# YTD Report

## When to use this skill

Load when the user wants a **year-to-date microseasons report** for a city and period.
This repo is report-first: the output should read like a local wrote it, using the
taxonomy vernacular (**Find Bananas**, **Paralyzing Snow**, **Fool's Spring**,
**Juneuary**, **Welcome Drizzle**, **The Long Dark**, etc.) — not dry meteorology.
Every section uses **text-passable UTF-8 emoji** (🍌 **Find Bananas**, 📋 section
headings, 🌧️ precip rows) so reports read well in GitHub, terminals, and plain text.

One file: `reports/<city>_<year>_ytd.md` (gitignored except `reports/.gitkeep`).

## Prerequisites

1. **j-weather-sync** — observations in DB for the city and date range.
2. **j-report-review** — verify DB matches live Open-Meteo before publishing.

```bash
uv sync
uv run scripts/build_db.py   # if DB missing
```

## Generate

```bash
uv run scripts/report.py --city seattle --year 2019
uv run scripts/report.py --city seattle --through 2026-06-05
# Neighborhood-level slugs live in gitignored data/cities.local.yaml:
uv run scripts/report.py --city seattle_neighborhood --year 2019
```

## Report structure (in order)

| # | Section | Emoji | Voice |
|---|---------|-------|-------|
| 1 | **YTD Summary** | 📋 | Opening paragraphs in microseason vernacular; triggered highlights (banana run, snowmageddon, etc.); spring series arc |
| 2 | **The numbers** | 📊 | Stats table with row emoji (🌧️ precip, ❄️ snow, 🔥 hottest, …) |
| 3 | **Monthly story** | 📅 | One vivid bullet per month — **must use taxonomy names** with emoji |
| 4 | **Season timeline** | 🗓️ | Biweekly chapters with microseason titles + prose |
| 5 | **Series progression** | 🔁 | winter → spring chronology (❄️/🌷/☀️/🍂 series headers) |
| 6 | **Triggered events** | ⚡ | Full table; event column uses `tag()` emoji |
| 7 | **Notable days** | 📌 | Top hot/cold/wet (🔥/🧊/🌧️ subsections) |
| 8 | **Method** | 🔬 | Data caveats |

## Vernacular cheat sheet (weave these in)

| Term | Emoji | When to use |
|------|-------|-------------|
| **Find Bananas** | 🍌 | Any snow-in-forecast panic; grocery stampede |
| **Paralyzing Snow** | 🚌 | ≥0.5" accumulation; city paralyzed |
| snowmageddon / snow siege | 🌨️ / ❄️ | Multi-day Feb events (use in prose) |
| **Fool's Spring** | 🌤️ | First warm tease, often Feb |
| **Spring of Deception** | 🌸 | Convincing March fake-out |
| **Third Winter** | 🌨️ | April cold snap / hail / snow |
| **Actual Spring** | 🌷 | When spring finally sticks (May) |
| **Juneuary** | 🌫️ | Early June marine layer |
| **Welcome Drizzle** | 🌧️ | First real rain after summer dry spell |
| **Photon Fraud** | 🌥️ | Low-angle useless sun |
| **The Long Dark** / **The Dark Wet** | 🌑 / 🌧️ | Winter grey |
| **Convergence Zones** | ⚡ | Localized soak (Lynnwood/Everett band) |

Snow events live in **Triggered events** AND should be called out in **Monthly story**
and **Season timeline** chapters — never bury **Find Bananas** in a stats footnote.

## Emoji convention

Reports use **text-passable UTF-8 emoji** (GitHub, terminals, plain text) via
`scripts/report.py`:

- Section headings: 📋 YTD Summary, 📊 The numbers, 🗓️ Season timeline, etc.
- Microseason names: 🍌 **Find Bananas**, 🚌 **Paralyzing Snow**, 🌤️ **Fool's Spring**, …
- Narrative terms: 🌨️ **snowmageddon**, ❄️ **snow siege**, 🍌 **banana weather**
- Stats rows and notable-day blocks get row-level emoji (🌧️ precip, 🔥 hottest, …)

`emojify()` and `tag()` in `report.py` are the source of truth — extend `MS_EMOJI`,
`TERM_EMOJI`, `SECTION_EMOJI`, or `STAT_ROW_EMOJI` when adding new taxonomy terms.
Do **not** hand-add emoji in generated markdown; let the generator apply them consistently.
`emojify()` runs once at the end of `main()` on the assembled document — sub-renderers
produce raw text. The replacement is idempotent (multi-pass safe).

**Emoji-collision policy (intentional):** Several microseasons share glyphs by design
(☀️ Summer / Glorious Sun, 🔥 Hell's Front Porch / Smoketember, 🌧️ The Dark Wet /
Welcome Drizzle, 🌫️ Juneuary / Smogust, 🫠 Molding Wet / Oppressive Sun). The collision
isn't a bug — emoji are always paired with the bolded name via `tag()`, so the reader
sees `🔥 **Hell's Front Porch**` vs `🔥 **Smoketember**` and is never asked to disambiguate
the icon alone.

## Cities

| Slug | Location | Notes |
|------|----------|-------|
| `seattle` | City center | Catalog owner (microseasons, normals, narrative voice) |
| `san_francisco` | City center | Independent catalog |
| _your local children_ | grid cells / ZIPs | Defined in **gitignored** `data/cities.local.yaml` (see `data/cities.local.example.yaml`) |

**Sibling cities:** Child cities (`parent_slug` in `data/cities.yaml` OR
`data/cities.local.yaml`) inherit their parent's microseason occurrences,
climate normals, and narrative templates via `v_catalog_city`. Neighborhood
/ ZIP-level entries are PII-adjacent — keep them in `cities.local.yaml`
(gitignored) so they never get committed. Per-grid normal overrides go in
`data/cities/<slug>.local.yaml` (also gitignored).

## If `report.py` prose feels thin

The generator uses heuristics from classified data and templates from
`data/cities/<catalog_slug>.yaml#narrative`. For landmark years (e.g. Feb 2019
snowmageddon), the auto prose should suffice after classification. If a specific
lived-experience detail matters, **edit the YAML**, not the Python — the voice lives
in `narrative.months`, `narrative.chunks`, `narrative.ytd_*`, etc. The Python only
computes features (snow_label, peak_*, d_hi, …) and dispatches to the templates.

## Examples

- "neighborhood report for 2019" → ensure the slug exists in `data/cities.local.yaml`, sync, verify OM, `report.py --city <local_slug> --year 2019`
- "Write it in our microseason voice" → this skill; check Monthly story + Season timeline
