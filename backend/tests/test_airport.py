from __future__ import annotations

from pathlib import Path

from tempest.airport import get_airport, normalize_airport
from tempest.cache import JsonFileCache


def test_normalize_airport_maps_runway_fields() -> None:
    payload = {
        "icaoId": "KLAF",
        "name": "Lafayette/Purdue Univ Arpt, IN, US",
        "lat": 40.4124,
        "lon": -86.9474,
        "elev": 606,
        "runways": [
            {
                "id": "10",
                "heading": 100,
                "length_ft": 6600,
                "width_ft": 150,
                "surface": "ASPHALT",
            }
        ],
    }

    airport = normalize_airport(payload)

    assert airport.icao_id == "KLAF"
    assert airport.name and "Purdue" in airport.name
    assert len(airport.runways) == 1
    assert airport.runways[0].heading_degrees == 100.0
    assert airport.runways[0].surface == "asphalt"


def test_normalize_airport_uses_alignment_and_derives_reciprocal_runway() -> None:
    payload = {
        "icaoId": "KLAF",
        "runways": [
            {
                "id": "10/28",
                "alignment": 99,
                "length_ft": 6600,
                "width_ft": 150,
                "surface": "ASPHALT",
            }
        ],
    }

    airport = normalize_airport(payload)
    assert len(airport.runways) == 2

    by_id = {runway.runway_id: runway for runway in airport.runways}
    assert by_id["10"].heading_degrees == 99.0
    assert by_id["28"].heading_degrees == 279.0


def test_get_airport_uses_cache(tmp_path: Path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_seconds=300)
    cache.set(
        "airport_KLAF",
        {
            "icaoId": "KLAF",
            "runways": [{"id": "10", "heading": 100}],
        },
    )

    airport, source = get_airport("KLAF", cache_dir=tmp_path)

    assert source == "cache"
    assert airport.icao_id == "KLAF"


def test_normalize_airport_parses_dimension_field_for_length_and_width() -> None:
    payload = {
        "icaoId": "KLAF",
        "runways": [
            {
                "id": "05/23",
                "alignment": 49,
                "dimension": "6600x150",
                "surface": "CONCRETE",
            }
        ],
    }

    airport = normalize_airport(payload)
    by_id = {runway.runway_id: runway for runway in airport.runways}

    assert by_id["05"].length_ft == 6600
    assert by_id["05"].width_ft == 150
    assert by_id["23"].length_ft == 6600
    assert by_id["23"].width_ft == 150
