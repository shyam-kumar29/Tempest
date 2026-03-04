"""Simple local disk cache for API responses."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class JsonFileCache:
    """Tiny JSON file cache with per-key TTL support."""

    def __init__(self, root: Path, ttl_seconds: int) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        safe_key = "".join(ch if ch.isalnum() else "_" for ch in key).lower()
        return self.root / f"{safe_key}.json"

    def get(self, key: str, now: float | None = None) -> dict[str, Any] | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None

        current = now if now is not None else time.time()
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(data["fetched_at_epoch"])
        if current - fetched_at > self.ttl_seconds:
            return None
        return data

    def get_stale(self, key: str) -> dict[str, Any] | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, key: str, payload: dict[str, Any], now: float | None = None) -> None:
        path = self._path_for_key(key)
        current = now if now is not None else time.time()
        wrapped = {
            "fetched_at_epoch": current,
            "payload": payload,
        }
        path.write_text(json.dumps(wrapped, indent=2, sort_keys=True), encoding="utf-8")
