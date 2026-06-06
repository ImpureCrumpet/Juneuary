"""Generate a combined YTD microseasons report for a city.

The report is a pure CONSUMER of Juneuary's HTTP API: it fetches a classified
date range (`/v1/days`) and climate normals (`/v1/normals`) and renders them
through the city's narrative templates. It never touches the DB or Open-Meteo
directly — the API does the fetching/classifying — which makes this script an
end-to-end test that the contract is rich enough to rebuild the full report.

By default it boots the API in-process against the local catalog DB; point it
at a running server with `--api-url`. Prose lives in
`data/cities/<catalog_slug>.narrative.yaml`; this script computes features
(snow_label, peak_*, avg_hi, ...) and renders them. Voice is data; dispatch +
features are code.

Example:
    uv run scripts/report.py --city seattle --year 2019
    uv run scripts/report.py --city seattle --api-url http://localhost:8787
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sqlite3
import sys
import threading
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "microseasons.db"
CITIES_YAML_DIR = ROOT / "data" / "cities"

sys.path.insert(0, str(ROOT / "src"))
from juneuary.presentation import emoji_map    # noqa: E402
from juneuary.serve import make_handler         # noqa: E402

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

# ---------------------------------------------------------------------------
# Emoji tables
#
# Concept emoji live in data/presentation.yaml (the single source of truth
# shared with the JSON/display layer); MS_EMOJI is loaded from there rather
# than hand-maintained here.
#
# COLLISION POLICY: Several microseasons intentionally share emoji where the
# vibe overlaps (☀️ Summer/Glorious Sun, 🔥 Hell's Front Porch/Smoketember,
# 🌧️ The Dark Wet/Welcome Drizzle, 🌫️ Juneuary/Smogust, 🫠 Molding Wet/
# Oppressive Sun). The collision is intentional — emoji are paired with the
# bolded name via tag(), so the renderer never has to disambiguate them.
#
# TERM_EMOJI / SECTION_EMOJI / STAT_ROW_EMOJI below are report-specific
# (narrative vernacular + document chrome), not concept metadata, so they
# stay local to the report.
# ---------------------------------------------------------------------------
MS_EMOJI: dict[str, str] = emoji_map()

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
    """Prefix known microseason / narrative terms with emoji (idempotent).

    Called once at the end of main(); sub-renderers produce raw text and
    let this normalize the whole document. The negative lookbehind keeps
    multi-pass safe even if a caller emojifies twice.
    """
    for term, emoji in sorted(
        {**MS_EMOJI, **TERM_EMOJI}.items(), key=lambda x: -len(x[0])
    ):
        bare = f"**{term}**"
        marked = f"{emoji} {bare}"
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


# ---------------------------------------------------------------------------
# API client — the report consumes Juneuary's HTTP API, never the DB directly.
# The downstream renderers expect dict rows keyed exactly like the old SQL
# results, so the adapters below reshape the JSON payloads into those rows.
# ---------------------------------------------------------------------------

def _api_get(base: str, path: str) -> dict:
    url = base.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=180) as resp:   # noqa: S310 (localhost)
        return json.loads(resp.read().decode("utf-8"))


def fetch_days(base: str, city: str, start: str, end: str) -> dict:
    q = urllib.parse.urlencode({"city": city, "start": start, "end": end})
    return _api_get(base, f"/v1/days?{q}")


def fetch_normals(base: str, city: str) -> dict:
    q = urllib.parse.urlencode({"city": city})
    return _api_get(base, f"/v1/normals?{q}")


def observations_from_days(payload: dict) -> list[dict]:
    """One observation-row per day. Fields the API doesn't carry (mean temp,
    cloud, sun, air quality) are None; renderers degrade gracefully."""
    rows = []
    for day in payload.get("days", []):
        rows.append({
            "observed_date": day["date"],
            "temp_high_f": day.get("temp_high_f"),
            "temp_low_f": day.get("temp_low_f"),
            "temp_mean_f": None,
            "precip_in": day.get("precip_in"),
            "snow_in": day.get("snow_in"),
            "cloud_cover_mean_pct": None,
            "sun_hours": None,
            "smoke": None,
            "pm25_ug_m3": None,
            "aqi_us": None,
            "solar_elevation_max_deg": None,
            "is_aberration": day.get("is_aberration", False),
            "aberration_reason": day.get("aberration_reason", ""),
        })
    return rows


def classifications_from_days(payload: dict) -> list[dict]:
    """Flatten each day's primary/secondary/triggered views into the
    classification rows the renderers consume."""
    rows = []
    for day in payload.get("days", []):
        for tier in ("primary", "secondary", "triggered"):
            for v in day.get(tier, []):
                rows.append({
                    "d": day["date"],
                    "tier": v["tier"],
                    "confidence": v["confidence"],
                    "reason": v["reason"],
                    "display_name": v["display_name"],
                    "canonical_name": v["canonical_name"],
                    "category": v["category"],
                    "series_key": v.get("series_key"),
                    "series_order": v.get("series_order"),
                    "series_label": v.get("series_label"),
                    "is_aberration": day.get("is_aberration", False),
                })
    return rows


def normals_from_payload(payload: dict) -> dict[int, dict]:
    """{month:int -> normals row}, mirroring the old get_normals shape."""
    return {int(month): {"month": int(month), **vals}
            for month, vals in (payload.get("normals") or {}).items()}


@contextlib.contextmanager
def ephemeral_api(db_path: str):
    """Boot the JSON API in-process on an ephemeral port for the duration of a
    report run, so the report dogfoods the real HTTP contract."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------------------------------------------------------------------------
