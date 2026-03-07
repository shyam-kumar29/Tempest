"""Runway wind component helpers."""

from __future__ import annotations

import math
from typing import Any

from .models import AirportRecord, MetarRecord


def _normalize_angle(delta: float) -> float:
    # Keep angular difference within +/- 180.
    while delta > 180:
        delta -= 360
    while delta < -180:
        delta += 360
    return delta


def compute_runway_wind_components(
    metar: MetarRecord,
    airport: AirportRecord,
) -> list[dict[str, Any]]:
    """Compute head/tail and crosswind components for each runway with heading data."""

    if metar.wind_direction_degrees is None or metar.wind_speed_kt is None:
        return []

    components: list[dict[str, Any]] = []
    for runway in airport.runways:
        if runway.heading_degrees is None:
            continue

        delta = _normalize_angle(metar.wind_direction_degrees - runway.heading_degrees)
        radians = math.radians(delta)

        headwind = metar.wind_speed_kt * math.cos(radians)
        crosswind = metar.wind_speed_kt * math.sin(radians)

        components.append(
            {
                "runway_id": runway.runway_id,
                "runway_heading_degrees": round(runway.heading_degrees, 1),
                "wind_direction_degrees": metar.wind_direction_degrees,
                "wind_speed_kt": metar.wind_speed_kt,
                "headwind_kt": round(headwind, 1),
                "tailwind_kt": round(max(0.0, -headwind), 1),
                "crosswind_kt": round(abs(crosswind), 1),
                "crosswind_from": "right" if crosswind > 0 else "left",
            }
        )

    return components
