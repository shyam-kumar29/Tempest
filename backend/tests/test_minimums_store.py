from __future__ import annotations

from pathlib import Path

import pytest

from tempest.minimums import MinimumsProfile
from tempest.minimums_store import JsonMinimumsStore, MinimumsStoreError


def _sample_profile(profile_id: str = "primary") -> MinimumsProfile:
    return MinimumsProfile(
        profile_id=profile_id,
        display_name="Primary",
        min_ceiling_ft_agl=2500,
        min_visibility_sm=5.0,
        max_surface_wind_kt=20,
        max_crosswind_kt=12,
        max_gust_kt=28,
        allow_night=False,
        allow_ifr=False,
        notes="No night flights",
    )


def test_store_upsert_get_list_delete(tmp_path: Path) -> None:
    store = JsonMinimumsStore(tmp_path / "profiles.json")

    saved = store.upsert_profile(_sample_profile())
    fetched = store.get_profile("primary")
    listed = store.list_profiles()
    deleted = store.delete_profile("primary")
    missing = store.get_profile("primary")

    assert saved.profile_id == "primary"
    assert fetched is not None
    assert fetched.display_name == "Primary"
    assert len(listed) == 1
    assert deleted is True
    assert missing is None


def test_store_preserves_created_at_on_update(tmp_path: Path) -> None:
    store = JsonMinimumsStore(tmp_path / "profiles.json")

    first = store.upsert_profile(_sample_profile())
    second_profile = _sample_profile()
    second_profile.min_visibility_sm = 6.0
    second = store.upsert_profile(second_profile)

    assert first.created_at == second.created_at
    assert second.updated_at is not None
    assert second.min_visibility_sm == 6.0


def test_store_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("not-json", encoding="utf-8")
    store = JsonMinimumsStore(path)

    with pytest.raises(MinimumsStoreError, match="not valid JSON"):
        store.list_profiles()
