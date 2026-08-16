"""JSON-backed persistence for personal minimums profiles."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .minimums import MinimumsProfile, MinimumsValidationError, utc_now_iso


class MinimumsStoreError(RuntimeError):
    """Raised for storage-level failures (I/O or data corruption)."""


class JsonMinimumsStore:
    def __init__(self, path: Path, *, owner_id: str | None = None) -> None:
        self.path = path
        self.owner_id = owner_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[MinimumsProfile]:
        data = self._load_raw()
        profiles_raw = self._profiles_raw(data)

        profiles: list[MinimumsProfile] = []
        for item in profiles_raw.values():
            if not isinstance(item, dict):
                raise MinimumsStoreError("Invalid minimums store format: profile must be an object")
            profiles.append(MinimumsProfile.from_dict(item))
        return sorted(profiles, key=lambda p: p.profile_id)

    def get_profile(self, profile_id: str) -> MinimumsProfile | None:
        key = profile_id.strip()
        if not key:
            raise MinimumsValidationError("profile_id is required")

        data = self._load_raw()
        profiles_raw = self._profiles_raw(data)

        raw = profiles_raw.get(key)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise MinimumsStoreError("Invalid minimums store format: profile must be an object")
        return MinimumsProfile.from_dict(raw)

    def upsert_profile(self, profile: MinimumsProfile) -> MinimumsProfile:
        profile.validate()

        data = self._load_raw()
        profiles_raw = self._profiles_raw(data)

        now = utc_now_iso()
        existing = profiles_raw.get(profile.profile_id)
        created_at = None
        if isinstance(existing, dict):
            created_at = existing.get("created_at")

        saved = MinimumsProfile(
            profile_id=profile.profile_id,
            display_name=profile.display_name,
            min_ceiling_ft_agl=profile.min_ceiling_ft_agl,
            min_visibility_sm=profile.min_visibility_sm,
            max_surface_wind_kt=profile.max_surface_wind_kt,
            max_crosswind_kt=profile.max_crosswind_kt,
            max_gust_kt=profile.max_gust_kt,
            max_tailwind_kt=profile.max_tailwind_kt,
            allow_night=profile.allow_night,
            allow_ifr=profile.allow_ifr,
            min_runway_length_ft=profile.min_runway_length_ft,
            min_runway_width_ft=profile.min_runway_width_ft,
            allowed_runway_surfaces=profile.allowed_runway_surfaces,
            require_dry_runway=profile.require_dry_runway,
            min_fuel_reserve_min=profile.min_fuel_reserve_min,
            min_fuel_reserve_day_min=profile.min_fuel_reserve_day_min,
            min_fuel_reserve_night_min=profile.min_fuel_reserve_night_min,
            max_density_altitude_ft=profile.max_density_altitude_ft,
            require_alternate_for_ifr=profile.require_alternate_for_ifr,
            home_airport=profile.home_airport,
            recommendation_min_distance_nm=profile.recommendation_min_distance_nm,
            recommendation_radius_nm=profile.recommendation_radius_nm,
            recommendation_count=profile.recommendation_count,
            favorite_airports=profile.favorite_airports,
            notes=profile.notes,
            created_at=str(created_at) if created_at else now,
            updated_at=now,
        )
        saved.validate()

        profiles_raw[saved.profile_id] = saved.to_dict()
        self._save_raw(data)
        return saved

    def delete_profile(self, profile_id: str) -> bool:
        key = profile_id.strip()
        if not key:
            raise MinimumsValidationError("profile_id is required")

        data = self._load_raw()
        profiles_raw = self._profiles_raw(data)

        if key not in profiles_raw:
            return False

        del profiles_raw[key]
        self._save_raw(data)
        return True

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MinimumsStoreError(f"Minimums store is not valid JSON: {self.path}") from exc
        except OSError as exc:
            raise MinimumsStoreError(f"Failed reading minimums store: {self.path}") from exc

        if not isinstance(raw, dict):
            raise MinimumsStoreError("Invalid minimums store format: root must be an object")

        return raw

    def _profiles_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.owner_id is None:
            profiles = data.get("profiles")
            if profiles is None:
                profiles = {}
                data["profiles"] = profiles
            if not isinstance(profiles, dict):
                raise MinimumsStoreError("Invalid minimums store format: profiles must be an object")
            return profiles

        users = data.get("users")
        if users is None:
            users = {}
            data["users"] = users
        if not isinstance(users, dict):
            raise MinimumsStoreError("Invalid minimums store format: users must be an object")
        user_bucket = users.get(self.owner_id)
        if user_bucket is None:
            user_bucket = {"profiles": {}}
            users[self.owner_id] = user_bucket
        if not isinstance(user_bucket, dict):
            raise MinimumsStoreError("Invalid minimums store format: user profile bucket must be an object")
        profiles = user_bucket.get("profiles")
        if profiles is None:
            profiles = {}
            user_bucket["profiles"] = profiles
        if not isinstance(profiles, dict):
            raise MinimumsStoreError("Invalid minimums store format: user profiles must be an object")
        return profiles

    def _save_raw(self, data: dict[str, Any]) -> None:
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")

            os.replace(tmp_path, self.path)
        except OSError as exc:
            raise MinimumsStoreError(f"Failed writing minimums store: {self.path}") from exc
