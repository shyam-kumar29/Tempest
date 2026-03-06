"""Personal minimums model and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ALLOWED_RUNWAY_SURFACES = {
    "asphalt",
    "concrete",
    "grass",
    "gravel",
    "dirt",
    "turf",
    "snow",
    "ice",
    "water",
}


class MinimumsValidationError(ValueError):
    """Raised when a minimums profile contains invalid values."""


@dataclass(slots=True)
class MinimumsProfile:
    profile_id: str
    display_name: str
    min_ceiling_ft_agl: int | None = None
    min_visibility_sm: float | None = None
    max_surface_wind_kt: int | None = None
    max_crosswind_kt: int | None = None
    max_gust_kt: int | None = None
    max_tailwind_kt: int | None = None
    allow_night: bool | None = None
    allow_ifr: bool | None = None
    min_runway_length_ft: int | None = None
    min_runway_width_ft: int | None = None
    allowed_runway_surfaces: list[str] | None = None
    require_dry_runway: bool | None = None
    min_fuel_reserve_min: int | None = None
    min_fuel_reserve_day_min: int | None = None
    min_fuel_reserve_night_min: int | None = None
    max_density_altitude_ft: int | None = None
    require_alternate_for_ifr: bool | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def validate(self) -> None:
        if not self.profile_id or not self.profile_id.strip():
            raise MinimumsValidationError("profile_id is required")
        if not self.display_name or not self.display_name.strip():
            raise MinimumsValidationError("display_name is required")
        if self.min_ceiling_ft_agl is not None and self.min_ceiling_ft_agl < 0:
            raise MinimumsValidationError("min_ceiling_ft_agl must be >= 0")
        if self.min_visibility_sm is not None and self.min_visibility_sm < 0:
            raise MinimumsValidationError("min_visibility_sm must be >= 0")
        if self.max_surface_wind_kt is not None and self.max_surface_wind_kt < 0:
            raise MinimumsValidationError("max_surface_wind_kt must be >= 0")
        if self.max_crosswind_kt is not None and self.max_crosswind_kt < 0:
            raise MinimumsValidationError("max_crosswind_kt must be >= 0")
        if self.max_gust_kt is not None and self.max_gust_kt < 0:
            raise MinimumsValidationError("max_gust_kt must be >= 0")
        if self.max_tailwind_kt is not None and self.max_tailwind_kt < 0:
            raise MinimumsValidationError("max_tailwind_kt must be >= 0")
        if self.min_runway_length_ft is not None and self.min_runway_length_ft < 0:
            raise MinimumsValidationError("min_runway_length_ft must be >= 0")
        if self.min_runway_width_ft is not None and self.min_runway_width_ft < 0:
            raise MinimumsValidationError("min_runway_width_ft must be >= 0")
        if self.min_fuel_reserve_min is not None and self.min_fuel_reserve_min < 0:
            raise MinimumsValidationError("min_fuel_reserve_min must be >= 0")
        if self.min_fuel_reserve_day_min is not None and self.min_fuel_reserve_day_min < 0:
            raise MinimumsValidationError("min_fuel_reserve_day_min must be >= 0")
        if (
            self.min_fuel_reserve_night_min is not None
            and self.min_fuel_reserve_night_min < 0
        ):
            raise MinimumsValidationError("min_fuel_reserve_night_min must be >= 0")
        if self.max_density_altitude_ft is not None and self.max_density_altitude_ft < 0:
            raise MinimumsValidationError("max_density_altitude_ft must be >= 0")

        surfaces = self.allowed_runway_surfaces
        if surfaces is None:
            return

        normalized_surfaces: list[str] = []
        for surface in surfaces:
            normalized = str(surface).strip().lower()
            if normalized not in ALLOWED_RUNWAY_SURFACES:
                raise MinimumsValidationError(
                    f"Unsupported runway surface: {surface!r}. "
                    f"Allowed: {sorted(ALLOWED_RUNWAY_SURFACES)}"
                )
            if normalized not in normalized_surfaces:
                normalized_surfaces.append(normalized)
        self.allowed_runway_surfaces = normalized_surfaces

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "min_ceiling_ft_agl": self.min_ceiling_ft_agl,
            "min_visibility_sm": self.min_visibility_sm,
            "max_surface_wind_kt": self.max_surface_wind_kt,
            "max_crosswind_kt": self.max_crosswind_kt,
            "max_gust_kt": self.max_gust_kt,
            "max_tailwind_kt": self.max_tailwind_kt,
            "allow_night": self.allow_night,
            "allow_ifr": self.allow_ifr,
            "min_runway_length_ft": self.min_runway_length_ft,
            "min_runway_width_ft": self.min_runway_width_ft,
            "allowed_runway_surfaces": self.allowed_runway_surfaces,
            "require_dry_runway": self.require_dry_runway,
            "min_fuel_reserve_min": self.min_fuel_reserve_min,
            "min_fuel_reserve_day_min": self.min_fuel_reserve_day_min,
            "min_fuel_reserve_night_min": self.min_fuel_reserve_night_min,
            "max_density_altitude_ft": self.max_density_altitude_ft,
            "require_alternate_for_ifr": self.require_alternate_for_ifr,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MinimumsProfile:
        profile = cls(
            profile_id=str(data.get("profile_id", "")).strip(),
            display_name=str(data.get("display_name", "")).strip(),
            min_ceiling_ft_agl=(
                int(data["min_ceiling_ft_agl"])
                if data.get("min_ceiling_ft_agl") is not None
                else None
            ),
            min_visibility_sm=(
                float(data["min_visibility_sm"])
                if data.get("min_visibility_sm") is not None
                else None
            ),
            max_surface_wind_kt=(
                int(data["max_surface_wind_kt"])
                if data.get("max_surface_wind_kt") is not None
                else None
            ),
            max_crosswind_kt=(
                int(data["max_crosswind_kt"])
                if data.get("max_crosswind_kt") is not None
                else None
            ),
            max_gust_kt=(
                int(data["max_gust_kt"]) if data.get("max_gust_kt") is not None else None
            ),
            max_tailwind_kt=(
                int(data["max_tailwind_kt"]) if data.get("max_tailwind_kt") is not None else None
            ),
            allow_night=(
                bool(data["allow_night"]) if data.get("allow_night") is not None else None
            ),
            allow_ifr=(
                bool(data["allow_ifr"]) if data.get("allow_ifr") is not None else None
            ),
            min_runway_length_ft=(
                int(data["min_runway_length_ft"])
                if data.get("min_runway_length_ft") is not None
                else None
            ),
            min_runway_width_ft=(
                int(data["min_runway_width_ft"])
                if data.get("min_runway_width_ft") is not None
                else None
            ),
            allowed_runway_surfaces=(
                [str(value) for value in data["allowed_runway_surfaces"]]
                if data.get("allowed_runway_surfaces") is not None
                else None
            ),
            require_dry_runway=(
                bool(data["require_dry_runway"])
                if data.get("require_dry_runway") is not None
                else None
            ),
            min_fuel_reserve_min=(
                int(data["min_fuel_reserve_min"])
                if data.get("min_fuel_reserve_min") is not None
                else None
            ),
            min_fuel_reserve_day_min=(
                int(data["min_fuel_reserve_day_min"])
                if data.get("min_fuel_reserve_day_min") is not None
                else None
            ),
            min_fuel_reserve_night_min=(
                int(data["min_fuel_reserve_night_min"])
                if data.get("min_fuel_reserve_night_min") is not None
                else None
            ),
            max_density_altitude_ft=(
                int(data["max_density_altitude_ft"])
                if data.get("max_density_altitude_ft") is not None
                else None
            ),
            require_alternate_for_ifr=(
                bool(data["require_alternate_for_ifr"])
                if data.get("require_alternate_for_ifr") is not None
                else None
            ),
            notes=str(data["notes"]) if data.get("notes") is not None else None,
            created_at=(str(data["created_at"]) if data.get("created_at") else None),
            updated_at=(str(data["updated_at"]) if data.get("updated_at") else None),
        )
        profile.validate()
        return profile


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
