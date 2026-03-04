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
from .metar import MetarNotFoundError, get_latest_metar


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cache_ttl_seconds < 0:
        parser.error("--cache-ttl-seconds must be >= 0")
    if args.min_fetch_interval_seconds < 0:
        parser.error("--min-fetch-interval-seconds must be >= 0")

    try:
        record, source = get_latest_metar(
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

    output = {
        "source": source,
        "metar": record.to_dict(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0
