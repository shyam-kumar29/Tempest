"""TAF orchestration: fetch + cache + normalize."""

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
from .models import TafRecord


class TafNotFoundError(RuntimeError):
    """Raised when no TAF record is found for a station."""


def _pick(payload: dict[str, Any], *candidates: str) -> Any:
    for key in candidates:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def normalize_taf(payload: dict[str, Any]) -> TafRecord:
    icao_id = str(_pick(payload, "icaoId", "station_id", "station")).upper()
    raw_text = str(_pick(payload, "rawTAF", "raw_text", "raw") or "")

    if not icao_id:
        raise ValueError("TAF payload missing ICAO station id")
    if not raw_text:
        raise ValueError("TAF payload missing raw TAF text")

    forecast = payload.get("fcsts") or payload.get("forecast") or []
    if not isinstance(forecast, list):
        forecast = []

    return TafRecord(
        icao_id=icao_id,
        raw_text=raw_text,
        issued_at=_pick(payload, "issueTime", "issue_time"),
        valid_from=_pick(payload, "validTimeFrom", "valid_from"),
        valid_to=_pick(payload, "validTimeTo", "valid_to"),
        station_name=_pick(payload, "name", "station_name"),
        forecast=forecast,
        source_payload=payload,
    )


def get_latest_taf(
    icao_id: str,
    *,
    cache_dir: Path,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    min_fetch_interval_seconds: int = DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    prefer_cache: bool = True,
) -> tuple[TafRecord, str]:
    """Get latest TAF, returning (normalized record, source) where source is cache or api."""

    key = f"taf_{icao_id.strip().upper()}"
    cache = JsonFileCache(root=cache_dir, ttl_seconds=cache_ttl_seconds)

    if prefer_cache:
        cached = cache.get(key)
        if cached and isinstance(cached.get("payload"), dict):
            return normalize_taf(cached["payload"]), "cache"

        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            fetched_at = stale.get("fetched_at_epoch")
            if isinstance(fetched_at, (int, float)):
                if time.time() - float(fetched_at) < min_fetch_interval_seconds:
                    return normalize_taf(stale["payload"]), "throttled-cache"

    client = AviationWeatherClient(user_agent=user_agent)

    try:
        items = client.fetch_latest_taf_json(icao_id)
    except AviationWeatherError:
        stale = cache.get_stale(key)
        if stale and isinstance(stale.get("payload"), dict):
            return normalize_taf(stale["payload"]), "stale-cache"
        raise

    if not items:
        raise TafNotFoundError(f"No TAF found for ICAO {icao_id.strip().upper()}")

    latest = items[0]
    cache.set(key, latest)
    return normalize_taf(latest), "api"