# Narrative loader + template engine
# ---------------------------------------------------------------------------

@dataclass
class Narrative:
    """Templates loaded from the catalog city's YAML. Empty fields mean the
    city has no opinion; renderers fall back to a generic shape."""
    clauses:       dict[str, dict]      = field(default_factory=dict)
    ytd_lead:      dict                 = field(default_factory=dict)
    ytd_spring_arc:dict                 = field(default_factory=dict)
    ytd_summer:    dict                 = field(default_factory=dict)
    months:        dict[str, dict]      = field(default_factory=dict)
    chunk_titles:  dict                 = field(default_factory=dict)
    chunks:        dict                 = field(default_factory=dict)
    summer_labels: dict[str, str]       = field(default_factory=dict)


def load_narrative(catalog_slug: str) -> Narrative:
    path = CITIES_YAML_DIR / f"{catalog_slug}.narrative.yaml"
    if not path.exists():
        return Narrative()
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    n = doc.get("narrative") or {}
    return Narrative(
        clauses=        n.get("clauses")        or {},
        ytd_lead=       n.get("ytd_lead")       or {},
        ytd_spring_arc= n.get("ytd_spring_arc") or {},
        ytd_summer=     n.get("ytd_summer")     or {},
        months=         n.get("months")         or {},
        chunk_titles=   n.get("chunk_titles")   or {},
        chunks=         n.get("chunks")         or {},
        summer_labels=  n.get("summer_labels")  or {},
    )


# ---- when-clause evaluator ----

_OP_SUFFIXES = ("_eq", "_ne", "_gt", "_gte", "_lt", "_lte",
                "_in", "_not_in", "_any", "_blank")

_OPS = {
    "eq":     lambda a, b: a == b,
    "ne":     lambda a, b: a != b,
    "gt":     lambda a, b: a is not None and a > b,
    "gte":    lambda a, b: a is not None and a >= b,
    "lt":     lambda a, b: a is not None and a < b,
    "lte":    lambda a, b: a is not None and a <= b,
    "in":     lambda a, b: a in (b or []),
    "not_in": lambda a, b: a not in (b or []),
    "any":    lambda a, b: bool(a) == bool(b),
    "blank":  lambda a, b: (not a) == bool(b),
}


