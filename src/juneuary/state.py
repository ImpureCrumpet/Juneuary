"""Neutral render-model DTO + builder.

`build_state()` turns a classified day in the SQLite DB into a
`MicroseasonState` — a presentation-agnostic snapshot that any consumer can
render: the markdown report, a JSON HTTP endpoint, or a 64x32 pixel display.

Design intent: this is the *contract* between the Juneuary engine and any
out-of-process client (notably a Starlark/tronbyt display app, which can only
speak HTTP+JSON). Keep `to_dict()` stable and bump `SCHEMA_VERSION` when its
shape changes.

It reads only the existing schema (cities, observations,
observation_microseasons, microseasons) — no new tables — and decorates each
match with concept-level emoji/color/glyph from `presentation`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field

from . import SCHEMA_VERSION
from .presentation import presentation_for


@dataclass
class Location:
    slug: str
    name: str
    latitude: float | None
    longitude: float | None
    source: str = "catalog"          # "catalog" | "zip" | "latlng"
    catalog_slug: str | None = None  # which catalog was borrowed (when source != catalog)


@dataclass
class MicroseasonView:
    """One classified microseason, decorated for display."""
    canonical_name: str
    display_name: str
    category: str
    tier: str                        # "primary" | "secondary" | "triggered"
    confidence: float
    reason: str
    emoji: str
    color: str
    glyph: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MicroseasonView":
        p = presentation_for(row["canonical_name"])
        return cls(
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            category=row["category"],
            tier=row["tier"],
            confidence=row["confidence"] if row["confidence"] is not None else 0.0,
            reason=row["reason"] or "",
            emoji=p.emoji,
            color=p.color,
            glyph=p.glyph,
        )


@dataclass
class DayState:
    """A single day's classification snapshot + the weather behind it."""
    date: str
    primary: list[MicroseasonView] = field(default_factory=list)
    secondary: list[MicroseasonView] = field(default_factory=list)
    triggered: list[MicroseasonView] = field(default_factory=list)
    is_aberration: bool = False
    aberration_reason: str = ""
    is_forecast: bool = False
    temp_high_f: float | None = None
    temp_low_f: float | None = None
    precip_in: float | None = None
    snow_in: float | None = None
    # Anomaly vs monthly climate normals. Populated on the fetch+classify path
    # (/v1/days, /v1/forecast); null on /v1/state (which reads stored rows that
    # don't persist the per-day anomaly).
    normal_high_f: float | None = None
    normal_low_f: float | None = None
    normal_precip_in: float | None = None
    high_anomaly_f: float | None = None
    low_anomaly_f: float | None = None

    @property
    def headline(self) -> MicroseasonView | None:
        """Single most relevant microseason for a tiny display: the
        highest-confidence primary, else the first triggered, else first
        secondary."""
        if self.primary:
            return max(self.primary, key=lambda v: v.confidence)
        if self.triggered:
            return self.triggered[0]
        if self.secondary:
            return self.secondary[0]
        return None


@dataclass
class MicroseasonState:
    """Top-level contract: where, when, what's happening now, and what's next."""
    schema_version: str
    location: Location
    as_of: str
    current: DayState
    forecast: list[DayState] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict() drops the `headline` property; surface it explicitly so a
        # display client can render the single dominant microseason directly.
        hv = self.current.headline
        d["current"]["headline"] = asdict(hv) if hv else None
        return d


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_CLASSIFY_SQL = """
    SELECT om.tier                                       AS tier,
           om.confidence                                 AS confidence,
           om.reason                                     AS reason,
           COALESCE(occ.local_name, m.canonical_name)    AS display_name,
           m.canonical_name                              AS canonical_name,
           m.category                                    AS category
    FROM observation_microseasons om
    JOIN observations o              ON o.id   = om.observation_id
    JOIN microseason_occurrences occ ON occ.id = om.occurrence_id
    JOIN microseasons m              ON m.id   = occ.microseason_id
    WHERE o.city_id = ? AND o.observed_date = ?
    ORDER BY om.tier, om.confidence DESC, m.canonical_name
"""


