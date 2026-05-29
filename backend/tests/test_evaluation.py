from __future__ import annotations

from tempest.evaluation import evaluate_conditions
from tempest.minimums import MinimumsProfile
from tempest.models import AirportRecord, MetarRecord, RunwayRecord, TafRecord
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
    latitude: float | None = 40.4124,
    longitude: float | None = -86.9474,
    temperature_c: float | None = 20.0,
    altimeter_in_hg: float | None = 29.92,
    elevation_m: float | None = 184.0,
) -> MetarRecord:
    return MetarRecord(
        icao_id="KLAF",
        raw_text="KLAF ...",
        observed_at=observed_at,
        station_name=None,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation_m,
        flight_category=flight_category,
        wind_direction_degrees=wind_direction_degrees,
        wind_speed_kt=wind_speed_kt,
        wind_gust_kt=wind_gust_kt,
        visibility_sm=visibility_sm,
        temperature_c=temperature_c,
        dewpoint_c=None,
        altimeter_in_hg=altimeter_in_hg,
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
        latitude=40.4124,
        longitude=-86.9474,
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
        planned_departure="2026-04-04T18:00:00Z",
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
        planned_departure="2026-04-04T18:00:00Z",
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

    result = evaluate_conditions(
        profile=profile,
        metar=metar,
        airport=None,
        runway_wind_components=[],
        planned_departure="2026-04-04T18:00:00Z",
    )

    assert result.decision == "caution"
    assert result.fail_reasons == []
    assert len(result.unknowns) >= 2


def test_evaluate_conditions_blocks_night_when_profile_disallows_it() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        allow_night=False,
    )
    metar = _metar(observed_at="2026-04-05T03:00:00Z")

    result = evaluate_conditions(profile=profile, metar=metar, planned_departure="2026-04-05T03:00:00Z")

    assert result.decision == "no-go"
    assert any("night" in reason.lower() for reason in result.fail_reasons)


def test_evaluate_conditions_treats_klaf_afternoon_observation_as_daytime() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        allow_night=False,
    )
    metar = _metar(observed_at="2026-04-04T18:54:00Z")

    result = evaluate_conditions(profile=profile, metar=metar, planned_departure="2026-04-04T18:54:00Z")

    assert result.decision != "no-go"
    assert not any("night operations" in reason.lower() for reason in result.fail_reasons)


def test_evaluate_conditions_uses_taf_periods_for_planned_window() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_visibility_sm=5.0,
        min_ceiling_ft_agl=2500,
    )
    taf = TafRecord(
        icao_id="KLAF",
        raw_text="TAF KLAF ...",
        issued_at="2026-04-04T12:00:00Z",
        valid_from="2026-04-04T12:00:00Z",
        valid_to="2026-04-05T12:00:00Z",
        station_name=None,
        forecast=[
            {
                "timeFrom": "2026-04-04T18:00:00Z",
                "timeTo": "2026-04-04T21:00:00Z",
                "visib": 3,
                "clouds": [{"cover": "OVC", "base": 1200}],
            }
        ],
        source_payload={},
    )

    result = evaluate_conditions(
        profile=profile,
        metar=_metar(),
        taf=taf,
        planned_departure="2026-04-04T18:30:00Z",
    )

    assert result.decision == "no-go"
    assert any("TAF period" in reason for reason in result.fail_reasons)
    assert result.taf_summary is not None
    assert len(result.taf_summary["evaluated_periods"]) == 1


def test_evaluate_conditions_checks_density_altitude() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        max_density_altitude_ft=1500,
    )
    airport = _airport()
    metar = _metar(temperature_c=35.0, altimeter_in_hg=29.70)

    result = evaluate_conditions(
        profile=profile,
        metar=metar,
        airport=airport,
        planned_departure="2026-04-04T18:00:00Z",
    )

    assert result.decision == "no-go"
    assert any("Density altitude" in reason for reason in result.fail_reasons)


def test_evaluate_conditions_checks_fuel_reserve_when_provided() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_fuel_reserve_day_min=45,
    )

    result = evaluate_conditions(
        profile=profile,
        metar=_metar(),
        planned_departure="2026-04-04T18:00:00Z",
        fuel_reserve_min=30,
    )

    assert result.decision == "no-go"
    assert any("fuel reserve" in reason.lower() for reason in result.fail_reasons)
