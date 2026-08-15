from __future__ import annotations

import pytest

from tempest.minimums import MinimumsProfile, MinimumsValidationError


def test_minimums_profile_validate_success() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_ceiling_ft_agl=2500,
        min_visibility_sm=5.0,
        max_surface_wind_kt=20,
        max_crosswind_kt=12,
        max_gust_kt=28,
        max_tailwind_kt=7,
        allow_night=False,
        allow_ifr=False,
        min_runway_length_ft=3000,
        min_runway_width_ft=75,
        allowed_runway_surfaces=["asphalt", "concrete"],
        require_dry_runway=True,
        min_fuel_reserve_min=45,
        min_fuel_reserve_day_min=45,
        min_fuel_reserve_night_min=60,
        max_density_altitude_ft=6000,
        require_alternate_for_ifr=True,
        home_airport="klaf",
        recommendation_min_distance_nm=20,
        recommendation_radius_nm=100,
        recommendation_count=5,
        favorite_airports=[{"icao_id": "kind", "weight": 2, "note": "Easy lunch"}],
    )
    profile.validate()
    assert profile.home_airport == "KLAF"
    assert profile.favorite_airports == [
        {"icao_id": "KIND", "weight": 2.0, "note": "Easy lunch"}
    ]


def test_minimums_profile_validate_rejects_negative_values() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_ceiling_ft_agl=-1,
        min_visibility_sm=5.0,
        max_surface_wind_kt=20,
        max_crosswind_kt=12,
    )

    with pytest.raises(MinimumsValidationError, match="min_ceiling_ft_agl"):
        profile.validate()


def test_minimums_profile_validate_rejects_unknown_runway_surface() -> None:
    profile = MinimumsProfile(
        profile_id="primary",
        display_name="Primary",
        min_ceiling_ft_agl=2500,
        min_visibility_sm=5.0,
        max_surface_wind_kt=20,
        max_crosswind_kt=12,
        allowed_runway_surfaces=["asphalt", "moon-dust"],
    )

    with pytest.raises(MinimumsValidationError, match="Unsupported runway surface"):
        profile.validate()


def test_minimums_profile_optional_fields_can_be_none() -> None:
    profile = MinimumsProfile(profile_id="basic", display_name="Basic")
    profile.validate()
    assert profile.min_ceiling_ft_agl is None
    assert profile.min_fuel_reserve_night_min is None
    assert profile.home_airport is None
    assert profile.recommendation_min_distance_nm == 15.0
    assert profile.recommendation_radius_nm == 150.0
    assert profile.recommendation_count == 10


def test_minimums_profile_rejects_invalid_recommendation_fields() -> None:
    with pytest.raises(MinimumsValidationError, match="home_airport"):
        MinimumsProfile(
            profile_id="primary",
            display_name="Primary",
            home_airport="LAF",
        ).validate()

    with pytest.raises(MinimumsValidationError, match="recommendation_radius_nm"):
        MinimumsProfile(
            profile_id="primary",
            display_name="Primary",
            recommendation_radius_nm=0,
        ).validate()

    with pytest.raises(MinimumsValidationError, match="recommendation_radius_nm"):
        MinimumsProfile(
            profile_id="primary",
            display_name="Primary",
            recommendation_min_distance_nm=75,
            recommendation_radius_nm=50,
        ).validate()

    with pytest.raises(MinimumsValidationError, match="recommendation_count"):
        MinimumsProfile(
            profile_id="primary",
            display_name="Primary",
            recommendation_count=0,
        ).validate()

    with pytest.raises(MinimumsValidationError, match="favorite_airports"):
        MinimumsProfile(
            profile_id="primary",
            display_name="Primary",
            favorite_airports=[{"icao_id": "ABC"}],
        ).validate()
