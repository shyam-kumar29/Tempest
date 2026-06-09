"""Thin FastAPI layer over Tempest core backend modules."""

from __future__ import annotations

import os
from dataclasses import replace
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
from tempest.route import (
    AirportIndexEntry,
    RoutePoint,
    estimate_route_point_times,
    load_route_station_index,
    parse_route,
    route_leg_summaries,
    sample_enroute_airports,
)
from tempest.taf import get_latest_taf
from tempest.timeutils import parse_aviation_time
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


def _airport_index_path() -> Path:
    return Path(os.environ.get("TEMPEST_AIRPORT_INDEX_PATH", REPO_ROOT / "data" / "airport_index.csv"))


def _station_index_path() -> Path:
    return Path(os.environ.get("TEMPEST_STATION_INDEX_PATH", REPO_ROOT / "data" / "station_index.csv"))


def _fetch_station_cache() -> bool:
    return os.environ.get("TEMPEST_FETCH_STATION_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


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


def _positive_float(payload: dict[str, Any], key: str, default: float) -> float:
    value = _optional_float(payload, key, default)
    if value is None or value <= 0:
        raise HTTPException(status_code=422, detail=f"{key} must be greater than 0")
    return value


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
    if metar_source != "api" and not is_metar_payload_current(metar.source_payload, now=now):
        raise HTTPException(
            status_code=502,
            detail=(
                f"METAR fetch returned stale {metar_source} data for {station}; "
                "live weather is unavailable."
            ),
        )

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
            if taf_source != "api" and not is_taf_payload_current(taf.source_payload, now=now):
                taf_error = (
                    f"TAF fetch returned stale {taf_source} data for {station}; "
                    "live forecast is unavailable."
                )
                taf = None
                taf_source = None
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


def _load_profile(profile_id: str) -> MinimumsProfile:
    if not profile_id:
        raise HTTPException(status_code=422, detail="profile_id is required")

    try:
        profile = _store().get_profile(profile_id)
    except MinimumsStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Minimums profile not found")
    return profile


def _evaluation_response(
    *,
    result: Any,
    bundle: dict[str, Any],
) -> dict[str, Any]:
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


def _route_point_from_index(
    station: str,
    airport_index: list[AirportIndexEntry],
) -> RoutePoint | None:
    for airport in airport_index:
        if airport.icao_id == station:
            return RoutePoint(
                icao_id=station,
                name=airport.name,
                latitude=airport.latitude,
                longitude=airport.longitude,
            )
    return None


def _route_point_for_icao(
    icao: str,
    *,
    prefer_cache: bool,
    airport_index: list[AirportIndexEntry],
    coverage_notes: list[str],
) -> RoutePoint:
    station = _validate_icao(icao)
    indexed = _route_point_from_index(station, airport_index)
    if indexed is not None:
        return indexed

    cache = JsonFileCache(_cache_dir(), ttl_seconds=300)
    now = datetime.now(UTC)
    try:
        airport, _source = get_airport(
            station,
            cache_dir=_cache_dir(),
            prefer_cache=_prefer_airport_cache(
                station,
                prefer_cache=prefer_cache,
                cache=cache,
                now=now,
            ),
        )
    except Exception as exc:
        indexed = _route_point_from_index(station, airport_index)
        if indexed is not None:
            coverage_notes.append(
                f"Used bundled airport index coordinates for {station}; airport API coordinate fetch failed: {exc}"
            )
            return indexed
        raise HTTPException(
            status_code=502,
            detail=f"Airport coordinate fetch failed for {station}: {exc}",
        ) from exc

    if airport.latitude is None or airport.longitude is None:
        raise HTTPException(
            status_code=422,
            detail=f"Airport coordinates are unavailable for {station}",
        )

    return RoutePoint(
        icao_id=station,
        name=airport.name,
        latitude=airport.latitude,
        longitude=airport.longitude,
    )


def _profile_for_route_role(profile: MinimumsProfile, role: str) -> MinimumsProfile:
    if role != "enroute":
        return profile

    return replace(
        profile,
        max_surface_wind_kt=None,
        max_crosswind_kt=None,
        max_gust_kt=None,
        max_tailwind_kt=None,
        allow_night=None,
        min_runway_length_ft=None,
        min_runway_width_ft=None,
        allowed_runway_surfaces=None,
        require_dry_runway=None,
        min_fuel_reserve_min=None,
        min_fuel_reserve_day_min=None,
        min_fuel_reserve_night_min=None,
        max_density_altitude_ft=None,
        require_alternate_for_ifr=None,
    )


def _taf_period_weather_text(period: dict[str, Any]) -> str:
    raw = period.get("raw")
    sources = [period.get("wxString"), period.get("wx_string"), period.get("wx")]
    if isinstance(raw, dict):
        sources.extend([raw.get("wxString"), raw.get("wx_string"), raw.get("wx")])
    return " ".join(str(value) for value in sources if value)


def _weather_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in text.upper().replace(",", " ").split():
        cleaned = token.strip("+-")
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _add_enroute_weather_hazards(result: Any) -> None:
    weather_texts: list[str] = []
    weather_texts.append(str(result.metar_summary.get("wx_string") or ""))
    if result.taf_summary and result.taf_summary.get("evaluated_periods"):
        weather_texts.extend(
            _taf_period_weather_text(period)
            for period in result.taf_summary["evaluated_periods"]
            if isinstance(period, dict)
        )

    tokens = _weather_tokens(" ".join(weather_texts))
    has_thunderstorm = any("TS" in token for token in tokens)
    has_precipitation = any(
        code in token
        for token in tokens
        for code in ("RA", "SN", "DZ", "PL", "GR", "GS", "UP", "IC")
    )

    if has_thunderstorm:
        result.caution_reasons.append(
            "Enroute weather reports thunderstorms near the planned overflight."
        )
    elif has_precipitation:
        result.caution_reasons.append(
            "Enroute weather reports precipitation near the planned overflight."
        )

    result.pass_reasons.append(
        "Enroute station evaluated for route weather only; runway suitability and runway wind limits are not applied."
    )
    if result.decision == "go" and result.caution_reasons:
        result.decision = "caution"


def _evaluate_station_for_route(
    *,
    station: str,
    role: str,
    profile: MinimumsProfile,
    planned_time: datetime,
    distance_from_departure_nm: float,
    include_taf: bool,
    taf_lookahead_hours: float,
    fuel_reserve_min: int | None,
    prefer_cache: bool,
    sample: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    try:
        bundle = _weather_bundle(
            station,
            include_taf=include_taf,
            include_airport=True,
            prefer_cache=prefer_cache,
        )
        station_profile = _profile_for_route_role(profile, role)
        result = evaluate_conditions(
            profile=station_profile,
            metar=bundle["metar"],
            taf=bundle["taf"],
            airport=bundle["airport"],
            runway_wind_components=bundle["runway_wind_components"],
            planned_departure=planned_time,
            taf_lookahead_hours=taf_lookahead_hours,
            fuel_reserve_min=None if role == "enroute" else fuel_reserve_min,
        )
        if role == "enroute":
            _add_enroute_weather_hazards(result)
        response = _evaluation_response(result=result, bundle=bundle)
        response.update(
            {
                "icao_id": station,
                "role": role,
                "planned_time": planned_time.astimezone(UTC).isoformat(),
                "distance_from_departure_nm": round(distance_from_departure_nm, 1),
            }
        )
        if sample is not None:
            response["sample"] = sample
        return response, None
    except HTTPException as exc:
        message = str(exc.detail)
    except Exception as exc:
        message = str(exc)

    decision = "no-go" if role in {"departure", "arrival"} else "caution"
    reason_key = "fail_reasons" if decision == "no-go" else "caution_reasons"
    decision_payload = {
        "profile_id": profile.profile_id,
        "airport_id": station,
        "decision": decision,
        "fail_reasons": [],
        "caution_reasons": [],
        "pass_reasons": [],
        "unknowns": [],
        "metar_summary": {},
        "taf_summary": None,
        "airport_summary": None,
        "best_runway": None,
    }
    decision_payload[reason_key].append(f"{station} weather evaluation failed: {message}")
    station_payload: dict[str, Any] = {
        "icao_id": station,
        "role": role,
        "planned_time": planned_time.astimezone(UTC).isoformat(),
        "distance_from_departure_nm": round(distance_from_departure_nm, 1),
        "decision": decision_payload,
        "sources": {"metar": None, "taf": None, "airport": None},
        "errors": {"weather": message},
        "weather": {"metar": None, "taf": None, "airport": None, "runway_wind_components": []},
    }
    if sample is not None:
        station_payload["sample"] = sample
    return station_payload, f"{station} weather fetch failed: {message}"


def _route_summary_decision(stations: list[dict[str, Any]], coverage_notes: list[str]) -> str:
    decisions = [station["decision"]["decision"] for station in stations]
    if any(decision == "no-go" for decision in decisions):
        return "no-go"
    if coverage_notes or any(decision == "caution" for decision in decisions):
        return "caution"
    return "go"


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
    profile = _load_profile(profile_id)

    bundle = _weather_bundle(
        station,
        include_taf=bool(payload.get("include_taf", True)),
        include_airport=True,
        prefer_cache=bool(payload.get("prefer_cache", False)),
    )

    taf_lookahead_hours = _optional_float(payload, "taf_lookahead_hours", 0.0) or 0.0

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

    return _evaluation_response(result=result, bundle=bundle)


@app.post("/evaluate-route")
def evaluate_route(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    profile = _load_profile(str(payload.get("profile_id", "")).strip())

    try:
        route = parse_route(str(payload.get("route", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(route) < 2:
        raise HTTPException(status_code=422, detail="Route must include at least two ICAO airport ids")

    planned_at = parse_aviation_time(payload.get("planned_departure"))
    if planned_at is None:
        planned_at = datetime.now(UTC)
    planned_at = planned_at.astimezone(UTC)

    corridor_radius_nm = _positive_float(payload, "corridor_radius_nm", 10.0)
    sample_spacing_nm = _positive_float(payload, "sample_spacing_nm", 25.0)
    groundspeed_kt = _positive_float(payload, "groundspeed_kt", 100.0)
    taf_lookahead_hours = _optional_float(payload, "taf_lookahead_hours", 0.0) or 0.0
    include_taf = bool(payload.get("include_taf", True))
    prefer_cache = bool(payload.get("prefer_cache", False))
    fuel_reserve_min = _optional_int(payload, "fuel_reserve_min")

    airport_index, index_notes = load_route_station_index(
        cache_dir=_cache_dir(),
        bundled_station_index_path=_station_index_path(),
        fallback_airport_index_path=_airport_index_path(),
        allow_refresh=_fetch_station_cache(),
    )
    coverage_notes: list[str] = []
    if not airport_index:
        coverage_notes.extend(index_notes)
    route_points = [
        _route_point_for_icao(
            station,
            prefer_cache=prefer_cache,
            airport_index=airport_index,
            coverage_notes=coverage_notes,
        )
        for station in route
    ]
    legs = route_leg_summaries(
        route_points=route_points,
        planned_departure=planned_at,
        groundspeed_kt=groundspeed_kt,
    )
    route_point_times = estimate_route_point_times(
        route_points=route_points,
        planned_departure=planned_at,
        groundspeed_kt=groundspeed_kt,
    )
    samples, sampling_notes = sample_enroute_airports(
        route_points=route_points,
        airport_index=airport_index,
        planned_departure=planned_at,
        corridor_radius_nm=corridor_radius_nm,
        sample_spacing_nm=sample_spacing_nm,
        groundspeed_kt=groundspeed_kt,
    )
    coverage_notes.extend(sampling_notes)

    station_defs: list[dict[str, Any]] = []
    for index, station in enumerate(route):
        planned_time, distance_nm = route_point_times[station]
        role = "departure" if index == 0 else ("arrival" if index == len(route) - 1 else "enroute")
        station_defs.append(
            {
                "station": station,
                "role": role,
                "planned_time": planned_time,
                "distance_from_departure_nm": distance_nm,
                "sample": None,
            }
        )
    for sample in samples:
        station_defs.append(
            {
                "station": sample.icao_id,
                "role": "enroute",
                "planned_time": sample.planned_time,
                "distance_from_departure_nm": sample.distance_from_departure_nm,
                "sample": {
                    "name": sample.name,
                    "latitude": sample.latitude,
                    "longitude": sample.longitude,
                    "nearest_sample_distance_nm": sample.nearest_sample_distance_nm,
                },
            }
        )

    station_defs.sort(key=lambda item: float(item["distance_from_departure_nm"]))
    stations: list[dict[str, Any]] = []
    for station_def in station_defs:
        station_payload, coverage_note = _evaluate_station_for_route(
            station=station_def["station"],
            role=station_def["role"],
            profile=profile,
            planned_time=station_def["planned_time"],
            distance_from_departure_nm=float(station_def["distance_from_departure_nm"]),
            include_taf=include_taf,
            taf_lookahead_hours=taf_lookahead_hours,
            fuel_reserve_min=fuel_reserve_min,
            prefer_cache=prefer_cache,
            sample=station_def["sample"],
        )
        stations.append(station_payload)
        if coverage_note:
            coverage_notes.append(coverage_note)

    return {
        "route": route,
        "summary_decision": _route_summary_decision(stations, coverage_notes),
        "parameters": {
            "corridor_radius_nm": corridor_radius_nm,
            "sample_spacing_nm": sample_spacing_nm,
            "groundspeed_kt": groundspeed_kt,
            "planned_departure": planned_at.isoformat(),
        },
        "legs": legs,
        "stations": stations,
        "coverage_notes": coverage_notes,
        "index_notes": index_notes,
    }


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
