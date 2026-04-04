"""Decision logic for comparing weather and airport data to personal minimums."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .minimums import MinimumsProfile
from .models import AirportRecord, EvaluationResult, MetarRecord, TafRecord


def _parse_observed_time(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _lowest_ceiling_ft(metar: MetarRecord) -> int | None:
    ceilings: list[int] = []
    for layer in metar.sky_cover:
        cover = str(layer.get("cover", "")).upper()
        base = layer.get("base")
        if cover in {"BKN", "OVC", "VV"} and isinstance(base, (int, float)):
            ceilings.append(int(base))
    if not ceilings:
        return None
    return min(ceilings)


def _is_night(observed_at: datetime | None) -> bool | None:
    if observed_at is None:
        return None
    hour = observed_at.hour
    return hour < 6 or hour >= 18


def _pick_best_runway(runway_wind_components: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runway_wind_components:
        return None
    return max(runway_wind_components, key=lambda item: item.get("headwind_kt", float("-inf")))


def evaluate_conditions(
    *,
    profile: MinimumsProfile,
    metar: MetarRecord,
    taf: TafRecord | None = None,
    airport: AirportRecord | None = None,
    runway_wind_components: list[dict[str, Any]] | None = None,
) -> EvaluationResult:
    """Compare the current station conditions to one minimums profile."""

    profile.validate()

    fail_reasons: list[str] = []
    caution_reasons: list[str] = []
    pass_reasons: list[str] = []
    unknowns: list[str] = []

    observed_at = _parse_observed_time(metar.observed_at)
    is_night = _is_night(observed_at)
    ceiling_ft = _lowest_ceiling_ft(metar)
    best_runway = _pick_best_runway(runway_wind_components or [])

    if profile.min_visibility_sm is not None:
        if metar.visibility_sm is None:
            unknowns.append("Visibility minimum is set, but METAR visibility is unavailable.")
        elif metar.visibility_sm < profile.min_visibility_sm:
            fail_reasons.append(
                f"Visibility {metar.visibility_sm:.1f} SM is below minimum {profile.min_visibility_sm:.1f} SM."
            )
        else:
            pass_reasons.append(
                f"Visibility {metar.visibility_sm:.1f} SM meets minimum {profile.min_visibility_sm:.1f} SM."
            )

    if profile.min_ceiling_ft_agl is not None:
        if ceiling_ft is None:
            unknowns.append("Ceiling minimum is set, but no broken/overcast ceiling was parsed from METAR.")
        elif ceiling_ft < profile.min_ceiling_ft_agl:
            fail_reasons.append(
                f"Ceiling {ceiling_ft} ft is below minimum {profile.min_ceiling_ft_agl} ft."
            )
        else:
            pass_reasons.append(
                f"Ceiling {ceiling_ft} ft meets minimum {profile.min_ceiling_ft_agl} ft."
            )

    if profile.max_surface_wind_kt is not None:
        if metar.wind_speed_kt is None:
            unknowns.append("Surface wind limit is set, but METAR wind speed is unavailable.")
        elif metar.wind_speed_kt > profile.max_surface_wind_kt:
            fail_reasons.append(
                f"Surface wind {metar.wind_speed_kt} kt exceeds limit {profile.max_surface_wind_kt} kt."
            )
        else:
            pass_reasons.append(
                f"Surface wind {metar.wind_speed_kt} kt is within limit {profile.max_surface_wind_kt} kt."
            )

    if profile.max_gust_kt is not None:
        if metar.wind_gust_kt is None:
            caution_reasons.append("Gust limit is set, but no gust was reported in the current METAR.")
        elif metar.wind_gust_kt > profile.max_gust_kt:
            fail_reasons.append(
                f"Gust {metar.wind_gust_kt} kt exceeds limit {profile.max_gust_kt} kt."
            )
        else:
            pass_reasons.append(
                f"Gust {metar.wind_gust_kt} kt is within limit {profile.max_gust_kt} kt."
            )

    if profile.allow_night is False:
        if is_night is None:
            unknowns.append("Night restriction is set, but METAR observation time could not be parsed.")
        elif is_night:
            fail_reasons.append("Profile does not allow night operations, and the observation is at night.")
        else:
            pass_reasons.append("Profile does not allow night operations, and current observation is daytime.")

    if profile.allow_ifr is False:
        if metar.flight_category is None:
            unknowns.append("IFR restriction is set, but METAR flight category is unavailable.")
        elif metar.flight_category.upper() in {"IFR", "LIFR"}:
            fail_reasons.append(
                f"Profile does not allow IFR, and current flight category is {metar.flight_category}."
            )
        else:
            pass_reasons.append(
                f"Current flight category {metar.flight_category} is acceptable for a non-IFR profile."
            )

    if airport is not None:
        if profile.min_runway_length_ft is not None:
            qualifying = [r for r in airport.runways if r.length_ft is not None and r.length_ft >= profile.min_runway_length_ft]
            if not qualifying:
                fail_reasons.append(
                    f"No runway meets minimum length {profile.min_runway_length_ft} ft."
                )
            else:
                pass_reasons.append(
                    f"At least one runway meets minimum length {profile.min_runway_length_ft} ft."
                )

        if profile.min_runway_width_ft is not None:
            qualifying = [r for r in airport.runways if r.width_ft is not None and r.width_ft >= profile.min_runway_width_ft]
            if not qualifying:
                fail_reasons.append(
                    f"No runway meets minimum width {profile.min_runway_width_ft} ft."
                )
            else:
                pass_reasons.append(
                    f"At least one runway meets minimum width {profile.min_runway_width_ft} ft."
                )

        if profile.allowed_runway_surfaces is not None:
            qualifying = [
                r
                for r in airport.runways
                if r.surface is not None and r.surface in profile.allowed_runway_surfaces
            ]
            if not qualifying:
                fail_reasons.append(
                    f"No runway matches allowed surfaces {profile.allowed_runway_surfaces}."
                )
            else:
                pass_reasons.append(
                    f"At least one runway matches allowed surfaces {profile.allowed_runway_surfaces}."
                )
    elif any(
        value is not None
        for value in (
            profile.min_runway_length_ft,
            profile.min_runway_width_ft,
            profile.allowed_runway_surfaces,
        )
    ):
        unknowns.append("Runway minimums are set, but airport/runway data is unavailable.")

    if profile.max_crosswind_kt is not None:
        if best_runway is None:
            unknowns.append("Crosswind limit is set, but runway wind components are unavailable.")
        elif float(best_runway["crosswind_kt"]) > profile.max_crosswind_kt:
            fail_reasons.append(
                f"Best available runway crosswind {best_runway['crosswind_kt']} kt exceeds limit {profile.max_crosswind_kt} kt."
            )
        else:
            pass_reasons.append(
                f"Best available runway crosswind {best_runway['crosswind_kt']} kt is within limit {profile.max_crosswind_kt} kt."
            )

    if profile.max_tailwind_kt is not None:
        if best_runway is None:
            unknowns.append("Tailwind limit is set, but runway wind components are unavailable.")
        elif float(best_runway["tailwind_kt"]) > profile.max_tailwind_kt:
            fail_reasons.append(
                f"Best available runway tailwind {best_runway['tailwind_kt']} kt exceeds limit {profile.max_tailwind_kt} kt."
            )
        else:
            pass_reasons.append(
                f"Best available runway tailwind {best_runway['tailwind_kt']} kt is within limit {profile.max_tailwind_kt} kt."
            )

    if profile.require_dry_runway is True:
        caution_reasons.append(
            "Dry-runway minimum is set, but runway surface condition is not currently evaluated from airport weather data."
        )

    if profile.min_fuel_reserve_min is not None:
        caution_reasons.append(
            f"Fuel reserve minimum {profile.min_fuel_reserve_min} min is stored, but fuel planning is not yet evaluated."
        )
    if profile.min_fuel_reserve_day_min is not None:
        caution_reasons.append(
            f"Day fuel reserve minimum {profile.min_fuel_reserve_day_min} min is stored, but fuel planning is not yet evaluated."
        )
    if profile.min_fuel_reserve_night_min is not None:
        caution_reasons.append(
            f"Night fuel reserve minimum {profile.min_fuel_reserve_night_min} min is stored, but fuel planning is not yet evaluated."
        )
    if profile.max_density_altitude_ft is not None:
        caution_reasons.append(
            f"Density altitude limit {profile.max_density_altitude_ft} ft is stored, but density altitude is not yet computed."
        )
    if profile.require_alternate_for_ifr is True and taf is None:
        caution_reasons.append(
            "IFR alternate requirement is set, but no TAF was provided to evaluate alternate planning."
        )

    decision = "go"
    if fail_reasons:
        decision = "no-go"
    elif caution_reasons or unknowns:
        decision = "caution"

    metar_summary = {
        "flight_category": metar.flight_category,
        "visibility_sm": metar.visibility_sm,
        "ceiling_ft_agl": ceiling_ft,
        "wind_direction_degrees": metar.wind_direction_degrees,
        "wind_speed_kt": metar.wind_speed_kt,
        "wind_gust_kt": metar.wind_gust_kt,
        "observed_at": metar.observed_at,
        "is_night": is_night,
    }
    taf_summary = None if taf is None else {"raw_text": taf.raw_text, "issued_at": taf.issued_at}
    airport_summary = None
    if airport is not None:
        airport_summary = {
            "name": airport.name,
            "runway_count": len(airport.runways),
        }

    return EvaluationResult(
        profile_id=profile.profile_id,
        airport_id=metar.icao_id,
        decision=decision,
        fail_reasons=fail_reasons,
        caution_reasons=caution_reasons,
        pass_reasons=pass_reasons,
        unknowns=unknowns,
        metar_summary=metar_summary,
        taf_summary=taf_summary,
        airport_summary=airport_summary,
        best_runway=best_runway,
    )
