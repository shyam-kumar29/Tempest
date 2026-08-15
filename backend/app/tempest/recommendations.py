"""Destination recommendation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .route import AirportIndexEntry, RoutePoint, haversine_nm


DECISION_RANK = {"go": 0, "caution": 1, "no-go": 2}


@dataclass(slots=True)
class DestinationCandidate:
    airport: AirportIndexEntry
    distance_nm: float
    estimated_arrival: datetime


def _station_type_rank(airport_type: str) -> int:
    normalized = {part.strip().upper() for part in airport_type.split("|") if part.strip()}
    if {"METAR", "TAF"} <= normalized:
        return 0
    if "METAR" in normalized:
        return 1
    if "TAF" in normalized:
        return 2
    return 3


def destination_candidates(
    *,
    home: RoutePoint,
    airport_index: list[AirportIndexEntry],
    min_distance_nm: float,
    radius_nm: float,
    groundspeed_kt: float,
    planned_departure: datetime,
    max_candidates: int,
    favorite_airports: set[str] | None = None,
) -> list[DestinationCandidate]:
    """Find nearby weather-reporting destination candidates from the station index."""

    planned_departure = planned_departure.astimezone(UTC)
    favorite_airports = favorite_airports or set()
    candidates: list[DestinationCandidate] = []
    for airport in airport_index:
        if airport.icao_id == home.icao_id:
            continue
        if _station_type_rank(airport.airport_type) >= 3:
            continue
        distance_nm = haversine_nm(home.latitude, home.longitude, airport.latitude, airport.longitude)
        if distance_nm < min_distance_nm or distance_nm > radius_nm:
            continue
        candidates.append(
            DestinationCandidate(
                airport=airport,
                distance_nm=round(distance_nm, 1),
                estimated_arrival=planned_departure + timedelta(hours=distance_nm / groundspeed_kt),
            )
        )

    candidates.sort(
        key=lambda item: (
            item.airport.icao_id not in favorite_airports,
            _station_type_rank(item.airport.airport_type),
            item.distance_nm,
        )
    )
    if len(candidates) <= max_candidates:
        return candidates

    span = max(radius_nm - min_distance_nm, 0.0)
    if span <= 0:
        return candidates[:max_candidates]

    bucket_edges = [
        min_distance_nm + (span / 3.0),
        min_distance_nm + (span * 2.0 / 3.0),
    ]
    buckets: list[list[DestinationCandidate]] = [[], [], []]
    for candidate in candidates:
        if candidate.distance_nm <= bucket_edges[0]:
            buckets[0].append(candidate)
        elif candidate.distance_nm <= bucket_edges[1]:
            buckets[1].append(candidate)
        else:
            buckets[2].append(candidate)

    selected: list[DestinationCandidate] = []
    while len(selected) < max_candidates and any(buckets):
        for bucket in buckets:
            if bucket and len(selected) < max_candidates:
                selected.append(bucket.pop(0))
    return selected


def _margin_score(decision: dict[str, Any]) -> float:
    score = 0.0
    metar = decision.get("metar_summary") or {}
    taf = decision.get("taf_summary") or {}
    periods = taf.get("evaluated_periods") or []
    period = periods[0] if periods else {}

    visibility = period.get("visibility_sm") if period else metar.get("visibility_sm")
    ceiling = period.get("ceiling_ft_agl") if period else metar.get("ceiling_ft_agl")
    wind_speed = period.get("wind_speed_kt") if period else metar.get("wind_speed_kt")

    if isinstance(visibility, (int, float)):
        score += min(float(visibility), 10.0) * 2.0
    if isinstance(ceiling, (int, float)):
        score += min(float(ceiling), 10000.0) / 500.0
    if isinstance(wind_speed, (int, float)):
        score += max(0.0, 20.0 - float(wind_speed)) / 2.0
    if decision.get("best_runway"):
        score += 5.0
    if periods:
        score += 3.0
    return round(score, 2)


def recommendation_score(
    station_payload: dict[str, Any],
    *,
    favorite_weight: float = 0.0,
) -> dict[str, Any]:
    decision = station_payload.get("decision") or {}
    decision_name = str(decision.get("decision") or "caution")
    severity = DECISION_RANK.get(decision_name, 1)
    distance = float(station_payload.get("distance_from_home_nm") or 0.0)
    margin = _margin_score(decision)
    data_quality = 0
    sources = station_payload.get("sources") or {}
    if sources.get("metar"):
        data_quality += 2
    if sources.get("taf"):
        data_quality += 2
    if sources.get("airport"):
        data_quality += 1

    return {
        "severity": severity,
        "margin": margin,
        "data_quality": data_quality,
        "favorite_weight": favorite_weight,
        "distance_nm": distance,
        "sort_key": [severity, -margin, -favorite_weight, -data_quality, distance],
    }


def apply_ai_downgrade(
    *,
    base_decision: str,
    ai_decision: str | None,
) -> str:
    base_rank = DECISION_RANK.get(base_decision, 1)
    ai_rank = DECISION_RANK.get(str(ai_decision or "").lower())
    if ai_rank is None or ai_rank < base_rank:
        return base_decision
    return str(ai_decision).lower()
