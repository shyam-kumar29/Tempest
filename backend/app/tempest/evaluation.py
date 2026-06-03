"""Decision logic for comparing weather and airport data to personal minimums."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from .minimums import MinimumsProfile
from .models import AirportRecord, EvaluationResult, MetarRecord, TafRecord
from .timeutils import parse_aviation_time, to_local_time_string


def _day_of_year(dt: datetime) -> int:
    return dt.timetuple().tm_yday


def _normalize_hour_utc(value: float) -> float:
    while value < 0:
        value += 24
    while value >= 24:
        value -= 24
    return value


def _solar_event_utc_hour(
    observed_at: datetime,
    latitude: float,
    longitude: float,
    *,
    is_sunrise: bool,
) -> float | None:
    zenith = math.radians(90.833)
    day = _day_of_year(observed_at)
    lng_hour = longitude / 15.0
    approx = day + ((6.0 - lng_hour) / 24.0) if is_sunrise else day + ((18.0 - lng_hour) / 24.0)

    mean_anomaly = math.radians((0.9856 * approx) - 3.289)
    true_longitude_deg = math.degrees(mean_anomaly)
    true_longitude_deg += 1.916 * math.sin(mean_anomaly)
    true_longitude_deg += 0.020 * math.sin(2 * mean_anomaly)
    true_longitude_deg += 282.634
    true_longitude_deg %= 360.0
    true_longitude = math.radians(true_longitude_deg)

    right_ascension_deg = math.degrees(math.atan(0.91764 * math.tan(true_longitude)))
    right_ascension_deg %= 360.0

    l_quadrant = math.floor(true_longitude_deg / 90.0) * 90.0
    ra_quadrant = math.floor(right_ascension_deg / 90.0) * 90.0
    right_ascension_deg += l_quadrant - ra_quadrant
    right_ascension_hours = right_ascension_deg / 15.0

    sin_dec = 0.39782 * math.sin(true_longitude)
    cos_dec = math.cos(math.asin(sin_dec))
    lat_rad = math.radians(latitude)

    cos_hour_angle = (
        math.cos(zenith) - (sin_dec * math.sin(lat_rad))
    ) / (cos_dec * math.cos(lat_rad))
    if cos_hour_angle < -1.0 or cos_hour_angle > 1.0:
        return None

    hour_angle_deg = (
        360.0 - math.degrees(math.acos(cos_hour_angle))
        if is_sunrise
        else math.degrees(math.acos(cos_hour_angle))
    )
    hour_angle_hours = hour_angle_deg / 15.0

    local_mean_time = hour_angle_hours + right_ascension_hours - (0.06571 * approx) - 6.622
    return _normalize_hour_utc(local_mean_time - lng_hour)


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


def _has_clear_sky_report(metar: MetarRecord) -> bool:
    clear_codes = {"CLR", "SKC", "NSC", "NCD"}
    if any(str(layer.get("cover", "")).upper() in clear_codes for layer in metar.sky_cover):
        return True
    return any(code in metar.raw_text.upper().split() for code in clear_codes)


def _surface_matches(runway_surface: str | None, allowed_surfaces: list[str]) -> bool | None:
    if runway_surface is None:
        return None

    surface = runway_surface.strip().lower()
    allowed = {surface.strip().lower() for surface in allowed_surfaces}
    if surface in allowed:
        return True

    hard_surfaces = {"asphalt", "concrete"}
    if surface in {"hard", "paved"} and allowed & hard_surfaces:
        return True

    return False


def _profile_needs_weather_source(profile: MinimumsProfile) -> bool:
    return any(
        value is not None
        for value in (
            profile.min_visibility_sm,
            profile.min_ceiling_ft_agl,
            profile.max_surface_wind_kt,
            profile.max_gust_kt,
            profile.max_crosswind_kt,
            profile.max_tailwind_kt,
            profile.allow_ifr,
            profile.max_density_altitude_ft,
        )
    )


def _is_night(
    observed_at: datetime | None,
    *,
    latitude: float | None,
    longitude: float | None,
) -> bool | None:
    if observed_at is None or latitude is None or longitude is None:
        return None

    sunrise_hour = _solar_event_utc_hour(observed_at, latitude, longitude, is_sunrise=True)
    sunset_hour = _solar_event_utc_hour(observed_at, latitude, longitude, is_sunrise=False)
    if sunrise_hour is None or sunset_hour is None:
        return None

    observed_hour = (
        observed_at.hour
        + (observed_at.minute / 60.0)
        + (observed_at.second / 3600.0)
    )
    if sunrise_hour <= sunset_hour:
        return observed_hour < sunrise_hour or observed_hour >= sunset_hour

    # When sunset falls after 00:00 UTC, daytime spans [sunrise, 24) union [0, sunset).
    is_day = observed_hour >= sunrise_hour or observed_hour < sunset_hour
    return not is_day


def _pick_best_runway(runway_wind_components: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runway_wind_components:
        return None
    return max(runway_wind_components, key=lambda item: item.get("headwind_kt", float("-inf")))


def _metar_covers_planned_departure(metar: MetarRecord, planned_at: datetime) -> bool:
    observed_at = parse_aviation_time(metar.observed_at)
    if observed_at is None:
        return False
    delta = planned_at.astimezone(UTC) - observed_at.astimezone(UTC)
    return timedelta(0) <= delta <= timedelta(hours=1)


def _normalize_angle(delta: float) -> float:
    while delta > 180:
        delta -= 360
    while delta < -180:
        delta += 360
    return delta


def _runway_components_for_wind(
    *,
    wind_direction_degrees: int | None,
    wind_speed_kt: int | None,
    airport: AirportRecord | None,
) -> list[dict[str, Any]]:
    if airport is None or wind_direction_degrees is None or wind_speed_kt is None:
        return []

    components: list[dict[str, Any]] = []
    for runway in airport.runways:
        if runway.heading_degrees is None:
            continue
        delta = _normalize_angle(wind_direction_degrees - runway.heading_degrees)
        radians = math.radians(delta)
        headwind = wind_speed_kt * math.cos(radians)
        crosswind = wind_speed_kt * math.sin(radians)
        components.append(
            {
                "runway_id": runway.runway_id,
                "runway_heading_degrees": round(runway.heading_degrees, 1),
                "wind_direction_degrees": wind_direction_degrees,
                "wind_speed_kt": wind_speed_kt,
                "headwind_kt": round(headwind, 1),
                "tailwind_kt": round(max(0.0, -headwind), 1),
                "crosswind_kt": round(abs(crosswind), 1),
                "crosswind_from": "right" if crosswind > 0 else "left",
            }
        )
    return components


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().upper().replace("SM", "").replace("P", "").replace("+", "")
        if cleaned in {"", "M"}:
            return None
        value = cleaned
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _taf_period_bounds(period: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start = parse_aviation_time(
        period.get("timeFrom")
        or period.get("validTimeFrom")
        or period.get("valid_from")
        or period.get("from")
    )
    end = parse_aviation_time(
        period.get("timeTo")
        or period.get("validTimeTo")
        or period.get("valid_to")
        or period.get("to")
    )
    return start, end


def _period_overlaps(
    period_start: datetime | None,
    period_end: datetime | None,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if period_start is None or period_end is None:
        return False
    start = period_start.astimezone(UTC)
    end = period_end.astimezone(UTC)
    return start <= window_end and end >= window_start


def _period_contains(
    period_start: datetime | None,
    period_end: datetime | None,
    instant: datetime,
) -> bool:
    if period_start is None or period_end is None:
        return False
    current = instant.astimezone(UTC)
    return period_start.astimezone(UTC) <= current <= period_end.astimezone(UTC)


def _ceiling_from_clouds(clouds: Any) -> int | None:
    if not isinstance(clouds, list):
        return None
    ceilings: list[int] = []
    for layer in clouds:
        if not isinstance(layer, dict):
            continue
        cover = str(layer.get("cover", "")).upper()
        base = layer.get("base")
        if cover in {"BKN", "OVC", "VV"} and isinstance(base, (int, float)):
            ceilings.append(int(base))
    if not ceilings:
        return None
    return min(ceilings)


def _taf_period_summary(period: dict[str, Any]) -> dict[str, Any]:
    start, end = _taf_period_bounds(period)
    return {
        "from": None if start is None else start.isoformat(),
        "to": None if end is None else end.isoformat(),
        "visibility_sm": _as_float(period.get("visib") or period.get("visibility")),
        "ceiling_ft_agl": _ceiling_from_clouds(period.get("clouds") or period.get("sky_condition")),
        "wind_speed_kt": _as_int(period.get("wspd") or period.get("wind_speed_kt")),
        "wind_gust_kt": _as_int(period.get("wgst") or period.get("wind_gust_kt")),
        "raw": period,
    }


def _density_altitude_ft(metar: MetarRecord, airport: AirportRecord | None) -> int | None:
    if metar.temperature_c is None or metar.altimeter_in_hg is None:
        return None

    elevation_ft: float | None = None
    if airport is not None and airport.elevation_ft is not None:
        elevation_ft = float(airport.elevation_ft)
    elif metar.elevation_m is not None:
        elevation_ft = metar.elevation_m * 3.28084

    if elevation_ft is None:
        return None

    pressure_altitude = elevation_ft + ((29.92 - metar.altimeter_in_hg) * 1000.0)
    isa_temp_c = 15.0 - (2.0 * (elevation_ft / 1000.0))
    density_altitude = pressure_altitude + (120.0 * (metar.temperature_c - isa_temp_c))
    return round(density_altitude)


def evaluate_conditions(
    *,
    profile: MinimumsProfile,
    metar: MetarRecord,
    taf: TafRecord | None = None,
    airport: AirportRecord | None = None,
    runway_wind_components: list[dict[str, Any]] | None = None,
    planned_departure: str | int | datetime | None = None,
    taf_lookahead_hours: float = 0.0,
    fuel_reserve_min: int | None = None,
) -> EvaluationResult:
    """Compare the current station conditions to one minimums profile."""

    profile.validate()

    fail_reasons: list[str] = []
    caution_reasons: list[str] = []
    pass_reasons: list[str] = []
    unknowns: list[str] = []

    planned_at = (
        planned_departure
        if isinstance(planned_departure, datetime)
        else parse_aviation_time(planned_departure)
    )
    if planned_at is None:
        planned_at = datetime.now(UTC)
    planned_at = planned_at.astimezone(UTC)
    taf_window_end = planned_at + timedelta(hours=max(0.0, taf_lookahead_hours))
    metar_applies = _metar_covers_planned_departure(metar, planned_at)

    is_night = _is_night(
        planned_at,
        latitude=metar.latitude if metar.latitude is not None else (airport.latitude if airport else None),
        longitude=metar.longitude if metar.longitude is not None else (airport.longitude if airport else None),
    )
    ceiling_ft = _lowest_ceiling_ft(metar)
    clear_sky = _has_clear_sky_report(metar)
    density_altitude_ft = _density_altitude_ft(metar, airport)

    relevant_taf_periods: list[dict[str, Any]] = []
    if taf is not None:
        for period in taf.forecast:
            if not isinstance(period, dict):
                continue
            period_start, period_end = _taf_period_bounds(period)
            if taf_lookahead_hours > 0:
                matches_period = _period_overlaps(period_start, period_end, planned_at, taf_window_end)
            else:
                matches_period = _period_contains(period_start, period_end, planned_at)
            if matches_period:
                relevant_taf_periods.append(_taf_period_summary(period))

    weather_source = "metar" if metar_applies else "taf"
    selected_taf_period = relevant_taf_periods[0] if relevant_taf_periods else None
    selected_runway_components = (
        runway_wind_components or []
        if metar_applies
        else _runway_components_for_wind(
            wind_direction_degrees=(
                None if selected_taf_period is None else _as_int(selected_taf_period["raw"].get("wdir"))
            ),
            wind_speed_kt=None if selected_taf_period is None else selected_taf_period["wind_speed_kt"],
            airport=airport,
        )
    )
    best_runway = _pick_best_runway(selected_runway_components)

    needs_weather_source = _profile_needs_weather_source(profile)
    if not metar_applies and selected_taf_period is None and needs_weather_source:
        unknowns.append(
            "Planned departure is outside the current METAR window, and no TAF period covers the planned departure."
        )

    if profile.min_visibility_sm is not None and metar_applies:
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
    elif profile.min_visibility_sm is not None and selected_taf_period is not None:
        visibility_sm = selected_taf_period["visibility_sm"]
        if visibility_sm is None:
            unknowns.append("Visibility minimum is set, but TAF visibility is unavailable for the planned departure.")
        elif visibility_sm < profile.min_visibility_sm:
            fail_reasons.append(
                f"TAF forecasts visibility {visibility_sm:.1f} SM below minimum {profile.min_visibility_sm:.1f} SM at planned departure."
            )
        else:
            pass_reasons.append(
                f"TAF visibility {visibility_sm:.1f} SM meets minimum {profile.min_visibility_sm:.1f} SM at planned departure."
            )

    if profile.min_ceiling_ft_agl is not None and metar_applies:
        if ceiling_ft is None and clear_sky:
            pass_reasons.append("No ceiling is reported in the current METAR.")
        elif ceiling_ft is None:
            unknowns.append("Ceiling minimum is set, but no broken/overcast ceiling was parsed from METAR.")
        elif ceiling_ft < profile.min_ceiling_ft_agl:
            fail_reasons.append(
                f"Ceiling {ceiling_ft} ft is below minimum {profile.min_ceiling_ft_agl} ft."
            )
        else:
            pass_reasons.append(
                f"Ceiling {ceiling_ft} ft meets minimum {profile.min_ceiling_ft_agl} ft."
            )
    elif profile.min_ceiling_ft_agl is not None and selected_taf_period is not None:
        taf_ceiling_ft = selected_taf_period["ceiling_ft_agl"]
        taf_clouds = selected_taf_period["raw"].get("clouds") or selected_taf_period["raw"].get("sky_condition")
        taf_clear = (
            isinstance(taf_clouds, list)
            and any(str(layer.get("cover", "")).upper() in {"CLR", "SKC", "NSC", "NCD"} for layer in taf_clouds if isinstance(layer, dict))
        )
        if taf_ceiling_ft is None and taf_clear:
            pass_reasons.append("TAF reports no ceiling at planned departure.")
        elif taf_ceiling_ft is None:
            unknowns.append("Ceiling minimum is set, but TAF ceiling is unavailable for the planned departure.")
        elif taf_ceiling_ft < profile.min_ceiling_ft_agl:
            fail_reasons.append(
                f"TAF forecasts ceiling {taf_ceiling_ft} ft below minimum {profile.min_ceiling_ft_agl} ft at planned departure."
            )
        else:
            pass_reasons.append(
                f"TAF ceiling {taf_ceiling_ft} ft meets minimum {profile.min_ceiling_ft_agl} ft at planned departure."
            )

    if profile.max_surface_wind_kt is not None and metar_applies:
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
    elif profile.max_surface_wind_kt is not None and selected_taf_period is not None:
        wind_speed_kt = selected_taf_period["wind_speed_kt"]
        if wind_speed_kt is None:
            unknowns.append("Surface wind limit is set, but TAF wind speed is unavailable for the planned departure.")
        elif wind_speed_kt > profile.max_surface_wind_kt:
            fail_reasons.append(
                f"TAF forecasts wind {wind_speed_kt} kt above limit {profile.max_surface_wind_kt} kt at planned departure."
            )
        else:
            pass_reasons.append(
                f"TAF wind {wind_speed_kt} kt is within limit {profile.max_surface_wind_kt} kt at planned departure."
            )

    if profile.max_gust_kt is not None and metar_applies:
        if metar.wind_gust_kt is None:
            pass_reasons.append("No gust is reported in the current METAR.")
        elif metar.wind_gust_kt > profile.max_gust_kt:
            fail_reasons.append(
                f"Gust {metar.wind_gust_kt} kt exceeds limit {profile.max_gust_kt} kt."
            )
        else:
            pass_reasons.append(
                f"Gust {metar.wind_gust_kt} kt is within limit {profile.max_gust_kt} kt."
            )
    elif profile.max_gust_kt is not None and selected_taf_period is not None:
        gust_kt = selected_taf_period["wind_gust_kt"]
        if gust_kt is None:
            pass_reasons.append("TAF reports no gust at planned departure.")
        elif gust_kt > profile.max_gust_kt:
            fail_reasons.append(
                f"TAF forecasts gust {gust_kt} kt above limit {profile.max_gust_kt} kt at planned departure."
            )
        else:
            pass_reasons.append(
                f"TAF gust {gust_kt} kt is within limit {profile.max_gust_kt} kt at planned departure."
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
            matches = [
                _surface_matches(r.surface, profile.allowed_runway_surfaces)
                for r in airport.runways
            ]
            qualifying = [match for match in matches if match is True]
            if not qualifying:
                if any(match is None for match in matches):
                    unknowns.append(
                        f"Allowed runway surfaces are set to {profile.allowed_runway_surfaces}, but one or more runway surfaces are unavailable."
                    )
                else:
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
            unknowns.append(f"Crosswind limit is set, but {weather_source.upper()} runway wind components are unavailable.")
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
            unknowns.append(f"Tailwind limit is set, but {weather_source.upper()} runway wind components are unavailable.")
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

    fuel_requirements: list[tuple[str, int]] = []
    if profile.min_fuel_reserve_min is not None:
        fuel_requirements.append(("fuel reserve", profile.min_fuel_reserve_min))
    if is_night is True and profile.min_fuel_reserve_night_min is not None:
        fuel_requirements.append(("night fuel reserve", profile.min_fuel_reserve_night_min))
    if is_night is False and profile.min_fuel_reserve_day_min is not None:
        fuel_requirements.append(("day fuel reserve", profile.min_fuel_reserve_day_min))
    if fuel_requirements:
        if fuel_reserve_min is None:
            pass_reasons.append("Fuel reserve minimum is saved in the profile; no current fuel value was provided for this check.")
        else:
            for label, required in fuel_requirements:
                if fuel_reserve_min < required:
                    fail_reasons.append(
                        f"Current fuel reserve {fuel_reserve_min} min is below {label} minimum {required} min."
                    )
                else:
                    pass_reasons.append(
                        f"Current fuel reserve {fuel_reserve_min} min meets {label} minimum {required} min."
                    )

    if profile.max_density_altitude_ft is not None:
        if density_altitude_ft is None:
            unknowns.append("Density altitude limit is set, but density altitude could not be computed.")
        elif density_altitude_ft > profile.max_density_altitude_ft:
            fail_reasons.append(
                f"Density altitude {density_altitude_ft} ft exceeds limit {profile.max_density_altitude_ft} ft."
            )
        else:
            pass_reasons.append(
                f"Density altitude {density_altitude_ft} ft is within limit {profile.max_density_altitude_ft} ft."
            )

    if taf is not None and not relevant_taf_periods and not metar_applies and needs_weather_source:
        unknowns.append("TAF was provided, but no forecast period matched the planned evaluation window.")

    for period in ([] if not metar_applies else relevant_taf_periods):
        label = f"TAF period {period['from']} to {period['to']}"
        if profile.min_visibility_sm is not None and period["visibility_sm"] is not None:
            if period["visibility_sm"] < profile.min_visibility_sm:
                fail_reasons.append(
                    f"{label} forecasts visibility {period['visibility_sm']:.1f} SM below minimum {profile.min_visibility_sm:.1f} SM."
                )
        if profile.min_ceiling_ft_agl is not None and period["ceiling_ft_agl"] is not None:
            if period["ceiling_ft_agl"] < profile.min_ceiling_ft_agl:
                fail_reasons.append(
                    f"{label} forecasts ceiling {period['ceiling_ft_agl']} ft below minimum {profile.min_ceiling_ft_agl} ft."
                )
        if profile.max_surface_wind_kt is not None and period["wind_speed_kt"] is not None:
            if period["wind_speed_kt"] > profile.max_surface_wind_kt:
                fail_reasons.append(
                    f"{label} forecasts wind {period['wind_speed_kt']} kt above limit {profile.max_surface_wind_kt} kt."
                )
        if profile.max_gust_kt is not None and period["wind_gust_kt"] is not None:
            if period["wind_gust_kt"] > profile.max_gust_kt:
                fail_reasons.append(
                    f"{label} forecasts gust {period['wind_gust_kt']} kt above limit {profile.max_gust_kt} kt."
                )

    if relevant_taf_periods:
        pass_reasons.append(
            f"Evaluated {len(relevant_taf_periods)} TAF forecast period(s) for the planned window."
        )

    if profile.require_alternate_for_ifr is True:
        if taf is None:
            caution_reasons.append(
                "IFR alternate requirement is set, but no TAF was provided to evaluate alternate planning."
            )
        else:
            caution_reasons.append(
                "IFR alternate requirement is set; destination TAF was checked, but alternate airport selection is not implemented yet."
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
        "observed_at_local": to_local_time_string(metar.observed_at),
        "planned_departure": planned_at.isoformat(),
        "planned_departure_local": planned_at.astimezone().isoformat(),
        "is_night": is_night,
        "density_altitude_ft": density_altitude_ft,
    }
    taf_summary = (
        None
        if taf is None
        else {
            "raw_text": taf.raw_text,
            "issued_at": taf.issued_at,
            "issued_at_local": to_local_time_string(taf.issued_at),
            "valid_from": taf.valid_from,
            "valid_from_local": to_local_time_string(taf.valid_from),
            "valid_to": taf.valid_to,
            "valid_to_local": to_local_time_string(taf.valid_to),
            "evaluation_window_end": taf_window_end.isoformat(),
            "evaluation_window_end_local": taf_window_end.astimezone().isoformat(),
            "evaluated_periods": relevant_taf_periods,
        }
    )
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
