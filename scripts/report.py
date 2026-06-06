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


def _month_story_line(ms: MonthStats) -> str:
    m = MONTH_NAMES[ms.month]
    parts: list[str] = []
    if ms.d_hi is not None:
        if ms.d_hi <= -5:
            parts.append(f"**cold month** (highs {ms.d_hi:+.0f}°F vs normal)")
        elif ms.d_hi >= 5:
            parts.append(f"**warm month** (highs {ms.d_hi:+.0f}°F)")
        elif abs(ms.d_hi) >= 2:
            parts.append(f"highs {ms.d_hi:+.0f}°F vs normal")
    if ms.d_lo is not None and ms.d_lo >= 2 and (ms.d_hi is None or ms.d_hi < 3):
        parts.append(f"mild nights (+{ms.d_lo:.0f}°F on lows)")
    if ms.d_precip is not None and ms.d_precip >= 2:
        parts.append(f"**very wet** ({ms.precip:.1f} in, {ms.d_precip:+.1f} in vs norm)")
    elif ms.d_precip is not None and ms.d_precip <= -1:
        parts.append(f"dry ({ms.precip:.1f} in)")
    if ms.snow_days >= 3 or ms.snow >= 3:
        parts.append(f"**{ms.snow_days} snow days** ({ms.snow:.1f} in total)")
    elif ms.snow_days >= 1:
        parts.append(f"{ms.snow_days} snow day(s)")
    if ms.freeze_days >= 5:
        parts.append(f"{ms.freeze_days} sub-freezing lows")
    if ms.days < 28 and ms.norm_precip and ms.days < 31:
        parts.append(f"*{ms.days} days in period — compare precip to full-month normal cautiously*")
    if not parts:
        if ms.avg_hi is not None and ms.norm_hi is not None:
            parts.append(f"near-normal (avg high {_fmt(ms.avg_hi)})")
        else:
            parts.append("unremarkable vs normals")
    detail = "; ".join(parts)
    hi_lo = ""
    if ms.avg_hi is not None and ms.avg_lo is not None:
        hi_lo = f" Avg {_fmt(ms.avg_hi)} / {_fmt(ms.avg_lo)}."
    return f"- **{m}** — {detail}.{hi_lo}"


def _ytd_headline(stats: YtdStats, triggered: list[sqlite3.Row]) -> str:
    feb = stats.months.get(2)
    mar = stats.months.get(3)
    bits: list[str] = []

    if feb and feb.d_hi is not None and feb.d_hi <= -5 and feb.snow_days >= 3:
        bits.append("a **real winter** anchored by February snow")
    elif stats.freeze_days <= 6 and feb and feb.d_lo is not None and feb.d_lo >= 2:
        bits.append("a **mild winter** with few hard freezes")
    elif stats.freeze_days >= 15:
        bits.append("a **cold year** with many sub-freezing nights")
    else:
        bits.append("a mixed winter")

    if mar and mar.d_hi is not None and mar.d_hi >= -2 and mar.d_precip is not None and mar.d_precip <= -1:
        if feb and feb.snow_days >= 2:
            bits.append("a **March fake-out** after the snow")
        else:
            bits.append("an early **false spring** in March")
    elif mar and mar.d_precip is not None and mar.d_precip >= 2:
        bits.append("a **soaking March**")

    summer_months = [stats.months.get(m) for m in (6, 7, 8) if m in stats.months]
    cool_summer = sum(1 for sm in summer_months if sm and sm.d_hi is not None and sm.d_hi <= -2)
    if cool_summer >= 2:
        bits.append("a **cooler-than-normal summer**")
    elif stats.days_80 >= 10:
        bits.append("a **hot summer**")
    elif stats.days_70 >= 30:
        bits.append("a solid summer")

    snow_events = [c for c in triggered
                   if c["canonical_name"] in ("Find Bananas", "Paralyzing Snow")]
    if snow_events:
        bits.append(f"**{len(snow_events)} snow-event days** (Find Bananas / Paralyzing Snow)")

    return "This period had " + ", then ".join(bits[:3]) + "."


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def render_header(city: sqlite3.Row, start: str, end: str, total_days: int) -> str:
    return (
        f"# {city['name']} — YTD Microseasons Report\n\n"
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
) -> str:
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    by_tier = defaultdict(set)
    for c in classifications:
        by_tier[c["tier"]].add(c["canonical_name"])

    lines = [
        "## YTD Summary",
        "",
        _ytd_headline(stats, triggered),
        "",
        f"- **{stats.total_days}** observed days; **{stats.primary_days}** with a primary microseason "
        f"({stats.primary_days * 100 // max(stats.total_days, 1)}%). "
        f"Primary labels overlap — multiple per day is normal.",
        f"- **{len(by_tier['triggered'])}** triggered event types fired; "
        f"**{sum(1 for o in observations if o['is_aberration'])}** aberration days.",
        "",
    ]

    # False-spring arc (series slots in order)
    series_days = Counter(
        c["canonical_name"] for c in classifications
        if c["tier"] == "primary" and c["category"] == "series"
    )
    spring_arc = ["Fool's Spring", "Second Winter", "Spring of Deception",
                  "Third Winter", "Actual Spring"]
    fired = [s for s in spring_arc if series_days.get(s, 0) > 0]
    if fired:
        lines.append("**Spring series arc:** " + " → ".join(fired) + ".")
        lines.append("")

    return "\n".join(lines)


