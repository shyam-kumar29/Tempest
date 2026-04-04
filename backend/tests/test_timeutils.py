from __future__ import annotations

from datetime import UTC, datetime

from tempest.timeutils import (
    is_airport_payload_current,
    is_metar_payload_current,
    is_taf_payload_current,
    to_local_time_string,
)


def test_is_metar_payload_current_true_within_one_hour() -> None:
    now = datetime(2026, 4, 4, 19, 0, tzinfo=UTC)
    payload = {"obsTime": "2026-04-04T18:30:00Z"}
    assert is_metar_payload_current(payload, now=now) is True


def test_is_metar_payload_current_false_when_too_old() -> None:
    now = datetime(2026, 4, 4, 19, 0, tzinfo=UTC)
    payload = {"obsTime": "2026-04-04T17:30:00Z"}
    assert is_metar_payload_current(payload, now=now) is False


def test_is_taf_payload_current_true_within_valid_window() -> None:
    now = datetime(2026, 4, 4, 19, 0, tzinfo=UTC)
    payload = {
        "issueTime": "2026-04-04T12:00:00Z",
        "validTimeFrom": "2026-04-04T18:00:00Z",
        "validTimeTo": "2026-04-05T18:00:00Z",
    }
    assert is_taf_payload_current(payload, now=now) is True


def test_is_taf_payload_current_false_outside_valid_window() -> None:
    now = datetime(2026, 4, 5, 19, 0, tzinfo=UTC)
    payload = {
        "issueTime": "2026-04-04T12:00:00Z",
        "validTimeFrom": "2026-04-04T18:00:00Z",
        "validTimeTo": "2026-04-05T18:00:00Z",
    }
    assert is_taf_payload_current(payload, now=now) is False


def test_is_airport_payload_current_true_within_thirty_days() -> None:
    now = datetime(2026, 4, 4, 19, 0, tzinfo=UTC)
    wrapped = {"fetched_at_epoch": datetime(2026, 3, 20, 19, 0, tzinfo=UTC).timestamp()}
    assert is_airport_payload_current(wrapped, now=now) is True


def test_to_local_time_string_returns_none_for_unknown_input() -> None:
    assert to_local_time_string(None) is None
