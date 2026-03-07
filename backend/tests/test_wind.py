from __future__ import annotations

from tempest.models import AirportRecord, MetarRecord, RunwayRecord
from tempest.wind import compute_runway_wind_components


def test_compute_runway_wind_components() -> None:
    metar = MetarRecord(
        icao_id="KLAF",
        raw_text="KLAF ...",
        observed_at=None,
        station_name=None,
        latitude=None,
        longitude=None,
        elevation_m=None,
        flight_category=None,
        wind_direction_degrees=220,
        wind_speed_kt=20,
        wind_gust_kt=None,
        visibility_sm=None,
        temperature_c=None,
        dewpoint_c=None,
        altimeter_in_hg=None,
        sea_level_pressure_mb=None,
        sky_cover=[],
        wx_string=None,
        source_payload={},
    )

    airport = AirportRecord(
        icao_id="KLAF",
        iata_id=None,
        name=None,
        latitude=None,
        longitude=None,
        elevation_ft=None,
        runways=[RunwayRecord("22", 220.0, 6600, 150, "asphalt")],
        source_payload={},
    )

    components = compute_runway_wind_components(metar, airport)

    assert len(components) == 1
    assert components[0]["runway_id"] == "22"
    assert components[0]["headwind_kt"] == 20.0
    assert components[0]["crosswind_kt"] == 0.0
