"""Tests for the stdlib HTTP serving layer.

Spins the real server on an ephemeral port against a temp SQLite file and
exercises the routes a display client will hit.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from juneuary import SCHEMA_VERSION
from juneuary.serve import make_handler


def _seed_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE cities (id INTEGER PRIMARY KEY, slug TEXT, name TEXT,
                             latitude REAL, longitude REAL);
        CREATE TABLE microseasons (id INTEGER PRIMARY KEY, canonical_name TEXT,
                                   category TEXT);
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
        INSERT INTO cities VALUES (1,'seattle','Seattle',47.6,-122.3);
        INSERT INTO microseasons VALUES (10,'Fool''s Spring','series');
        INSERT INTO microseason_occurrences VALUES (100,10,1,NULL);
        INSERT INTO observations VALUES (1000,1,'2026-02-14',61,44,0,0,0,NULL);
        INSERT INTO observation_microseasons VALUES (1000,100,'primary',0.8,'fits');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def server(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(str(db))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(str(db)))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_health(server):
    status, body = _get(f"{server}/v1/health")
    assert status == 200
    assert body == {"status": "ok", "schema_version": SCHEMA_VERSION}


def test_presentation_palette(server):
    status, body = _get(f"{server}/v1/presentation")
    assert status == 200
    assert body["microseasons"]["Winter"]["emoji"] == "❄️"
    assert body["microseasons"]["Winter"]["color"].startswith("#")


def test_state_ok(server):
    status, body = _get(f"{server}/v1/state?city=seattle")
    assert status == 200
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["as_of"] == "2026-02-14"
    assert body["current"]["headline"]["canonical_name"] == "Fool's Spring"


def test_state_missing_city_is_400(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{server}/v1/state")
    assert exc.value.code == 400


def test_state_unknown_city_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{server}/v1/state?city=atlantis")
    assert exc.value.code == 404
