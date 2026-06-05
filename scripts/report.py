"""Generate a markdown year-to-date microseasons report for a city.

Pulls everything from the local SQLite DB (no API calls). Run
`scripts/fetch_weather.py --skip-existing` first to top up the
observations.

Example:
    uv run scripts/report.py --city seattle
    uv run scripts/report.py --city seattle --through 2026-06-05
    uv run scripts/report.py --city seattle --out reports/custom.md
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "microseasons.db"

# How many "best" weather days to call out under Notable Days.
TOP_N = 5

CATEGORY_LABEL = {
    "calendar": "calendar",
    "series": "series",
    "triggered_event": "triggered",
    "constant": "constant",
    "climate_disaster": "disaster",
    "sun_phenomenon": "sun",
}


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
# Aggregation helpers
# ---------------------------------------------------------------------------

def contiguous_spans(dates: list[str]) -> list[tuple[str, str, int]]:
    """Collapse a sorted list of YYYY-MM-DD into (first, last, day_count) runs."""
    if not dates:
        return []
    out: list[tuple[str, str, int]] = []
    run_start = prev = dates[0]
    run_len = 1
    for d in dates[1:]:
        prev_dt = date.fromisoformat(prev)
        cur_dt = date.fromisoformat(d)
        if (cur_dt - prev_dt).days == 1:
            run_len += 1
        else:
            out.append((run_start, prev, run_len))
            run_start = d
            run_len = 1
        prev = d
    out.append((run_start, prev, run_len))
    return out


def humanize_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d")


def humanize_span(first: str, last: str) -> str:
    if first == last:
        return humanize_date(first)
    return f"{humanize_date(first)} – {humanize_date(last)}"


# ---------------------------------------------------------------------------
# Section builders. Each returns a string of markdown.
# ---------------------------------------------------------------------------

def render_header(city: sqlite3.Row, start: str, end: str, total_days: int) -> str:
    today = date.today().isoformat()
    return (
        f"# {city['name']} Microseasons — YTD Report\n\n"
        f"**Generated:** {today}  \n"
        f"**Period:** {start} → {end} ({total_days} days)  \n"
        f"**Data source:** Open-Meteo (ERA5 archive + forecast)  \n"
        f"**DB:** `db/microseasons.db`\n"
    )


def render_snapshot(
    observations: list[sqlite3.Row], classifications: list[sqlite3.Row]
) -> str:
    n_days = len(observations)
    n_aberration = sum(1 for o in observations if o["is_aberration"])
    by_tier_concepts: dict[str, set[str]] = defaultdict(set)
    by_tier_days: dict[str, set[str]] = defaultdict(set)
    for c in classifications:
        by_tier_concepts[c["tier"]].add(c["canonical_name"])
        by_tier_days[c["tier"]].add(c["d"])
    classified_days = (
        by_tier_days["primary"] | by_tier_days["secondary"] | by_tier_days["triggered"]
    )
    return (
        "## Snapshot\n\n"
        f"- Observed days: **{n_days}**\n"
        f"- Days with a classification: **{len(classified_days)}** "
        f"({len(classified_days) * 100 // max(n_days, 1)}%)\n"
        f"- Aberrations flagged: **{n_aberration}**\n"
        f"- Distinct primary microseasons: **{len(by_tier_concepts['primary'])}**\n"
        f"- Distinct secondary (constants): **{len(by_tier_concepts['secondary'])}**\n"
        f"- Distinct triggered events: **{len(by_tier_concepts['triggered'])}**\n"
    )


def render_timeline(classifications: list[sqlite3.Row], tier: str) -> str:
    """Span-style timeline grouped by microseason."""
    by_concept: dict[str, dict] = {}
    for c in classifications:
        if c["tier"] != tier:
            continue
        key = c["display_name"]
        entry = by_concept.setdefault(
            key,
            {
                "display_name": c["display_name"],
                "category": c["category"],
                "series_label": c["series_label"],
                "dates": [],
            },
        )
        entry["dates"].append(c["d"])

    if not by_concept:
        return ""

    rows = []
    for key, e in by_concept.items():
        spans = contiguous_spans(sorted(set(e["dates"])))
        total = sum(s[2] for s in spans)
        span_str = ", ".join(humanize_span(s[0], s[1]) for s in spans)
        rows.append(
            {
                "name": e["display_name"],
                "category": CATEGORY_LABEL.get(e["category"], e["category"]),
                "label": e["series_label"] or "—",
                "days": total,
                "spans": span_str,
                "first": min(e["dates"]),
            }
        )
    rows.sort(key=lambda r: (r["first"], -r["days"]))

    out = [
        f"## {tier.capitalize()} Microseasons — Timeline",
        "",
        "| Microseason | Series Slot | Category | Days | Span(s) |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for r in rows:
        out.append(
            f"| {r['name']} | {r['label']} | {r['category']} "
            f"| {r['days']} | {r['spans']} |"
        )
    return "\n".join(out) + "\n"


def render_series_progression(classifications: list[sqlite3.Row]) -> str:
    """Chronological walk of the winter→spring→summer arc by series_label."""
    sequenced: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for c in classifications:
        if c["tier"] != "primary" or not c["series_key"]:
            continue
        sequenced[c["series_key"]].append((c["d"], c["display_name"], c["series_label"] or ""))

    if not sequenced:
        return ""

    out = ["## Series Progression\n"]
    for series_key in ("winter", "spring", "summer", "fall"):
        entries = sequenced.get(series_key, [])
        if not entries:
            continue
        out.append(f"### {series_key.title()} series\n")
        per_concept: dict[str, list[str]] = defaultdict(list)
        order: list[str] = []
        for d, name, _label in entries:
            if name not in per_concept:
                order.append(name)
            per_concept[name].append(d)
        steps: list[tuple[str, str, str, int]] = []
        for name in order:
            spans = contiguous_spans(sorted(set(per_concept[name])))
            for first, last, n in spans:
                steps.append((first, last, name, n))
        steps.sort(key=lambda s: s[0])
        for first, last, name, n in steps:
            out.append(f"- **{humanize_span(first, last)}** ({n}d) — {name}")
        out.append("")
    return "\n".join(out)


def render_triggered_events(classifications: list[sqlite3.Row]) -> str:
    triggered = [c for c in classifications if c["tier"] == "triggered"]
    if not triggered:
        return "## Triggered Events\n\n_No triggered events fired in this period._\n"
    out = [
        "## Triggered Events",
        "",
        "| Date | Event | Reason |",
        "| --- | --- | --- |",
    ]
    for c in triggered:
        reason = (c["reason"] or "").replace("|", "\\|")
        out.append(f"| {c['d']} | {c['display_name']} | {reason} |")
    return "\n".join(out) + "\n"


def render_aberrations(observations: list[sqlite3.Row]) -> str:
    abers = [o for o in observations if o["is_aberration"]]
    if not abers:
        return (
            "## Aberrations\n\n"
            "_No statistical aberrations recorded. This means no day in the "
            "period had a temperature anomaly above the city's aberration "
            "threshold, and no out-of-season smoke/snow signals fired._\n"
        )
    out = [
        "## Aberrations",
        "",
        "Days whose conditions were far enough from the local norm that they were"
        " flagged as one-off outliers. They are kept in observations but excluded"
        " from new-microseason proposals and downgraded in primary-match confidence.",
        "",
        "| Date | Hi/Lo | Reason |",
        "| --- | --- | --- |",
    ]
    for o in abers:
        hi = f"{o['temp_high_f']:.0f}" if o["temp_high_f"] is not None else "—"
        lo = f"{o['temp_low_f']:.0f}" if o["temp_low_f"] is not None else "—"
        reason = (o["aberration_reason"] or "").replace("|", "\\|")
        out.append(f"| {o['observed_date']} | {hi}/{lo}°F | {reason} |")
    return "\n".join(out) + "\n"


def render_monthly_summary(
    observations: list[sqlite3.Row], normals: dict[int, sqlite3.Row]
) -> str:
    by_month: dict[int, dict] = defaultdict(
        lambda: {"highs": [], "lows": [], "precip": 0.0, "days": 0}
    )
    for o in observations:
        m = int(o["observed_date"][5:7])
        if o["temp_high_f"] is not None:
            by_month[m]["highs"].append(o["temp_high_f"])
        if o["temp_low_f"] is not None:
            by_month[m]["lows"].append(o["temp_low_f"])
        if o["precip_in"] is not None:
            by_month[m]["precip"] += o["precip_in"]
        by_month[m]["days"] += 1

    if not by_month:
        return ""
    out = [
        "## Monthly Summary vs Normals",
        "",
        "| Month | Days | Avg High | Normal High | Δ | Avg Low | Normal Low | Δ |"
        " Precip | Normal Precip | Δ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    month_names = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    for m in sorted(by_month):
        d = by_month[m]
        avg_hi = sum(d["highs"]) / len(d["highs"]) if d["highs"] else None
        avg_lo = sum(d["lows"]) / len(d["lows"]) if d["lows"] else None
        n = normals.get(m)
        nh = n["temp_max_avg_f"] if n else None
        nl = n["temp_min_avg_f"] if n else None
        np_ = n["precip_total_in"] if n else None
        dh = (avg_hi - nh) if (avg_hi is not None and nh is not None) else None
        dl = (avg_lo - nl) if (avg_lo is not None and nl is not None) else None
        dp = (d["precip"] - np_) if np_ is not None else None
        out.append(
            f"| {month_names[m]} | {d['days']} "
            f"| {_fmt(avg_hi)} | {_fmt(nh)} | {_fmt_delta(dh)} "
            f"| {_fmt(avg_lo)} | {_fmt(nl)} | {_fmt_delta(dl)} "
            f"| {_fmt(d['precip'], suffix=' in')} "
            f"| {_fmt(np_, suffix=' in')} | {_fmt_delta(dp, suffix=' in')} |"
        )
    return "\n".join(out) + "\n"


def render_notable_days(observations: list[sqlite3.Row]) -> str:
    if not observations:
        return ""
    with_temps = [o for o in observations if o["temp_high_f"] is not None]
    with_precip = [o for o in observations
                   if o["precip_in"] is not None and o["precip_in"] > 0]

    out = ["## Notable Days\n"]

    def block(title: str, rows: list[sqlite3.Row], fmt) -> None:
        if not rows:
            return
        out.append(f"### {title}\n")
        for o in rows[:TOP_N]:
            out.append(f"- {o['observed_date']}: {fmt(o)}")
        out.append("")

    hot = sorted(with_temps, key=lambda o: o["temp_high_f"], reverse=True)
    cold = sorted(with_temps, key=lambda o: o["temp_low_f"])
    wet = sorted(with_precip, key=lambda o: o["precip_in"], reverse=True)

    block(
        f"Hottest highs",
        hot,
        lambda o: f"**{o['temp_high_f']:.0f}°F** high (low {o['temp_low_f']:.0f}°F)",
    )
    block(
        f"Coldest lows",
        cold,
        lambda o: f"**{o['temp_low_f']:.0f}°F** low (high {o['temp_high_f']:.0f}°F)",
    )
    block(
        f"Wettest days",
        wet,
        lambda o: f"**{o['precip_in']:.2f}\"** precip"
                  + (f", {o['cloud_cover_mean_pct']:.0f}% cloud"
                     if o['cloud_cover_mean_pct'] is not None else ""),
    )
    return "\n".join(out)


def render_method_notes(start: str, end: str, total_days: int) -> str:
    return (
        "## Method & API Care\n\n"
        f"- This run uses cached observations from the local SQLite DB; "
        f"the report itself makes **0 API calls**.\n"
        f"- Backfilling the {total_days}-day window cost **2 Open-Meteo calls per"
        f" city** (one weather, one air-quality), routed automatically across"
        f" the `archive` (ERA5) and `/forecast` endpoints. Well under the"
        f" free-tier daily limit.\n"
        f"- Re-runs use `fetch_weather.py --skip-existing` so we never re-pull"
        f" dates we already have.\n"
        f"- Classification follows the three-tier model (primary / secondary"
        f" constants / triggered events) defined in `scripts/classify.py`.\n"
        f"- Aberrations are days whose anomaly against the relevant monthly"
        f" climate normal exceeds the threshold in `classify.py`. They are"
        f" preserved as data but excluded from \"propose new microseason\""
        f" output and downgraded in primary-match confidence.\n"
    )


def _fmt(v, suffix: str = "°F") -> str:
    if v is None:
        return "—"
    if suffix in ("°F",):
        return f"{v:.0f}{suffix}"
    return f"{v:.2f}{suffix}"


def _fmt_delta(v, suffix: str = "°F") -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    if suffix in ("°F",):
        return f"{sign}{v:.0f}{suffix}"
    return f"{sign}{v:.2f}{suffix}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", required=True, help="city slug, e.g. seattle")
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

    out_path = Path(
        args.out or ROOT / "reports" / f"{args.city}_{args.year}_ytd.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = open_db(Path(args.db))
    city = get_city(conn, args.city)
    observations = get_observations(conn, city["id"], start, end)
    classifications = get_classifications(conn, city["id"], start, end)
    normals = get_normals(conn, city["id"])

    if not observations:
        raise SystemExit(
            f"No observations found for {args.city} in [{start}, {end}]. "
            f"Run: uv run scripts/fetch_weather.py --city {args.city} "
            f"--start {start} --end {end} --skip-existing"
        )

    sections = [
        render_header(city, start, end, total_days),
        render_snapshot(observations, classifications),
        render_timeline(classifications, "primary"),
        render_series_progression(classifications),
        render_timeline(classifications, "secondary"),
        render_triggered_events(classifications),
        render_aberrations(observations),
        render_monthly_summary(observations, normals),
        render_notable_days(observations),
        render_method_notes(start, end, total_days),
    ]
    body = "\n".join(s for s in sections if s).rstrip() + "\n"
    out_path.write_text(body)
    print(f"Wrote {out_path} ({len(body):,} bytes, {body.count(chr(10))} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
