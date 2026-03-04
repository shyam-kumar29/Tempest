"""METAR orchestration: fetch + cache + normalize."""

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
from .models import MetarRecord


class MetarNotFoundError(RuntimeError):
    """Raised when no METAR record is found for a station."""


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


def _pick(payload: dict[str, Any], *candidates: str) -> Any:
    for key in candidates:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def normalize_metar(payload: dict[str, Any]) -> MetarRecord:
    icao_id = str(_pick(payload, "icaoId", "station_id", "station")).upper()
    raw_text = str(_pick(payload, "rawOb", "raw_text", "raw") or "")

    if not icao_id:
        raise ValueError("METAR payload missing ICAO station id")
    if not raw_text:
        raise ValueError("METAR payload missing raw METAR text")

    sky_cover = payload.get("clouds") or payload.get("sky_condition") or []
    if not isinstance(sky_cover, list):
        sky_cover = []

    return MetarRecord(
        icao_id=icao_id,
        raw_text=raw_text,
        observed_at=_pick(payload, "obsTime", "observation_time", "reportTime"),
        station_name=_pick(payload, "name", "station_name"),
        latitude=_as_float(_pick(payload, "lat", "latitude")),
        longitude=_as_float(_pick(payload, "lon", "longitude")),
        elevation_m=_as_float(_pick(payload, "elev", "elevation_m")),
        flight_category=_pick(payload, "fltCat", "flight_category"),
        wind_direction_degrees=_as_int(_pick(payload, "wdir", "wind_dir_degrees")),
        wind_speed_kt=_as_int(_pick(payload, "wspd", "wind_speed_kt")),
        wind_gust_kt=_as_int(_pick(payload, "wgst", "wind_gust_kt")),
        visibility_sm=_as_float(_pick(payload, "visib", "visibility_statute_mi")),
        temperature_c=_as_float(_pick(payload, "temp", "temp_c")),
        dewpoint_c=_as_float(_pick(payload, "dewp", "dewpoint_c")),
        altimeter_in_hg=_as_float(_pick(payload, "altim", "altim_in_hg")),
        sea_level_pressure_mb=_as_float(_pick(payload, "slp", "sea_level_pressure_mb")),
        sky_cover=sky_cover,
        wx_string=_pick(payload, "wxString", "wx_string"),
        source_payload=payload,
    )


def get_latest_metar(
    icao_id: str,
    *,
    cache_dir: Path,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    min_fetch_interval_seconds: int = DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    prefer_cache: bool = True,
) -> tuple[MetarRecord, str]:
    """Get latest METAR, returning (normalized record, source) where source is cache or api."""

    key = f"metar_{icao_id.strip().upper()}"
    cache = JsonFileCache(root=cache_dir, ttl_seconds=cache_ttl_seconds)

    if prefer_cache:
        cached = cache.get(key)
        if cached and isinstance(cached.get("payload"), dict):
            payload = cached["payload"]
            return normalize_metar(payload), "cache"

        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            fetched_at = stale.get("fetched_at_epoch")
            if isinstance(fetched_at, (int, float)):
                if time.time() - float(fetched_at) < min_fetch_interval_seconds:
                    return normalize_metar(stale["payload"]), "throttled-cache"

    client = AviationWeatherClient(user_agent=user_agent)

    try:
        items = client.fetch_latest_metar_json(icao_id)
    except AviationWeatherError:
        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            return normalize_metar(stale["payload"]), "stale-cache"
        raise

    if not items:
        raise MetarNotFoundError(f"No METAR found for ICAO {icao_id.strip().upper()}")

    latest = items[0]
    cache.set(key, latest)
    return normalize_metar(latest), "api"
