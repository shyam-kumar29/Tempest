"""Shared time parsing and freshness helpers for aviation data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def parse_aviation_time(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            return None
    return None


def to_local_time_string(value: str | int | None) -> str | None:
    parsed = parse_aviation_time(value)
    if parsed is None:
        return None
    return parsed.astimezone().isoformat()


def is_metar_payload_current(payload: dict[str, Any], now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    observed_at = parse_aviation_time(
        payload.get("obsTime") or payload.get("reportTime") or payload.get("observation_time")
    )
    if observed_at is None:
        return False
    age = current - observed_at.astimezone(UTC)
    return timedelta(0) <= age <= timedelta(hours=1)


def is_taf_payload_current(payload: dict[str, Any], now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    valid_from = parse_aviation_time(payload.get("validTimeFrom") or payload.get("valid_from"))
    valid_to = parse_aviation_time(payload.get("validTimeTo") or payload.get("valid_to"))
    issue_time = parse_aviation_time(payload.get("issueTime") or payload.get("issue_time"))

    if valid_from is None or valid_to is None:
        return False
    current_utc = current.astimezone(UTC)
    if not (valid_from.astimezone(UTC) <= current_utc <= valid_to.astimezone(UTC)):
        return False
    if issue_time is None:
        return True

    age = current_utc - issue_time.astimezone(UTC)
    return timedelta(0) <= age <= timedelta(hours=36)


def is_airport_payload_current(
    wrapped_cache: dict[str, Any] | None,
    now: datetime | None = None,
) -> bool:
    if not wrapped_cache:
        return False
    fetched_at = wrapped_cache.get("fetched_at_epoch")
    if not isinstance(fetched_at, (int, float)):
        return False
    current = now or datetime.now(UTC)
    fetched_dt = datetime.fromtimestamp(float(fetched_at), tz=UTC)
    age = current - fetched_dt
    return timedelta(0) <= age <= timedelta(days=30)
