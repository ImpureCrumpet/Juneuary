"""Juneuary engine package.

Runtime-agnostic core that the CLI, the markdown report, and (future) the
HTTP serving layer all build on. The split:

  - presentation : concept-level emoji / color / glyph (display metadata).
  - state        : the neutral render-model DTO + builder that turns a
                   classified day in the DB into something any consumer
                   (markdown, JSON-over-HTTP, a 64x32 pixel display) can render.

The DTO carries SCHEMA_VERSION so the Python engine and out-of-process clients
(e.g. a Starlark/tronbyt display app) can deploy on independent schedules
without silently drifting.
"""

from __future__ import annotations

SCHEMA_VERSION = "1.0"

__all__ = ["SCHEMA_VERSION"]