def _resolve_date(conn: sqlite3.Connection, city_id: int, on_date: str | None) -> str | None:
    if on_date:
        row = conn.execute(
            "SELECT observed_date FROM observations WHERE city_id = ? AND observed_date = ?",
            [city_id, on_date],
        ).fetchone()
        return row["observed_date"] if row else None
    row = conn.execute(
        "SELECT MAX(observed_date) AS d FROM observations WHERE city_id = ?",
        [city_id],
    ).fetchone()
    return row["d"] if row and row["d"] else None


def build_day_state(conn: sqlite3.Connection, city_id: int, observed_date: str) -> DayState:
    obs = conn.execute(
        "SELECT temp_high_f, temp_low_f, precip_in, snow_in, "
        "is_aberration, aberration_reason "
        "FROM observations WHERE city_id = ? AND observed_date = ?",
        [city_id, observed_date],
    ).fetchone()

    day = DayState(date=observed_date)
    if obs is not None:
        day.temp_high_f = obs["temp_high_f"]
        day.temp_low_f = obs["temp_low_f"]
        day.precip_in = obs["precip_in"]
        day.snow_in = obs["snow_in"]
        day.is_aberration = bool(obs["is_aberration"])
        day.aberration_reason = obs["aberration_reason"] or ""

    for row in conn.execute(_CLASSIFY_SQL, [city_id, observed_date]):
        view = MicroseasonView.from_row(row)
        getattr(day, view.tier).append(view)
    return day


def build_state(
    conn: sqlite3.Connection,
    city_slug: str,
    on_date: str | None = None,
) -> MicroseasonState | None:
    """Build the render-model for `city_slug` on `on_date` (default: latest
    observation on file). Returns None if the city has no observations.
    """
    conn.row_factory = sqlite3.Row
    city = conn.execute(
        "SELECT id, slug, name, latitude, longitude FROM cities WHERE slug = ?",
        [city_slug],
    ).fetchone()
    if city is None:
        raise ValueError(f"unknown city: {city_slug}")

    observed_date = _resolve_date(conn, city["id"], on_date)
    if observed_date is None:
        return None

    return MicroseasonState(
        schema_version=SCHEMA_VERSION,
        location=Location(
            slug=city["slug"],
            name=city["name"],
            latitude=city["latitude"],
            longitude=city["longitude"],
            source="catalog",
        ),
        as_of=observed_date,
        current=build_day_state(conn, city["id"], observed_date),
        forecast=[],   # populated by the predict path (next moves).
    )


def build_normals(conn: sqlite3.Connection, city_slug: str) -> dict:
    """Monthly climate normals for a city, resolved through the catalog so
    child cities inherit the parent's normals. Shape mirrors what a consumer
    (e.g. the report) needs for vs-normal math.
    """
    conn.row_factory = sqlite3.Row
    city = conn.execute(
        "SELECT slug, name FROM cities WHERE slug = ?", [city_slug]
    ).fetchone()
    if city is None:
        raise ValueError(f"unknown city: {city_slug}")
    rows = conn.execute(
        """
        SELECT n.month, n.temp_max_avg_f, n.temp_min_avg_f, n.temp_mean_f,
               n.precip_total_in, n.precip_days, n.snow_total_in,
               n.sun_pct, n.cloud_cover_pct
        FROM city_climate_normals n
        JOIN v_catalog_city vc ON vc.catalog_city_id = n.city_id
        WHERE vc.city_slug = ?
        ORDER BY n.month
        """,
        [city_slug],
    ).fetchall()
    return {
        "schema_version": SCHEMA_VERSION,
        "location": {"slug": city["slug"], "name": city["name"]},
        "normals": {
            str(r["month"]): {
                "temp_max_avg_f": r["temp_max_avg_f"],
                "temp_min_avg_f": r["temp_min_avg_f"],
                "temp_mean_f": r["temp_mean_f"],
                "precip_total_in": r["precip_total_in"],
                "precip_days": r["precip_days"],
                "snow_total_in": r["snow_total_in"],
                "sun_pct": r["sun_pct"],
                "cloud_cover_pct": r["cloud_cover_pct"],
            }
            for r in rows
        },
    }
