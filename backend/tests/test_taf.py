from __future__ import annotations

from tempest.cache import JsonFileCache
from tempest.taf import get_latest_taf, normalize_taf


def test_normalize_taf_maps_core_fields() -> None:
    payload = {
        "icaoId": "KLAF",
        "rawTAF": "TAF KLAF 031120Z 0312/0412 22012KT P6SM SCT030",
        "issueTime": "2026-03-03T11:20:00Z",
        "validTimeFrom": "2026-03-03T12:00:00Z",
        "validTimeTo": "2026-03-04T12:00:00Z",
        "name": "Lafayette/Purdue Univ Arpt, IN, US",
        "fcsts": [{"timeFrom": "2026-03-03T12:00:00Z", "wspd": 12}],
    }

    record = normalize_taf(payload)

    assert record.icao_id == "KLAF"
    assert record.raw_text.startswith("TAF KLAF")
    assert record.valid_to == "2026-03-04T12:00:00Z"
    assert record.station_name == "Lafayette/Purdue Univ Arpt, IN, US"
    assert len(record.forecast) == 1


def test_get_latest_taf_uses_cache(tmp_path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_seconds=300)
    cache.set(
        "taf_KLAF",
        {
            "icaoId": "KLAF",
            "rawTAF": "TAF KLAF 031120Z 0312/0412 22012KT P6SM SCT030",
        },
    )

    record, source = get_latest_taf("KLAF", cache_dir=tmp_path)

    assert source == "cache"
    assert record.icao_id == "KLAF"


def test_get_latest_taf_throttled_cache(tmp_path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_seconds=0)
    cache.set(
        "taf_KLAF",
        {
            "icaoId": "KLAF",
            "rawTAF": "TAF KLAF 031120Z 0312/0412 22012KT P6SM SCT030",
        },
    )

    record, source = get_latest_taf(
        "KLAF",
        cache_dir=tmp_path,
        cache_ttl_seconds=0,
        min_fetch_interval_seconds=3600,
    )

    assert source == "throttled-cache"
    assert record.raw_text.startswith("TAF KLAF")