def _split_op(key: str) -> tuple[str, str]:
    for suffix in _OP_SUFFIXES:
        if key.endswith(suffix):
            return key[:-len(suffix)], suffix[1:]
    return key, "eq"


def _eval_when(when: dict | None, features: dict) -> bool:
    if not when:
        return True
    for key, expected in when.items():
        feature_name, op = _split_op(key)
        actual = features.get(feature_name)
        if not _OPS[op](actual, expected):
            return False
    return True


def _render_fragment(frag: dict, features: dict, clauses: dict[str, dict]) -> str | None:
    """Render one fragment. Returns None if its `when` (or referenced
    clause's `when`) doesn't match — caller decides what to do."""
    if not _eval_when(frag.get("when"), features):
        return None
    ref = frag.get("ref")
    if ref:
        cl = clauses.get(ref)
        if not cl or not _eval_when(cl.get("when"), features):
            return None
        return cl.get("template", "").format(**features)
    return frag.get("template", "").format(**features)


def render_section(spec: dict | None, features: dict, clauses: dict[str, dict]) -> str:
    """Render a narrative section (months/chunks/ytd_*) against features.

    spec.mode = 'branches' (first matching fragment wins) or
                'concat'   (default — all matching fragments concatenated)
    """
    if not spec:
        return ""
    mode = spec.get("mode", "concat")
    out: list[str] = []
    for f in spec.get("fragments") or []:
        rendered = _render_fragment(f, features, clauses)
        if rendered is None:
            continue
        out.append(rendered)
        if mode == "branches":
            break
    return "".join(out)


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

    stats.primary_days = len({c["d"] for c in classifications if c["tier"] == "primary"})
    return stats


# ---------------------------------------------------------------------------
# Per-month + per-chunk classification context
# ---------------------------------------------------------------------------

@dataclass
class MonthContext:
    month: int
    triggered: Counter[str] = field(default_factory=Counter)
    series: Counter[str] = field(default_factory=Counter)
    calendar: Counter[str] = field(default_factory=Counter)
    peak_snow: tuple[str, float] | None = None
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


# ---- snow-label heuristic, shared across month + chunk + ytd scopes ----

def _snow_label(snow_days: int, peak_in: float, total_in: float = 0) -> str:
    """Returns 'snowmageddon' | 'snow_siege' | 'banana_weather' | ''.
    Underscore form is the canonical key; humans get "snow siege"."""
    if peak_in >= 4 or total_in >= 8 or (snow_days >= 5 and peak_in >= 2.5):
        return "snowmageddon"
    if snow_days >= 3 or peak_in >= 1.5 or total_in >= 4:
        return "snow_siege"
    if snow_days >= 1:
        return "banana_weather"
    return ""


_SNOW_LABEL_HUMAN = {
    "snowmageddon": "snowmageddon",
    "snow_siege": "snow siege",
    "banana_weather": "banana weather",
    "": "",
}


# ---------------------------------------------------------------------------
# Feature builders (one per scope)
# ---------------------------------------------------------------------------

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


def _apply_clauses(features: dict, clauses: dict[str, dict]) -> dict:
    """Pre-render each named clause; add `clause_<name>` to features."""
    out = dict(features)
    for name, cl in clauses.items():
        key = f"clause_{name}"
        if _eval_when(cl.get("when"), features):
            out[key] = cl.get("template", "").format(**features)
        else:
            out[key] = ""
    return out


