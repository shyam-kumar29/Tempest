"""Thin FastAPI layer over Tempest core backend modules."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tempest.airport import get_airport
from tempest.cache import JsonFileCache
from tempest.evaluation import evaluate_conditions
from tempest.metar import get_latest_metar
from tempest.minimums import MinimumsProfile
from tempest.minimums_store import JsonMinimumsStore, MinimumsStoreError
from tempest.taf import get_latest_taf
from tempest.timeutils import (
    is_airport_payload_current,
    is_metar_payload_current,
    is_taf_payload_current,
)
from tempest.wind import compute_runway_wind_components


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = REPO_ROOT / "frontend"

app = FastAPI(title="Tempest API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _minimums_path() -> Path:
    return Path(os.environ.get("TEMPEST_MINIMUMS_PATH", "data/minimums/profiles.json"))


def _cache_dir() -> Path:
    return Path(os.environ.get("TEMPEST_CACHE_DIR", "data/cache"))


def _store() -> JsonMinimumsStore:
    return JsonMinimumsStore(_minimums_path())


def _validate_icao(icao: str) -> str:
    station = icao.strip().upper()
    if len(station) != 4 or not station.isalpha():
        raise HTTPException(status_code=422, detail="ICAO must be a 4-letter airport id")
    return station


def _optional_float(payload: dict[str, Any], key: str, default: float | None = None) -> float | None:
    value = payload.get(key, default)
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be a number") from exc
    if parsed < 0:
        raise HTTPException(status_code=422, detail=f"{key} cannot be negative")
    return parsed


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = _optional_float(payload, key)
    if value is None:
        return None
    return int(value)


def _profile_from_payload(profile_id: str, payload: dict[str, Any]) -> MinimumsProfile:
    body = dict(payload)
    body["profile_id"] = profile_id.strip()
    if not body.get("display_name"):
        raise HTTPException(status_code=422, detail="display_name is required")
    try:
        return MinimumsProfile.from_dict(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _prefer_metar_cache(icao: str, *, prefer_cache: bool, cache: JsonFileCache, now: datetime) -> bool:
    if prefer_cache:
        return True
    wrapped = cache.get_stale(f"metar_{icao}")
    return (
        isinstance(wrapped, dict)
        and isinstance(wrapped.get("payload"), dict)
        and is_metar_payload_current(wrapped["payload"], now=now)
    )


def _prefer_taf_cache(icao: str, *, prefer_cache: bool, cache: JsonFileCache, now: datetime) -> bool:
    if prefer_cache:
        return True
    wrapped = cache.get_stale(f"taf_{icao}")
    return (
        isinstance(wrapped, dict)
        and isinstance(wrapped.get("payload"), dict)
        and is_taf_payload_current(wrapped["payload"], now=now)
    )


def _prefer_airport_cache(
    icao: str, *, prefer_cache: bool, cache: JsonFileCache, now: datetime
) -> bool:
    if prefer_cache:
        return True
    wrapped = cache.get_stale(f"airport_{icao}")
    return is_airport_payload_current(wrapped, now=now)


def _weather_bundle(
    icao: str,
    *,
    include_taf: bool,
    include_airport: bool,
    prefer_cache: bool,
) -> dict[str, Any]:
    station = _validate_icao(icao)
    cache = JsonFileCache(_cache_dir(), ttl_seconds=300)
    now = datetime.now(UTC)

    try:
        metar, metar_source = get_latest_metar(
            station,
            cache_dir=_cache_dir(),
            prefer_cache=_prefer_metar_cache(station, prefer_cache=prefer_cache, cache=cache, now=now),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"METAR fetch failed: {exc}") from exc

    taf = None
    taf_source = None
    taf_error = None
    if include_taf:
        try:
            taf, taf_source = get_latest_taf(
                station,
                cache_dir=_cache_dir(),
                prefer_cache=_prefer_taf_cache(station, prefer_cache=prefer_cache, cache=cache, now=now),
            )
        except Exception as exc:
            taf_error = f"TAF fetch failed: {exc}"

    airport = None
    airport_source = None
    airport_error = None
    if include_airport:
        try:
            airport, airport_source = get_airport(
                station,
                cache_dir=_cache_dir(),
                prefer_cache=_prefer_airport_cache(
                    station, prefer_cache=prefer_cache, cache=cache, now=now
                ),
            )
        except Exception as exc:
            airport_error = f"Airport fetch failed: {exc}"

    runway_wind_components = (
        compute_runway_wind_components(metar, airport) if airport is not None else []
    )

    return {
        "metar": metar,
        "metar_source": metar_source,
        "taf": taf,
        "taf_source": taf_source,
        "taf_error": taf_error,
        "airport": airport,
        "airport_source": airport_source,
        "airport_error": airport_error,
        "runway_wind_components": runway_wind_components,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/weather/{icao}")
def weather(
    icao: str,
    include_taf: bool = True,
    include_airport: bool = True,
    prefer_cache: bool = False,
) -> dict[str, Any]:
    bundle = _weather_bundle(
        icao,
        include_taf=include_taf,
        include_airport=include_airport,
        prefer_cache=prefer_cache,
    )
    return {
        "sources": {
            "metar": bundle["metar_source"],
            "taf": bundle["taf_source"],
            "airport": bundle["airport_source"],
        },
        "errors": {
            "taf": bundle["taf_error"],
            "airport": bundle["airport_error"],
        },
        "weather": {
            "metar": bundle["metar"].to_dict(),
            "taf": None if bundle["taf"] is None else bundle["taf"].to_dict(),
            "airport": None if bundle["airport"] is None else bundle["airport"].to_dict(),
            "runway_wind_components": bundle["runway_wind_components"],
        },
    }


@app.get("/minimums")
def list_minimums() -> dict[str, Any]:
    try:
        return {"profiles": [profile.to_dict() for profile in _store().list_profiles()]}
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/minimums/{profile_id}")
def get_minimums(profile_id: str) -> dict[str, Any]:
    try:
        profile = _store().get_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Minimums profile not found")
    return {"profile": profile.to_dict()}


@app.post("/minimums/{profile_id}")
def upsert_minimums(
    profile_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    profile = _profile_from_payload(profile_id, payload)
    try:
        saved = _store().upsert_profile(profile)
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"profile": saved.to_dict()}


@app.delete("/minimums/{profile_id}")
def delete_minimums(profile_id: str) -> dict[str, Any]:
    try:
        deleted = _store().delete_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Minimums profile not found")
    return {"deleted": True, "profile_id": profile_id}


@app.post("/evaluate")
def evaluate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    station = _validate_icao(str(payload.get("icao", "")))
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise HTTPException(status_code=422, detail="profile_id is required")

    try:
        profile = _store().get_profile(profile_id)
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Minimums profile not found")

    bundle = _weather_bundle(
        station,
        include_taf=bool(payload.get("include_taf", True)),
        include_airport=True,
        prefer_cache=bool(payload.get("prefer_cache", False)),
    )

    taf_lookahead_hours = _optional_float(payload, "taf_lookahead_hours", 3.0) or 3.0
    if taf_lookahead_hours <= 0:
        raise HTTPException(status_code=422, detail="taf_lookahead_hours must be greater than 0")

    result = evaluate_conditions(
        profile=profile,
        metar=bundle["metar"],
        taf=bundle["taf"],
        airport=bundle["airport"],
        runway_wind_components=bundle["runway_wind_components"],
        planned_departure=payload.get("planned_departure"),
        taf_lookahead_hours=taf_lookahead_hours,
        fuel_reserve_min=_optional_int(payload, "fuel_reserve_min"),
    )

    return {
        "decision": result.to_dict(),
        "sources": {
            "metar": bundle["metar_source"],
            "taf": bundle["taf_source"],
            "airport": bundle["airport_source"],
        },
        "errors": {
            "taf": bundle["taf_error"],
            "airport": bundle["airport_error"],
        },
        "weather": {
            "metar": bundle["metar"].to_dict(),
            "taf": None if bundle["taf"] is None else bundle["taf"].to_dict(),
            "airport": None if bundle["airport"] is None else bundle["airport"].to_dict(),
            "runway_wind_components": bundle["runway_wind_components"],
        },
    }


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
