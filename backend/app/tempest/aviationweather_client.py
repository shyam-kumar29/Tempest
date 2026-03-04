"""AviationWeather.gov Data API client."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import API_BASE_URL, DEFAULT_API_TIMEOUT_SECONDS, DEFAULT_FORMAT, METAR_PATH


class AviationWeatherError(RuntimeError):
    """Raised when API access fails or returns unexpected data."""


@dataclass(slots=True)
class AviationWeatherClient:
    user_agent: str
    timeout_seconds: int = DEFAULT_API_TIMEOUT_SECONDS
    base_url: str = API_BASE_URL
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5

    def fetch_latest_metar_json(self, icao_id: str) -> list[dict[str, Any]]:
        station = icao_id.strip().upper()
        if len(station) != 4 or not station.isalpha():
            raise ValueError(f"Invalid ICAO id: {icao_id!r}")

        query = urlencode(
            {
                "ids": station,
                "format": DEFAULT_FORMAT,
            }
        )
        url = f"{self.base_url}{METAR_PATH}?{query}"

        request = Request(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="GET",
        )

        body = self._read_with_retries(request=request, station=station)

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AviationWeatherError("AviationWeather returned invalid JSON") from exc

        if not isinstance(parsed, list):
            raise AviationWeatherError("Unexpected METAR response shape (expected list)")

        typed: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                typed.append(item)

        return typed

    def _read_with_retries(self, request: Request, station: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except URLError as exc:
                last_error = exc

            if attempt < self.max_attempts:
                sleep_seconds = self.backoff_base_seconds * (2 ** (attempt - 1))
                time.sleep(sleep_seconds)

        if isinstance(last_error, HTTPError):
            raise AviationWeatherError(
                f"AviationWeather HTTP error {last_error.code} for ICAO {station}"
            ) from last_error
        if isinstance(last_error, URLError):
            raise AviationWeatherError(
                f"AviationWeather network error for ICAO {station}: {last_error.reason}"
            ) from last_error
        raise AviationWeatherError(
            f"AviationWeather request failed for ICAO {station} with unknown error"
        )