def build_month_features(
    ms: MonthStats, ctx: MonthContext, narrative: Narrative,
) -> dict:
    top_calendar = ctx.calendar.most_common(1)[0][0] if ctx.calendar else "Winter"
    top_series = ctx.series.most_common(1)[0][0] if ctx.series else ""
    snow_label = _snow_label(
        ms.snow_days,
        ctx.peak_snow[1] if ctx.peak_snow else 0,
        ms.snow,
    )

    smoke_triggers = ctx.triggered.get("Smogust", 0) + ctx.triggered.get("Smoketember", 0)
    heat_triggers = ctx.triggered.get("Oppressive Sun", 0) + ctx.triggered.get("Hell's Front Porch", 0)
    sl = narrative.summer_labels
    summer_label = (
        sl.get("smoke", "**Summer**") if smoke_triggers
        else sl.get("heat",  "**Summer**") if heat_triggers
        else sl.get("plain", "**Summer**")
    )

    base = {
        "month_name":       MONTH_NAMES[ms.month],
        "month_short":      MONTH_SHORT[ms.month],
        "primary_calendar": top_calendar,
        "primary_series":   top_series,
        "primary_series_or_deception": top_series or "Spring of Deception",
        "avg_hi":           ms.avg_hi,
        "avg_lo":           ms.avg_lo,
        "avg_hi_str":       _fmt(ms.avg_hi),
        "avg_lo_str":       _fmt(ms.avg_lo),
        "precip":           ms.precip,
        "precip_str":       f"{ms.precip:.1f} in",
        "snow":             ms.snow,
        "snow_days":        ms.snow_days,
        "freeze_days":      ms.freeze_days,
        "days_60":          ms.days_60,
        "d_hi":             ms.d_hi,
        "d_lo":             ms.d_lo,
        "d_precip":         ms.d_precip,
        "d_hi_str":         _fmt_delta(ms.d_hi) if ms.d_hi is not None else "",
        "d_lo_str":         _fmt_delta(ms.d_lo) if ms.d_lo is not None else "",
        "d_precip_str":     _fmt_delta(ms.d_precip, " in") if ms.d_precip is not None else "",
        "has_d_hi":         ms.d_hi is not None,
        "snow_label":       snow_label,
        "snow_label_human": _SNOW_LABEL_HUMAN[snow_label],
        "has_snow_label":   bool(snow_label),
        "peak_snow_in":     ctx.peak_snow[1] if ctx.peak_snow else 0,
        "peak_snow_in_str": f"{ctx.peak_snow[1]:.1f}\"" if ctx.peak_snow else "",
        "peak_snow_date":   humanize_date(ctx.peak_snow[0]) if ctx.peak_snow else "",
        "peak_hi_f":        ctx.peak_hi[1] if ctx.peak_hi else 0,
        "peak_hi_str":      f"{ctx.peak_hi[1]:.0f}°F" if ctx.peak_hi else "",
        "peak_hi_date":     humanize_date(ctx.peak_hi[0]) if ctx.peak_hi else "",
        "bananas":          ctx.triggered.get("Find Bananas", 0),
        "paralyzing":       ctx.triggered.get("Paralyzing Snow", 0),
        "photon":           ctx.triggered.get("Photon Fraud", 0),
        "drizzle":          ctx.triggered.get("Welcome Drizzle", 0),
        "smogust":          smoke_triggers,
        "oppressive":       heat_triggers,
        "is_juneuary":      "Juneuary" in ctx.calendar or (ms.d_hi is not None and ms.d_hi <= -2),
        "summer_label":     summer_label,
    }
    return _apply_clauses(base, narrative.clauses)


