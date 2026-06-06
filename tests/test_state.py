"""Tests for the presentation catalog and the render-model DTO builder.

Guards the contract that the markdown report, the JSON serving layer, and any
display client all depend on:
  - presentation.yaml stays the single source for emoji (no drift vs report).
  - build_state() produces a stable, JSON-serialisable shape.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from juneuary import SCHEMA_VERSION
from juneuary.presentation import emoji_map, presentation_for
from juneuary.state import build_state


# ---------------------------------------------------------------------------
# Presentation source-of-truth guards
# ---------------------------------------------------------------------------

# The emoji table report.py used to hard-code. Pinned here so a careless edit
# to presentation.yaml that changes a published glyph fails loudly.
_EXPECTED_EMOJI = {
    "Find Bananas": "🍌", "Paralyzing Snow": "🚌", "Winter": "❄️",
    "Second Winter": "🥶", "Third Winter": "🌨️", "Fool's Spring": "🌤️",
    "Spring of Deception": "🌸", "The Pollening": "🤧", "Actual Spring": "🌷",
    "Juneuary": "🌫️", "Summer": "☀️", "Hell's Front Porch": "🔥",
    "Oppressive Sun": "🫠", "False Fall": "🍂", "Second Summer": "🌅",
    "Actual Fall": "🍁", "The Grey": "🩶", "The Long Dark": "🌑",
    "The Dark Wet": "🌧️", "Brightening Wet": "🌦️", "Molding Wet": "🫠",
    "Flowering Wet": "🌺", "Welcome Drizzle": "🌧️", "Praise the Sun": "🌞",
    "Glorious Sun": "☀️", "Photon Fraud": "🌥️", "Smogust": "🌫️",
    "Smoketember": "🔥", "Choking Smoke": "😷", "Convergence Zones": "⚡",
    "Spider Season": "🕷️",
}


def test_emoji_map_preserves_published_glyphs():
    """presentation.yaml must keep every emoji the report previously shipped."""
    em = emoji_map()
    for name, glyph in _EXPECTED_EMOJI.items():
        assert em.get(name) == glyph, f"{name} emoji drifted"


def test_presentation_has_color_and_glyph():
    p = presentation_for("Winter")
    assert p.emoji == "❄️"
    assert p.color.startswith("#") and len(p.color) == 7
    assert p.glyph


def test_presentation_unknown_concept_falls_back():
    p = presentation_for("Definitely Not A Microseason")
    assert p.emoji == ""
    assert p.color.startswith("#")


# ---------------------------------------------------------------------------
# build_state() against a minimal in-memory DB
# ---------------------------------------------------------------------------

def _seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE cities (id INTEGER PRIMARY KEY, slug TEXT, name TEXT,
                             latitude REAL, longitude REAL);
        CREATE TABLE series (id INTEGER PRIMARY KEY, key TEXT, name TEXT);
        CREATE TABLE microseasons (id INTEGER PRIMARY KEY, canonical_name TEXT,
                                   category TEXT, series_id INTEGER,
                                   series_order INTEGER, series_label TEXT);
        CREATE TABLE microseason_occurrences (id INTEGER PRIMARY KEY,
                                   microseason_id INTEGER, city_id INTEGER,
                                   local_name TEXT);
        CREATE TABLE observations (id INTEGER PRIMARY KEY, city_id INTEGER,
                                   observed_date TEXT, temp_high_f REAL,
                                   temp_low_f REAL, precip_in REAL, snow_in REAL,
                                   is_aberration INTEGER, aberration_reason TEXT);
        CREATE TABLE observation_microseasons (observation_id INTEGER,
                                   occurrence_id INTEGER, tier TEXT,
                                   confidence REAL, reason TEXT);
        """
    )
    conn.execute("INSERT INTO cities VALUES (1,'seattle','Seattle',47.6,-122.3)")
    conn.execute("INSERT INTO series VALUES (1,'spring','Spring')")
    conn.execute("INSERT INTO microseasons (id,canonical_name,category,series_id,"
                 "series_order,series_label) VALUES "
                 "(10,'Fool''s Spring','series',1,1,'spring1')")
    conn.execute("INSERT INTO microseasons (id,canonical_name,category) VALUES "
                 "(11,'Find Bananas','triggered_event')")
    conn.execute("INSERT INTO microseason_occurrences VALUES (100,10,1,NULL)")
    conn.execute("INSERT INTO microseason_occurrences VALUES (101,11,1,NULL)")
    conn.execute(
        "INSERT INTO observations VALUES "
        "(1000,1,'2026-02-14',61,44,0.0,0.0,0,NULL)"
    )
    conn.execute(
        "INSERT INTO observation_microseasons VALUES "
        "(1000,100,'primary',0.8,'high 61F in range')"
    )
    conn.execute(
        "INSERT INTO observation_microseasons VALUES "
        "(1000,101,'triggered',0.95,'snow in forecast')"
    )
    conn.commit()
    return conn


def test_build_state_shape_and_headline():
    conn = _seed_db()
    state = build_state(conn, "seattle")
    assert state is not None
    assert state.schema_version == SCHEMA_VERSION
    assert state.location.name == "Seattle"
    assert state.as_of == "2026-02-14"
    assert state.current.temp_high_f == 61
    assert [v.canonical_name for v in state.current.primary] == ["Fool's Spring"]
    assert [v.canonical_name for v in state.current.triggered] == ["Find Bananas"]
    # headline = highest-confidence primary, decorated with emoji from YAML
    assert state.current.headline.canonical_name == "Fool's Spring"
    assert state.current.headline.emoji == "🌤️"


def test_build_state_to_dict_is_json_serialisable():
    conn = _seed_db()
    state = build_state(conn, "seattle")
    blob = json.dumps(state.to_dict(), ensure_ascii=False)
    parsed = json.loads(blob)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["current"]["headline"]["color"].startswith("#")
    assert parsed["forecast"] == []


def test_build_state_returns_none_without_observations():
    conn = _seed_db()
    conn.execute("DELETE FROM observations")
    conn.commit()
    assert build_state(conn, "seattle") is None


def test_build_state_unknown_city_raises():
    conn = _seed_db()
    with pytest.raises(ValueError):
        build_state(conn, "atlantis")
