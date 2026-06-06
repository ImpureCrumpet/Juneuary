"""Launch the zero-dependency HTTP serving layer.

Serves the render-model DTO as JSON for display clients (web, or a
Starlark/tronbyt app). Reads the local DB only.

Example:
    uv run scripts/serve.py --port 8787
    curl 'http://localhost:8787/v1/state?city=seattle' | jq .
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from juneuary.serve import DEFAULT_DB, serve    # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--db", default=str(DEFAULT_DB))
    args = p.parse_args()
    serve(db_path=args.db, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