def build_ytd_features(
    stats: YtdStats, month_ctx: dict[int, MonthContext],
    classifications: list[sqlite3.Row], narrative: Narrative,
) -> dict:
    """Year-level features for ytd_lead / ytd_spring_arc / ytd_summer."""
    triggered_counts = Counter(
        c["canonical_name"] for c in classifications if c["tier"] == "triggered"
    )
    series_days = Counter(
        c["canonical_name"] for c in classifications
        if c["tier"] == "primary" and c["category"] == "series"
    )
    spring_arc_concepts = ["Fool's Spring", "Second Winter", "Spring of Deception",
                           "Third Winter", "Actual Spring"]
    fired_arc = [s for s in spring_arc_concepts if series_days.get(s, 0) > 0]

    feb = stats.months.get(2)
    feb_ctx = month_ctx.get(2, MonthContext(2))
    feb_peak = feb_ctx.peak_snow
    feb_snow_label = _snow_label(
        feb.snow_days if feb else 0,
        feb_peak[1] if feb_peak else 0,
        feb.snow if feb else 0,
    )
    mar = stats.months.get(3)

    summer_cool = sum(
        1 for m in (6, 7, 8)
        if (sm := stats.months.get(m)) and sm.d_hi is not None and sm.d_hi <= -2
    )

    base = {
        "bananas_total":     triggered_counts.get("Find Bananas", 0),
        "paralyzing_total":  triggered_counts.get("Paralyzing Snow", 0),
        "photon_total":      triggered_counts.get("Photon Fraud", 0),
        "drizzle_total":     triggered_counts.get("Welcome Drizzle", 0),
        "freeze_days_total": stats.freeze_days,
        "days_70":           stats.days_70,
        "days_80":           stats.days_80,
        "summer_cool_count": summer_cool,
        # February-specific snapshot
        "feb_snow_days":     feb.snow_days if feb else 0,
        "feb_snow_label":    feb_snow_label,
        "feb_was_snowmageddon": feb_snow_label == "snowmageddon",
        "feb_peak_snow_in":  feb_peak[1] if feb_peak else 0,
        "feb_peak_snow_in_str": f"{feb_peak[1]:.1f}\"" if feb_peak else "",
        "feb_peak_snow_date": humanize_date(feb_peak[0]) if feb_peak else "",
        "feb_d_hi":          feb.d_hi if feb else None,
        "feb_d_hi_label":    (f"{feb.d_hi:+.0f}°F on highs" if feb and feb.d_hi is not None
                              else "well below normal"),
        "mar_d_precip":      mar.d_precip if mar else None,
        # Spring arc
        "has_spring_arc":    bool(fired_arc),
        "spring_arc_str":    arc_line(fired_arc) if fired_arc else "",
        "spring_arc_len":    len(fired_arc),
    }
    return _apply_clauses(base, narrative.clauses)


