#!/usr/bin/env python3
"""CLI entrypoint for evaluating current conditions against personal minimums."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tempest.airport import get_airport
from tempest.evaluation import evaluate_conditions
from tempest.metar import get_latest_metar
from tempest.minimums_store import JsonMinimumsStore, MinimumsStoreError
from tempest.taf import get_latest_taf
from tempest.wind import compute_runway_wind_components


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evaluate_flight")
    parser.add_argument("icao", help="4-letter ICAO airport id (example: KLAF)")
    parser.add_argument("profile_id", help="Saved minimums profile id")
    parser.add_argument(
        "--store-path",
        default="data/minimums/profiles.json",
        help="Path to minimums JSON store (default: data/minimums/profiles.json)",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/cache",
        help="Directory for weather and airport cache files (default: data/cache)",
    )
    parser.add_argument("--cache-ttl-seconds", type=int, default=300)
    parser.add_argument("--min-fetch-interval-seconds", type=int, default=60)
    parser.add_argument(
        "--prefer-cache",
        action="store_true",
        help="Use fresh cache first instead of checking the live API first",
    )
    parser.add_argument("--include-taf", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    store = JsonMinimumsStore(Path(args.store_path))
    try:
        profile = store.get_profile(args.profile_id)
        if profile is None:
            print(f"Error: minimums profile {args.profile_id!r} was not found", file=sys.stderr)
            return 2

        metar, metar_source = get_latest_metar(
            args.icao,
            cache_dir=Path(args.cache_dir),
            cache_ttl_seconds=args.cache_ttl_seconds,
            min_fetch_interval_seconds=args.min_fetch_interval_seconds,
            prefer_cache=args.prefer_cache,
        )
        airport, airport_source = get_airport(
            args.icao,
            cache_dir=Path(args.cache_dir),
            cache_ttl_seconds=args.cache_ttl_seconds,
            min_fetch_interval_seconds=args.min_fetch_interval_seconds,
            prefer_cache=args.prefer_cache,
        )
        taf = None
        taf_source = None
        if args.include_taf:
            taf, taf_source = get_latest_taf(
                args.icao,
                cache_dir=Path(args.cache_dir),
                cache_ttl_seconds=args.cache_ttl_seconds,
                min_fetch_interval_seconds=args.min_fetch_interval_seconds,
                prefer_cache=args.prefer_cache,
            )

        runway_components = compute_runway_wind_components(metar, airport)
        result = evaluate_conditions(
            profile=profile,
            metar=metar,
            taf=taf,
            airport=airport,
            runway_wind_components=runway_components,
        )

        output = {
            "profile": profile.to_dict(),
            "decision": result.to_dict(),
            "metar_source": metar_source,
            "airport_source": airport_source,
            "taf_source": taf_source,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except (ValueError, MinimumsStoreError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
