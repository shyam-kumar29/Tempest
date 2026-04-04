from __future__ import annotations

from tempest.evaluation import evaluate_conditions
from tempest.minimums import MinimumsProfile
from tempest.models import AirportRecord, MetarRecord, RunwayRecord
from tempest.wind import compute_runway_wind_components


def _metar(
    *,
    visibility_sm: float | None = 10.0,
    flight_category: str | None = "VFR",
    wind_direction_degrees: int | None = 220,
    wind_speed_kt: int | None = 12,
    wind_gust_kt: int | None = None,
    sky_cover: list[dict[str, object]] | None = None,
    observed_at: str | int | None = "2026-04-04T15:00:00Z",
) -> MetarRecord:
    return MetarRecord(
        icao_id="KLAF",
        raw_text="KLAF ...",
        observed_at=observed_at,
        station_name=None,
        latitude=None,
        longitude=None,
        elevation_m=None,
        flight_category=flight_category,
        wind_direction_degrees=wind_direction_degrees,
        wind_speed_kt=wind_speed_kt,
        wind_gust_kt=wind_gust_kt,
        visibility_sm=visibility_sm,
        temperature_c=None,
        dewpoint_c=None,
        altimeter_in_hg=None,
        sea_level_pressure_mb=None,
        sky_cover=sky_cover if sky_cover is not None else [{"cover": "BKN", "base": 3000}],
        wx_string=None,
        source_payload={},
    )


def _airport() -> AirportRecord:
    return AirportRecord(
        icao_id="KLAF",
        iata_id=None,
        name="Test Airport",
        latitude=None,
        longitude=None,
        elevation_ft=None,
        runways=[
            RunwayRecord("22", 220.0, 6600, 150, "asphalt"),
            RunwayRecord("04", 40.0, 6600, 150, "asphalt"),
        ],
        source_payload={},
    )


def test_evaluate_conditions_returns_go_when_conditions_meet_profile() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_ceiling_ft_agl=2500,
        min_visibility_sm=5.0,
        max_surface_wind_kt=20,
        max_crosswind_kt=12,
        min_runway_length_ft=3000,
        allowed_runway_surfaces=["asphalt"],
        allow_ifr=False,
        allow_night=False,
    )
    metar = _metar()
    airport = _airport()

    result = evaluate_conditions(
        profile=profile,
        metar=metar,
        airport=airport,
        runway_wind_components=compute_runway_wind_components(metar, airport),
    )

    assert result.decision == "go"
    assert result.fail_reasons == []
    assert result.best_runway is not None


def test_evaluate_conditions_returns_no_go_for_low_visibility_and_crosswind() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_visibility_sm=5.0,
        max_crosswind_kt=5,
    )
    metar = _metar(visibility_sm=2.0, wind_direction_degrees=170, wind_speed_kt=15)
    airport = _airport()

    result = evaluate_conditions(
        profile=profile,
        metar=metar,
        airport=airport,
        runway_wind_components=compute_runway_wind_components(metar, airport),
    )

    assert result.decision == "no-go"
    assert any("Visibility" in reason for reason in result.fail_reasons)
    assert any("crosswind" in reason for reason in result.fail_reasons)


def test_evaluate_conditions_returns_caution_for_missing_required_inputs() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_visibility_sm=5.0,
        max_crosswind_kt=10,
    )
    metar = _metar(visibility_sm=None, wind_direction_degrees=None, wind_speed_kt=None)

    result = evaluate_conditions(profile=profile, metar=metar, airport=None, runway_wind_components=[])

    assert result.decision == "caution"
    assert result.fail_reasons == []
    assert len(result.unknowns) >= 2


def test_evaluate_conditions_blocks_night_when_profile_disallows_it() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        allow_night=False,
    )
    metar = _metar(observed_at="2026-04-04T23:00:00Z")

    result = evaluate_conditions(profile=profile, metar=metar)

    assert result.decision == "no-go"
    assert any("night" in reason.lower() for reason in result.fail_reasons)
