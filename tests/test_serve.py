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
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from juneuary import SCHEMA_VERSION
from juneuary.serve import make_handler

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# /v1/days + /v1/normals against a full-schema catalog with an injected
# (network-free) Open-Meteo fetcher.
# ---------------------------------------------------------------------------

def _seed_catalog(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO cities (id,slug,name,latitude,longitude) "
                 "VALUES (1,'seattle','Seattle',47.6,-122.3)")
    conn.execute("INSERT INTO series (id,key,name) VALUES (1,'winter','Winter')")
    conn.execute(
        "INSERT INTO microseasons (id,canonical_name,slug,category,series_id,"
        "series_order,series_label) VALUES (10,'Winter','winter','series',1,1,'winter1')"
    )
    conn.execute(
        "INSERT INTO microseason_occurrences (id,microseason_id,city_id,"
        "typical_start_month,typical_end_month,temp_max_f) VALUES (100,10,1,12,3,50)"
    )
    conn.execute(
        "INSERT INTO city_climate_normals (city_id,month,temp_max_avg_f,"
        "temp_min_avg_f,precip_total_in) VALUES (1,2,48,37,3.5)"
    )
    conn.commit()
    conn.close()


def _fake_fetch(lat, lng, start, end):
    return [
        {"date": "2026-02-10", "temp_high_f": 40, "temp_low_f": 31,
         "precip_in": 0.1, "snow_in": 0.0, "cloud_cover_mean_pct": 90},
        {"date": "2026-02-11", "temp_high_f": 44, "temp_low_f": 33,
         "precip_in": 0.0, "snow_in": 0.0, "cloud_cover_mean_pct": 70},
    ]


@pytest.fixture()
def catalog_server(tmp_path):
    db = tmp_path / "catalog.db"
    _seed_catalog(str(db))
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(str(db), weather_fetcher=_fake_fetch, aq_fetcher=None),
    )
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


def test_days_fetches_and_classifies_range(catalog_server):
    status, body = _get(
        f"{catalog_server}/v1/days?city=seattle&start=2026-02-10&end=2026-02-11"
    )
    assert status == 200
    assert body["location"]["slug"] == "seattle"
    assert len(body["days"]) == 2
    assert "Winter" in [v["canonical_name"] for v in body["days"][0]["primary"]]
    assert body["days"][0]["high_anomaly_f"] == 40 - 48


def test_days_missing_range_is_400(catalog_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{catalog_server}/v1/days?city=seattle")
    assert exc.value.code == 400


def test_normals(catalog_server):
    status, body = _get(f"{catalog_server}/v1/normals?city=seattle")
    assert status == 200
    assert body["normals"]["2"]["temp_max_avg_f"] == 48
