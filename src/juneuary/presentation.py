"""Concept-level presentation metadata (emoji / color / glyph).

Loaded once from ``data/presentation.yaml`` and cached. This is the single
source of truth for how a microseason *looks*, independent of how it's
classified (classify.py) or worded (per-city narrative YAML).

Consumers:
  - scripts/report.py        : derives its emoji table from here.
  - src/juneuary/state.py     : decorates the render-model DTO.
  - (future) serving layer    : same metadata, emitted as JSON for displays.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PRESENTATION_YAML = ROOT / "data" / "presentation.yaml"

_FALLBACK = {"emoji": "", "color": "#9AA3A8", "glyph": "dot"}


@dataclass(frozen=True)
class Presentation:
    """How one microseason concept renders. `emoji` is the empty string when
    the concept has no glyph (human surfaces then show just the bolded name)."""
    emoji: str
    color: str
    glyph: str


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Presentation], Presentation]:
    doc = yaml.safe_load(PRESENTATION_YAML.read_text(encoding="utf-8")) or {}
    raw_default = {**_FALLBACK, **(doc.get("default") or {})}
    default = Presentation(
        emoji=raw_default.get("emoji", ""),
        color=raw_default.get("color", _FALLBACK["color"]),
        glyph=raw_default.get("glyph", _FALLBACK["glyph"]),
    )
    table: dict[str, Presentation] = {}
    for name, vals in (doc.get("microseasons") or {}).items():
        vals = vals or {}
        table[name] = Presentation(
            emoji=vals.get("emoji", default.emoji),
            color=vals.get("color", default.color),
            glyph=vals.get("glyph", default.glyph),
        )
    return table, default


def presentation_for(canonical_name: str) -> Presentation:
    """Presentation for a concept by canonical name; neutral fallback if absent."""
    table, default = _load()
    return table.get(canonical_name, default)


def emoji_map() -> dict[str, str]:
    """{canonical_name: emoji} for every concept that defines one.

    Used by the markdown report; entries with an empty emoji are omitted so
    the report's emojify()/tag() behaviour is unchanged for them.
    """
    table, _ = _load()
    return {name: p.emoji for name, p in table.items() if p.emoji}


def color_map() -> dict[str, str]:
    table, _ = _load()
    return {name: p.color for name, p in table.items()}


def glyph_map() -> dict[str, str]:
    table, _ = _load()
    return {name: p.glyph for name, p in table.items()}


def all_concepts() -> list[str]:
    table, _ = _load()
    return sorted(table)
