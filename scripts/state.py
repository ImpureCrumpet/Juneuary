"""Dump the render-model DTO for a city as JSON.

This is the same payload the (forthcoming) HTTP serving layer will return and
that a display client (web, or a Starlark/tronbyt app) will consume. Reads the
local DB only — run scripts/fetch_weather.py first to populate observations.

Example:
    uv run scripts/state.py --city seattle
    uv run scripts/state.py --city seattle --date 2026-02-14
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from juneuary.state import build_state    # noqa: E402

DB_PATH = ROOT / "db" / "microseasons.db"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", required=True, help="city slug (see data/cities.yaml)")
    p.add_argument("--date", help="observation date YYYY-MM-DD (default: latest on file)")
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--compact", action="store_true", help="single-line JSON")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    state = build_state(conn, args.city, args.date)
    if state is None:
        raise SystemExit(
            f"No observations for {args.city}"
            + (f" on {args.date}" if args.date else "")
            + ". Run: uv run scripts/fetch_weather.py --city "
            + f"{args.city}"
        )

    indent = None if args.compact else 2
    print(json.dumps(state.to_dict(), indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
