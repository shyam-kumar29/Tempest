"""Airport orchestration: fetch + cache + normalize."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .aviationweather_client import AviationWeatherClient, AviationWeatherError
from .cache import JsonFileCache
from .config import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
    DEFAULT_USER_AGENT,
)
from .models import AirportRecord, RunwayRecord


class AirportNotFoundError(RuntimeError):
    """Raised when no airport record is found for a station."""


def _pick(payload: dict[str, Any], *candidates: str) -> Any:
    for key in candidates:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _reciprocal_heading(heading: float) -> float:
    return (heading + 180.0) % 360.0


def _parse_dimension(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return (None, None)
    text = str(value).strip().lower()
    match = re.search(r"(\d+)\s*[x×]\s*(\d+)", text)
    if not match:
        return (None, None)
    return (int(match.group(1)), int(match.group(2)))


def _normalize_runway(item: dict[str, Any]) -> list[RunwayRecord]:
    runway_id = str(_pick(item, "id", "runwayId", "name", "ident", "rwy") or "").strip()
    if not runway_id:
        return []

    heading = _as_float(
        _pick(item, "heading", "bearing", "magHdg", "heading_deg", "alignment")
    )
    length_ft = _as_int(_pick(item, "length_ft", "length", "len"))
    width_ft = _as_int(_pick(item, "width_ft", "width", "wid"))
    if length_ft is None or width_ft is None:
        parsed_length, parsed_width = _parse_dimension(_pick(item, "dimension", "dimensions"))
        if length_ft is None:
            length_ft = parsed_length
        if width_ft is None:
            width_ft = parsed_width
    surface = _pick(item, "surface", "surf")
    surface_str = str(surface).lower() if surface is not None else None

    if "/" in runway_id:
        parts = [part.strip() for part in runway_id.split("/") if part.strip()]
        if len(parts) >= 2 and heading is not None:
            primary = RunwayRecord(
                runway_id=parts[0],
                heading_degrees=heading,
                length_ft=length_ft,
                width_ft=width_ft,
                surface=surface_str,
            )
            reciprocal = RunwayRecord(
                runway_id=parts[1],
                heading_degrees=_reciprocal_heading(heading),
                length_ft=length_ft,
                width_ft=width_ft,
                surface=surface_str,
            )
            return [primary, reciprocal]

    return [
        RunwayRecord(
            runway_id=runway_id,
            heading_degrees=heading,
            length_ft=length_ft,
            width_ft=width_ft,
            surface=surface_str,
        )
    ]


def normalize_airport(payload: dict[str, Any]) -> AirportRecord:
    icao_id = str(_pick(payload, "icaoId", "icao", "ident") or "").upper()
    if not icao_id:
        raise ValueError("Airport payload missing ICAO id")

    raw_runways = _pick(payload, "runways", "rwys", "runway")
    runways: list[RunwayRecord] = []
    if isinstance(raw_runways, list):
        for runway in raw_runways:
            if isinstance(runway, dict):
                runways.extend(_normalize_runway(runway))

    return AirportRecord(
        icao_id=icao_id,
        iata_id=_pick(payload, "iataId", "iata"),
        name=_pick(payload, "name", "airportName"),
        latitude=_as_float(_pick(payload, "lat", "latitude")),
        longitude=_as_float(_pick(payload, "lon", "longitude")),
        elevation_ft=_as_int(_pick(payload, "elev", "elevation_ft")),
        runways=runways,
        source_payload=payload,
    )


def get_airport(
    icao_id: str,
    *,
    cache_dir: Path,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    min_fetch_interval_seconds: int = DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    prefer_cache: bool = True,
) -> tuple[AirportRecord, str]:
    """Get airport info, returning (normalized record, source) where source is cache or api."""

    key = f"airport_{icao_id.strip().upper()}"
    cache = JsonFileCache(root=cache_dir, ttl_seconds=cache_ttl_seconds)

    if prefer_cache:
        cached = cache.get(key)
        if cached and isinstance(cached.get("payload"), dict):
            return normalize_airport(cached["payload"]), "cache"

        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            fetched_at = stale.get("fetched_at_epoch")
            if isinstance(fetched_at, (int, float)):
                if time.time() - float(fetched_at) < min_fetch_interval_seconds:
                    return normalize_airport(stale["payload"]), "throttled-cache"

    client = AviationWeatherClient(user_agent=user_agent)

    try:
        items = client.fetch_airport_json(icao_id)
    except AviationWeatherError:
        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            return normalize_airport(stale["payload"]), "stale-cache"
        raise

    if not items:
        raise AirportNotFoundError(f"No airport data found for ICAO {icao_id.strip().upper()}")

    latest = items[0]
    cache.set(key, latest)
    return normalize_airport(latest), "api"
