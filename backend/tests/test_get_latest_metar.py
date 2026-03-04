from __future__ import annotations

from pathlib import Path

from tempest.cache import JsonFileCache
from tempest.metar import get_latest_metar


def test_get_latest_metar_uses_cache_when_recent(tmp_path: Path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_seconds=300)
    cache.set(
        "metar_KLAF",
        {
            "icaoId": "KLAF",
            "rawOb": "KLAF 011654Z 22012KT 10SM CLR 08/M02 A2992",
        },
    )

    record, source = get_latest_metar("KLAF", cache_dir=tmp_path)

    assert source == "cache"
    assert record.icao_id == "KLAF"


def test_get_latest_metar_respects_min_fetch_interval(tmp_path: Path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_seconds=0)
    cache.set(
        "metar_KLAF",
        {
            "icaoId": "KLAF",
            "rawOb": "KLAF 011654Z 22012KT 10SM CLR 08/M02 A2992",
        },
    )

    record, source = get_latest_metar(
        "KLAF",
        cache_dir=tmp_path,
        cache_ttl_seconds=0,
        min_fetch_interval_seconds=3600,
    )

    assert source == "throttled-cache"
    assert record.raw_text.startswith("KLAF")
