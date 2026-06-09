from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime

import pytest

from tempest.route import (
    AirportIndexEntry,
    RoutePoint,
    haversine_nm,
    load_route_station_index,
    load_station_cache_index,
    parse_route,
    sample_enroute_airports,
)


def test_parse_route_normalizes_common_separators() -> None:
    assert parse_route("KLAF - KIND") == ["KLAF", "KIND"]
    assert parse_route("KLAF KIND") == ["KLAF", "KIND"]
    assert parse_route("klaf-kind") == ["KLAF", "KIND"]


def test_parse_route_rejects_invalid_tokens() -> None:
    with pytest.raises(ValueError, match="Invalid ICAO"):
        parse_route("KLAF 123 KIND")


def test_load_station_cache_index_filters_metar_taf_stations(tmp_path) -> None:
    cache_path = tmp_path / "stations.cache.json.gz"
    payload = [
        {
            "icaoId": "KSAC",
            "site": "Sacramento Exec",
            "lat": 38.50658,
            "lon": -121.49604,
            "siteType": ["METAR", "TAF"],
        },
        {
            "icaoId": "BAD1",
            "site": "Invalid ID",
            "lat": 1,
            "lon": 2,
            "siteType": ["METAR"],
        },
        {
            "icaoId": "KNOA",
            "site": "No Weather",
            "lat": 1,
            "lon": 2,
            "siteType": [],
        },
    ]
    with gzip.open(cache_path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)

    entries = load_station_cache_index(cache_path)

    assert [entry.icao_id for entry in entries] == ["KSAC"]
    assert entries[0].name == "Sacramento Exec"
    assert entries[0].airport_type == "METAR|TAF"


def test_load_route_station_index_merges_cache_bundled_and_fallback(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_path = cache_dir / "stations.cache.json.gz"
    with gzip.open(cache_path, "wt", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "icaoId": "KSAC",
                    "site": "Sacramento Exec",
                    "lat": 38.50658,
                    "lon": -121.49604,
                    "siteType": ["METAR", "TAF"],
                }
            ],
            handle,
        )

    bundled_path = tmp_path / "station_index.csv"
    bundled_path.write_text(
        "icao_id,name,latitude,longitude,type\nKHAF,Half Moon Bay,37.51359,-122.49959,METAR|TAF\n",
        encoding="utf-8",
    )
    fallback_path = tmp_path / "airport_index.csv"
    fallback_path.write_text(
        "icao_id,name,latitude,longitude,type\nKLAF,Purdue,40.4123,-86.9369,airport\n",
        encoding="utf-8",
    )

    entries, notes = load_route_station_index(
        cache_dir=cache_dir,
        bundled_station_index_path=bundled_path,
        fallback_airport_index_path=fallback_path,
        allow_refresh=False,
    )

    assert [entry.icao_id for entry in entries] == ["KHAF", "KLAF", "KSAC"]
    assert notes == []


def test_haversine_distance_is_plausible_for_known_airports() -> None:
    distance = haversine_nm(40.4123, -86.9369, 39.7173, -86.2944)
    assert 50.0 <= distance <= 52.0


def test_sample_enroute_airports_selects_nearest_within_radius() -> None:
    samples, notes = sample_enroute_airports(
        route_points=[
            RoutePoint("KAAA", "Start", 0.0, 0.0),
            RoutePoint("KBBB", "End", 0.0, 1.0),
        ],
        airport_index=[
            AirportIndexEntry("KNEA", "Near", 0.0, 0.42, "airport"),
            AirportIndexEntry("KNEB", "Near B", 0.0, 0.84, "airport"),
            AirportIndexEntry("KFAR", "Far", 1.0, 1.0, "airport"),
        ],
        planned_departure=datetime(2026, 4, 4, 18, tzinfo=UTC),
        corridor_radius_nm=10.0,
        sample_spacing_nm=25.0,
        groundspeed_kt=100.0,
    )

    assert [sample.icao_id for sample in samples] == ["KNEA", "KNEB"]
    assert notes == []


def test_sample_enroute_airports_deduplicates_selected_airports() -> None:
    samples, notes = sample_enroute_airports(
        route_points=[
            RoutePoint("KAAA", "Start", 0.0, 0.0),
            RoutePoint("KBBB", "End", 0.0, 2.0),
        ],
        airport_index=[
            AirportIndexEntry("KONE", "One", 0.0, 0.75, "airport"),
        ],
        planned_departure=datetime(2026, 4, 4, 18, tzinfo=UTC),
        corridor_radius_nm=40.0,
        sample_spacing_nm=25.0,
        groundspeed_kt=100.0,
    )

    assert [sample.icao_id for sample in samples] == ["KONE"]
    assert len(notes) >= 1


def test_sample_enroute_airports_reports_missing_coverage() -> None:
    samples, notes = sample_enroute_airports(
        route_points=[
            RoutePoint("KAAA", "Start", 0.0, 0.0),
            RoutePoint("KBBB", "End", 0.0, 1.0),
        ],
        airport_index=[],
        planned_departure=datetime(2026, 4, 4, 18, tzinfo=UTC),
        corridor_radius_nm=10.0,
        sample_spacing_nm=25.0,
        groundspeed_kt=100.0,
    )

    assert samples == []
    assert len(notes) == 2
    assert "No reporting airport" in notes[0]
