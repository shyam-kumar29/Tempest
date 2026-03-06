#!/usr/bin/env python3
"""CLI entrypoint for managing personal minimums profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tempest.minimums import MinimumsProfile
from tempest.minimums_store import JsonMinimumsStore, MinimumsStoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage_minimums")
    parser.add_argument(
        "--store-path",
        default="data/minimums/profiles.json",
        help="Path to minimums JSON store (default: data/minimums/profiles.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    set_cmd = sub.add_parser("set", help="Create or update a minimums profile")
    set_cmd.add_argument("profile_id")
    set_cmd.add_argument("display_name")
    set_cmd.add_argument("--min-ceiling-ft-agl", type=int, required=True)
    set_cmd.add_argument("--min-visibility-sm", type=float, required=True)
    set_cmd.add_argument("--max-surface-wind-kt", type=int, required=True)
    set_cmd.add_argument("--max-crosswind-kt", type=int, required=True)
    set_cmd.add_argument("--max-gust-kt", type=int)
    set_cmd.add_argument("--max-tailwind-kt", type=int)
    set_cmd.add_argument("--allow-night", action="store_true")
    set_cmd.add_argument("--allow-ifr", action="store_true")
    set_cmd.add_argument("--min-runway-length-ft", type=int, default=0)
    set_cmd.add_argument(
        "--allowed-runway-surface",
        action="append",
        dest="allowed_runway_surfaces",
        help=(
            "Allowed runway surface (repeat for multiple). "
            "Examples: asphalt, concrete, grass, gravel"
        ),
    )
    set_cmd.add_argument("--require-dry-runway", action="store_true")
    set_cmd.add_argument("--min-fuel-reserve-min", type=int, default=45)
    set_cmd.add_argument("--max-density-altitude-ft", type=int)
    set_cmd.add_argument("--no-require-alternate-for-ifr", action="store_true")
    set_cmd.add_argument("--notes")

    get_cmd = sub.add_parser("get", help="Get a minimums profile by id")
    get_cmd.add_argument("profile_id")

    sub.add_parser("list", help="List all minimums profiles")

    del_cmd = sub.add_parser("delete", help="Delete a minimums profile")
    del_cmd.add_argument("profile_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    store = JsonMinimumsStore(Path(args.store_path))

    try:
        if args.command == "set":
            profile = MinimumsProfile(
                profile_id=args.profile_id,
                display_name=args.display_name,
                min_ceiling_ft_agl=args.min_ceiling_ft_agl,
                min_visibility_sm=args.min_visibility_sm,
                max_surface_wind_kt=args.max_surface_wind_kt,
                max_crosswind_kt=args.max_crosswind_kt,
                max_gust_kt=args.max_gust_kt,
                max_tailwind_kt=args.max_tailwind_kt,
                allow_night=args.allow_night,
                allow_ifr=args.allow_ifr,
                min_runway_length_ft=args.min_runway_length_ft,
                allowed_runway_surfaces=args.allowed_runway_surfaces,
                require_dry_runway=args.require_dry_runway,
                min_fuel_reserve_min=args.min_fuel_reserve_min,
                max_density_altitude_ft=args.max_density_altitude_ft,
                require_alternate_for_ifr=not args.no_require_alternate_for_ifr,
                notes=args.notes,
            )
            saved = store.upsert_profile(profile)
            print(json.dumps({"profile": saved.to_dict()}, indent=2, sort_keys=True))
            return 0

        if args.command == "get":
            profile = store.get_profile(args.profile_id)
            if profile is None:
                print(json.dumps({"profile": None, "found": False}, indent=2, sort_keys=True))
                return 0
            print(json.dumps({"profile": profile.to_dict(), "found": True}, indent=2, sort_keys=True))
            return 0

        if args.command == "list":
            profiles = [p.to_dict() for p in store.list_profiles()]
            print(json.dumps({"profiles": profiles}, indent=2, sort_keys=True))
            return 0

        if args.command == "delete":
            deleted = store.delete_profile(args.profile_id)
            print(json.dumps({"deleted": deleted, "profile_id": args.profile_id}, indent=2, sort_keys=True))
            return 0

        parser.error("unknown command")
        return 2
    except (ValueError, MinimumsStoreError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
