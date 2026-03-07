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