def build_chunk_features(
    days: list[sqlite3.Row], classifications: list[sqlite3.Row],
    start_iso: str, end_iso: str, narrative: Narrative,
) -> dict | None:
    """Features for one biweekly chunk; None if the chunk has no usable temps."""
    hi_days = [d for d in days if d["temp_high_f"] is not None]
    if not hi_days:
        return None
    avg_hi = sum(d["temp_high_f"] for d in hi_days) / len(hi_days)
    hi_min = min(d["temp_high_f"] for d in hi_days)
    hi_max = max(d["temp_high_f"] for d in hi_days)
    precip = sum(d["precip_in"] or 0 for d in days)
    snow_days = sum(1 for d in days if (d["snow_in"] or 0) >= 0.1)

    series_counts: Counter[str] = Counter()
    for d in days:
        series_counts.update(
            c["canonical_name"] for c in classifications
            if c["d"] == d["observed_date"]
            and c["tier"] == "primary"
            and c["category"] == "series"
        )
    dominant = series_counts.most_common(1)[0][0] if series_counts else "—"

    triggered = [
        c for c in classifications
        if c["tier"] == "triggered"
        and start_iso <= c["d"] <= end_iso
        and c["canonical_name"] != "Photon Fraud"
    ]
    triggered_names = {c["canonical_name"] for c in triggered}

    # Peak snow day + temp on that day (B2 guard: temp may be None)
    snow_rows = [d for d in days if (d["snow_in"] or 0) > 0]
    peak_snow_row = max(snow_rows, key=lambda d: d["snow_in"]) if snow_rows else None
    peak_snow_in = (peak_snow_row["snow_in"] or 0) if peak_snow_row else 0
    peak_snow_date = humanize_date(peak_snow_row["observed_date"]) if peak_snow_row else ""
    peak_snow_temp = peak_snow_row["temp_high_f"] if peak_snow_row else None
    peak_snow_temp_str = f"{peak_snow_temp:.0f}°F" if peak_snow_temp is not None else f"{avg_hi:.0f}°F"

    chunk_snow_label = _snow_label(snow_days, peak_snow_in, sum(d["snow_in"] or 0 for d in days))

    base = {
        "chunk_dominant":        dominant,
        "chunk_dominant_tag":    tag(dominant) if dominant != "—" else "—",
        "chunk_avg_hi":          avg_hi,
        "chunk_avg_hi_str":      f"{avg_hi:.0f}°F",
        "chunk_hi_min":          hi_min,
        "chunk_hi_max":          hi_max,
        "chunk_precip":          precip,
        "chunk_precip_str":      f"{precip:.1f} in",
        "chunk_snow_days":       snow_days,
        "chunk_peak_snow_in":    peak_snow_in,
        "chunk_peak_snow_in_str": f"{peak_snow_in:.1f}\"",
        "chunk_peak_snow_date":  peak_snow_date,
        "chunk_peak_snow_temp_str": peak_snow_temp_str,
        "chunk_snow_label":      chunk_snow_label,
        "chunk_snow_label_human":_SNOW_LABEL_HUMAN[chunk_snow_label],
        "has_paralyzing_snow_chunk": "Paralyzing Snow" in triggered_names,
        "has_find_bananas_chunk":    "Find Bananas" in triggered_names,
        "has_welcome_drizzle_chunk": "Welcome Drizzle" in triggered_names,
        # Triggered events list for the weather row
        "triggered_rows":        triggered,
    }
    return _apply_clauses(base, narrative.clauses)


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
    stats: YtdStats, classifications: list[sqlite3.Row],
    month_ctx: dict[int, MonthContext], narrative: Narrative,
) -> str:
    yfeat = build_ytd_features(stats, month_ctx, classifications, narrative)
    trig_counts = Counter(
        c["canonical_name"] for c in classifications if c["tier"] == "triggered"
    )

    lines = [section_heading("YTD Summary"), ""]
    for spec in (narrative.ytd_lead, narrative.ytd_spring_arc, narrative.ytd_summer):
        paragraph = render_section(spec, yfeat, narrative.clauses).strip()
        if paragraph:
            lines.append(paragraph)
            lines.append("")

    # Triggered highlights — terse vernacular, deduped, ordered.
    highlight_specs = [
        ("Find Bananas",     "the QFC banana run"),
        ("Paralyzing Snow",  "hills abandoned"),
        ("Photon Fraud",     "useless sun"),
        ("Welcome Drizzle",  "summer's curtain call"),
        ("Praise the Sun",   f"first real sun after {tag('The Long Dark')}"),
        ("Glorious Sun",     "warm enough to feel it"),
        ("Smogust",          "wildfire smoke season"),
        ("Smoketember",      "wildfire smoke season"),
        ("Choking Smoke",    "wildfire smoke season"),
    ]
    highlights: list[str] = []
    for name, blurb in highlight_specs:
        n = trig_counts.get(name, 0)
        if not n:
            continue
        if name in ("Praise the Sun", "Glorious Sun"):
            highlights.append(f"{tag(name)} ({blurb})")
        else:
            highlights.append(f"{tag(name)} ({n} day(s) — {blurb})")
    if highlights:
        lines.append("⚡ **Triggered microseasons that fired:** "
                     + "; ".join(highlights) + ".")
        lines.append("")

    if yfeat["has_spring_arc"]:
        lines.append(f"🔁 **Spring series arc:** {yfeat['spring_arc_str']}.")
        lines.append("")

    return "\n".join(lines)


