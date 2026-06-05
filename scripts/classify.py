"""Shared classifier.

Given a city + an observation (temp/precip/snow/smoke/solar_elev/etc.),
return three tiers of matches plus anomaly metadata + suggestions:

  primary    - the weather-of-the-day microseason(s) (calendar, series,
               climate_disaster, triggered_event with temp profile).
  secondary  - background traits currently in their typical window
               (constants: Karl the Fog, Spider Season, Convergence Zones).
  triggered  - signal-driven events that fired today (Find Bananas,
               Paralyzing Snow, Welcome Drizzle, Choking Smoke, Praise
               the Sun, Glorious Sun, Photon Fraud).

The same function powers `query.py propose` (hypothetical inputs) and
`fetch_weather.py` (real Open-Meteo data).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import solar


# Default first-sun thresholds. Per-city overrides can come later; these are
# tuned to be STRICT for Seattle so we don't false-positive on every passing
# cloud break.
FIRST_SUN_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "seattle": {
        "praise_min_prior_overcast_days":   14,
        "praise_max_cloud_cover_pct":       25.0,
        "glorious_min_high_f":              62.0,
        "glorious_min_solar_elev_deg":      solar.GLORIOUS_SUN_MIN_ELEVATION_DEG,
    },
    # SF doesn't currently have Praise/Glorious occurrences but defaults stand by.
    "san_francisco": {
        "praise_min_prior_overcast_days":   7,
        "praise_max_cloud_cover_pct":       20.0,
        "glorious_min_high_f":              65.0,
        "glorious_min_solar_elev_deg":      solar.GLORIOUS_SUN_MIN_ELEVATION_DEG,
    },
}

DEFAULT_THRESHOLDS = {
    "praise_min_prior_overcast_days":   10,
    "praise_max_cloud_cover_pct":       25.0,
    "glorious_min_high_f":              62.0,
    "glorious_min_solar_elev_deg":      solar.GLORIOUS_SUN_MIN_ELEVATION_DEG,
}

OVERCAST_CLOUD_PCT = 80.0   # cloud_cover >= this counts a day as "overcast"

TEMP_RANGE_SLACK_F = 3.0    # forgiveness on bracketed temp ranges
SMOKE_PM25_UG_M3 = 35.0     # PM2.5 threshold for smoke=True

# --- Aberration thresholds ---
# A single observation more than this many degrees from the monthly normal
# is considered a statistical aberration: a real measurement, but NOT
# evidence for a new microseason. (~3-sigma for most months in the
# mid-latitudes.) Set high enough that real-but-rare days like a 70°F
# Seattle January (~ +23°F) are flagged but a 60°F Jan day is not.
ABERRATION_ANOMALY_F = 20.0

# Confidence assigned to primary matches when the day itself is an
# aberration. Stays in the DB so re-classification can lift it later if
# the pattern persists, but it's low enough to be filtered out of the
# default "last-seen" sequence display.
ABERRATION_PRIMARY_CONFIDENCE = 0.2

# Months in which the listed signals are themselves aberrant.
WINTER_MONTHS = {12, 1, 2}
SUMMER_MONTHS = {6, 7, 8}


@dataclass
class ObservationIn:
    """What classify_observation needs to know about a day."""
    city_slug: str
    month: int                               # 1..12
    temp_high_f: float
    temp_low_f: float | None = None
    precip_in: float = 0.0
    snow_in: float = 0.0
    cloud_cover_mean_pct: float | None = None
    smoke: bool = False
    pm25_ug_m3: float | None = None
    solar_elevation_max_deg: float | None = None
    # History context for first-sun events.
    prior_overcast_days: int = 0             # consecutive overcast days immediately before today


@dataclass
class Match:
    occurrence_id: int
    microseason_id: int
    canonical_name: str
    display_name: str
    category: str
    series_label: str | None
    tier: str                                 # 'primary' | 'secondary' | 'triggered'
    confidence: float
    reason: str


@dataclass
class Anomaly:
    high_anomaly_f: float | None = None      # observed_high - normal_high
    low_anomaly_f: float | None = None
    normal_high_f: float | None = None
    normal_low_f: float | None = None
    normal_precip_in: float | None = None


@dataclass
class ClassifyResult:
    primary:                list[Match]      = field(default_factory=list)
    secondary:              list[Match]      = field(default_factory=list)
    triggered:              list[Match]      = field(default_factory=list)
    out_of_window_temp_fit: list[Match]      = field(default_factory=list)
    anomaly:                Anomaly          = field(default_factory=Anomaly)
    is_aberration:          bool             = False
    aberration_reason:      str              = ""
    proposed_new_bits:      list[str]        = field(default_factory=list)
    naming_suggestions:     list[str]        = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_observation(conn: sqlite3.Connection, inp: ObservationIn) -> ClassifyResult:
    result = ClassifyResult()
    city_row = conn.execute(
        "SELECT id, latitude FROM cities WHERE slug = ?", [inp.city_slug],
    ).fetchone()
    if not city_row:
        raise ValueError(f"unknown city: {inp.city_slug}")

    # ---- anomalies vs climate normals ----
    n = conn.execute(
        "SELECT * FROM city_climate_normals WHERE city_id = ? AND month = ?",
        [city_row["id"], inp.month],
    ).fetchone()
    if n:
        result.anomaly.normal_high_f = n["temp_max_avg_f"]
        result.anomaly.normal_low_f = n["temp_min_avg_f"]
        result.anomaly.normal_precip_in = n["precip_total_in"]
        if n["temp_max_avg_f"] is not None:
            result.anomaly.high_anomaly_f = inp.temp_high_f - n["temp_max_avg_f"]
        if inp.temp_low_f is not None and n["temp_min_avg_f"] is not None:
            result.anomaly.low_anomaly_f = inp.temp_low_f - n["temp_min_avg_f"]

    # ---- aberration detection (must happen before propose-new) ----
    result.is_aberration, result.aberration_reason = _detect_aberration(inp, result.anomaly)

    # ---- per-city occurrences ----
    occ_rows = conn.execute(
        "SELECT * FROM v_city_microseasons WHERE city_slug = ?",
        [inp.city_slug],
    ).fetchall()

    thresholds = FIRST_SUN_THRESHOLDS.get(inp.city_slug, DEFAULT_THRESHOLDS)

    for r in occ_rows:
        cat = r["category"]
        cname = r["canonical_name"]
        m = _build_match(r, tier="primary", confidence=0.0, reason="")

        # --- Secondary: constants in their window ---
        if cat == "constant":
            if _month_in_window(inp.month, r["typical_start_month"], r["typical_end_month"]):
                m.tier = "secondary"
                m.confidence = 1.0
                m.reason = "background trait active in this window"
                result.secondary.append(m)
            continue

        # --- Triggered: sun_phenomenon (Photon Fraud) ---
        if cat == "sun_phenomenon" and cname == "Photon Fraud":
            if (inp.solar_elevation_max_deg is not None
                and inp.solar_elevation_max_deg <= solar.PHOTON_FRAUD_MAX_ELEVATION_DEG
                and (inp.cloud_cover_mean_pct is None or inp.cloud_cover_mean_pct <= 60)):
                m.tier = "triggered"
                m.confidence = 0.9
                m.reason = (f"solar elevation {inp.solar_elevation_max_deg:.1f}° "
                            f"≤ {solar.PHOTON_FRAUD_MAX_ELEVATION_DEG:.0f}° with sun visible")
                result.triggered.append(m)
            continue

        # --- Triggered: signal-gated events ---
        gated = _signal_gate(cname, inp)
        if gated is not None:
            present, reason = gated
            if present and _month_in_window(inp.month, r["typical_start_month"], r["typical_end_month"]):
                m.tier = "triggered" if cat in ("triggered_event", "climate_disaster") else "primary"
                m.confidence = 0.95
                m.reason = reason
                (result.triggered if m.tier == "triggered" else result.primary).append(m)
            continue

        # --- First-sun events with strict tolerances ---
        if cname == "Praise the Sun":
            if _praise_the_sun_fires(inp, thresholds):
                m.tier = "triggered"
                m.confidence = 0.9
                m.reason = (f"≤{thresholds['praise_max_cloud_cover_pct']:.0f}% cloud after "
                            f"≥{thresholds['praise_min_prior_overcast_days']} prior overcast days")
                result.triggered.append(m)
            continue
        if cname == "Glorious Sun":
            if _glorious_sun_fires(inp, thresholds):
                m.tier = "triggered"
                m.confidence = 0.9
                m.reason = (f"first warm sun: high {inp.temp_high_f:.0f}°F, "
                            f"solar elev {inp.solar_elevation_max_deg or 0:.0f}°")
                result.triggered.append(m)
            continue

        # --- Primary: weather classification with temp profile ---
        temp_fit = _temp_fit_score(inp.temp_high_f, inp.temp_low_f,
                                   r["temp_min_f"], r["temp_max_f"])
        if temp_fit is None:
            continue   # no temp profile and not a recognized signal — skip
        if temp_fit is False:
            continue
        in_window = _month_in_window(inp.month, r["typical_start_month"], r["typical_end_month"])
        if in_window:
            m.tier = "primary"
            m.confidence = 0.8
            m.reason = _primary_reason(inp, r)
            result.primary.append(m)
        else:
            m.tier = "primary"
            m.confidence = 0.4
            m.reason = "temperature fits but outside typical window"
            result.out_of_window_temp_fit.append(m)

    # ---- Aberration handling: downgrade primary confidence so a freak
    # day doesn't cement an "official" last-seen entry. Triggered and
    # secondary entries are unaffected (a smoke event in winter is still
    # a smoke event; Karl is still Karl).
    if result.is_aberration:
        for m in result.primary:
            m.confidence = min(m.confidence, ABERRATION_PRIMARY_CONFIDENCE)
            m.reason = (m.reason + " — TRANSIENT (aberration day)").strip(" —")

    # ---- Suggest new concept (suppressed for aberrations) ----
    _propose_new(result, inp)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_match(r: sqlite3.Row, tier: str, confidence: float, reason: str) -> Match:
    return Match(
        occurrence_id=r["occurrence_id"],
        microseason_id=r["microseason_id"],
        canonical_name=r["canonical_name"],
        display_name=r["display_name"],
        category=r["category"],
        series_label=r["series_label"],
        tier=tier,
        confidence=confidence,
        reason=reason,
    )


def _month_in_window(m: int, start: int | None, end: int | None) -> bool:
    if start is None and end is None:
        return True
    if start is None:
        return m <= end
    if end is None:
        return m >= start
    if start <= end:
        return start <= m <= end
    return m >= start or m <= end                            # wraps year-end


def _temp_fit_score(obs_high: float, obs_low: float | None,
                    def_min: float | None, def_max: float | None,
                    slack: float = TEMP_RANGE_SLACK_F) -> bool | None:
    if def_min is None and def_max is None:
        return None
    if def_min is not None and def_max is None:
        return obs_high >= def_min - slack
    if def_max is not None and def_min is None:
        return obs_high <= def_max + slack
    return (def_min - slack) <= obs_high <= (def_max + slack)


def _signal_gate(cname: str, inp: ObservationIn) -> tuple[bool, str] | None:
    """If cname is a signal-gated concept, return (signal_present, reason)."""
    if cname in ("Smogust", "Smoketember"):
        if inp.smoke:
            return True, f"smoke present (PM2.5 {inp.pm25_ug_m3 or '?'} µg/m³)"
        return False, ""
    if cname == "Choking Smoke":
        if inp.smoke and (inp.pm25_ug_m3 is None or inp.pm25_ug_m3 >= 55):
            return True, f"acute smoke event (PM2.5 {inp.pm25_ug_m3 or '?'} µg/m³)"
        return False, ""
    if cname == "Find Bananas":
        if inp.snow_in >= 0.1:
            return True, "snow in observation/forecast"
        return False, ""
    if cname == "Paralyzing Snow":
        if inp.snow_in >= 0.5:
            return True, f"{inp.snow_in:.1f}\" snow accumulation"
        return False, ""
    if cname == "Welcome Drizzle":
        if inp.precip_in > 0.05:
            return True, f"{inp.precip_in:.2f}\" precip after dry stretch"
        return False, ""
    return None


def _praise_the_sun_fires(inp: ObservationIn, t: dict) -> bool:
    if inp.cloud_cover_mean_pct is None:
        return False
    return (inp.cloud_cover_mean_pct <= t["praise_max_cloud_cover_pct"]
            and inp.prior_overcast_days >= t["praise_min_prior_overcast_days"])


def _glorious_sun_fires(inp: ObservationIn, t: dict) -> bool:
    if not _praise_the_sun_fires(inp, t):
        return False
    if inp.temp_high_f < t["glorious_min_high_f"]:
        return False
    if inp.solar_elevation_max_deg is None:
        return False
    return inp.solar_elevation_max_deg >= t["glorious_min_solar_elev_deg"]


def _primary_reason(inp: ObservationIn, r: sqlite3.Row) -> str:
    bits = []
    if r["temp_min_f"] is not None and r["temp_max_f"] is not None:
        bits.append(f"high {inp.temp_high_f:.0f}°F in {r['temp_min_f']:.0f}–{r['temp_max_f']:.0f}°F range")
    elif r["temp_min_f"] is not None:
        bits.append(f"high {inp.temp_high_f:.0f}°F ≥ {r['temp_min_f']:.0f}°F threshold")
    elif r["temp_max_f"] is not None:
        bits.append(f"high {inp.temp_high_f:.0f}°F ≤ {r['temp_max_f']:.0f}°F threshold")
    return "; ".join(bits) if bits else "in window"


def _detect_aberration(inp: ObservationIn, anomaly: Anomaly) -> tuple[bool, str]:
    """Is this single observation a statistical outlier?

    True aberrations should NOT generate new microseason proposals or be
    treated as evidence of a recurring pattern. They might be noted (e.g.
    in an `aberrations` log) but they don't get to vote on the catalog.
    """
    reasons: list[str] = []
    if anomaly.high_anomaly_f is not None and abs(anomaly.high_anomaly_f) >= ABERRATION_ANOMALY_F:
        reasons.append(f"high {anomaly.high_anomaly_f:+.0f}°F vs normal "
                       f"(threshold ±{ABERRATION_ANOMALY_F:.0f}°F)")
    if anomaly.low_anomaly_f is not None and abs(anomaly.low_anomaly_f) >= ABERRATION_ANOMALY_F:
        reasons.append(f"low {anomaly.low_anomaly_f:+.0f}°F vs normal "
                       f"(threshold ±{ABERRATION_ANOMALY_F:.0f}°F)")
    if inp.smoke and inp.month in WINTER_MONTHS:
        reasons.append("wildfire smoke in deep winter is statistically rare")
    if inp.snow_in >= 0.1 and inp.month in SUMMER_MONTHS:
        reasons.append(f"{inp.snow_in:.1f}\" snow in summer is statistically rare")
    return bool(reasons), "; ".join(reasons)


def _propose_new(result: ClassifyResult, inp: ObservationIn) -> None:
    a = result.anomaly
    bits = result.proposed_new_bits
    names = result.naming_suggestions

    # --- ABERRATION SHORT-CIRCUIT ---
    # A single freak day is not evidence for a new microseason. Note it
    # but don't propose. The day still gets recorded and (low-confidence)
    # classified — pattern detection across multiple days is the right
    # surface for inventing new concepts.
    if result.is_aberration:
        bits.append(f"ABERRATION: {result.aberration_reason}. "
                    "Single-day extremes do NOT warrant a new microseason — "
                    "watch for the same anomaly recurring across multiple days "
                    "or years before codifying.")
        return

    big = (
        (a.high_anomaly_f is not None and abs(a.high_anomaly_f) >= 10)
        or (a.low_anomaly_f is not None and abs(a.low_anomaly_f) >= 10)
        or inp.smoke or inp.snow_in >= 0.5
    )
    if not big and result.primary:
        return

    month_label = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][inp.month]
    if inp.smoke:
        bits.append("CLIMATE DISASTER: wildfire smoke present")
    if inp.snow_in >= 0.5:
        bits.append("triggered SNOW event (city-paralyzing if low-snow city)")
    if a.high_anomaly_f is not None:
        if a.high_anomaly_f >= 20:
            bits.append("MAJOR HEAT ANOMALY (heat-dome territory) — category: triggered_event")
            names.append(f"Heat-dome style: \"{month_label}'s Front Porch\" / \"{month_label} Furnace\"")
        elif a.high_anomaly_f >= 10:
            bits.append(f"warm anomaly (+{a.high_anomaly_f:.0f}°F over normal high) — category: triggered_event or series fakeout")
            names.append(f"Fake-spring style: \"Fool's {month_label}\" / \"{month_label} of Deception\"")
        elif a.high_anomaly_f <= -15:
            bits.append("MAJOR COLD ANOMALY (arctic outflow / blocking ridge) — category: triggered_event")
            names.append(f"Return-of-winter style: \"Surprise Winter\" / \"{month_label} Backslide\"")
        elif a.high_anomaly_f <= -8:
            bits.append(f"cold anomaly ({a.high_anomaly_f:.0f}°F below normal high) — category: triggered_event")
    if a.low_anomaly_f is not None and a.low_anomaly_f <= -10:
        bits.append("hard frost / tropical-night absence — category: triggered_event")
    if not bits and not result.primary:
        bits.append("within normal envelope but no defined microseason matches — "
                    "might be an unnamed transitional period worth defining as `calendar`")
