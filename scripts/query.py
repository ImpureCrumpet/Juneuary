"""Inspect the built DB.

Usage:
  uv run scripts/query.py [--city <slug>] <command> [...args]

Commands:
  all                     - microseasons grouped by category
  calendar                - microseasons sorted by start month
  series                  - series ordering
  overlaps                - microseason pairs that co-occur
  rain                    - precipitation taxonomy
  cities                  - list cities and per-city counts
  find <text>             - search canonical names + aliases
  concepts                - concepts (global) and which cities have occurrences
  compare <concept>       - show one concept across all cities that have it
  normals                 - monthly climate normals (use --city for one city)
  anomaly                 - each microseason's delta-from-normal for its start month
  propose <month> <high> [<low>] [--precip N] [--smoke] [--snow N]
          [--cloud N] [--prior-overcast N] [--day YYYY-MM-DD]
                          - classify hypothetical conditions. Returns three
                            tiers (primary / triggered / secondary) and
                            suggests defining a new microseason if the
                            observation is far from normal. Requires --city.
  active                  - show the most recent observation's classification
                            (requires --city; needs fetch_weather to have run)
  last-seen [all]         - per-microseason, when it was last classified from
                            real observations (requires --city). Excludes
                            transient/aberration days by default; pass
                            `all` to include them.
  aberrations             - list days flagged as statistical outliers (true
                            aberrations that don't get to define new
                            microseasons). Requires --city.

`--city <slug>` (e.g. --city seattle, --city san_francisco) scopes
city-bound output. Defaults to all cities.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402
import solar     # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "microseasons.db"
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_window(sm, sd, em, ed) -> str:
    if not sm and not em:
        return "any time / triggered"
    start = f"{MONTHS[sm]} {sd}" if sm and sd else (MONTHS[sm] if sm else "?")
    end = f"{MONTHS[em]} {ed}" if em and ed else (MONTHS[em] if em else "?")
    return f"{start} – {end}"


def open_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        sys.exit(f"DB not found at {DB_PATH}. Run scripts/build_db.py first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def city_filter(city: str | None) -> tuple[str, list]:
    if not city:
        return "", []
    return " AND city_slug = ?", [city]


def cmd_all(conn, city):
    where, args = city_filter(city)
    sql = f"""
        SELECT * FROM v_city_microseasons
        WHERE 1=1{where}
        ORDER BY city_slug, category, COALESCE(series_order, 99),
                 COALESCE(typical_start_month, 99), display_name
    """
    current_city, current_cat = None, None
    for r in conn.execute(sql, args):
        if r["city_slug"] != current_city:
            current_city = r["city_slug"]
            current_cat = None
            print(f"\n=== {r['city_name']} ({r['city_slug']}) ===")
        if r["category"] != current_cat:
            current_cat = r["category"]
            print(f"\n  [{current_cat}]")
        label = f"  ({r['series_label']})" if r["series_label"] else ""
        win = fmt_window(r["typical_start_month"], r["typical_start_day"],
                         r["typical_end_month"], r["typical_end_day"])
        print(f"    {r['display_name']:<28}{label:<18} {win}")


def cmd_calendar(conn, city):
    where, args = city_filter(city)
    sql = f"""
        SELECT * FROM v_city_microseasons
        WHERE typical_start_month IS NOT NULL{where}
        ORDER BY city_slug, typical_start_month, typical_start_day, display_name
    """
    current_city = None
    for r in conn.execute(sql, args):
        if r["city_slug"] != current_city:
            current_city = r["city_slug"]
            print(f"\n=== {r['city_name']} ===")
        win = fmt_window(r["typical_start_month"], r["typical_start_day"],
                         r["typical_end_month"], r["typical_end_day"])
        print(f"  {win:<22} {r['display_name']:<28} [{r['category']}]")


def cmd_series(conn, _city):
    sql = """
        SELECT s.key, s.name, s.is_alternating, m.series_order, m.series_label,
               m.canonical_name
        FROM series s
        LEFT JOIN microseasons m ON m.series_id = s.id
        ORDER BY s.key, m.series_order
    """
    current = None
    for r in conn.execute(sql):
        if r["key"] != current:
            current = r["key"]
            alt = " (alternating)" if r["is_alternating"] else ""
            print(f"\n[{r['key']}] {r['name']}{alt}")
        if r["canonical_name"]:
            print(f"  {r['series_order']}. {r['canonical_name']:<28} "
                  f"{r['series_label'] or ''}")


def cmd_overlaps(conn, city):
    args = []
    where = ""
    if city:
        where = "WHERE c.slug = ?"
        args = [city]
    sql = f"""
        SELECT c.slug AS city_slug, c.name AS city_name,
               COALESCE(oa.local_name, ma.canonical_name) AS a_name,
               COALESCE(ob.local_name, mb.canonical_name) AS b_name,
               o.note
        FROM microseason_overlaps o
        JOIN microseason_occurrences oa ON oa.id = o.a_occurrence_id
        JOIN microseason_occurrences ob ON ob.id = o.b_occurrence_id
        JOIN microseasons ma ON ma.id = oa.microseason_id
        JOIN microseasons mb ON mb.id = ob.microseason_id
        JOIN cities c ON c.id = oa.city_id
        {where}
        ORDER BY c.slug, a_name, b_name
    """
    current_city = None
    for r in conn.execute(sql, args):
        if r["city_slug"] != current_city:
            current_city = r["city_slug"]
            print(f"\n=== {r['city_name']} ===")
        print(f"  {r['a_name']}  <->  {r['b_name']}")
        if r["note"]:
            print(f"      {r['note']}")


def cmd_rain(conn, city):
    print("\n[intensity]  (universal)")
    for r in conn.execute(
        "SELECT canonical_name, intensity_rank, precip_rate_in_per_hr_min, "
        "precip_rate_in_per_hr_max FROM precipitation_types "
        "WHERE kind='intensity' ORDER BY intensity_rank"
    ):
        rng = ""
        if r["precip_rate_in_per_hr_min"] is not None and r["precip_rate_in_per_hr_max"] is not None:
            rng = f"  {r['precip_rate_in_per_hr_min']:.3f}–{r['precip_rate_in_per_hr_max']:.3f} in/hr"
        rank = r["intensity_rank"] if r["intensity_rank"] is not None else "?"
        print(f"  {rank:>2}. {r['canonical_name']:<20}{rng}")

    print("\n[pattern]  (city-scoped)")
    if city:
        sql = ("SELECT p.canonical_name, c.slug AS city_slug FROM precipitation_pattern_cities pc "
               "JOIN precipitation_types p ON p.id = pc.precipitation_type_id "
               "JOIN cities c ON c.id = pc.city_id WHERE c.slug = ? ORDER BY p.canonical_name")
        for r in conn.execute(sql, [city]):
            print(f"  - {r['canonical_name']}  ({r['city_slug']})")
    else:
        sql = ("SELECT p.canonical_name, GROUP_CONCAT(c.slug, ', ') AS cities "
               "FROM precipitation_types p "
               "LEFT JOIN precipitation_pattern_cities pc ON pc.precipitation_type_id = p.id "
               "LEFT JOIN cities c ON c.id = pc.city_id "
               "WHERE p.kind='pattern' GROUP BY p.id ORDER BY p.canonical_name")
        for r in conn.execute(sql):
            cities_label = r["cities"] or "(no city subscribed)"
            print(f"  - {r['canonical_name']:<25} -> {cities_label}")


def cmd_cities(conn, _city):
    # Catalog-aware: child cities show inherited occurrence count + parent slug.
    sql = """
        SELECT c.slug, c.name, c.latitude, c.longitude,
               (SELECT slug FROM cities WHERE id = c.parent_city_id) AS parent_slug,
               (SELECT COUNT(*) FROM microseason_occurrences o
                 WHERE o.city_id = COALESCE(c.parent_city_id, c.id)) AS n_occurrences
        FROM cities c
        ORDER BY c.slug
    """
    print(f"  {'slug':<18} {'name':<22} {'lat':>8} {'lng':>10}  occ  inherits")
    for r in conn.execute(sql):
        inh = f"← {r['parent_slug']}" if r["parent_slug"] else ""
        print(f"  {r['slug']:<18} {r['name']:<22} {r['latitude']:>8.4f} "
              f"{r['longitude']:>10.4f}  {r['n_occurrences']:>3}  {inh}")


def cmd_concepts(conn, _city):
    sql = """
        SELECT
            m.canonical_name,
            m.category,
            m.series_label,
            (SELECT GROUP_CONCAT(c.slug, ', ')
               FROM microseason_occurrences o
               JOIN cities c ON c.id = o.city_id
              WHERE o.microseason_id = m.id
              ORDER BY c.slug)                       AS cities,
            (SELECT COUNT(*) FROM microseason_occurrences o
              WHERE o.microseason_id = m.id)         AS n_cities,
            (SELECT GROUP_CONCAT(a.alias, ', ')
               FROM microseason_aliases a
              WHERE a.microseason_id = m.id
              ORDER BY a.alias)                      AS aliases
        FROM microseasons m
        ORDER BY n_cities DESC, m.canonical_name
    """
    print(f"  {'concept':<26} {'category':<18} {'#cities':>7}  cities")
    for r in conn.execute(sql):
        label = f" [{r['series_label']}]" if r["series_label"] else ""
        print(f"  {r['canonical_name']+label:<26} {r['category']:<18} "
              f"{r['n_cities']:>7}  {r['cities'] or '(no occurrences)'}")
        if r["aliases"]:
            print(f"      aliases: {r['aliases']}")


def cmd_compare(conn, _city, concept_name):
    # Fuzzy match: strip apostrophes, allow LIKE, fall back to alias.
    needle = concept_name.replace("'", "").replace("'", "")
    sql = """
        SELECT * FROM v_city_microseasons
        WHERE REPLACE(REPLACE(canonical_name, '''', ''), '''', '') LIKE ? COLLATE NOCASE
           OR canonical_name IN (
                SELECT m.canonical_name FROM microseasons m
                JOIN microseason_aliases a ON a.microseason_id = m.id
                WHERE a.alias LIKE ? COLLATE NOCASE
           )
        ORDER BY city_slug
    """
    like = f"%{needle}%"
    rows = list(conn.execute(sql, [like, like]))
    if not rows:
        print(f"  no concept named {concept_name!r} has occurrences")
        return
    print(f"\nConcept: {rows[0]['canonical_name']}  [{rows[0]['category']}]")
    print(f"  {rows[0]['concept_description'] or ''}")
    for r in rows:
        print(f"\n  -- {r['city_name']} --")
        win = fmt_window(r["typical_start_month"], r["typical_start_day"],
                         r["typical_end_month"], r["typical_end_day"])
        print(f"     window:   {win}")
        if r["temp_min_f"] is not None or r["temp_max_f"] is not None:
            tmin = f"{r['temp_min_f']:.0f}" if r["temp_min_f"] is not None else "?"
            tmax = f"{r['temp_max_f']:.0f}" if r["temp_max_f"] is not None else "?"
            print(f"     temp:     {tmin}–{tmax} °F")
        if r["conditions_json"]:
            print(f"     conds:    {r['conditions_json']}")
        if r["triggers"]:
            print(f"     trigger:  {r['triggers']}")
        if r["climate_drivers_json"]:
            print(f"     drivers:  {r['climate_drivers_json']}")
        if r["local_description"]:
            print(f"     local:    {r['local_description']}")


def cmd_find(conn, _city, query):
    like = f"%{query}%"
    sql = """
        SELECT m.canonical_name, m.category, m.series_label,
               GROUP_CONCAT(DISTINCT a.alias) AS aliases,
               GROUP_CONCAT(DISTINCT c.slug)  AS cities
        FROM microseasons m
        LEFT JOIN microseason_aliases a ON a.microseason_id = m.id
        LEFT JOIN microseason_occurrences o ON o.microseason_id = m.id
        LEFT JOIN cities c ON c.id = o.city_id
        WHERE m.canonical_name LIKE ? COLLATE NOCASE
           OR EXISTS (SELECT 1 FROM microseason_aliases x
                      WHERE x.microseason_id = m.id AND x.alias LIKE ? COLLATE NOCASE)
        GROUP BY m.id
        ORDER BY m.canonical_name
    """
    rows = list(conn.execute(sql, (like, like)))
    if not rows:
        print(f"  no concept matches {query!r}")
        return
    for r in rows:
        label = f"  [{r['series_label']}]" if r["series_label"] else ""
        print(f"  {r['canonical_name']}{label}  ({r['category']})")
        if r["aliases"]:
            print(f"      aliases: {r['aliases']}")
        if r["cities"]:
            print(f"      cities:  {r['cities']}")


def cmd_normals(conn, city):
    # Catalog-aware: child cities show parent's normals; the (inherited)
    # banner makes the inheritance visible.
    where, args = ("WHERE vc.city_slug = ?", [city]) if city else ("", [])
    sql = f"""
        SELECT vc.city_slug                                  AS city_slug,
               vc.city_name                                  AS city_name,
               (vc.city_id != vc.catalog_city_id)            AS inherited,
               (SELECT slug FROM cities WHERE id = vc.catalog_city_id) AS parent_slug,
               n.month, n.temp_max_avg_f, n.temp_min_avg_f, n.temp_mean_f,
               n.precip_total_in, n.precip_days, n.snow_total_in, n.sun_pct,
               n.period_start_year, n.period_end_year, n.source
        FROM v_catalog_city vc
        JOIN city_climate_normals n ON n.city_id = vc.catalog_city_id
        {where}
        ORDER BY vc.city_slug, n.month
    """
    current_city = None
    for r in conn.execute(sql, args):
        if r["city_slug"] != current_city:
            current_city = r["city_slug"]
            period = ""
            if r["period_start_year"] and r["period_end_year"]:
                period = f"  ({r['period_start_year']}–{r['period_end_year']})"
            inh = f"  (inherited from {r['parent_slug']})" if r["inherited"] else ""
            print(f"\n=== {r['city_name']}{period}{inh} ===")
            if r["source"]:
                print(f"    source: {r['source']}")
            print(f"    {'mo':<4}{'hi':>5}{'lo':>5}{'mean':>6}{'precip':>9}"
                  f"{'rainy':>7}{'snow':>6}{'sun%':>6}")
        snow = f"{r['snow_total_in']:.1f}\"" if r["snow_total_in"] is not None else "  -"
        sun = f"{r['sun_pct']}" if r["sun_pct"] is not None else "  -"
        rainy = f"{r['precip_days']:.0f}" if r["precip_days"] is not None else "  -"
        precip = f"{r['precip_total_in']:.1f}\"" if r["precip_total_in"] is not None else "  -"
        print(f"    {MONTHS[r['month']]:<4}{r['temp_max_avg_f']:>5.0f}"
              f"{r['temp_min_avg_f']:>5.0f}{r['temp_mean_f']:>6.0f}"
              f"{precip:>9}{rainy:>7}{snow:>6}{sun:>6}")


def cmd_anomaly(conn, city):
    where, args = (" AND city_slug = ?", [city]) if city else ("", [])
    sql = f"""
        SELECT * FROM v_occurrence_vs_normals
        WHERE (high_anomaly_f IS NOT NULL OR low_anomaly_f IS NOT NULL){where}
        ORDER BY city_slug, ABS(COALESCE(high_anomaly_f, 0)) DESC, display_name
    """
    current_city = None
    print(f"\n  microseason          start  defines        vs. normal      delta")
    print(f"  -------------------  -----  -------------  --------------  -----")
    for r in conn.execute(sql, args):
        if r["city_slug"] != current_city:
            current_city = r["city_slug"]
            print(f"\n  === {r['city_name']} ===")
        mo = MONTHS[r["start_month"]] if r["start_month"] else "?"
        defines = ""
        if r["temp_min_f"] is not None and r["temp_max_f"] is not None:
            defines = f"{r['temp_min_f']:.0f}–{r['temp_max_f']:.0f}°F"
        elif r["temp_max_f"] is not None:
            defines = f"≤{r['temp_max_f']:.0f}°F"
        elif r["temp_min_f"] is not None:
            defines = f"≥{r['temp_min_f']:.0f}°F"
        normal = f"{r['normal_low_f']:.0f}–{r['normal_high_f']:.0f}°F"
        # Show the more dramatic anomaly
        delta_parts = []
        if r["high_anomaly_f"] is not None:
            delta_parts.append(f"hi {r['high_anomaly_f']:+.0f}")
        if r["low_anomaly_f"] is not None:
            delta_parts.append(f"lo {r['low_anomaly_f']:+.0f}")
        delta = "  ".join(delta_parts)
        print(f"  {r['display_name']:<20} {mo:<5}  {defines:<13}  {normal:<14}  {delta}")


def cmd_propose(conn, city, args):
    """
    propose <month> <high> [<low>] [--precip N] [--smoke] [--snow N]
            [--cloud N] [--prior-overcast N] [--day D]

    Match observed conditions to existing microseason occurrences in a city.
    Returns three tiers: primary (weather-of-the-day), secondary
    (background constants in window), triggered (signal-driven). If the
    observation is far from normal, also suggests defining a new concept.
    """
    if not city:
        sys.exit("propose requires --city <slug>")
    if len(args) < 2:
        sys.exit("propose: need at least <month> and <high_f>")

    # Parse positionals + flags
    pos: list[str] = []
    flags: dict[str, str | bool] = {}
    it = iter(args)
    for tok in it:
        if tok == "--smoke":
            flags["smoke"] = True
        elif tok == "--precip":
            flags["precip"] = next(it, "0")
        elif tok == "--snow":
            flags["snow"] = next(it, "0")
        elif tok == "--cloud":
            flags["cloud"] = next(it, "100")
        elif tok == "--prior-overcast":
            flags["prior_overcast"] = next(it, "0")
        elif tok == "--day":
            flags["day"] = next(it, _date.today().isoformat())
        else:
            pos.append(tok)

    try:
        month = int(pos[0])
        obs_high = float(pos[1])
        obs_low = float(pos[2]) if len(pos) > 2 else None
    except ValueError:
        sys.exit("propose: month must be 1..12 and temps must be numeric")
    if not 1 <= month <= 12:
        sys.exit("propose: month out of range")
    precip = float(flags.get("precip", 0) or 0)
    snow = float(flags.get("snow", 0) or 0)
    smoke = bool(flags.get("smoke", False))
    cloud = float(flags["cloud"]) if "cloud" in flags else None
    prior_overcast = int(flags.get("prior_overcast", 0) or 0)

    city_row = conn.execute("SELECT id, name, latitude FROM cities WHERE slug = ?", [city]).fetchone()
    if not city_row:
        sys.exit(f"unknown city: {city}")

    # Solar elevation: defaults to the 15th of the given month if no --day.
    when = _date.fromisoformat(flags["day"]) if "day" in flags else _date(_date.today().year, month, 15)
    solar_elev = solar.max_solar_elevation_deg(city_row["latitude"], when)

    inp = classify.ObservationIn(
        city_slug=city,
        month=month,
        temp_high_f=obs_high,
        temp_low_f=obs_low,
        precip_in=precip,
        snow_in=snow,
        cloud_cover_mean_pct=cloud,
        smoke=smoke,
        solar_elevation_max_deg=solar_elev,
        prior_overcast_days=prior_overcast,
    )
    result = classify.classify_observation(conn, inp)

    print(f"\nObserved ({city_row['name']}, {MONTHS[month]}):")
    print(f"  high: {obs_high:.0f}°F" + (f"   low: {obs_low:.0f}°F" if obs_low is not None else ""))
    if precip:                print(f"  precip: {precip:.2f} in")
    if snow:                  print(f"  snow:   {snow:.2f} in")
    if smoke:                 print(f"  smoke:  present (PM2.5 ≥ {classify.SMOKE_PM25_UG_M3:.0f} µg/m³)")
    if cloud is not None:     print(f"  cloud:  {cloud:.0f}%   prior overcast days: {prior_overcast}")
    print(f"  solar elev (noon): {solar_elev:.1f}°  ({when.isoformat()})")

    if result.anomaly.normal_high_f is not None:
        a = result.anomaly
        print(f"\nNormal for {MONTHS[month]} in {city_row['name']}:")
        print(f"  {a.normal_low_f:.0f}–{a.normal_high_f:.0f}°F   precip {a.normal_precip_in:.1f}\"")
        bits = []
        if a.high_anomaly_f is not None: bits.append(f"high {a.high_anomaly_f:+.0f}°F")
        if a.low_anomaly_f is not None:  bits.append(f"low {a.low_anomaly_f:+.0f}°F")
        if bits: print(f"  anomaly: {'  '.join(bits)}")

    _print_classification(result)


def _print_classification(result: classify.ClassifyResult) -> None:
    def section(title: str, matches: list[classify.Match]) -> None:
        if not matches:
            return
        print(f"\n{title}:")
        for m in matches:
            label = f" [{m.series_label}]" if m.series_label else ""
            conf = f"  (conf {m.confidence:.1f})" if m.confidence < 0.5 else ""
            print(f"  - {m.display_name}{label}  ({m.category}){conf}")
            if m.reason:
                print(f"      {m.reason}")

    if result.is_aberration:
        print("\n*** ABERRATION DAY ***")
        print(f"  {result.aberration_reason}")
        print("  Primary matches downgraded to transient confidence; "
              "new-microseason proposal suppressed.")

    if not (result.primary or result.secondary or result.triggered):
        print("\nMatches: (none)")
    section("PRIMARY (weather classification)", result.primary)
    section("TRIGGERED (signal-driven events)", result.triggered)
    section("SECONDARY (background traits active)", result.secondary)

    if result.out_of_window_temp_fit:
        names = ", ".join(m.display_name for m in result.out_of_window_temp_fit[:6])
        print(f"\n  (temperature also fits, outside typical window: {names})")

    if result.proposed_new_bits:
        header = ("\nWorth considering a new microseason concept:"
                  if result.primary else "\nProposed new microseason:")
        print(header)
        for b in result.proposed_new_bits:
            print(f"  • {b}")
        if result.naming_suggestions:
            print("Naming suggestions:")
            for n in result.naming_suggestions:
                print(f"  - {n}")
        print("\nTo codify, add a concept to data/microseasons.yaml and an "
              "occurrence to data/cities/<slug>.yaml.")


def cmd_last_seen(conn, city, rest=None):
    """Show, per microseason in the city, when it was last observed.

    By default excludes transient/aberration-day matches (those with
    confidence < 0.5). Pass `all` as a positional arg to include them.
    """
    if not city:
        sys.exit("last-seen requires --city <slug>")
    include_all = bool(rest) and rest[0] == "all"
    # Aggregate at query time so we can filter by confidence + aberration flag.
    sql = f"""
        SELECT
            COALESCE(occ.local_name, m.canonical_name)        AS display_name,
            m.series_label,
            om.tier,
            MIN(o.observed_date)                              AS first_seen_date,
            MAX(o.observed_date)                              AS last_seen_date,
            COUNT(*)                                          AS days_observed,
            SUM(o.is_aberration)                              AS aberration_days
        FROM observation_microseasons om
        JOIN observations o            ON o.id   = om.observation_id
        JOIN microseason_occurrences occ ON occ.id = om.occurrence_id
        JOIN microseasons m            ON m.id   = occ.microseason_id
        JOIN cities c                  ON c.id   = o.city_id
        WHERE c.slug = ?
          { "" if include_all else "AND (om.confidence IS NULL OR om.confidence >= 0.5) AND o.is_aberration = 0" }
        GROUP BY occ.id, om.tier
        ORDER BY last_seen_date DESC, display_name
    """
    rows = list(conn.execute(sql, [city]))
    if not rows:
        if include_all:
            print("  no observations yet. Run: uv run scripts/fetch_weather.py "
                  f"--city {city} --days 30")
        else:
            print("  no high-confidence observations yet. "
                  "Pass `all` to include transient/aberration matches.")
        return
    if not include_all:
        print(f"  (excluding transient + aberration days; pass `all` to include)")
    print(f"\n  {'microseason':<25}  {'tier':<10}  {'last seen':<12}  {'first seen':<12}  days  aberr")
    print(f"  {'-'*25}  {'-'*10}  {'-'*12}  {'-'*12}  ----  -----")
    for r in rows:
        label = f"  [{r['series_label']}]" if r["series_label"] else ""
        print(f"  {(r['display_name']+label):<25}  {r['tier']:<10}  "
              f"{r['last_seen_date']:<12}  {r['first_seen_date']:<12}  "
              f"{r['days_observed']:>4}  {r['aberration_days']:>5}")


def cmd_aberrations(conn, city):
    """List recent aberration days (statistical outliers) for inspection."""
    if not city:
        sys.exit("aberrations requires --city <slug>")
    sql = """
        SELECT o.observed_date, o.temp_high_f, o.temp_low_f,
               o.precip_in, o.snow_in, o.smoke, o.aberration_reason
        FROM observations o
        JOIN cities c ON c.id = o.city_id
        WHERE c.slug = ? AND o.is_aberration = 1
        ORDER BY o.observed_date DESC
    """
    rows = list(conn.execute(sql, [city]))
    if not rows:
        print("  no aberrations recorded.")
        return
    print(f"\n  {'date':<12}  conditions                                  reason")
    print(f"  {'-'*12}  {'-'*42}  ------")
    for r in rows:
        bits = []
        if r["temp_high_f"] is not None:
            bits.append(f"hi {r['temp_high_f']:.0f}°F")
        if r["temp_low_f"] is not None:
            bits.append(f"lo {r['temp_low_f']:.0f}°F")
        if (r["precip_in"] or 0) > 0:
            bits.append(f"precip {r['precip_in']:.2f}\"")
        if (r["snow_in"] or 0) > 0:
            bits.append(f"snow {r['snow_in']:.2f}\"")
        if r["smoke"]:
            bits.append("smoke")
        conds = " ".join(bits)
        print(f"  {r['observed_date']:<12}  {conds:<42}  {r['aberration_reason'] or ''}")


def cmd_active(conn, city):
    """Show today's most recent classification(s) from observations."""
    if not city:
        sys.exit("active requires --city <slug>")
    row = conn.execute(
        "SELECT id, observed_date FROM observations "
        "WHERE city_id = (SELECT id FROM cities WHERE slug = ?) "
        "ORDER BY observed_date DESC LIMIT 1",
        [city],
    ).fetchone()
    if not row:
        print(f"  no observations recorded for {city}. Run fetch_weather first.")
        return
    obs_id = row["id"]
    obs_date = row["observed_date"]
    detail = conn.execute(
        "SELECT * FROM observations WHERE id = ?", [obs_id]
    ).fetchone()
    print(f"\n  Most recent observation: {obs_date}")
    bits = []
    if detail["temp_high_f"] is not None:
        bits.append(f"hi {detail['temp_high_f']:.0f}°F")
    if detail["temp_low_f"] is not None:
        bits.append(f"lo {detail['temp_low_f']:.0f}°F")
    if detail["cloud_cover_mean_pct"] is not None:
        bits.append(f"cloud {detail['cloud_cover_mean_pct']:.0f}%")
    if (detail["precip_in"] or 0) > 0:
        bits.append(f"precip {detail['precip_in']:.2f}\"")
    if (detail["snow_in"] or 0) > 0:
        bits.append(f"snow {detail['snow_in']:.2f}\"")
    if detail["smoke"]:
        bits.append(f"smoke (PM2.5 {detail['pm25_ug_m3']:.0f})")
    if detail["solar_elevation_max_deg"] is not None:
        bits.append(f"solar elev {detail['solar_elevation_max_deg']:.0f}°")
    print(f"  {' / '.join(bits)}")
    if detail["is_aberration"]:
        print(f"\n  *** ABERRATION DAY ***  {detail['aberration_reason']}")
        print(f"  Primary matches below are TRANSIENT (low confidence).")

    for tier in ("primary", "triggered", "secondary"):
        rows = list(conn.execute(
            """
            SELECT COALESCE(occ.local_name, m.canonical_name) AS display_name,
                   m.canonical_name, m.category, om.reason
            FROM observation_microseasons om
            JOIN microseason_occurrences occ ON occ.id = om.occurrence_id
            JOIN microseasons m ON m.id = occ.microseason_id
            WHERE om.observation_id = ? AND om.tier = ?
            ORDER BY display_name
            """,
            [obs_id, tier],
        ))
        if not rows:
            continue
        print(f"\n  [{tier.upper()}]")
        for r in rows:
            print(f"    - {r['display_name']}  ({r['category']})")
            if r["reason"]:
                print(f"        {r['reason']}")


def parse_args(argv: list[str]) -> tuple[str | None, str, list[str]]:
    args = argv[1:]
    city = None
    if args and args[0] == "--city":
        if len(args) < 2:
            sys.exit("--city requires a slug")
        city = args[1]
        args = args[2:]
    cmd = args[0] if args else "all"
    rest = args[1:]
    return city, cmd, rest


def main(argv: list[str]) -> int:
    city, cmd, rest = parse_args(argv)
    handlers = {
        "all": cmd_all,
        "calendar": cmd_calendar,
        "series": cmd_series,
        "overlaps": cmd_overlaps,
        "rain": cmd_rain,
        "cities": cmd_cities,
        "concepts": cmd_concepts,
        "normals": cmd_normals,
        "anomaly": cmd_anomaly,
        "active": cmd_active,
        "aberrations": cmd_aberrations,
    }
    conn = open_db()
    try:
        if cmd in handlers:
            handlers[cmd](conn, city)
        elif cmd == "last-seen":
            cmd_last_seen(conn, city, rest)
        elif cmd == "find" and rest:
            cmd_find(conn, city, rest[0])
        elif cmd == "compare" and rest:
            cmd_compare(conn, city, " ".join(rest))
        elif cmd == "propose":
            cmd_propose(conn, city, rest)
        else:
            print(__doc__)
            return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
