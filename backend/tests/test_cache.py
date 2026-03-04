from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from tempest.cache import JsonFileCache


def test_cache_honors_ttl() -> None:
    with TemporaryDirectory() as tmp:
        cache = JsonFileCache(root=Path(tmp), ttl_seconds=60)
        cache.set("metar_klaf", {"icaoId": "KLAF"}, now=100.0)

        fresh = cache.get("metar_klaf", now=150.0)
        stale = cache.get("metar_klaf", now=161.0)

        assert fresh is not None
        assert stale is None
