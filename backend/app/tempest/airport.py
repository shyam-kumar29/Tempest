"""Airport orchestration: fetch + cache + normalize."""

from __future__ import annotations

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


def _normalize_runway(item: dict[str, Any]) -> RunwayRecord | None:
    runway_id = str(_pick(item, "id", "runwayId", "name", "ident", "rwy") or "").strip()
    if not runway_id:
        return None

    heading = _as_float(_pick(item, "heading", "bearing", "magHdg", "heading_deg"))
    length_ft = _as_int(_pick(item, "length_ft", "length", "len"))
    width_ft = _as_int(_pick(item, "width_ft", "width", "wid"))
    surface = _pick(item, "surface", "surf")

    return RunwayRecord(
        runway_id=runway_id,
        heading_degrees=heading,
        length_ft=length_ft,
        width_ft=width_ft,
        surface=str(surface).lower() if surface is not None else None,
    )


def normalize_airport(payload: dict[str, Any]) -> AirportRecord:
    icao_id = str(_pick(payload, "icaoId", "icao", "ident") or "").upper()
    if not icao_id:
        raise ValueError("Airport payload missing ICAO id")

    raw_runways = _pick(payload, "runways", "rwys", "runway")
    runways: list[RunwayRecord] = []
    if isinstance(raw_runways, list):
        for runway in raw_runways:
            if isinstance(runway, dict):
                normalized = _normalize_runway(runway)
                if normalized is not None:
                    runways.append(normalized)

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
