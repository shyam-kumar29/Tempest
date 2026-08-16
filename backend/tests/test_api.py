from __future__ import annotations

import os
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from tempest.minimums import MinimumsProfile
from tempest.models import AirportRecord, MetarRecord, RunwayRecord, TafRecord
from tempest.route import AirportIndexEntry


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


def _airport_for(icao_id: str) -> AirportRecord:
    coordinates = {
        "KLAF": (40.4123, -86.9369, 606),
        "KIND": (39.7173, -86.2944, 797),
        "KEYE": (39.8307, -86.2944, 823),
    }
    latitude, longitude, elevation_ft = coordinates[icao_id]
    return AirportRecord(
        icao_id=icao_id,
        iata_id=None,
        name=f"{icao_id} Airport",
        latitude=latitude,
        longitude=longitude,
        elevation_ft=elevation_ft,
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
    monkeypatch.setenv("TEMPEST_USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("TEMPEST_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("TEMPEST_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TEMPEST_FETCH_STATION_CACHE", "0")
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(tmp_path / "station_index.csv"))

    api_app = importlib.import_module("tempest_api.app")

    monkeypatch.setattr(api_app, "get_latest_metar", lambda *args, **kwargs: (_metar(), "api"))
    monkeypatch.setattr(api_app, "get_airport", lambda *args, **kwargs: (_airport(), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda *args, **kwargs: (_taf(), "api"))
    test_client = TestClient(api_app.app)
    response = test_client.post(
        "/auth/signup",
        json={"username": "pilot@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return test_client


@pytest.fixture()
def unauthenticated_client(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPEST_MINIMUMS_PATH", str(tmp_path / "profiles.json"))
    monkeypatch.setenv("TEMPEST_USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("TEMPEST_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("TEMPEST_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TEMPEST_FETCH_STATION_CACHE", "0")
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(tmp_path / "station_index.csv"))

    api_app = importlib.import_module("tempest_api.app")

    monkeypatch.setattr(api_app, "get_latest_metar", lambda *args, **kwargs: (_metar(), "api"))
    monkeypatch.setattr(api_app, "get_airport", lambda *args, **kwargs: (_airport(), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda *args, **kwargs: (_taf(), "api"))
    return TestClient(api_app.app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_signup_login_logout_me(unauthenticated_client):
    signup = unauthenticated_client.post(
        "/auth/signup",
        json={"username": "newpilot@example.com", "password": "correct horse battery staple"},
    )
    assert signup.status_code == 200
    assert signup.json()["user"]["username"] == "newpilot@example.com"

    me = unauthenticated_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "newpilot@example.com"

    logout = unauthenticated_client.post("/auth/logout")
    assert logout.status_code == 200
    assert unauthenticated_client.get("/auth/me").status_code == 401

    login = unauthenticated_client.post(
        "/auth/login",
        json={"username": "newpilot@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert unauthenticated_client.get("/auth/me").status_code == 200


def test_auth_required_for_protected_endpoints(unauthenticated_client):
    assert unauthenticated_client.get("/minimums").status_code == 401
    assert unauthenticated_client.get("/weather/KLAF").status_code == 401
    assert unauthenticated_client.post("/evaluate", json={}).status_code == 401
    assert unauthenticated_client.post("/evaluate-route", json={}).status_code == 401
    assert unauthenticated_client.post("/recommendations", json={}).status_code == 401
    assert unauthenticated_client.post("/ai/briefing", json={}).status_code == 401


def test_minimums_are_isolated_by_user(unauthenticated_client):
    first = unauthenticated_client.post(
        "/auth/signup",
        json={"username": "first@example.com", "password": "correct horse battery staple"},
    )
    assert first.status_code == 200
    assert unauthenticated_client.post(
        "/minimums/primary",
        json={"display_name": "First"},
    ).status_code == 200
    assert len(unauthenticated_client.get("/minimums").json()["profiles"]) == 1

    unauthenticated_client.post("/auth/logout")
    second = unauthenticated_client.post(
        "/auth/signup",
        json={"username": "second@example.com", "password": "correct horse battery staple"},
    )
    assert second.status_code == 200
    assert unauthenticated_client.get("/minimums").json()["profiles"] == []
    assert unauthenticated_client.get("/minimums/primary").status_code == 404


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

    response = client.post(
        "/evaluate",
        json={
            "icao": "KLAF",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:30:00Z",
        },
    )
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


def test_evaluate_rejects_invalid_numeric_fields(client):
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate",
        json={"icao": "KLAF", "profile_id": "primary", "taf_lookahead_hours": "soon"},
    )

    assert response.status_code == 422
    assert "taf_lookahead_hours" in response.json()["detail"]


def test_evaluate_rejects_negative_fuel_reserve(client):
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate",
        json={"icao": "KLAF", "profile_id": "primary", "fuel_reserve_min": -1},
    )

    assert response.status_code == 422
    assert "fuel_reserve_min" in response.json()["detail"]


def _write_route_index(path, *, include_endpoints: bool = False):
    rows = ["icao_id,name,latitude,longitude,type"]
    if include_endpoints:
        rows.extend(
            [
                "KLAF,Purdue University Airport,40.4123,-86.9369,airport",
                "KIND,Indianapolis International Airport,39.7173,-86.2944,airport",
            ]
        )
    rows.append("KEYE,Eagle Creek Airpark,39.8307,-86.2944,airport")
    path.write_text(
        "\n".join(rows),
        encoding="utf-8",
    )


def _write_recommendation_index(path):
    path.write_text(
        "\n".join(
            [
                "icao_id,name,latitude,longitude,type",
                "KAAA,Home Airport,0.0,0.0,METAR|TAF",
                "KBBB,Bad Weather,0.0,0.5,METAR|TAF",
                "KCCC,Good Weather,0.0,1.0,METAR",
                "KDDD,Far Airport,0.0,3.5,METAR|TAF",
                "KNON,No Weather,0.0,0.25,airport",
            ]
        ),
        encoding="utf-8",
    )


def _recommendation_airport(icao_id: str) -> AirportRecord:
    coordinates = {
        "KAAA": (0.0, 0.0, 100),
        "KBBB": (0.0, 0.5, 120),
        "KCCC": (0.0, 1.0, 130),
        "KDDD": (0.0, 3.5, 200),
    }
    latitude, longitude, elevation_ft = coordinates[icao_id]
    return AirportRecord(
        icao_id=icao_id,
        iata_id=None,
        name=f"{icao_id} Airport",
        latitude=latitude,
        longitude=longitude,
        elevation_ft=elevation_ft,
        runways=[RunwayRecord("22", 220.0, 5000, 100, "asphalt")],
        source_payload={},
    )


def test_recommendations_requires_home_airport(client):
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post("/recommendations", json={"profile_id": "primary"})

    assert response.status_code == 422
    assert "home_airport" in response.json()["detail"]


def test_recommendations_returns_ranked_destinations(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "station_index.csv"
    _write_recommendation_index(index_path)
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_recommendation_airport(icao.strip().upper()), "api"))

    def metar_for_recommendations(icao, *args, **kwargs):
        station = icao.strip().upper()
        visibility = 2.0 if station == "KBBB" else 10.0
        return _metar(icao_id=station, visibility_sm=visibility, latitude=0.0, longitude=0.0), "api"

    monkeypatch.setattr(api_app, "get_latest_metar", metar_for_recommendations)
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "home_airport": "kaaa",
            "recommendation_min_distance_nm": 10,
            "recommendation_radius_nm": 100,
            "recommendation_count": 2,
            "favorite_airports": [{"icao_id": "KBBB", "weight": 5, "note": "Good cafe"}],
            "min_visibility_sm": 5,
            "min_runway_width_ft": 75,
        },
    )

    response = client.post(
        "/recommendations",
        json={
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["home_airport"] == "KAAA"
    assert body["summary_decision"] == "go"
    assert body["ai"]["status"] == "not_requested"
    assert [item["icao_id"] for item in body["recommendations"]] == ["KCCC", "KBBB"]
    assert body["recommendations"][0]["decision"]["decision"] == "go"
    assert body["recommendations"][1]["decision"]["decision"] == "no-go"
    assert body["recommendations"][1]["favorite"] is True
    assert body["recommendations"][1]["favorite_note"] == "Good cafe"
    assert body["parameters"]["min_distance_nm"] == 10.0
    assert body["parameters"]["max_distance_nm"] == 100.0
    assert body["recommendations"][0]["estimated_arrival"].startswith("2026-04-04T18:36")


def test_recommendations_supports_distance_band_and_radius_alias(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "station_index.csv"
    _write_recommendation_index(index_path)
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_recommendation_airport(icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper(), latitude=0.0, longitude=0.0), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "home_airport": "KAAA",
            "recommendation_radius_nm": 150,
            "recommendation_count": 5,
        },
    )

    response = client.post(
        "/recommendations",
        json={
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "min_distance_nm": 40,
            "radius_nm": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["icao_id"] for item in body["recommendations"]] == ["KCCC"]
    assert body["parameters"]["min_distance_nm"] == 40.0
    assert body["parameters"]["max_distance_nm"] == 100.0

    response = client.post(
        "/recommendations",
        json={
            "profile_id": "primary",
            "min_distance_nm": 120,
            "max_distance_nm": 50,
        },
    )

    assert response.status_code == 422
    assert "min_distance_nm" in response.json()["detail"]


def test_recommendations_keeps_results_when_candidate_fetch_fails(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "station_index.csv"
    _write_recommendation_index(index_path)
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_recommendation_airport(icao.strip().upper()), "api"))

    def metar_for_recommendations(icao, *args, **kwargs):
        station = icao.strip().upper()
        if station == "KBBB":
            raise RuntimeError("metar unavailable")
        return _metar(icao_id=station, latitude=0.0, longitude=0.0), "api"

    monkeypatch.setattr(api_app, "get_latest_metar", metar_for_recommendations)
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "home_airport": "KAAA",
            "recommendation_radius_nm": 100,
            "recommendation_count": 3,
        },
    )

    response = client.post(
        "/recommendations",
        json={
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_decision"] == "go"
    assert [item["icao_id"] for item in body["recommendations"]] == ["KCCC", "KBBB"]
    assert any("KBBB weather fetch failed" in note for note in body["notes"])


def test_recommendations_include_ai_applies_conservative_downgrade(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "station_index.csv"
    _write_recommendation_index(index_path)
    monkeypatch.setenv("TEMPEST_STATION_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_recommendation_airport(icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper(), latitude=0.0, longitude=0.0), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))

    def ai_briefing(context):
        assert context["kind"] == "destination_recommendations"
        return {
            "status": "completed",
            "summary": "Usable options exist, but convective risk needs review.",
            "recommended_action": "Treat this as caution and review radar before departure.",
            "downgrade_decision": "caution",
            "top_risks": ["Storms nearby."],
            "best_options": ["KBBB"],
            "watch_items": ["Radar trend"],
            "pilot_questions": ["Are storms moving toward the route?"],
            "limitations": ["AI is advisory."],
        }

    monkeypatch.setattr(api_app, "generate_ai_briefing", ai_briefing)
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "home_airport": "KAAA",
            "recommendation_radius_nm": 100,
            "recommendation_count": 1,
        },
    )

    response = client.post(
        "/recommendations",
        json={
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "include_ai": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_decision"] == "caution"
    assert body["ai"]["status"] == "completed"
    assert body["ai"]["top_risks"] == ["Storms nearby."]


def test_ai_briefing_endpoint_returns_unavailable_without_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = client.post(
        "/ai/briefing",
        json={"base_decision": "go", "context": {"summary_decision": "go"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "go"
    assert body["ai"]["status"] == "unavailable"


def test_ai_status_reports_configuration(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.get("/ai/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TEMPEST_AI_MODEL", "gpt-test")
    response = client.get("/ai/status")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "model": "gpt-test"}


def test_evaluate_route_endpoint_returns_route_stations(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport_for(icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))

    client.post("/minimums/primary", json={"display_name": "Primary"})
    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF - KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "corridor_radius_nm": 10,
            "sample_spacing_nm": 25,
            "groundspeed_kt": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == ["KLAF", "KIND"]
    assert body["summary_decision"] == "caution"
    assert [station["icao_id"] for station in body["stations"]] == ["KLAF", "KEYE", "KIND"]
    assert [station["role"] for station in body["stations"]] == ["departure", "enroute", "arrival"]
    assert body["stations"][1]["planned_time"].startswith("2026-04-04T18:30:00")
    assert body["coverage_notes"]


def test_evaluate_route_endpoint_uses_worst_station_decision(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport_for(icao.strip().upper()), "api"))

    def metar_for_route(icao, *args, **kwargs):
        station = icao.strip().upper()
        visibility = 1.0 if station == "KIND" else 10.0
        return _metar(icao_id=station, visibility_sm=visibility), "api"

    monkeypatch.setattr(api_app, "get_latest_metar", metar_for_route)
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post("/minimums/primary", json={"display_name": "Primary", "min_visibility_sm": 5})

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_decision"] == "no-go"
    arrival = body["stations"][-1]
    assert arrival["icao_id"] == "KIND"
    assert arrival["decision"]["decision"] == "no-go"


def test_evaluate_route_endpoint_keeps_results_when_enroute_fetch_fails(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport_for(icao.strip().upper()), "api"))

    def metar_for_route(icao, *args, **kwargs):
        station = icao.strip().upper()
        if station == "KEYE":
            raise RuntimeError("metar unavailable")
        return _metar(icao_id=station), "api"

    monkeypatch.setattr(api_app, "get_latest_metar", metar_for_route)
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate-route",
        json={
            "route": "klaf-kind",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_decision"] == "caution"
    assert [station["icao_id"] for station in body["stations"]] == ["KLAF", "KEYE", "KIND"]
    assert body["stations"][1]["decision"]["decision"] == "caution"
    assert any("KEYE weather fetch failed" in note for note in body["coverage_notes"])


def test_evaluate_route_ignores_enroute_runway_minimums(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))

    def airport_for_route(icao, *args, **kwargs):
        airport = _airport_for(icao.strip().upper())
        if airport.icao_id == "KEYE":
            airport.runways = [RunwayRecord("22", 220.0, 6600, 50, "asphalt")]
        return airport, "api"

    monkeypatch.setattr(api_app, "get_airport", airport_for_route)
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post(
        "/minimums/primary",
        json={"display_name": "Primary", "min_runway_width_ft": 100},
    )

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF - KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "corridor_radius_nm": 10,
            "sample_spacing_nm": 25,
        },
    )

    assert response.status_code == 200
    enroute = response.json()["stations"][1]["decision"]
    assert enroute["decision"] == "go"
    assert not any("runway" in reason.lower() for reason in enroute["fail_reasons"])
    assert any("runway suitability" in reason for reason in enroute["pass_reasons"])


def test_evaluate_route_ignores_enroute_taf_runway_wind_unknowns(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport_for(icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper()), "api"))

    def variable_wind_taf(icao, *args, **kwargs):
        taf = _taf()
        taf.icao_id = icao.strip().upper()
        taf.forecast = [
            {
                "timeFrom": "2026-04-04T20:00:00Z",
                "timeTo": "2026-04-04T22:00:00Z",
                "wdir": "VRB",
                "wspd": 6,
                "visib": 10,
                "clouds": [{"cover": "BKN", "base": 3000}],
            }
        ]
        return taf, "api"

    monkeypatch.setattr(api_app, "get_latest_taf", variable_wind_taf)
    client.post(
        "/minimums/primary",
        json={
            "display_name": "Primary",
            "min_visibility_sm": 5,
            "min_ceiling_ft_agl": 2500,
            "max_crosswind_kt": 10,
            "max_tailwind_kt": 5,
        },
    )

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF - KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T20:00:00Z",
            "corridor_radius_nm": 10,
            "sample_spacing_nm": 25,
        },
    )

    assert response.status_code == 200
    enroute = response.json()["stations"][1]["decision"]
    assert enroute["decision"] == "go"
    unknown_text = " ".join(enroute["unknowns"]).lower()
    assert "crosswind" not in unknown_text
    assert "tailwind" not in unknown_text


def test_evaluate_route_marks_enroute_storms_as_caution(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport_for(icao.strip().upper()), "api"))

    def metar_for_route(icao, *args, **kwargs):
        station = icao.strip().upper()
        if station == "KEYE":
            return _metar(
                icao_id=station,
                raw_text="KEYE 041800Z 22012KT 10SM TSRA BKN030 20/10 A2992",
                wx_string="TSRA",
            ), "api"
        return _metar(icao_id=station), "api"

    monkeypatch.setattr(api_app, "get_latest_metar", metar_for_route)
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post(
        "/minimums/primary",
        json={"display_name": "Primary", "min_visibility_sm": 5, "min_ceiling_ft_agl": 2500},
    )

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF - KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "corridor_radius_nm": 10,
            "sample_spacing_nm": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    enroute = body["stations"][1]["decision"]
    assert body["summary_decision"] == "caution"
    assert enroute["decision"] == "caution"
    assert any("thunderstorms" in reason for reason in enroute["caution_reasons"])


def test_evaluate_route_uses_airport_index_when_endpoint_coordinate_fetch_fails(client, monkeypatch, tmp_path):
    api_app = importlib.import_module("tempest_api.app")
    index_path = tmp_path / "airport_index.csv"
    _write_route_index(index_path, include_endpoints=True)
    monkeypatch.setenv("TEMPEST_AIRPORT_INDEX_PATH", str(index_path))

    def airport_for_route(icao, *args, **kwargs):
        station = icao.strip().upper()
        if station in {"KLAF", "KIND"}:
            raise RuntimeError("certificate verify failed")
        return _airport_for(station), "api"

    monkeypatch.setattr(api_app, "get_airport", airport_for_route)
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KLAF - KIND",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == ["KLAF", "KIND"]
    assert [station["icao_id"] for station in body["stations"]] == ["KLAF", "KEYE", "KIND"]


def test_evaluate_route_index_notes_do_not_force_caution(client, monkeypatch):
    api_app = importlib.import_module("tempest_api.app")
    monkeypatch.setattr(
        api_app,
        "load_route_station_index",
        lambda **kwargs: (
            [
                AirportIndexEntry("KAAA", "Start", 0.0, 0.0, "METAR"),
                AirportIndexEntry("KBBB", "End", 0.0, 0.2, "METAR"),
            ],
            ["Station cache refresh failed; using local station index: certificate verify failed"],
        ),
    )
    monkeypatch.setattr(api_app, "get_latest_metar", lambda icao, *args, **kwargs: (_metar(icao_id=icao.strip().upper()), "api"))
    monkeypatch.setattr(api_app, "get_latest_taf", lambda icao, *args, **kwargs: (_taf(), "api"))
    monkeypatch.setattr(api_app, "get_airport", lambda icao, *args, **kwargs: (_airport(), "api"))
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate-route",
        json={
            "route": "KAAA - KBBB",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_decision"] == "go"
    assert body["coverage_notes"] == []
    assert body["index_notes"]


def test_evaluate_rejects_stale_cached_metar_fallback(client, monkeypatch):
    api_app = importlib.import_module("tempest_api.app")
    monkeypatch.setattr(api_app, "get_latest_metar", lambda *args, **kwargs: (_metar(observed_at="2026-01-01T00:00:00Z"), "stale-cache"))
    client.post("/minimums/primary", json={"display_name": "Primary"})

    response = client.post(
        "/evaluate",
        json={
            "icao": "KLAF",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
        },
    )

    assert response.status_code == 502
    assert "stale-cache" in response.json()["detail"]


def test_evaluate_ignores_stale_cached_taf_fallback(client, monkeypatch):
    api_app = importlib.import_module("tempest_api.app")
    monkeypatch.setattr(api_app, "get_latest_taf", lambda *args, **kwargs: (_taf(), "stale-cache"))
    client.post("/minimums/primary", json={"display_name": "Primary", "require_alternate_for_ifr": True})

    response = client.post(
        "/evaluate",
        json={
            "icao": "KLAF",
            "profile_id": "primary",
            "planned_departure": "2026-04-04T18:00:00Z",
            "include_taf": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["weather"]["taf"] is None
    assert "stale-cache" in body["errors"]["taf"]
