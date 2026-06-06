"""Zero-dependency HTTP serving layer for the render-model DTO.

This is the seam an out-of-process display client talks to (a web page, or a
Starlark/tronbyt app via `http.get`). It speaks only stdlib `http.server`, so
there's nothing to install and nothing to keep patched.

Endpoints (all JSON, all GET):
  /v1/health                         -> {status, schema_version}
  /v1/presentation                   -> the emoji/color/glyph palette
  /v1/state?city=<slug>[&date=ISO]   -> MicroseasonState for that city
  /v1/forecast?city=<slug>[&days=N]  -> state with a populated forecast[]

Run it:
    uv run scripts/serve.py --port 8787
    curl 'http://localhost:8787/v1/state?city=seattle'
"""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import SCHEMA_VERSION
from .presentation import color_map, emoji_map, glyph_map
from .state import build_state

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "db" / "microseasons.db"


def _presentation_payload() -> dict:
    em, cm, gm = emoji_map(), color_map(), glyph_map()
    return {
        "schema_version": SCHEMA_VERSION,
        "microseasons": {
            name: {"emoji": em.get(name, ""), "color": cm[name], "glyph": gm[name]}
            for name in cm
        },
    }


def make_handler(db_path: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "juneuary/" + SCHEMA_VERSION

        # --- helpers ---
        def _send(self, status: HTTPStatus, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=900")
            self.end_headers()
            self.wfile.write(body)

        def _connect(self) -> sqlite3.Connection:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

        # --- routing ---
        def do_GET(self) -> None:                       # noqa: N802 (stdlib name)
            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                self._route(route, params)
            except ValueError as e:                     # unknown city, bad date
                self._send(HTTPStatus.NOT_FOUND, {"error": str(e)})
            except Exception as e:                       # noqa: BLE001
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})

        def _route(self, route: str, params: dict) -> None:
            if route == "/v1/health":
                self._send(HTTPStatus.OK,
                           {"status": "ok", "schema_version": SCHEMA_VERSION})
            elif route == "/v1/presentation":
                self._send(HTTPStatus.OK, _presentation_payload())
            elif route == "/v1/state":
                self._state(params)
            elif route == "/v1/forecast":
                self._state(params, with_forecast=True)
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": f"no route {route}"})

        def _state(self, params: dict, with_forecast: bool = False) -> None:
            city = params.get("city")
            lat, lng = params.get("lat"), params.get("lng")
            if not city and not (lat and lng):
                self._send(HTTPStatus.BAD_REQUEST,
                           {"error": "provide ?city= or ?lat=&lng="})
                return

            days = int(params.get("days", 7))
            conn = self._connect()
            try:
                if lat and lng:
                    # Arbitrary point: live nowcast borrowing the nearest
                    # catalog. forecast[] is always populated here.
                    from .predict import build_state_for_point
                    state = build_state_for_point(
                        conn, float(lat), float(lng),
                        label=params.get("label"), days=days,
                    )
                    not_found = f"no forecast available for {lat},{lng}"
                else:
                    state = build_state(conn, city, params.get("date"))
                    if with_forecast and state is not None:
                        # Lazy import: keeps the predict path optional for the
                        # read-only /v1/state route.
                        from .predict import attach_forecast
                        attach_forecast(conn, state, days=days)
                    not_found = f"no observations for {city}"
            finally:
                conn.close()
            if state is None:
                self._send(HTTPStatus.NOT_FOUND, {"error": not_found})
                return
            self._send(HTTPStatus.OK, state.to_dict())

        def log_message(self, fmt: str, *args) -> None:
            # Quieter than the default stderr spam; still shows method + path.
            print(f"  {self.address_string()} {fmt % args}")

    return Handler


def serve(db_path: str = str(DEFAULT_DB), host: str = "127.0.0.1", port: int = 8787) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(db_path))
    print(f"juneuary serve v{SCHEMA_VERSION} on http://{host}:{port}  (db: {db_path})")
    print("  GET /v1/health  /v1/presentation  /v1/state?city=  /v1/forecast?city=")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
