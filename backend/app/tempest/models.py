"""Typed models for weather observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MetarRecord:
    """Normalized METAR record used by Tempest internals and CLI output."""

    icao_id: str
    raw_text: str
    observed_at: str | None
    station_name: str | None
    latitude: float | None
    longitude: float | None
    elevation_m: float | None
    flight_category: str | None
    wind_direction_degrees: int | None
    wind_speed_kt: int | None
    wind_gust_kt: int | None
    visibility_sm: float | None
    temperature_c: float | None
    dewpoint_c: float | None
    altimeter_in_hg: float | None
    sea_level_pressure_mb: float | None
    sky_cover: list[dict[str, Any]] = field(default_factory=list)
    wx_string: str | None = None
    source_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "icao_id": self.icao_id,
            "raw_text": self.raw_text,
            "observed_at": self.observed_at,
            "station_name": self.station_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "flight_category": self.flight_category,
            "wind_direction_degrees": self.wind_direction_degrees,
            "wind_speed_kt": self.wind_speed_kt,
            "wind_gust_kt": self.wind_gust_kt,
            "visibility_sm": self.visibility_sm,
            "temperature_c": self.temperature_c,
            "dewpoint_c": self.dewpoint_c,
            "altimeter_in_hg": self.altimeter_in_hg,
            "sea_level_pressure_mb": self.sea_level_pressure_mb,
            "sky_cover": self.sky_cover,
            "wx_string": self.wx_string,
            "source_payload": self.source_payload,
        }


@dataclass(slots=True)
class TafRecord:
    """Normalized TAF record used by Tempest internals and CLI output."""

    icao_id: str
    raw_text: str
    issued_at: str | int | None
    valid_from: str | int | None
    valid_to: str | int | None
    station_name: str | None
    forecast: list[dict[str, Any]] = field(default_factory=list)
    source_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "icao_id": self.icao_id,
            "raw_text": self.raw_text,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "station_name": self.station_name,
            "forecast": self.forecast,
            "source_payload": self.source_payload,
        }
