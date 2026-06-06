"""Generate a combined YTD microseasons report for a city.

One markdown file: narrative summary up front, data tables and season timeline
below. Pulls from the local SQLite DB (no API calls). Run
`scripts/fetch_weather.py` first and verify against Open-Meteo for recent dates.

Example:
    uv run scripts/report.py --city seattle
    uv run scripts/report.py --city seattle_neighborhood --year 2019
    uv run scripts/report.py --city seattle --through 2026-06-05
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "microseasons.db"

TOP_N = 5
BIWEEKLY_DAYS = 14

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_SHORT = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Text-passable UTF-8 emoji for markdown reports (GitHub, terminals, plain text).
MS_EMOJI: dict[str, str] = {
    "Find Bananas": "🍌",
    "Paralyzing Snow": "🚌",
    "Winter": "❄️",
    "Second Winter": "🥶",
    "Third Winter": "🌨️",
    "Fool's Spring": "🌤️",
    "Spring of Deception": "🌸",
    "The Pollening": "🤧",
    "Actual Spring": "🌷",
    "Juneuary": "🌫️",
    "Summer": "☀️",
    "Hell's Front Porch": "🔥",
    "Oppressive Sun": "🫠",
    "False Fall": "🍂",
    "Second Summer": "🌅",
    "Actual Fall": "🍁",
    "The Grey": "🩶",
    "The Long Dark": "🌑",
    "The Dark Wet": "🌧️",
    "Brightening Wet": "🌦️",
    "Molding Wet": "🫠",
    "Flowering Wet": "🌺",
    "Welcome Drizzle": "🌧️",
    "Praise the Sun": "🌞",
    "Glorious Sun": "☀️",
    "Photon Fraud": "🌥️",
    "Smogust": "🌫️",
    "Smoketember": "🔥",
    "Choking Smoke": "😷",
    "Convergence Zones": "⚡",
    "Spider Season": "🕷️",
}

TERM_EMOJI: dict[str, str] = {
    "snowmageddon": "🌨️",
    "snow siege": "❄️",
    "banana weather": "🍌",
    "false spring": "🌤️",
    "The Snow Siege": "🌨️",
    "Banana Weather": "🍌",
}

SECTION_EMOJI: dict[str, str] = {
    "YTD Summary": "📋",
    "The numbers": "📊",
    "Monthly story": "📅",
    "Season timeline": "🗓️",
    "Series progression": "🔁",
    "Triggered events": "⚡",
    "Notable days": "📌",
    "Method": "🔬",
}

STAT_ROW_EMOJI: dict[str, str] = {
    "Total precip": "🌧️",
    "Total snowfall": "❄️",
    "Days low": "🥶",
    "Days high ≥ 60": "🌤️",
    "Days high ≥ 70": "☀️",
    "Coldest low": "🧊",
    "Hottest high": "🔥",
}


def emojify(text: str) -> str:
    """Prefix known microseason / narrative terms with emoji (idempotent)."""
    for term, emoji in sorted(
        {**MS_EMOJI, **TERM_EMOJI}.items(), key=lambda x: -len(x[0])
    ):
        bare = f"**{term}**"
        marked = f"{emoji} {bare}"
        # Per-occurrence: skip if this instance is already tagged (not whole-doc).
        text = re.sub(
            rf"(?<!{re.escape(emoji)} ){re.escape(bare)}",
            marked,
            text,
        )
    return text


def tag(name: str) -> str:
    """Microseason name with emoji, for inline prose."""
    emoji = MS_EMOJI.get(name, "")
    return f"{emoji} **{name}**" if emoji else f"**{name}**"


def arc_line(names: list[str]) -> str:
    return " → ".join(tag(n) for n in names)


def section_heading(title: str) -> str:
    emoji = SECTION_EMOJI.get(title, "")
    prefix = f"{emoji} " if emoji else ""
    return f"## {prefix}{title}"


def subsection_heading(title: str, emoji: str = "") -> str:
    return f"### {f'{emoji} ' if emoji else ''}{title}"


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_city(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cities WHERE slug = ?", [slug]).fetchone()
    if row is None:
        raise SystemExit(f"city not found: {slug}")
    return row


def get_observations(
    conn: sqlite3.Connection, city_id: int, start: str, end: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, observed_date, temp_high_f, temp_low_f, temp_mean_f,
               precip_in, snow_in, cloud_cover_mean_pct, sun_hours,
               smoke, pm25_ug_m3, aqi_us, solar_elevation_max_deg,
               is_aberration, aberration_reason
        FROM observations
        WHERE city_id = ? AND observed_date BETWEEN ? AND ?
        ORDER BY observed_date
        """,
        [city_id, start, end],
    ).fetchall()


