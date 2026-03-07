"""CLI helpers for Tempest backend scripts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
    DEFAULT_USER_AGENT,
)
from .airport import AirportNotFoundError, get_airport
from .metar import MetarNotFoundError, get_latest_metar
from .taf import TafNotFoundError, get_latest_taf
from .wind import compute_runway_wind_components


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_metar",
        description="Fetch latest METAR for a given ICAO id from AviationWeather.gov",
    )
    parser.add_argument("icao", help="4-letter ICAO airport id (example: KLAF)")
    parser.add_argument(
        "--cache-dir",
        default="data/cache",
        help="Directory for local cache files (default: data/cache)",
    )
    parser.add_argument(
        "--cache-ttl-seconds",
        type=int,
        default=DEFAULT_CACHE_TTL_SECONDS,
        help=f"Cache TTL in seconds (default: {DEFAULT_CACHE_TTL_SECONDS})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass fresh cache and fetch from API",
    )
    parser.add_argument(
        "--min-fetch-interval-seconds",
        type=int,
        default=DEFAULT_MIN_FETCH_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between API fetches for the same station. "
            f"Default: {DEFAULT_MIN_FETCH_INTERVAL_SECONDS}"
        ),
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="Custom User-Agent for AviationWeather requests",
    )
    parser.add_argument(
        "--include-taf",
        action="store_true",
        help="Also fetch latest TAF for the same station",
    )
    parser.add_argument(
        "--include-airport",
        action="store_true",
        help="Also fetch airport/runway data for the same station",
    )
    parser.add_argument(
        "--include-runway-wind",
        action="store_true",
        help="Compute runway wind components (requires airport runway headings)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cache_ttl_seconds < 0:
        parser.error("--cache-ttl-seconds must be >= 0")
    if args.min_fetch_interval_seconds < 0:
        parser.error("--min-fetch-interval-seconds must be >= 0")

    try:
        metar_record, metar_source = get_latest_metar(
            args.icao,
            cache_dir=Path(args.cache_dir),
            cache_ttl_seconds=args.cache_ttl_seconds,
            min_fetch_interval_seconds=args.min_fetch_interval_seconds,
            user_agent=args.user_agent,
            prefer_cache=not args.no_cache,
        )
    except (ValueError, MetarNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    output: dict[str, object] = {"source": metar_source, "metar": metar_record.to_dict()}

    if args.include_taf:
        try:
            taf_record, taf_source = get_latest_taf(
                args.icao,
                cache_dir=Path(args.cache_dir),
                cache_ttl_seconds=args.cache_ttl_seconds,
                min_fetch_interval_seconds=args.min_fetch_interval_seconds,
                user_agent=args.user_agent,
                prefer_cache=not args.no_cache,
            )
            output["taf"] = taf_record.to_dict()
            output["taf_source"] = taf_source
        except (ValueError, TafNotFoundError) as exc:
            output["taf"] = None
            output["taf_error"] = str(exc)
        except Exception as exc:
            output["taf"] = None
            output["taf_error"] = f"TAF fetch failed: {exc}"

    if args.include_airport or args.include_runway_wind:
        try:
            airport_record, airport_source = get_airport(
                args.icao,
                cache_dir=Path(args.cache_dir),
                cache_ttl_seconds=args.cache_ttl_seconds,
                min_fetch_interval_seconds=args.min_fetch_interval_seconds,
                user_agent=args.user_agent,
                prefer_cache=not args.no_cache,
            )
            output["airport"] = airport_record.to_dict()
            output["airport_source"] = airport_source

            if args.include_runway_wind:
                output["runway_wind_components"] = compute_runway_wind_components(
                    metar=metar_record,
                    airport=airport_record,
                )
        except (ValueError, AirportNotFoundError) as exc:
            output["airport"] = None
            output["airport_error"] = str(exc)
            if args.include_runway_wind:
                output["runway_wind_components"] = []
        except Exception as exc:
            output["airport"] = None
            output["airport_error"] = f"Airport fetch failed: {exc}"
            if args.include_runway_wind:
                output["runway_wind_components"] = []

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0
