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
        allow_night=False,
        allow_ifr=False,
    )
    profile.validate()


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
