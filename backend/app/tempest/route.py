"""Route parsing and enroute airport sampling utilities."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


EARTH_RADIUS_NM = 3440.065


@dataclass(slots=True)
class AirportIndexEntry:
    icao_id: str
    name: str
    latitude: float
    longitude: float
    airport_type: str


@dataclass(slots=True)
class RoutePoint:
    icao_id: str
    name: str | None
    latitude: float
    longitude: float


@dataclass(slots=True)
class EnrouteSample:
    icao_id: str
    name: str
    latitude: float
    longitude: float
    distance_from_departure_nm: float
    planned_time: datetime
    nearest_sample_distance_nm: float


def parse_route(text: str) -> list[str]:
    """Parse an ICAO route string into normalized station ids."""

    tokens = [token.strip().upper() for token in re.split(r"[\s,;\->]+", text) if token.strip()]
    if not tokens:
        raise ValueError("Route must include at least two ICAO airport ids")
    invalid = [token for token in tokens if len(token) != 4 or not token.isalpha()]
    if invalid:
        raise ValueError(f"Invalid ICAO airport id in route: {invalid[0]}")
    return tokens


def load_airport_index(path: Path) -> list[AirportIndexEntry]:
    entries: list[AirportIndexEntry] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            icao_id = str(row.get("icao_id") or "").strip().upper()
            if len(icao_id) != 4 or not icao_id.isalpha():
                continue
            try:
                latitude = float(str(row.get("latitude") or "").strip())
                longitude = float(str(row.get("longitude") or "").strip())
            except ValueError:
                continue
            entries.append(
                AirportIndexEntry(
                    icao_id=icao_id,
                    name=str(row.get("name") or icao_id).strip(),
                    latitude=latitude,
                    longitude=longitude,
                    airport_type=str(row.get("type") or "").strip(),
                )
            )
    return entries


def haversine_nm(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_NM * c


def intermediate_point(
    start: RoutePoint,
    end: RoutePoint,
    fraction: float,
) -> tuple[float, float]:
    """Return a point at fraction along the great-circle path from start to end."""

    fraction = min(1.0, max(0.0, fraction))
    lat1 = math.radians(start.latitude)
    lon1 = math.radians(start.longitude)
    lat2 = math.radians(end.latitude)
    lon2 = math.radians(end.longitude)

    angular_distance = haversine_nm(
        start.latitude,
        start.longitude,
        end.latitude,
        end.longitude,
    ) / EARTH_RADIUS_NM
    if angular_distance == 0.0:
        return (start.latitude, start.longitude)

    a = math.sin((1.0 - fraction) * angular_distance) / math.sin(angular_distance)
    b = math.sin(fraction * angular_distance) / math.sin(angular_distance)

    x = (a * math.cos(lat1) * math.cos(lon1)) + (b * math.cos(lat2) * math.cos(lon2))
    y = (a * math.cos(lat1) * math.sin(lon1)) + (b * math.cos(lat2) * math.sin(lon2))
    z = (a * math.sin(lat1)) + (b * math.sin(lat2))

    lat = math.atan2(z, math.sqrt((x * x) + (y * y)))
    lon = math.atan2(y, x)
    return (math.degrees(lat), math.degrees(lon))


def nearest_airport(
    *,
    latitude: float,
    longitude: float,
    airport_index: list[AirportIndexEntry],
    radius_nm: float,
    exclude_icao_ids: set[str],
) -> tuple[AirportIndexEntry, float] | None:
    nearest: tuple[AirportIndexEntry, float] | None = None
    for airport in airport_index:
        if airport.icao_id in exclude_icao_ids:
            continue
        distance_nm = haversine_nm(latitude, longitude, airport.latitude, airport.longitude)
        if distance_nm > radius_nm:
            continue
        if nearest is None or distance_nm < nearest[1]:
            nearest = (airport, distance_nm)
    return nearest


def route_leg_summaries(
    *,
    route_points: list[RoutePoint],
    planned_departure: datetime,
    groundspeed_kt: float,
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    elapsed_hours = 0.0
    planned_departure = planned_departure.astimezone(UTC)
    for start, end in zip(route_points, route_points[1:], strict=False):
        leg_departure = planned_departure + timedelta(hours=elapsed_hours)
        distance_nm = haversine_nm(start.latitude, start.longitude, end.latitude, end.longitude)
        elapsed_hours += distance_nm / groundspeed_kt
        leg_arrival = planned_departure + timedelta(hours=elapsed_hours)
        summaries.append(
            {
                "from": start.icao_id,
                "to": end.icao_id,
                "distance_nm": round(distance_nm, 1),
                "estimated_departure": leg_departure.isoformat(),
                "estimated_arrival": leg_arrival.isoformat(),
            }
        )
    return summaries


def estimate_route_point_times(
    *,
    route_points: list[RoutePoint],
    planned_departure: datetime,
    groundspeed_kt: float,
) -> dict[str, tuple[datetime, float]]:
    planned_departure = planned_departure.astimezone(UTC)
    result: dict[str, tuple[datetime, float]] = {
        route_points[0].icao_id: (planned_departure, 0.0)
    }
    elapsed_hours = 0.0
    distance_from_departure_nm = 0.0
    for start, end in zip(route_points, route_points[1:], strict=False):
        leg_distance_nm = haversine_nm(start.latitude, start.longitude, end.latitude, end.longitude)
        distance_from_departure_nm += leg_distance_nm
        elapsed_hours += leg_distance_nm / groundspeed_kt
        result[end.icao_id] = (
            planned_departure + timedelta(hours=elapsed_hours),
            distance_from_departure_nm,
        )
    return result


def sample_enroute_airports(
    *,
    route_points: list[RoutePoint],
    airport_index: list[AirportIndexEntry],
    planned_departure: datetime,
    corridor_radius_nm: float,
    sample_spacing_nm: float,
    groundspeed_kt: float,
) -> tuple[list[EnrouteSample], list[str]]:
    planned_departure = planned_departure.astimezone(UTC)
    exclude = {point.icao_id for point in route_points}
    selected: dict[str, EnrouteSample] = {}
    coverage_notes: list[str] = []
    cumulative_distance_nm = 0.0

    for start, end in zip(route_points, route_points[1:], strict=False):
        leg_distance_nm = haversine_nm(start.latitude, start.longitude, end.latitude, end.longitude)
        sample_distance_nm = sample_spacing_nm

        while sample_distance_nm < leg_distance_nm:
            fraction = sample_distance_nm / leg_distance_nm
            latitude, longitude = intermediate_point(start, end, fraction)
            distance_from_departure_nm = cumulative_distance_nm + sample_distance_nm
            planned_time = planned_departure + timedelta(
                hours=distance_from_departure_nm / groundspeed_kt
            )
            nearest = nearest_airport(
                latitude=latitude,
                longitude=longitude,
                airport_index=airport_index,
                radius_nm=corridor_radius_nm,
                exclude_icao_ids=exclude,
            )
            if nearest is None:
                coverage_notes.append(
                    f"No reporting airport found within {corridor_radius_nm:g} NM near "
                    f"{round(distance_from_departure_nm, 1)} NM from departure."
                )
            else:
                airport, sample_offset_nm = nearest
                if airport.icao_id not in selected:
                    selected[airport.icao_id] = EnrouteSample(
                        icao_id=airport.icao_id,
                        name=airport.name,
                        latitude=airport.latitude,
                        longitude=airport.longitude,
                        distance_from_departure_nm=round(distance_from_departure_nm, 1),
                        planned_time=planned_time,
                        nearest_sample_distance_nm=round(sample_offset_nm, 1),
                    )
                exclude.add(airport.icao_id)

            sample_distance_nm += sample_spacing_nm

        cumulative_distance_nm += leg_distance_nm

    samples = sorted(selected.values(), key=lambda item: item.distance_from_departure_nm)
    return samples, coverage_notes
