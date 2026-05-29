from __future__ import annotations

import os
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from tempest.minimums import MinimumsProfile
from tempest.models import AirportRecord, MetarRecord, RunwayRecord, TafRecord


def _metar(**overrides):
    values = {
        "icao_id": "KLAF",
        "raw_text": "KLAF 041800Z 22012KT 10SM BKN030 20/10 A2992",
        "observed_at": "2026-04-04T18:00:00Z",
        "station_name": "Test",
        "latitude": 40.4124,
        "longitude": -86.9474,
        "elevation_m": 184.0,
        "flight_category": "VFR",
        "wind_direction_degrees": 220,
        "wind_speed_kt": 12,
        "wind_gust_kt": None,
        "visibility_sm": 10.0,
        "temperature_c": 20.0,
        "dewpoint_c": 10.0,
        "altimeter_in_hg": 29.92,
        "sea_level_pressure_mb": None,
        "sky_cover": [{"cover": "BKN", "base": 3000}],
        "wx_string": None,
        "source_payload": {},
    }
    values.update(overrides)
    return MetarRecord(**values)


def _airport():
    return AirportRecord(
        icao_id="KLAF",
        iata_id=None,
        name="Test Airport",
        latitude=40.4124,
        longitude=-86.9474,
        elevation_ft=606,
        runways=[RunwayRecord("22", 220.0, 6600, 150, "asphalt")],
        source_payload={},
    )


def _taf():
    return TafRecord(
        icao_id="KLAF",
        raw_text="TAF KLAF 041720Z 0418/0518 22012KT P6SM BKN030",
        issued_at="2026-04-04T17:20:00Z",
        valid_from="2026-04-04T18:00:00Z",
        valid_to="2026-04-05T18:00:00Z",
        station_name=None,
        forecast=[
            {
                "timeFrom": "2026-04-04T18:00:00Z",
                "timeTo": "2026-04-04T21:00:00Z",
                "visib": 10,
                "clouds": [{"cover": "BKN", "base": 3000}],
            }
        ],
        source_payload={},
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPEST_MINIMUMS_PATH", str(tmp_path / "profiles.json"))
    monkeypatch.setenv("TEMPEST_CACHE_DIR", str(tmp_path / "cache"))

    api_app = importlib.import_module("tempest_api.app")

    monkeypatch.setattr(api_app, "get_latest_metar", lambda *args, **kwargs: (_metar(), "api"))
    monkeypatch.setattr(api_app, "get_airport", lambda *args, **kwargs: (_airport(), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda *args, **kwargs: (_taf(), "api"))
    return TestClient(api_app.app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_minimums_crud(client):
    payload = {
        "display_name": "Primary",
        "min_visibility_sm": 5,
        "min_ceiling_ft_agl": 2500,
    }
    created = client.post("/minimums/primary", json=payload)
    assert created.status_code == 200
    assert created.json()["profile"]["profile_id"] == "primary"

    listed = client.get("/minimums")
    assert listed.status_code == 200
    assert len(listed.json()["profiles"]) == 1

    fetched = client.get("/minimums/primary")
    assert fetched.status_code == 200
    assert fetched.json()["profile"]["display_name"] == "Primary"

    deleted = client.delete("/minimums/primary")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_evaluate_endpoint_returns_go(client):
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "min_visibility_sm": 5,
            "min_ceiling_ft_agl": 2500,
            "max_crosswind_kt": 15,
        },
    )

    response = client.post(
        "/evaluate",
        json={
            "icao": "KLAF",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:30:00Z",
            "include_taf": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["decision"] == "go"
    assert body["sources"]["metar"] == "api"


def test_evaluate_endpoint_returns_no_go(client, monkeypatch):
    api_app = importlib.import_module("tempest_api.app")

    monkeypatch.setattr(
        api_app,
        "get_latest_metar",
        lambda *args, **kwargs: (_metar(visibility_sm=2.0, sky_cover=[{"cover": "OVC", "base": 900}]), "api"),
    )
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "min_visibility_sm": 5,
            "min_ceiling_ft_agl": 2500,
        },
    )

    response = client.post("/evaluate", json={"icao": "KLAF", "profile_id": "primary"})
    assert response.status_code == 200
    assert response.json()["decision"]["decision"] == "no-go"


def test_evaluate_endpoint_handles_taf_unavailable(client, monkeypatch):
    api_app = importlib.import_module("tempest_api.app")

    def fail_taf(*args, **kwargs):
        raise RuntimeError("taf unavailable")

    monkeypatch.setattr(api_app, "get_latest_taf", fail_taf)
    client.post(
        "/minimums/primary",
        json={"display_name": "Primary", "require_alternate_for_ifr": True},
    )

    response = client.post(
        "/evaluate",
        json={"icao": "KLAF", "profile_id": "primary", "include_taf": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"]["taf"] is not None
    assert body["decision"]["decision"] == "caution"


def test_invalid_icao_returns_422(client):
    response = client.post("/evaluate", json={"icao": "LAF", "profile_id": "primary"})
    assert response.status_code == 422


def test_missing_profile_returns_404(client):
    response = client.post("/evaluate", json={"icao": "KLAF", "profile_id": "missing"})
    assert response.status_code == 404