def render_the_numbers(stats: YtdStats) -> str:
    d_precip = stats.total_precip - stats.norm_precip_sum if stats.norm_precip_sum else None
    coldest = stats.coldest
    hottest = stats.hottest
    lines = [
        "## The numbers",
        "",
        "| | Observed | vs Normal | Notes |",
        "| --- | ---: | ---: | --- |",
        f"| Total precip | **{stats.total_precip:.1f} in** | "
        f"{_fmt_delta(d_precip, ' in') if d_precip is not None else '—'} | |",
        f"| Total snowfall (ERA5) | **{stats.total_snow:.1f} in** | — | grid-cell estimate |",
        f"| Days low &lt; 32°F | **{stats.freeze_days}** | — | |",
        f"| Days high ≥ 60°F | **{stats.days_60}** | — | |",
        f"| Days high ≥ 70°F | **{stats.days_70}** | — | |",
        f"| Coldest low | **{_fmt(coldest[1]) if coldest else '—'}** | — | "
        f"{humanize_date(coldest[0]) if coldest else ''} |",
        f"| Hottest high | **{_fmt(hottest[1]) if hottest else '—'}** | — | "
        f"{humanize_date(hottest[0]) if hottest else ''} |",
        "",
    ]
    return "\n".join(lines)


def render_monthly_story(stats: YtdStats) -> str:
    lines = ["## Monthly story", ""]
    for m in sorted(stats.months):
        lines.append(_month_story_line(stats.months[m]))
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

    lines = ["## Season timeline", ""]
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
            tr_bits.append(f"{c['d'][5:]} {c['display_name']}")
        tr_line = ", ".join(tr_bits[:6])
        if len(tr_bits) > 6:
            tr_line += f", +{len(tr_bits) - 6} more"

        title = f"### {humanize_span(cur.isoformat(), chunk_end.isoformat())} · {dominant}"
        lines.append(title)
        lines.append("")
        weather = (
            f"**Weather:** ~{avg_hi:.0f}°F avg high ({hi_min:.0f}–{hi_max:.0f}), "
            f"{precip:.1f} in precip"
        )
        if snow_days:
            weather += f", **{snow_days} snow day(s)**"
        lines.append(weather + ".")
        if tr_line:
            lines.append(f"**Triggered:** {tr_line}.")
        lines.append("")

        # Short commentary heuristics
        comment = _chunk_commentary(days, dominant, snow_days, precip, avg_hi)
        if comment:
            lines.append(f"> *{comment}*")
            lines.append("")
        lines.append("---")
        lines.append("")

        cur = chunk_end + timedelta(days=1)

    return "\n".join(lines)