def render_the_numbers(stats: YtdStats) -> str:
    d_precip = stats.total_precip - stats.norm_precip_sum if stats.norm_precip_sum else None

    def stat_row(label: str, observed: str, delta: str, notes: str = "") -> str:
        key = next((k for k in STAT_ROW_EMOJI if label.startswith(k)), label)
        emoji = STAT_ROW_EMOJI.get(key, "")
        return f"| {emoji} {label} | {observed} | {delta} | {notes} |"

    coldest, hottest = stats.coldest, stats.hottest
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
            "—", "grid-cell estimate",
        ),
        stat_row("Days low &lt; 32°F",  f"**{stats.freeze_days}**", "—"),
        stat_row("Days high ≥ 60°F",    f"**{stats.days_60}**", "—"),
        stat_row("Days high ≥ 70°F",    f"**{stats.days_70}**", "—"),
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
    stats: YtdStats, month_ctx: dict[int, MonthContext], narrative: Narrative,
) -> str:
    lines = [
        section_heading("Monthly story"),
        "",
        "_📖 Each month in the microseason vernacular — the names locals actually use._",
        "",
    ]
    for m in sorted(stats.months):
        ctx = month_ctx.get(m, MonthContext(month=m))
        ms = stats.months[m]
        features = build_month_features(ms, ctx, narrative)
        spec = narrative.months.get(str(m))
        if spec:
            line = render_section(spec, features, narrative.clauses).rstrip()
        else:
            # Generic fallback when the city has no template for this month.
            line = (f"**{MONTH_NAMES[m]}** — {_fmt(ms.avg_hi)} / "
                    f"{_fmt(ms.avg_lo)} avg.")
        if line:
            lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def render_season_timeline(
    observations: list[sqlite3.Row], classifications: list[sqlite3.Row],
    narrative: Narrative,
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

        features = build_chunk_features(
            days, classifications,
            cur.isoformat(), chunk_end.isoformat(), narrative,
        )
        if features is None:                      # B1: no usable temps
            cur = chunk_end + timedelta(days=1)
            continue

        title = render_section(narrative.chunk_titles, features, narrative.clauses)
        if not title:
            title = features["chunk_dominant_tag"]
        commentary = render_section(narrative.chunks, features, narrative.clauses)

        lines.append(f"### {humanize_span(cur.isoformat(), chunk_end.isoformat())} · {title}")
        lines.append("")
        if commentary:
            lines.append(commentary.strip())
            lines.append("")

        weather = (
            f"🌡️ **Weather:** ~{features['chunk_avg_hi']:.0f}°F avg high "
            f"({features['chunk_hi_min']:.0f}–{features['chunk_hi_max']:.0f}), "
            f"🌧️ {features['chunk_precip']:.1f} in precip"
        )
        if features["chunk_snow_days"]:
            weather += f", ❄️ **{features['chunk_snow_days']} snow day(s)**"
        lines.append(weather + ".")

        triggered = features["triggered_rows"]
        if triggered:
            bits: list[str] = []
            seen: set[tuple[str, str]] = set()
            for c in triggered:
                key = (c["d"], c["canonical_name"])
                if key in seen:
                    continue
                seen.add(key)
                e = MS_EMOJI.get(c["canonical_name"], "•")
                bits.append(f"{c['d'][5:]} {e} {c['display_name']}")
            line = ", ".join(bits[:6])
            if len(bits) > 6:
                line += f", +{len(bits) - 6} more"
            lines.append(f"⚡ **Triggered:** {line}.")
        lines.append("")
        lines.append("---")
        lines.append("")

        cur = chunk_end + timedelta(days=1)

    return "\n".join(lines)


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
            lines.append(f"- **{humanize_span(first, last)}** ({n}d) — {tag(name)}")
        lines.append("")
    return "\n".join(lines)


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

    block("🔥 Hottest highs",
          sorted(with_temps, key=lambda o: o["temp_high_f"], reverse=True),
          lambda o: f"**{o['temp_high_f']:.0f}°F** high (low {o['temp_low_f']:.0f}°F)")
    block("🧊 Coldest lows",
          sorted(with_temps, key=lambda o: o["temp_low_f"]),
          lambda o: f"**{o['temp_low_f']:.0f}°F** low (high {o['temp_high_f']:.0f}°F)")
    block("🌧️ Wettest days",
          sorted(with_precip, key=lambda o: o["precip_in"], reverse=True),
          lambda o: f"**{o['precip_in']:.2f}\"** precip"
          + (f", ☁️ {o['cloud_cover_mean_pct']:.0f}% cloud"
             if o["cloud_cover_mean_pct"] is not None else ""))
    return "\n".join(lines)


def render_method_notes(total_days: int) -> str:
    return (
        f"{section_heading('Method')}\n\n"
        "- Report is a pure consumer of the Juneuary API: it pulls a classified "
        "range from `/v1/days` and climate normals from `/v1/normals` — the API "
        "fetches Open-Meteo and classifies; this script only renders.\n"
        f"- Building {total_days} days costs **2–4 Open-Meteo calls per city** "
        "(weather + air-quality, doubled when the range straddles the ~7-day "
        "archive/forecast seam in `fetch_weather.py`). Forecast-era days drift — "
        "rebuild before publishing.\n"
        "- Verify against live Open-Meteo before trusting degree-level values "
        "(see **j-report-review** skill).\n"
        "- ERA5 grid-cell data ≠ your block; north Seattle snow can differ from downtown.\n"
        "- Classification: `scripts/classify.py` (primary / secondary / triggered).\n"
        "- Narrative voice: `data/cities/<catalog_slug>.narrative.yaml` "
        "(child cities inherit via parent_slug).\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_report(base: str, city_slug: str, start: str, end: str) -> str:
    """Fetch a classified range + normals from the API and render the report.

    `base` is an API root like http://127.0.0.1:8787. Returns the markdown body.
    """
    days_payload = fetch_days(base, city_slug, start, end)
    if not days_payload.get("days"):
        raise SystemExit(
            f"API {base} returned no days for {city_slug} in [{start}, {end}]."
        )
    normals_payload = fetch_normals(base, city_slug)

    location = days_payload["location"]
    catalog_slug = location.get("catalog_slug") or location["slug"]
    narrative = load_narrative(catalog_slug)

    observations = observations_from_days(days_payload)
    classifications = classifications_from_days(days_payload)
    normals = normals_from_payload(normals_payload)

    total_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    stats = compute_stats(observations, normals, classifications)
    month_ctx = build_month_contexts(observations, classifications)

    sections = [
        render_header(location, start, end, total_days),
        render_ytd_summary(stats, classifications, month_ctx, narrative),
        render_the_numbers(stats),
        render_monthly_story(stats, month_ctx, narrative),
        render_season_timeline(observations, classifications, narrative),
        render_series_progression(classifications),
        render_triggered_events(classifications),
        render_notable_days(observations),
        render_method_notes(total_days),
    ]
    # Single emojify pass on the full document — sub-renderers stay focused
    # on structure; emoji decoration lives here.
    return emojify("\n".join(s for s in sections if s).rstrip() + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", required=True,
                   help="city slug (see data/cities.yaml + data/cities.local.yaml)")
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--from", dest="start", help="override start date (YYYY-MM-DD)")
    p.add_argument("--through", dest="end", help="override end date (YYYY-MM-DD)")
    p.add_argument("--out", help="output path (default: reports/<city>_<year>_ytd.md)")
    p.add_argument("--db", default=str(DB_PATH),
                   help="catalog DB the in-process API serves (ignored with --api-url)")
    p.add_argument("--api-url", dest="api_url",
                   help="use a running API instead of booting one in-process")
    args = p.parse_args()

    today = date.today()
    start = args.start or f"{args.year}-01-01"
    end = args.end or min(today.isoformat(), f"{args.year}-12-31")

    out_path = Path(args.out or ROOT / "reports" / f"{args.city}_{args.year}_ytd.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.api_url:
        body = build_report(args.api_url, args.city, start, end)
    else:
        with ephemeral_api(args.db) as base:
            body = build_report(base, args.city, start, end)

    out_path.write_text(body)
    print(f"Wrote {out_path} ({len(body):,} bytes, {body.count(chr(10))} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
