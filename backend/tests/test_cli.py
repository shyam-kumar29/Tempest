from __future__ import annotations

from tempest.cli import build_parser


def test_parser_requires_icao() -> None:
    parser = build_parser()
    args = parser.parse_args(["KLAF"])
    assert args.icao == "KLAF"
    assert args.no_cache is False
    assert args.min_fetch_interval_seconds == 60
    assert args.include_taf is False


def test_parser_supports_include_taf_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["KLAF", "--include-taf"])
    assert args.include_taf is True