def _chunk_commentary(
    days: list[sqlite3.Row], dominant: str, snow_days: int,
    precip: float, avg_hi: float,
) -> str:
    if snow_days >= 3:
        peak = max(days, key=lambda d: d["snow_in"] or 0)
        return (
            f"Lived experience: snow week — peak {peak['snow_in']:.1f}\" on "
            f"{humanize_date(peak['observed_date'])}. Find Bananas / Paralyzing Snow "
            f"should appear in triggered events above."
        )
    if dominant == "Fool's Spring" and avg_hi >= 50:
        return "Lived experience: early warm tease — false spring territory."
    if dominant == "Spring of Deception" and avg_hi >= 55:
        return "Lived experience: convincing spring that may still reverse."
    if dominant == "Actual Spring" and avg_hi >= 62:
        return "Lived experience: spring finally stuck."
    if precip >= 3:
        return "Lived experience: relentless rain — convergence-zone soak."
    if dominant == "Winter" and avg_hi < 45:
        return "Lived experience: proper winter grey and cold."
    if dominant == "Summer" and avg_hi >= 70:
        return "Lived experience: summer core — dry and warm."
    return ""


def render_series_progression(classifications: list[sqlite3.Row]) -> str:
    sequenced: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for c in classifications:
        if c["tier"] != "primary" or not c["series_key"]:
            continue
        sequenced[c["series_key"]].append((c["d"], c["display_name"]))

    if not sequenced:
        return ""

    lines = ["## Series progression", ""]
    for series_key in ("winter", "spring", "summer", "fall"):
        entries = sequenced.get(series_key, [])
        if not entries:
            continue
        lines.append(f"### {series_key.title()} series")
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
            lines.append(f"- **{humanize_span(first, last)}** ({n}d) — {name}")
        lines.append("")
    return "\n".join(lines)


def render_triggered_events(classifications: list[sqlite3.Row]) -> str:
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    if not triggered:
        return "## Triggered events\n\n_None in this period._\n"
    lines = [
        "## Triggered events",
        "",
        "| Date | Event | Reason |",
        "| --- | --- | --- |",
    ]
    for c in triggered:
        reason = (c["reason"] or "").replace("|", "\\|")
        lines.append(f"| {c['d']} | {c['display_name']} | {reason} |")
    return "\n".join(lines) + "\n"


def render_notable_days(observations: list[sqlite3.Row]) -> str:
    if not observations:
        return ""
    with_temps = [o for o in observations if o["temp_high_f"] is not None]
    with_precip = [o for o in observations if o["precip_in"] and o["precip_in"] > 0]
    lines = ["## Notable days", ""]

    def block(title: str, rows: list[sqlite3.Row], fmt) -> None:
        if not rows:
            return
        lines.append(f"### {title}")
        lines.append("")
        for o in rows[:TOP_N]:
            lines.append(f"- {o['observed_date']}: {fmt(o)}")
        lines.append("")

    block("Hottest highs", sorted(with_temps, key=lambda o: o["temp_high_f"], reverse=True),
          lambda o: f"**{o['temp_high_f']:.0f}°F** high (low {o['temp_low_f']:.0f}°F)")
    block("Coldest lows", sorted(with_temps, key=lambda o: o["temp_low_f"]),
          lambda o: f"**{o['temp_low_f']:.0f}°F** low (high {o['temp_high_f']:.0f}°F)")
    block("Wettest days", sorted(with_precip, key=lambda o: o["precip_in"], reverse=True),
          lambda o: f"**{o['precip_in']:.2f}\"** precip"
          + (f", {o['cloud_cover_mean_pct']:.0f}% cloud"
             if o["cloud_cover_mean_pct"] is not None else ""))
    return "\n".join(lines)


def render_method_notes(total_days: int) -> str:
    return (
        "## Method\n\n"
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

    sections = [
        render_header(city, start, end, total_days),
        render_ytd_summary(stats, classifications, observations),
        render_the_numbers(stats),
        render_monthly_story(stats),
        render_season_timeline(observations, classifications),
        render_series_progression(classifications),
        render_triggered_events(classifications),
        render_notable_days(observations),
        render_method_notes(total_days),
    ]
    body = "\n".join(s for s in sections if s).rstrip() + "\n"
    out_path.write_text(body)
    print(f"Wrote {out_path} ({len(body):,} bytes, {body.count(chr(10))} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
