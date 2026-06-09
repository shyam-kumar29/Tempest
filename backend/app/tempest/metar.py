"""METAR orchestration: fetch + cache + normalize."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
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


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _pick(payload: dict[str, Any], *candidates: str) -> Any:
    for key in candidates:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _altimeter_to_inhg(payload: dict[str, Any]) -> float | None:
    explicit_inhg = _as_float(_pick(payload, "altim_in_hg"))
    if explicit_inhg is not None:
        return explicit_inhg

    altim = _as_float(_pick(payload, "altim"))
    if altim is None:
        return None

    # AviationWeather METAR JSON provides altim in hPa (e.g. 1020.7),
    # but some payload variants may already provide inHg values (e.g. 29.92).
    if altim > 80:
        return round(altim / 33.8638866667, 2)
    return altim


def _visibility_from_raw(raw_text: str) -> float | None:
    tokens = raw_text.upper().split()
    for index, token in enumerate(tokens):
        if token.endswith("SM"):
            value = token[:-2]
            if not value:
                continue
            if value.startswith("P"):
                value = value[1:]
            if value.startswith("M"):
                value = value[1:]

            if "/" in value:
                whole = 0.0
                fraction = value
                if index > 0 and re.fullmatch(r"\d+", tokens[index - 1]):
                    whole = float(tokens[index - 1])
                numerator, denominator = fraction.split("/", 1)
                try:
                    return whole + (float(numerator) / float(denominator))
                except (TypeError, ValueError, ZeroDivisionError):
                    continue

            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _observed_at_from_raw(raw_text: str, *, now: datetime | None = None) -> str | None:
    match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_text.upper())
    if not match:
        return None

    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = int(match.group(1))
    hour = int(match.group(2))
    minute = int(match.group(3))

    year = now.year
    month = now.month
    if day > now.day + 15:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    elif day < now.day - 15:
        month += 1
        if month == 13:
            month = 1
            year += 1

    try:
        return datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat().replace(
            "+00:00", "Z"
        )
    except ValueError:
        return None


def _wind_from_raw(raw_text: str) -> tuple[int | None, int | None, int | None]:
    match = re.search(r"\b(?:(\d{3})|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", raw_text.upper())
    if not match:
        return (None, None, None)
    return (
        _as_int(match.group(1)),
        _as_int(match.group(2)),
        _as_int(match.group(3)),
    )


def _temperature_dewpoint_from_raw(raw_text: str) -> tuple[float | None, float | None]:
    match = re.search(r"\b(M?\d{2})/(M?\d{2})\b", raw_text.upper())
    if not match:
        return (None, None)

    def parse_temp(value: str) -> float:
        return -float(value[1:]) if value.startswith("M") else float(value)

    return (parse_temp(match.group(1)), parse_temp(match.group(2)))


def _altimeter_from_raw(raw_text: str) -> float | None:
    match = re.search(r"\bA(\d{4})\b", raw_text.upper())
    if not match:
        return None
    return round(float(match.group(1)) / 100.0, 2)


def _wx_string_from_raw(raw_text: str) -> str | None:
    weather_tokens: list[str] = []
    for token in raw_text.upper().split():
        if re.fullmatch(
            r"[-+]?((VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?"
            r"(DZ|RA|SN|SG|IC|PL|GR|GS|UP)|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+",
            token,
        ):
            weather_tokens.append(token)
    return " ".join(weather_tokens) or None


def _sky_cover_from_raw(raw_text: str) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for token in raw_text.upper().split():
        if token in {"CLR", "SKC", "NSC", "NCD"}:
            layers.append({"cover": token, "base": None})
            continue

        match = re.fullmatch(r"(FEW|SCT|BKN|OVC|VV)(\d{3})(CB|TCU)?", token)
        if match:
            layers.append(
                {
                    "cover": match.group(1),
                    "base": int(match.group(2)) * 100,
                    **({"cloud_type": match.group(3)} if match.group(3) else {}),
                }
            )

    return layers


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
    if not sky_cover:
        sky_cover = _sky_cover_from_raw(raw_text)

    visibility_sm = _as_float(_pick(payload, "visib", "visibility_statute_mi"))
    if visibility_sm is None:
        visibility_sm = _visibility_from_raw(raw_text)
    raw_wdir, raw_wspd, raw_wgst = _wind_from_raw(raw_text)
    raw_temp, raw_dewp = _temperature_dewpoint_from_raw(raw_text)
    payload_wdir = _as_int(_pick(payload, "wdir", "wind_dir_degrees"))
    payload_wspd = _as_int(_pick(payload, "wspd", "wind_speed_kt"))
    payload_wgst = _as_int(_pick(payload, "wgst", "wind_gust_kt"))
    payload_temp = _as_float(_pick(payload, "temp", "temp_c"))
    payload_dewp = _as_float(_pick(payload, "dewp", "dewpoint_c"))

    return MetarRecord(
        icao_id=icao_id,
        raw_text=raw_text,
        observed_at=_pick(payload, "obsTime", "observation_time", "reportTime")
        or _observed_at_from_raw(raw_text),
        station_name=_pick(payload, "name", "station_name"),
        latitude=_as_float(_pick(payload, "lat", "latitude")),
        longitude=_as_float(_pick(payload, "lon", "longitude")),
        elevation_m=_as_float(_pick(payload, "elev", "elevation_m")),
        flight_category=_pick(payload, "fltCat", "flight_category"),
        wind_direction_degrees=_first_not_none(payload_wdir, raw_wdir),
        wind_speed_kt=_first_not_none(payload_wspd, raw_wspd),
        wind_gust_kt=_first_not_none(payload_wgst, raw_wgst),
        visibility_sm=visibility_sm,
        temperature_c=_first_not_none(payload_temp, raw_temp),
        dewpoint_c=_first_not_none(payload_dewp, raw_dewp),
        altimeter_in_hg=_first_not_none(_altimeter_to_inhg(payload), _altimeter_from_raw(raw_text)),
        sea_level_pressure_mb=_as_float(_pick(payload, "slp", "sea_level_pressure_mb")),
        sky_cover=sky_cover,
        wx_string=_pick(payload, "wxString", "wx_string") or _wx_string_from_raw(raw_text),
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