def get_classifications(
    conn: sqlite3.Connection, city_id: int, start: str, end: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT o.observed_date         AS d,
               om.tier                 AS tier,
               om.confidence           AS confidence,
               om.reason               AS reason,
               COALESCE(occ.local_name, m.canonical_name) AS display_name,
               m.canonical_name        AS canonical_name,
               m.category              AS category,
               s.key                   AS series_key,
               m.series_order          AS series_order,
               m.series_label          AS series_label,
               o.is_aberration         AS is_aberration
        FROM observation_microseasons om
        JOIN observations o            ON o.id   = om.observation_id
        JOIN microseason_occurrences occ ON occ.id = om.occurrence_id
        JOIN microseasons m            ON m.id   = occ.microseason_id
        LEFT JOIN series s             ON s.id   = m.series_id
        WHERE o.city_id = ? AND o.observed_date BETWEEN ? AND ?
        ORDER BY o.observed_date, om.tier, m.canonical_name
        """,
        [city_id, start, end],
    ).fetchall()


def get_normals(conn: sqlite3.Connection, city_id: int) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM city_climate_normals WHERE city_id = ?", [city_id]
    ).fetchall()
    return {r["month"]: r for r in rows}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class MonthStats:
    month: int
    days: int = 0
    avg_hi: float | None = None
    avg_lo: float | None = None
    precip: float = 0.0
    snow: float = 0.0
    snow_days: int = 0
    freeze_days: int = 0
    days_60: int = 0
    norm_hi: float | None = None
    norm_lo: float | None = None
    norm_precip: float | None = None

    @property
    def d_hi(self) -> float | None:
        if self.avg_hi is not None and self.norm_hi is not None:
            return self.avg_hi - self.norm_hi
        return None

    @property
    def d_lo(self) -> float | None:
        if self.avg_lo is not None and self.norm_lo is not None:
            return self.avg_lo - self.norm_lo
        return None

    @property
    def d_precip(self) -> float | None:
        if self.norm_precip is not None:
            return self.precip - self.norm_precip
        return None


@dataclass
class YtdStats:
    months: dict[int, MonthStats] = field(default_factory=dict)
    total_precip: float = 0.0
    total_snow: float = 0.0
    freeze_days: int = 0
    days_60: int = 0
    days_70: int = 0
    days_80: int = 0
    coldest: tuple[str, float] | None = None
    hottest: tuple[str, float] | None = None
    norm_precip_sum: float = 0.0
    primary_days: int = 0
    total_days: int = 0


def compute_stats(
    observations: list[sqlite3.Row],
    normals: dict[int, sqlite3.Row],
    classifications: list[sqlite3.Row],
) -> YtdStats:
    stats = YtdStats(total_days=len(observations))
    by_month: dict[int, dict] = defaultdict(
        lambda: {"highs": [], "lows": [], "precip": 0.0, "snow": 0.0,
                 "snow_days": 0, "freeze": 0, "days_60": 0, "days": 0}
    )
    for o in observations:
        m = int(o["observed_date"][5:7])
        d = by_month[m]
        d["days"] += 1
        if o["temp_high_f"] is not None:
            d["highs"].append(o["temp_high_f"])
            if o["temp_high_f"] >= 60:
                d["days_60"] += 1
                stats.days_60 += 1
            if o["temp_high_f"] >= 70:
                stats.days_70 += 1
            if o["temp_high_f"] >= 80:
                stats.days_80 += 1
            if stats.hottest is None or o["temp_high_f"] > stats.hottest[1]:
                stats.hottest = (o["observed_date"], o["temp_high_f"])
        if o["temp_low_f"] is not None:
            d["lows"].append(o["temp_low_f"])
            if o["temp_low_f"] < 32:
                d["freeze"] += 1
                stats.freeze_days += 1
            if stats.coldest is None or o["temp_low_f"] < stats.coldest[1]:
                stats.coldest = (o["observed_date"], o["temp_low_f"])
        pr = o["precip_in"] or 0
        sn = o["snow_in"] or 0
        d["precip"] += pr
        d["snow"] += sn
        stats.total_precip += pr
        stats.total_snow += sn
        if sn >= 0.1:
            d["snow_days"] += 1

    for m, d in by_month.items():
        n = normals.get(m)
        ms = MonthStats(
            month=m,
            days=d["days"],
            avg_hi=sum(d["highs"]) / len(d["highs"]) if d["highs"] else None,
            avg_lo=sum(d["lows"]) / len(d["lows"]) if d["lows"] else None,
            precip=d["precip"],
            snow=d["snow"],
            snow_days=d["snow_days"],
            freeze_days=d["freeze"],
            days_60=d["days_60"],
            norm_hi=n["temp_max_avg_f"] if n else None,
            norm_lo=n["temp_min_avg_f"] if n else None,
            norm_precip=n["precip_total_in"] if n else None,
        )
        stats.months[m] = ms
        if ms.norm_precip is not None:
            stats.norm_precip_sum += ms.norm_precip

    primary_day_set = {c["d"] for c in classifications if c["tier"] == "primary"}
    stats.primary_days = len(primary_day_set)
    return stats


# ---------------------------------------------------------------------------
# Narrative context (microseason vernacular per month / period)
# ---------------------------------------------------------------------------

@dataclass
class MonthContext:
    month: int
    triggered: Counter[str] = field(default_factory=Counter)
    series: Counter[str] = field(default_factory=Counter)
    calendar: Counter[str] = field(default_factory=Counter)
    peak_snow: tuple[str, float] | None = None   # (date, inches)
    peak_hi: tuple[str, float] | None = None
    peak_precip: tuple[str, float] | None = None


def build_month_contexts(
    observations: list[sqlite3.Row],
    classifications: list[sqlite3.Row],
) -> dict[int, MonthContext]:
    ctx: dict[int, MonthContext] = {}
    for o in observations:
        m = int(o["observed_date"][5:7])
        c = ctx.setdefault(m, MonthContext(month=m))
        sn = o["snow_in"] or 0
        if sn >= 0.1 and (c.peak_snow is None or sn > c.peak_snow[1]):
            c.peak_snow = (o["observed_date"], sn)
        hi = o["temp_high_f"]
        if hi is not None and (c.peak_hi is None or hi > c.peak_hi[1]):
            c.peak_hi = (o["observed_date"], hi)
        pr = o["precip_in"] or 0
        if pr > 0 and (c.peak_precip is None or pr > c.peak_precip[1]):
            c.peak_precip = (o["observed_date"], pr)

    for row in classifications:
        m = int(row["d"][5:7])
        c = ctx.setdefault(m, MonthContext(month=m))
        if row["tier"] == "triggered":
            c.triggered[row["canonical_name"]] += 1
        elif row["tier"] == "primary":
            if row["category"] == "series":
                c.series[row["canonical_name"]] += 1
            elif row["category"] == "calendar":
                c.calendar[row["canonical_name"]] += 1
    return ctx


def _top(counter: Counter[str], n: int = 2) -> list[str]:
    return [name for name, _ in counter.most_common(n)]


def _snowmageddon_label(snow_days: int, peak_in: float, total_in: float = 0) -> str:
    if peak_in >= 4 or total_in >= 8 or (snow_days >= 5 and peak_in >= 2.5):
        return "snowmageddon"
    if snow_days >= 3 or peak_in >= 1.5 or total_in >= 4:
        return "snow siege"
    if snow_days >= 1:
        return "banana weather"
    return ""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def humanize_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def humanize_span(first: str, last: str) -> str:
    if first == last:
        return humanize_date(first)
    return f"{humanize_date(first)} – {humanize_date(last)}"


def contiguous_spans(dates: list[str]) -> list[tuple[str, str, int]]:
    if not dates:
        return []
    out: list[tuple[str, str, int]] = []
    run_start = prev = dates[0]
    run_len = 1
    for d in dates[1:]:
        if (date.fromisoformat(d) - date.fromisoformat(prev)).days == 1:
            run_len += 1
        else:
            out.append((run_start, prev, run_len))
            run_start = d
            run_len = 1
        prev = d
    out.append((run_start, prev, run_len))
    return out


def _fmt(v, suffix: str = "°F") -> str:
    if v is None:
        return "—"
    if suffix == "°F":
        return f"{v:.0f}{suffix}"
    return f"{v:.2f}{suffix}"


def _fmt_delta(v, suffix: str = "°F") -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    if suffix == "°F":
        return f"{sign}{v:.0f}{suffix}"
    return f"{sign}{v:.2f}{suffix}"


def _month_story_line(ms: MonthStats, ctx: MonthContext) -> str:
    """One vivid paragraph per month using microseason vernacular."""
    m = MONTH_NAMES[ms.month]
    series = _top(ctx.series, 1)
    calendar = _top(ctx.calendar, 2)
    trig = ctx.triggered

    bananas = trig.get("Find Bananas", 0)
    paralyzing = trig.get("Paralyzing Snow", 0)
    photon = trig.get("Photon Fraud", 0)
    drizzle = trig.get("Welcome Drizzle", 0)
    peak_snow = ctx.peak_snow[1] if ctx.peak_snow else 0
    snow_label = _snowmageddon_label(ms.snow_days, peak_snow, ms.snow)

    # --- month-specific voice ---
    if ms.month == 1:
        vibe = calendar[0] if calendar else "Winter"
        text = (
            f"**{m}** opened under **{vibe}** and **The Long Dark** — "
            f"grey, mid-40s, nothing telegraphing what was coming. "
        )
        if ms.d_precip is not None and ms.d_precip <= -1:
            text += f"Drier than usual ({ms.precip:.1f} in). "
        if photon:
            text += f"**Photon Fraud** days ({photon}) — sun visible, vitamin D not included. "
        return f"- {text.rstrip()}"

    if ms.month == 2:
        if snow_label == "snowmageddon":
            text = (
                f"**{m}** was the year. **The Long Dark** turned into **{snow_label}**: "
                f"**Find Bananas** panic on {bananas} day(s), **Paralyzing Snow** on {paralyzing} — "
                f"buses jackknifing, QFC stripped of bread, milk, and bananas. "
            )
            if ctx.peak_snow:
                text += (
                    f"Peak accumulation **{ctx.peak_snow[1]:.1f}\"** on "
                    f"{humanize_date(ctx.peak_snow[0])}. "
                )
            d_hi = f" ({ms.d_hi:+.0f}°F vs normal)" if ms.d_hi is not None else ""
            text += (
                f"Highs averaged {_fmt(ms.avg_hi)}{d_hi}. "
                f"This was **Winter**, not **Fool's Spring** — any tomato-start optimism died in the snowpack."
            )
            return f"- {text}"
        if snow_label:
            text = (
                f"**{m}** — **{snow_label}** inside **Winter**: "
                f"**Find Bananas** ({bananas}d), **Paralyzing Snow** ({paralyzing}d). "
            )
            if ctx.peak_snow:
                text += f"Peak **{ctx.peak_snow[1]:.1f}\"** on {humanize_date(ctx.peak_snow[0])}. "
            return f"- {text.rstrip()}"
        text = (
            f"**{m}** — **Fool's Spring** teased through **Brightening Wet** "
            f"({_fmt(ms.avg_hi)} avg high); no **Paralyzing Snow** to speak of."
        )
        return f"- {text}"

    if ms.month == 3:
        dom = series[0] if series else "Spring of Deception"
        text = f"**{m}** — **{dom}**"
        if ms.snow_days:
            text += f" with **Second Winter** echoes ({ms.snow_days} trace-snow day(s))"
        if ms.d_precip is not None and ms.d_precip <= -1.5:
            text += f", dry and bright ({ms.precip:.1f} in)"
        if ctx.peak_hi and ctx.peak_hi[1] >= 65:
            text += (
                f", then the **false spring**: **{ctx.peak_hi[1]:.0f}°F** on "
                f"{humanize_date(ctx.peak_hi[0])} — three weeks after the snow siege, "
                f"forgiven for planting something you shouldn't have"
            )
        text += "."
        return f"- {text}"

    if ms.month == 4:
        text = (
            f"**{m}** — **Third Winter** whiplash inside **Flowering Wet**: "
            f"blossoms and cold rain, 60°F afternoons that lied. "
        )
        if ms.d_hi is not None and ms.d_hi <= -3:
            text += f"Cooler than normal ({ms.d_hi:+.0f}°F on highs). "
        return f"- {text.rstrip()}"

    if ms.month == 5:
        text = (
            f"**{m}** — **Actual Spring** finally showed up: "
            f"reliable sun-breaks, {_fmt(ms.avg_hi)} highs, the year exhaled. "
        )
        if ms.d_precip is not None and ms.d_precip <= -0.5:
            text += "Dry enough to believe it."
        return f"- {text.rstrip()}"

    if ms.month == 6:
        text = f"**{m}** — "
        if "Juneuary" in calendar or (ms.d_hi is not None and ms.d_hi <= -2):
            text += (
                "**Juneuary** marine layer — cool, cloudy, drizzle-adjacent "
                f"({_fmt(ms.avg_hi)} avg high"
            )
            if ms.d_hi is not None:
                text += f", {ms.d_hi:+.0f}°F vs normal"
            text += "). "
        else:
            text += f"**Actual Spring** bleeding into summer ({_fmt(ms.avg_hi)} avg high). "
        if ctx.peak_hi and ctx.peak_hi[1] >= 78:
            text += f"A **{ctx.peak_hi[1]:.0f}°F** spike on {humanize_date(ctx.peak_hi[0])} teased **Summer** early."
        return f"- {text.rstrip()}"

    if ms.month in (7, 8):
        label = "**Summer**"
        if trig.get("Smogust") or trig.get("Smoketember"):
            label += " / **Smoketember** smoke"
        elif trig.get("Oppressive Sun") or trig.get("Hell's Front Porch"):
            label += " pushing **Hell's Front Porch**"
        text = f"**{m}** — {label}: "
        if ms.d_hi is not None and ms.d_hi <= -3:
            text += (
                f"cooler than the brochure ({_fmt(ms.avg_hi)} avg, {ms.d_hi:+.0f}°F vs normal) "
                f"but still {ms.days_60}+ days at 60°F+. "
            )
        else:
            text += f"dry, warm, {_fmt(ms.avg_hi)} highs — the reason anyone tolerates the other ten months. "
        if ctx.peak_hi and ctx.peak_hi[1] >= 80:
            text += f"Peak **{ctx.peak_hi[1]:.0f}°F** on {humanize_date(ctx.peak_hi[0])}."
        return f"- {text.rstrip()}"

    if ms.month == 9:
        text = f"**{m}** — **Second Summer** golden light"
        if drizzle:
            text += f" interrupted by **Welcome Drizzle** ({drizzle} day(s)) — rain washing summer out of the air"
        if ms.d_precip is not None and ms.d_precip >= 2:
            text += f", and wet ({ms.precip:.1f} in, {ms.d_precip:+.1f} in vs norm)"
        text += "."
        return f"- {text}"

    if ms.month in (10, 11):
        text = (
            f"**{m}** — **Actual Fall** → **The Grey**: "
            f"sweater weather, leaves, the lid coming down ({_fmt(ms.avg_hi)} avg high). "
        )
        if drizzle:
            text += f"**Welcome Drizzle** on {drizzle} day(s). "
        return f"- {text.rstrip()}"

    if ms.month == 12:
        text = f"**{m}** — back into **Winter** and **The Dark Wet**"
        if ms.d_precip is not None and ms.d_precip >= 1.5:
            text += f", soaking close ({ms.precip:.1f} in)"
        if bananas:
            text += f"; **Find Bananas** on {bananas} day(s) — trace snow, full panic"
        text += "."
        return f"- {text}"

    # fallback
    dom = series[0] if series else (calendar[0] if calendar else "the grey")
    return (
        f"- **{m}** — dominated by **{dom}** "
        f"({_fmt(ms.avg_hi)} / {_fmt(ms.avg_lo)} avg)."
    )


def _ytd_summary_prose(
    stats: YtdStats,
    month_ctx: dict[int, MonthContext],
    classifications: list[sqlite3.Row],
) -> list[str]:
    """Opening paragraphs in microseason vernacular."""
    paragraphs: list[str] = []
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    bananas = sum(1 for c in triggered if c["canonical_name"] == "Find Bananas")
    paralyzing = sum(1 for c in triggered if c["canonical_name"] == "Paralyzing Snow")
    feb = stats.months.get(2)
    mar = stats.months.get(3)

    # Lead paragraph
    if feb and feb.snow_days >= 1:
        peak = month_ctx.get(2, MonthContext(2)).peak_snow
        peak_s = f" (**{peak[1]:.1f}\"** on {humanize_date(peak[0])})" if peak else ""
        feb_label = _snowmageddon_label(feb.snow_days, peak[1] if peak else 0, feb.snow)
        if feb_label == "snowmageddon":
            paragraphs.append(
                f"If you lived through this period, you remember February's **snowmageddon** — "
                f"**Find Bananas** on {bananas} day(s), **Paralyzing Snow** on {paralyzing}{peak_s}. "
                f"The rest of the year was comparatively gentle, but February did the talking."
            )
        elif feb_label in ("snow siege", "banana weather"):
            cold_bit = (
                f"{feb.d_hi:+.0f}°F on highs" if feb.d_hi is not None else "well below normal"
            )
            paragraphs.append(
                f"**February** was **The Long Dark** in force — cold ({cold_bit}), "
                f"**Find Bananas** on {bananas} day(s) over trace snow{peak_s}. "
                f"Not a full **snowmageddon**, but **Paralyzing Snow** fired {paralyzing} day(s) "
                f"and the city acted like it was the end times."
            )
    elif stats.freeze_days <= 6:
        paragraphs.append(
            "This was a **mild winter** year — **The Long Dark** without many hard freezes, "
            "**Fool's Spring** teases that almost convinced you, and no real **Paralyzing Snow**."
        )
    else:
        paragraphs.append(
            f"A mixed **Winter** year — {stats.freeze_days} sub-freezing nights, "
            f"**The Dark Wet** doing its job."
        )

    # Spring arc
    series_days = Counter(
        c["canonical_name"] for c in classifications
        if c["tier"] == "primary" and c["category"] == "series"
    )
    spring_arc = ["Fool's Spring", "Second Winter", "Spring of Deception",
                  "Third Winter", "Actual Spring"]
    fired = [s for s in spring_arc if series_days.get(s, 0) > 0]
    if fired:
        arc = arc_line(fired)
        feb_peak = month_ctx.get(2, MonthContext(2)).peak_snow
        feb_was_snow = _snowmageddon_label(
            feb.snow_days if feb else 0,
            feb_peak[1] if feb_peak else 0,
            feb.snow if feb else 0,
        ) == "snowmageddon" if feb else False
        if mar and mar.d_precip is not None and mar.d_precip <= -1 and feb_was_snow:
            paragraphs.append(
                f"The spring **lies** ran in order: {arc}. "
                f"March's **Spring of Deception** hit especially hard — warmth after **snowmageddon**, "
                f"dry enough to feel like absolution."
            )
        elif mar and mar.d_precip is not None and mar.d_precip <= -1 and feb and feb.snow_days >= 1:
            paragraphs.append(
                f"The spring **lies** ran in order: {arc}. "
                f"March's **Spring of Deception** offered warmth after a punishing **Winter** — "
                f"dry enough to feel like absolution."
            )
        elif len(fired) >= 3:
            paragraphs.append(
                f"Seattle's recursive spring played out: {arc} — "
                f"each fake-out more convincing than the last until **Actual Spring** stuck."
            )

    # Summer / fall note
    summer_cool = sum(
        1 for m in (6, 7, 8)
        if (sm := stats.months.get(m)) and sm.d_hi is not None and sm.d_hi <= -2
    )
    if summer_cool >= 2:
        paragraphs.append(
            f"**Summer** arrived but kept its handbrake on — cooler than normal June through August, "
            f"no **Hell's Front Porch**, {stats.days_70} days still kissed 70°F+. "
            f"**Welcome Drizzle** eventually ended the dry spell."
        )
    elif stats.days_80 >= 8:
        paragraphs.append(
            f"**Summer** brought the heat — {stats.days_80} days at 80°F+, "
            f"**Oppressive Sun** territory even if the classifier didn't always tag it."
        )

    return paragraphs


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def render_header(city: sqlite3.Row, start: str, end: str, total_days: int) -> str:
    return (
        f"# 🌲 {city['name']} — YTD Microseasons Report\n\n"
        f"**Generated:** {date.today().isoformat()}  \n"
        f"**Period:** {start} → {end} ({total_days} days)  \n"
        f"**Weather:** Open-Meteo (ERA5 archive + forecast)  \n"
        f"**Location:** {city['latitude']:.4f}°N, {city['longitude']:.4f}°W  \n"
        f"**Normals:** NOAA NCEI 1991–2020 (city config)\n"
    )


def render_ytd_summary(
    stats: YtdStats,
    classifications: list[sqlite3.Row],
    observations: list[sqlite3.Row],
    month_ctx: dict[int, MonthContext],
) -> str:
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    by_tier = defaultdict(set)
    for c in classifications:
        by_tier[c["tier"]].add(c["canonical_name"])

    lines = [section_heading("YTD Summary"), ""]
    for para in _ytd_summary_prose(stats, month_ctx, classifications):
        lines.append(para)
        lines.append("")

    # Triggered highlights in vernacular
    highlights: list[str] = []
    if by_tier["triggered"]:
        if "Find Bananas" in by_tier["triggered"]:
            n = sum(1 for c in triggered if c["canonical_name"] == "Find Bananas")
            highlights.append(f"{tag('Find Bananas')} ({n} day(s) — the QFC banana run)")
        if "Paralyzing Snow" in by_tier["triggered"]:
            n = sum(1 for c in triggered if c["canonical_name"] == "Paralyzing Snow")
            highlights.append(f"{tag('Paralyzing Snow')} ({n} day(s) — hills abandoned)")
        if "Photon Fraud" in by_tier["triggered"]:
            n = sum(1 for c in triggered if c["canonical_name"] == "Photon Fraud")
            highlights.append(f"{tag('Photon Fraud')} ({n} day(s) — useless sun)")
        if "Welcome Drizzle" in by_tier["triggered"]:
            n = sum(1 for c in triggered if c["canonical_name"] == "Welcome Drizzle")
            highlights.append(f"{tag('Welcome Drizzle')} ({n} day(s) — summer's curtain call)")
        if "Praise the Sun" in by_tier["triggered"]:
            highlights.append(
                f"{tag('Praise the Sun')} (first real sun after {tag('The Long Dark')})"
            )
        if "Glorious Sun" in by_tier["triggered"]:
            highlights.append(f"{tag('Glorious Sun')} (warm enough to feel it)")
        for smoke in ("Smogust", "Smoketember", "Choking Smoke"):
            if smoke in by_tier["triggered"]:
                highlights.append(f"{tag(smoke)} (wildfire smoke season)")

    if highlights:
        lines.append("⚡ **Triggered microseasons that fired:** " + "; ".join(highlights) + ".")
        lines.append("")

    series_days = Counter(
        c["canonical_name"] for c in classifications
        if c["tier"] == "primary" and c["category"] == "series"
    )
    spring_arc = ["Fool's Spring", "Second Winter", "Spring of Deception",
                  "Third Winter", "Actual Spring"]
    fired = [s for s in spring_arc if series_days.get(s, 0) > 0]
    if fired:
        lines.append(f"🔁 **Spring series arc:** {arc_line(fired)}.")
        lines.append("")

    return emojify("\n".join(lines))


def render_the_numbers(stats: YtdStats) -> str:
    d_precip = stats.total_precip - stats.norm_precip_sum if stats.norm_precip_sum else None
    coldest = stats.coldest
    hottest = stats.hottest
    def stat_row(label: str, observed: str, delta: str, notes: str = "") -> str:
        key = next((k for k in STAT_ROW_EMOJI if label.startswith(k)), label)
        emoji = STAT_ROW_EMOJI.get(key, "")
        return f"| {emoji} {label} | {observed} | {delta} | {notes} |"

    lines = [
        section_heading("The numbers"),
        "",
        "| | Observed | vs Normal | Notes |",
        "| --- | ---: | ---: | --- |",
        stat_row(
            "Total precip",
            f"**{stats.total_precip:.1f} in**",
            _fmt_delta(d_precip, " in") if d_precip is not None else "—",
        ),
        stat_row(
            "Total snowfall (ERA5)",
            f"**{stats.total_snow:.1f} in**",
            "—",
            "grid-cell estimate",
        ),
        stat_row("Days low &lt; 32°F", f"**{stats.freeze_days}**", "—"),
        stat_row("Days high ≥ 60°F", f"**{stats.days_60}**", "—"),
        stat_row("Days high ≥ 70°F", f"**{stats.days_70}**", "—"),
        stat_row(
            "Coldest low",
            f"**{_fmt(coldest[1]) if coldest else '—'}**",
            "—",
            humanize_date(coldest[0]) if coldest else "",
        ),
        stat_row(
            "Hottest high",
            f"**{_fmt(hottest[1]) if hottest else '—'}**",
            "—",
            humanize_date(hottest[0]) if hottest else "",
        ),
        "",
    ]
    return "\n".join(lines)


def render_monthly_story(
    stats: YtdStats, month_ctx: dict[int, MonthContext]
) -> str:
    lines = [
        section_heading("Monthly story"),
        "",
        "_📖 Each month in the microseason vernacular — the names locals actually use._",
        "",
    ]
    for m in sorted(stats.months):
        ctx = month_ctx.get(m, MonthContext(month=m))
        lines.append(emojify(_month_story_line(stats.months[m], ctx)))
    lines.append("")
    return "\n".join(lines)


def _series_on_day(classifications: list[sqlite3.Row], d: str) -> list[str]:
    return [
        c["canonical_name"] for c in classifications
        if c["d"] == d and c["tier"] == "primary" and c["category"] == "series"
    ]


def render_season_timeline(
    observations: list[sqlite3.Row],
    classifications: list[sqlite3.Row],
) -> str:
    if not observations:
        return ""
    obs_by_date = {o["observed_date"]: o for o in observations}
    start = date.fromisoformat(observations[0]["observed_date"])
    end = date.fromisoformat(observations[-1]["observed_date"])

    lines = [
        section_heading("Season timeline"),
        "",
        "_🗺️ Biweekly chapters in microseason vernacular. Triggered events "
        f"({tag('Find Bananas')}, {tag('Paralyzing Snow')}, {tag('Welcome Drizzle')}, etc.) "
        "are the signal-driven moments that punctuate the calendar._",
        "",
    ]
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=BIWEEKLY_DAYS - 1), end)
        days = [
            obs_by_date[d.isoformat()]
            for d in (cur + timedelta(days=i) for i in range((chunk_end - cur).days + 1))
            if d.isoformat() in obs_by_date
        ]
        if not days:
            cur = chunk_end + timedelta(days=1)
            continue

        avg_hi = sum(d["temp_high_f"] for d in days) / len(days)
        precip = sum(d["precip_in"] or 0 for d in days)
        hi_min = min(d["temp_high_f"] for d in days)
        hi_max = max(d["temp_high_f"] for d in days)
        snow_days = sum(1 for d in days if (d["snow_in"] or 0) >= 0.1)

        series_counts: Counter[str] = Counter()
        for d in days:
            for s in _series_on_day(classifications, d["observed_date"]):
                series_counts[s] += 1
        dominant = series_counts.most_common(1)[0][0] if series_counts else "—"

        triggered = [
            c for c in classifications
            if c["tier"] == "triggered"
            and cur.isoformat() <= c["d"] <= chunk_end.isoformat()
            and c["canonical_name"] not in ("Photon Fraud",)
        ]
        tr_bits = []
        seen: set[tuple[str, str]] = set()
        for c in triggered:
            key = (c["d"], c["canonical_name"])
            if key in seen:
                continue
            seen.add(key)
            e = MS_EMOJI.get(c["canonical_name"], "•")
            tr_bits.append(f"{c['d'][5:]} {e} {c['display_name']}")
        tr_line = ", ".join(tr_bits[:6])
        if len(tr_bits) > 6:
            tr_line += f", +{len(tr_bits) - 6} more"

        peak_snow = max((d["snow_in"] or 0 for d in days), default=0)
        triggered_names = {c["canonical_name"] for c in triggered}
        chapter = _chunk_title(dominant, snow_days, peak_snow, triggered_names)
        lines.append(emojify(
            f"### {humanize_span(cur.isoformat(), chunk_end.isoformat())} · {chapter}"
        ))
        lines.append("")

        comment = _chunk_commentary(
            days, dominant, snow_days, precip, avg_hi, triggered_names,
        )
        if comment:
            lines.append(emojify(comment))
            lines.append("")

        weather = (
            f"🌡️ **Weather:** ~{avg_hi:.0f}°F avg high ({hi_min:.0f}–{hi_max:.0f}), "
            f"🌧️ {precip:.1f} in precip"
        )
        if snow_days:
            weather += f", ❄️ **{snow_days} snow day(s)**"
        lines.append(weather + ".")
        if tr_line:
            lines.append(f"⚡ **Triggered:** {emojify(tr_line)}.")
        lines.append("")
        lines.append("---")
        lines.append("")

        cur = chunk_end + timedelta(days=1)

    return "\n".join(lines)


def _chunk_title(
    dominant: str, snow_days: int, peak_snow: float, triggered_names: set[str],
) -> str:
    dom = tag(dominant) if dominant != "—" else dominant
    if peak_snow >= 4 or "Paralyzing Snow" in triggered_names:
        return f"**The Snow Siege** · {dom}"
    if peak_snow >= 1.5 or "Find Bananas" in triggered_names:
        return f"**Banana Weather** · {dom}"
    if dominant == "Fool's Spring":
        return f"**Fool's Spring** (the first lie)"
    if dominant == "Spring of Deception":
        return "**Spring of Deception**"
    if dominant == "Third Winter":
        return "**Third Winter** (the insult)"
    if dominant == "Actual Spring":
        return "**Actual Spring** (the real one)"
    return dom


def _chunk_commentary(
    days: list[sqlite3.Row], dominant: str, snow_days: int,
    precip: float, avg_hi: float, triggered_names: set[str],
) -> str:
    peak = max(days, key=lambda d: d["snow_in"] or 0)
    sn = peak["snow_in"] or 0
    if sn >= 1.5 or "Paralyzing Snow" in triggered_names:
        label = "snowmageddon" if sn >= 4 else "snow siege"
        return (
            f"You remember this week. **{label}** — **Find Bananas** emptied the produce aisle, "
            f"**Paralyzing Snow** stranded the hill neighborhoods. "
            f"Peak **{sn:.1f}\"** on {humanize_date(peak['observed_date'])}; "
            f"highs stuck near {peak['temp_high_f']:.0f}°F. Capitol Hill became a parking lot."
        )
    if sn >= 0.1 and snow_days >= 1 and avg_hi < 50:
        return (
            f"**Second Winter** echo — trace snow ({sn:.1f}\" on "
            f"{humanize_date(peak['observed_date'])}). Not **snowmageddon**, "
            f"just enough to keep you honest."
        )
    if "Welcome Drizzle" in triggered_names:
        return (
            "**Welcome Drizzle** — the first real rain after summer's dry spell. "
            "Petrichor, smoke clearing, everyone pretending they missed it."
        )
    if dominant == "Fool's Spring" and avg_hi >= 50:
        return (
            "**Fool's Spring** — shorts on Capitol Hill, tomato starts purchased, "
            "Second Winter loading in the background."
        )
    if dominant == "Spring of Deception" and avg_hi >= 55:
        return (
            "**Spring of Deception** — warm enough to uncover patio furniture, "
            "cold enough to regret it. Blossoms + betrayal."
        )
    if dominant == "Third Winter":
        return (
            "**Third Winter** — the final insult after the spring fake-outs. "
            "Flowering trees, hail, maybe snow. Classic Seattle whiplash."
        )
    if dominant == "Actual Spring" and avg_hi >= 62:
        return "**Actual Spring** — brief, real, jacket-optional evenings. It stuck."
    if precip >= 3:
        return (
            "**Molding Wet** / **Convergence Zones** energy — relentless soak, "
            "five miles south it's dry."
        )
    if dominant == "Winter" and avg_hi < 45:
        return "**The Long Dark** — sunset at 4:20, airborne dampness, low-grade despair."
    if dominant == "Summer" and avg_hi >= 70:
        return "**Summer** — 75°F, no humidity, the ten months of grey earn their keep."
    if dominant == "Second Summer":
        return "**Second Summer** — arguably the best weather of the year."
    if dominant == "Actual Fall":
        return "**Actual Fall** — crisp, leaves, **The Grey** loading."
    return ""


def render_series_progression(classifications: list[sqlite3.Row]) -> str:
    sequenced: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for c in classifications:
        if c["tier"] != "primary" or not c["series_key"]:
            continue
        sequenced[c["series_key"]].append((c["d"], c["display_name"]))

    if not sequenced:
        return ""

    series_emoji = {"winter": "❄️", "spring": "🌷", "summer": "☀️", "fall": "🍂"}
    lines = [section_heading("Series progression"), ""]
    for series_key in ("winter", "spring", "summer", "fall"):
        entries = sequenced.get(series_key, [])
        if not entries:
            continue
        e = series_emoji.get(series_key, "")
        lines.append(f"### {e} {series_key.title()} series")
        lines.append("")
        per_concept: dict[str, list[str]] = defaultdict(list)
        order: list[str] = []
        for d, name in entries:
            if name not in per_concept:
                order.append(name)
            per_concept[name].append(d)
        steps: list[tuple[str, str, str, int]] = []
        for name in order:
            for first, last, n in contiguous_spans(sorted(set(per_concept[name]))):
                steps.append((first, last, name, n))
        steps.sort(key=lambda s: s[0])
        for first, last, name, n in steps:
            lines.append(
                f"- **{humanize_span(first, last)}** ({n}d) — {tag(name)}"
            )
        lines.append("")
    return emojify("\n".join(lines))


def render_triggered_events(classifications: list[sqlite3.Row]) -> str:
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    if not triggered:
        return f"{section_heading('Triggered events')}\n\n_None in this period._\n"
    lines = [
        section_heading("Triggered events"),
        "",
        "| Date | Event | Reason |",
        "| --- | --- | --- |",
    ]
    for c in triggered:
        reason = (c["reason"] or "").replace("|", "\\|")
        lines.append(f"| {c['d']} | {tag(c['display_name'])} | {reason} |")
    return "\n".join(lines) + "\n"


def render_notable_days(observations: list[sqlite3.Row]) -> str:
    if not observations:
        return ""
    with_temps = [o for o in observations if o["temp_high_f"] is not None]
    with_precip = [o for o in observations if o["precip_in"] and o["precip_in"] > 0]
    lines = [section_heading("Notable days"), ""]

    def block(title: str, rows: list[sqlite3.Row], fmt) -> None:
        if not rows:
            return
        lines.append(f"### {title}")
        lines.append("")
        for o in rows[:TOP_N]:
            lines.append(f"- {o['observed_date']}: {fmt(o)}")
        lines.append("")

    block("🔥 Hottest highs", sorted(with_temps, key=lambda o: o["temp_high_f"], reverse=True),
          lambda o: f"**{o['temp_high_f']:.0f}°F** high (low {o['temp_low_f']:.0f}°F)")
    block("🧊 Coldest lows", sorted(with_temps, key=lambda o: o["temp_low_f"]),
          lambda o: f"**{o['temp_low_f']:.0f}°F** low (high {o['temp_high_f']:.0f}°F)")
    block("🌧️ Wettest days", sorted(with_precip, key=lambda o: o["precip_in"], reverse=True),
          lambda o: f"**{o['precip_in']:.2f}\"** precip"
          + (f", ☁️ {o['cloud_cover_mean_pct']:.0f}% cloud"
             if o["cloud_cover_mean_pct"] is not None else ""))
    return "\n".join(lines)


def render_method_notes(total_days: int) -> str:
    return (
        f"{section_heading('Method')}\n\n"
        "- Report reads cached observations from `db/microseasons.db` (0 API calls).\n"
        f"- Backfilling {total_days} days costs **2 Open-Meteo calls per city** "
        "(weather + air-quality). Re-fetch recent weeks before publishing — "
        "forecast-era rows drift.\n"
        "- Verify against live Open-Meteo before trusting degree-level values "
        "(see **j-report-review** skill).\n"
        "- ERA5 grid-cell data ≠ your block; north Seattle snow can differ from downtown.\n"
        "- Classification: `scripts/classify.py` (primary / secondary / triggered).\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", required=True, help="city slug, e.g. seattle or seattle_neighborhood")
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--from", dest="start", help="override start date (YYYY-MM-DD)")
    p.add_argument("--through", dest="end", help="override end date (YYYY-MM-DD)")
    p.add_argument("--out", help="output path (default: reports/<city>_<year>_ytd.md)")
    p.add_argument("--db", default=str(DB_PATH))
    args = p.parse_args()

    today = date.today()
    start = args.start or f"{args.year}-01-01"
    end = args.end or min(today.isoformat(), f"{args.year}-12-31")
    total_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1

    out_path = Path(args.out or ROOT / "reports" / f"{args.city}_{args.year}_ytd.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = open_db(Path(args.db))
    city = get_city(conn, args.city)
    observations = get_observations(conn, city["id"], start, end)
    classifications = get_classifications(conn, city["id"], start, end)
    normals = get_normals(conn, city["id"])

    if not observations:
        raise SystemExit(
            f"No observations for {args.city} in [{start}, {end}]. "
            f"Run: uv run scripts/fetch_weather.py --city {args.city} "
            f"--start {start} --end {end}"
        )

    stats = compute_stats(observations, normals, classifications)
    month_ctx = build_month_contexts(observations, classifications)

    sections = [
        render_header(city, start, end, total_days),
        render_ytd_summary(stats, classifications, observations, month_ctx),
        render_the_numbers(stats),
        render_monthly_story(stats, month_ctx),
        render_season_timeline(observations, classifications),
        render_series_progression(classifications),
        render_triggered_events(classifications),
        render_notable_days(observations),
        render_method_notes(total_days),
    ]
    body = emojify("\n".join(s for s in sections if s).rstrip() + "\n")
    out_path.write_text(body)
    print(f"Wrote {out_path} ({len(body):,} bytes, {body.count(chr(10))} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
