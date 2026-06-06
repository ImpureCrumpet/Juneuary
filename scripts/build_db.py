"""Build db/microseasons.db from data/*.yaml + data/cities/*.yaml.

Concept/occurrence split:
  - data/microseasons.yaml      : concepts (city-independent)
  - data/precipitation.yaml     : global precipitation vocabulary
  - data/cities.yaml            : city metadata
  - data/cities/<slug>.yaml     : occurrences, overlaps, precipitation_patterns

Idempotent: drops and rebuilds the DB on every run.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CITIES_DIR = DATA / "cities"
DB_DIR = ROOT / "db"
DB_PATH = DB_DIR / "microseasons.db"
SCHEMA_PATH = DB_DIR / "schema.sql"

CITIES_YAML = DATA / "cities.yaml"
CITIES_LOCAL_YAML = DATA / "cities.local.yaml"   # gitignored, optional


def slugify(value: str) -> str:
    s = value.lower()
    s = re.sub(r"['']", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def jblob(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def clean(s: Any) -> str | None:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def init_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _load_city_specs() -> tuple[list[dict], int]:
    """Tracked cities.yaml + optional gitignored cities.local.yaml.

    Local entries are appended after public ones; duplicate slugs raise.
    Neighborhood / grid-cell / per-ZIP entries belong in the local file
    so they never get committed (see data/cities.local.example.yaml).
    Returns (entries, n_local).
    """
    public = load_yaml(CITIES_YAML) or []
    if not CITIES_LOCAL_YAML.exists():
        return public, 0
    local = load_yaml(CITIES_LOCAL_YAML) or []
    seen = {c["slug"]: "cities.yaml" for c in public}
    for c in local:
        if c["slug"] in seen:
            raise ValueError(
                f"city {c['slug']!r} declared in both {seen[c['slug']]} and "
                f"cities.local.yaml — pick one"
            )
        seen[c["slug"]] = "cities.local.yaml"
    return public + local, len(local)


def insert_cities(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[str, str], int]:
    """Insert cities; return (slug→id, child_slug→parent_slug, n_local).

    Two passes: first INSERT every city with parent_city_id NULL, then UPDATE
    children to point at their parent. This avoids ordering constraints in
    cities.yaml and lets cities.local.yaml children reference tracked parents.
    """
    rows, n_local = _load_city_specs()
    ids: dict[str, int] = {}
    children: dict[str, str] = {}
    for c in rows:
        cur = conn.execute(
            "INSERT INTO cities (slug, name, latitude, longitude, notes) "
            "VALUES (:slug, :name, :latitude, :longitude, :notes)",
            {
                "slug": c["slug"],
                "name": c["name"],
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "notes": clean(c.get("notes")),
            },
        )
        ids[c["slug"]] = cur.lastrowid
        if c.get("parent_slug"):
            children[c["slug"]] = c["parent_slug"]

    for child_slug, parent_slug in children.items():
        if parent_slug not in ids:
            raise ValueError(
                f"city {child_slug!r} declares parent_slug={parent_slug!r} "
                f"which isn't in data/cities.yaml"
            )
        if parent_slug == child_slug:
            raise ValueError(f"city {child_slug!r} can't be its own parent")
        conn.execute(
            "UPDATE cities SET parent_city_id = ? WHERE id = ?",
            [ids[parent_slug], ids[child_slug]],
        )
    return ids, children, n_local


def insert_series(conn: sqlite3.Connection) -> dict[str, int]:
    rows = load_yaml(DATA / "series.yaml") or []
    ids: dict[str, int] = {}
    for s in rows:
        cur = conn.execute(
            "INSERT INTO series (key, name, description, is_alternating) "
            "VALUES (:key, :name, :description, :is_alternating)",
            {
                "key": s["key"],
                "name": s["name"],
                "description": clean(s.get("description")),
                "is_alternating": 1 if s.get("is_alternating") else 0,
            },
        )
        ids[s["key"]] = cur.lastrowid
    return ids


def insert_microseason_concepts(
    conn: sqlite3.Connection,
    series_ids: dict[str, int],
) -> dict[str, int]:
    rows = load_yaml(DATA / "microseasons.yaml") or []
    name_to_id: dict[str, int] = {}
    for m in rows:
        series_key = m.get("series")
        if series_key and series_key not in series_ids:
            raise ValueError(f"Microseason {m['canonical_name']!r} references unknown series {series_key!r}")
        cur = conn.execute(
            """
            INSERT INTO microseasons (
                canonical_name, slug, category,
                series_id, series_order, series_label,
                description, notes
            ) VALUES (
                :canonical_name, :slug, :category,
                :series_id, :series_order, :series_label,
                :description, :notes
            )
            """,
            {
                "canonical_name": m["canonical_name"],
                "slug": slugify(m["canonical_name"]),
                "category": m["category"],
                "series_id": series_ids[series_key] if series_key else None,
                "series_order": m.get("series_order"),
                "series_label": m.get("series_label"),
                "description": clean(m.get("description")),
                "notes": clean(m.get("notes")),
            },
        )
        mid = cur.lastrowid
        name_to_id[m["canonical_name"]] = mid
        for alias in m.get("aliases", []) or []:
            conn.execute(
                "INSERT INTO microseason_aliases (microseason_id, alias) VALUES (?, ?)",
                (mid, alias),
            )
    return name_to_id


def insert_precipitation(conn: sqlite3.Connection) -> dict[str, int]:
    rows = load_yaml(DATA / "precipitation.yaml") or []
    name_to_id: dict[str, int] = {}
    for p in rows:
        cur = conn.execute(
            """
            INSERT INTO precipitation_types (
                canonical_name, slug, kind, intensity_rank,
                precip_rate_in_per_hr_min, precip_rate_in_per_hr_max,
                description, notes
            ) VALUES (
                :canonical_name, :slug, :kind, :intensity_rank,
                :rmin, :rmax, :description, :notes
            )
            """,
            {
                "canonical_name": p["canonical_name"],
                "slug": slugify(p["canonical_name"]),
                "kind": p["kind"],
                "intensity_rank": p.get("intensity_rank"),
                "rmin": p.get("precip_rate_in_per_hr_min"),
                "rmax": p.get("precip_rate_in_per_hr_max"),
                "description": clean(p.get("description")),
                "notes": clean(p.get("notes")),
            },
        )
        name_to_id[p["canonical_name"]] = cur.lastrowid
    return name_to_id


def insert_climate_normals(
    conn: sqlite3.Connection,
    city_id: int,
    spec: dict | None,
    city_slug: str,
) -> int:
    """Insert monthly climate normals for one city. Returns number of months loaded."""
    if not spec:
        return 0
    period_start = spec.get("period_start_year")
    period_end = spec.get("period_end_year")
    source = clean(spec.get("source"))
    monthly = spec.get("monthly") or {}
    n = 0
    for month_key, vals in monthly.items():
        try:
            month = int(month_key)
        except (TypeError, ValueError):
            raise ValueError(f"{city_slug}: climate_normals.monthly key must be 1..12, got {month_key!r}")
        if not 1 <= month <= 12:
            raise ValueError(f"{city_slug}: climate_normals month out of range: {month}")
        conn.execute(
            """
            INSERT INTO city_climate_normals (
                city_id, month, period_start_year, period_end_year, source,
                temp_max_avg_f, temp_min_avg_f, temp_mean_f,
                precip_total_in, precip_days, snow_total_in,
                sun_pct, cloud_cover_pct,
                temp_record_max_f, temp_record_min_f
            ) VALUES (
                :city_id, :month, :p_start, :p_end, :source,
                :tmax, :tmin, :tmean,
                :ptot, :pdays, :snow,
                :sun, :cloud,
                :rmax, :rmin
            )
            """,
            {
                "city_id": city_id, "month": month,
                "p_start": period_start, "p_end": period_end, "source": source,
                "tmax": vals.get("temp_max_avg_f"),
                "tmin": vals.get("temp_min_avg_f"),
                "tmean": vals.get("temp_mean_f"),
                "ptot": vals.get("precip_total_in"),
                "pdays": vals.get("precip_days"),
                "snow": vals.get("snow_total_in"),
                "sun": vals.get("sun_pct"),
                "cloud": vals.get("cloud_cover_pct"),
                "rmax": vals.get("temp_record_max_f"),
                "rmin": vals.get("temp_record_min_f"),
            },
        )
        n += 1
    return n


def insert_city_files(
    conn: sqlite3.Connection,
    city_ids: dict[str, int],
    children: dict[str, str],
    concept_ids: dict[str, int],
    precip_ids: dict[str, int],
) -> tuple[int, int, int, int]:
    """Process every YAML under data/cities/. Returns (n_occurrences, n_overlaps, n_pattern_links, n_normals_months).

    Child cities (those with parent_slug set in cities.yaml) MAY have their
    own YAML for per-grid normal overrides etc.; if absent, they silently
    inherit everything from the parent via the catalog views.
    """
    n_occ = n_overlap = n_pat = n_normals = 0
    if not CITIES_DIR.exists():
        return 0, 0, 0, 0

    for path in sorted(CITIES_DIR.glob("*.yaml")):
        doc = load_yaml(path)
        if not doc:
            continue
        city_slug = doc["city"]
        if city_slug not in city_ids:
            raise ValueError(f"{path.name}: unknown city {city_slug!r} (add it to data/cities.yaml)")
        if city_slug in children and (doc.get("occurrences") or doc.get("overlaps")):
            raise ValueError(
                f"{path.name}: child city {city_slug!r} (parent_slug={children[city_slug]!r}) "
                f"cannot define its own occurrences/overlaps — those are inherited "
                f"from the parent. Per-grid climate-normal overrides are allowed."
            )
        city_id = city_ids[city_slug]

        # ---- climate normals ----
        n_normals += insert_climate_normals(conn, city_id, doc.get("climate_normals"), city_slug)

        # ---- precipitation pattern scoping ----
        for entry in doc.get("precipitation_patterns") or []:
            pname = entry["name"] if isinstance(entry, dict) else entry
            if pname not in precip_ids:
                raise ValueError(f"{path.name}: unknown precipitation type {pname!r}")
            conn.execute(
                "INSERT OR IGNORE INTO precipitation_pattern_cities "
                "(precipitation_type_id, city_id, note) VALUES (?, ?, ?)",
                (precip_ids[pname], city_id,
                 clean(entry.get("note")) if isinstance(entry, dict) else None),
            )
            n_pat += 1

        # ---- occurrences ----
        occ_by_concept: dict[str, int] = {}
        for o in doc.get("occurrences") or []:
            concept_name = o["microseason"]
            if concept_name not in concept_ids:
                raise ValueError(
                    f"{path.name}: occurrence references unknown concept {concept_name!r}. "
                    f"Add it to data/microseasons.yaml first."
                )
            cur = conn.execute(
                """
                INSERT INTO microseason_occurrences (
                    microseason_id, city_id,
                    typical_start_month, typical_start_day,
                    typical_end_month,   typical_end_day,
                    typical_duration_days,
                    temp_min_f, temp_max_f, conditions_json, triggers,
                    is_nonlinear, can_be_skipped, can_be_amplified,
                    climate_drivers_json,
                    local_name, local_description, notes
                ) VALUES (
                    :microseason_id, :city_id,
                    :typical_start_month, :typical_start_day,
                    :typical_end_month,   :typical_end_day,
                    :typical_duration_days,
                    :temp_min_f, :temp_max_f, :conditions_json, :triggers,
                    :is_nonlinear, :can_be_skipped, :can_be_amplified,
                    :climate_drivers_json,
                    :local_name, :local_description, :notes
                )
                """,
                {
                    "microseason_id": concept_ids[concept_name],
                    "city_id": city_id,
                    "typical_start_month": o.get("typical_start_month"),
                    "typical_start_day": o.get("typical_start_day"),
                    "typical_end_month": o.get("typical_end_month"),
                    "typical_end_day": o.get("typical_end_day"),
                    "typical_duration_days": o.get("typical_duration_days"),
                    "temp_min_f": o.get("temp_min_f"),
                    "temp_max_f": o.get("temp_max_f"),
                    "conditions_json": jblob(o.get("conditions")),
                    "triggers": clean(o.get("triggers")),
                    "is_nonlinear": 1 if o.get("is_nonlinear") else 0,
                    "can_be_skipped": 1 if o.get("can_be_skipped") else 0,
                    "can_be_amplified": 1 if o.get("can_be_amplified") else 0,
                    "climate_drivers_json": jblob(o.get("climate_drivers")),
                    "local_name": clean(o.get("local_name")),
                    "local_description": clean(o.get("local_description")),
                    "notes": clean(o.get("notes")),
                },
            )
            occ_by_concept[concept_name] = cur.lastrowid
            n_occ += 1

        # ---- overlaps (within this city) ----
        for pair in doc.get("overlaps") or []:
            a_name, b_name, *rest = pair
            note = rest[0] if rest else None
            if a_name not in occ_by_concept or b_name not in occ_by_concept:
                missing = [n for n in (a_name, b_name) if n not in occ_by_concept]
                print(
                    f"  WARN: {path.name}: overlap references {missing} which has no "
                    f"occurrence in {city_slug}",
                    file=sys.stderr,
                )
                continue
            a_id = occ_by_concept[a_name]
            b_id = occ_by_concept[b_name]
            lo, hi = sorted((a_id, b_id))
            conn.execute(
                "INSERT OR IGNORE INTO microseason_overlaps "
                "(a_occurrence_id, b_occurrence_id, note) VALUES (?, ?, ?)",
                (lo, hi, note),
            )
            n_overlap += 1

    return n_occ, n_overlap, n_pat, n_normals


def main() -> int:
    conn = init_db()
    try:
        city_ids, children, n_local = insert_cities(conn)
        series_ids = insert_series(conn)
        concept_ids = insert_microseason_concepts(conn, series_ids)
        precip_ids = insert_precipitation(conn)
        n_occ, n_overlap, n_pat, n_normals = insert_city_files(
            conn, city_ids, children, concept_ids, precip_ids
        )
        conn.commit()

        # Per-city summary, counted through the catalog view so children show
        # the inherited count (and we can label the inheritance).
        per_city = conn.execute(
            """
            SELECT c.slug,
                   c.parent_city_id IS NOT NULL                       AS is_child,
                   (SELECT slug FROM cities WHERE id = c.parent_city_id) AS parent_slug,
                   (SELECT COUNT(*) FROM microseason_occurrences o
                     WHERE o.city_id = COALESCE(c.parent_city_id, c.id)) AS n_occ
            FROM cities c
            ORDER BY c.slug
            """
        ).fetchall()
    finally:
        conn.close()

    print(f"Built {DB_PATH.relative_to(ROOT)}")
    local_note = f", {n_local} from cities.local.yaml" if n_local else ""
    print(f"  cities:                  {len(city_ids)}  "
          f"({len(children)} child / grid{local_note})")
    print(f"  series:                  {len(series_ids)}")
    print(f"  microseason concepts:    {len(concept_ids)}")
    print(f"  precipitation types:     {len(precip_ids)}")
    print(f"  occurrences (per city):")
    for slug, is_child, parent_slug, n in per_city:
        suffix = f"  (inherits from {parent_slug})" if is_child else ""
        print(f"    - {slug:<20} {n}{suffix}")
    print(f"  overlaps:                {n_overlap}")
    print(f"  pattern <-> city links:  {n_pat}")
    print(f"  climate-normal months:   {n_normals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
