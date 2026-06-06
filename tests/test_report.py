"""Regression tests for scripts/report.py and the narrative template engine.

Covers the issues flagged in the recent code review:
  B1 — render_season_timeline crashes on null temperatures.
  B2 — _chunk_commentary accesses peak["temp_high_f"] without a guard.
  Idempotency of emojify() (multi-pass safe).
  contiguous_spans correctness.
  When-clause evaluator (_eval_when) operator coverage.
  Template engine concat + branches modes + ref-clause resolution.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from report import (
    Narrative,
    _eval_when,
    build_chunk_features,
    contiguous_spans,
    emojify,
    render_section,
)


# ---------------------------------------------------------------------------
# B1 / B2: chunk-feature builder must survive a chunk where the *peak snow*
# day has no temperature recorded.
# ---------------------------------------------------------------------------

def _row(d: str, hi=None, lo=None, snow=0.0, precip=0.0) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE t (
            observed_date TEXT, temp_high_f REAL, temp_low_f REAL,
            snow_in REAL, precip_in REAL
        )
    """)
    conn.execute(
        "INSERT INTO t VALUES (?, ?, ?, ?, ?)", [d, hi, lo, snow, precip]
    )
    return conn.execute("SELECT * FROM t").fetchone()


def test_chunk_features_returns_none_when_no_temps():
    """B1: a chunk where every day has a null high must not crash."""
    days = [
        _row("2019-02-01", hi=None, lo=None, snow=0.2),
        _row("2019-02-02", hi=None, lo=None),
    ]
    result = build_chunk_features(
        days, classifications=[],
        start_iso="2019-02-01", end_iso="2019-02-02",
        narrative=Narrative(),
    )
    assert result is None


def test_chunk_features_handles_null_temp_on_peak_snow_day():
    """B2: the snow-peak day having a null temp must not crash; renderer
    falls back to the chunk's avg high."""
    days = [
        _row("2019-02-10", hi=35, lo=22, snow=0.5),
        _row("2019-02-11", hi=None, lo=None, snow=6.0),     # null temp + peak snow
        _row("2019-02-12", hi=38, lo=28, snow=0.2),
    ]
    features = build_chunk_features(
        days, classifications=[],
        start_iso="2019-02-10", end_iso="2019-02-12",
        narrative=Narrative(),
    )
    assert features is not None
    assert features["chunk_peak_snow_in"] == 6.0
    # Should not have crashed; the temp string falls back to avg_hi (36/37°F).
    assert features["chunk_peak_snow_temp_str"].endswith("°F")


# ---------------------------------------------------------------------------
# emojify(): idempotent across multiple passes (the negative lookbehind
# guard keeps re-emojification from doubling glyphs).
# ---------------------------------------------------------------------------

def test_emojify_idempotent():
    src = "Today brought **Find Bananas** and **Paralyzing Snow**."
    once = emojify(src)
    twice = emojify(once)
    assert once == twice
    assert once.count("🍌") == 1
    assert once.count("🚌") == 1


def test_emojify_handles_narrative_terms():
    text = "It was **snowmageddon** in February."
    assert "🌨️ **snowmageddon**" in emojify(text)


# ---------------------------------------------------------------------------
# contiguous_spans
# ---------------------------------------------------------------------------

def test_contiguous_spans_simple():
    assert contiguous_spans([]) == []
    assert contiguous_spans(["2026-01-01"]) == [("2026-01-01", "2026-01-01", 1)]
    spans = contiguous_spans(["2026-01-01", "2026-01-02", "2026-01-04"])
    assert spans == [("2026-01-01", "2026-01-02", 2),
                     ("2026-01-04", "2026-01-04", 1)]


# ---------------------------------------------------------------------------
# When-clause evaluator
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("when,features,expected", [
    ({}, {}, True),                                              # empty = always true
    (None, {}, True),                                            # missing = always true
    ({"snow_label_eq": "snowmageddon"},
     {"snow_label": "snowmageddon"}, True),
    ({"snow_label_eq": "snowmageddon"},
     {"snow_label": ""}, False),
    ({"d_hi_lte": -3}, {"d_hi": -5}, True),
    ({"d_hi_lte": -3}, {"d_hi": -2}, False),
    ({"d_hi_lte": -3}, {"d_hi": None}, False),                   # None is safe
    ({"d_hi_gt": 0}, {"d_hi": None}, False),
    ({"snow_label_in": ["snow_siege", "banana_weather"]},
     {"snow_label": "snow_siege"}, True),
    ({"snow_label_in": ["snow_siege", "banana_weather"]},
     {"snow_label": "snowmageddon"}, False),
    ({"has_snow_label_any": True}, {"has_snow_label": True}, True),
    ({"has_snow_label_any": True}, {"has_snow_label": False}, False),
    # AND across multiple conditions
    ({"d_hi_lte": -3, "snow_days_gt": 0},
     {"d_hi": -5, "snow_days": 2}, True),
    ({"d_hi_lte": -3, "snow_days_gt": 0},
     {"d_hi": -5, "snow_days": 0}, False),
])
def test_eval_when(when, features, expected):
    assert _eval_when(when, features) is expected


# ---------------------------------------------------------------------------
# Template engine: concat + branches + ref-clauses
# ---------------------------------------------------------------------------

def test_render_section_concat_picks_matching_fragments():
    spec = {
        "mode": "concat",
        "fragments": [
            {"template": "base "},
            {"when": {"add_a": True}, "template": "[A] "},
            {"when": {"add_b": True}, "template": "[B]"},
        ],
    }
    assert render_section(spec, {"add_a": True, "add_b": False}, {}) == "base [A] "
    assert render_section(spec, {"add_a": True, "add_b": True}, {}) == "base [A] [B]"
    assert render_section(spec, {}, {}) == "base "


def test_render_section_branches_first_match_wins():
    spec = {
        "mode": "branches",
        "fragments": [
            {"when": {"x_eq": 1}, "template": "one"},
            {"when": {"x_eq": 2}, "template": "two"},
            {"template": "fallback"},
        ],
    }
    assert render_section(spec, {"x": 1}, {}) == "one"
    assert render_section(spec, {"x": 2}, {}) == "two"
    assert render_section(spec, {"x": 99}, {}) == "fallback"


def test_render_section_resolves_ref_clauses():
    clauses = {
        "rain_addon": {
            "when": {"raining_eq": True},
            "template": " (raining)",
        },
    }
    spec = {
        "mode": "concat",
        "fragments": [
            {"template": "today"},
            {"ref": "rain_addon"},
        ],
    }
    assert render_section(spec, {"raining": True}, clauses) == "today (raining)"
    assert render_section(spec, {"raining": False}, clauses) == "today"


def test_render_section_format_substitution():
    spec = {"fragments": [{"template": "high {hi}°F"}]}
    assert render_section(spec, {"hi": 72}, {}) == "high 72°F"
