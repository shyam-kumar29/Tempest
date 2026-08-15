"""Static configuration for Tempest backend modules."""

from __future__ import annotations

API_BASE_URL = "https://aviationweather.gov/api/data"
METAR_PATH = "/metar"
TAF_PATH = "/taf"
AIRPORT_PATH = "/airport"
DEFAULT_FORMAT = "json"
STATIONS_CACHE_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"

DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_STATION_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_API_TIMEOUT_SECONDS = 10
DEFAULT_AI_TIMEOUT_SECONDS = 45
DEFAULT_MIN_FETCH_INTERVAL_SECONDS = 60

# Keep this stable and descriptive for upstream API operators.
DEFAULT_USER_AGENT = "Tempest/0.1 (+https://github.com/shyam-kumar29/tempest)"
