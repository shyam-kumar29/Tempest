from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from tempest.ai import (
    AIBriefingError,
    _ai_timeout_seconds,
    apply_ai_briefing_to_decision,
    generate_ai_briefing,
    validate_ai_briefing,
)


def _briefing(**overrides):
    payload = {
        "summary": "Good options exist, but review ceilings.",
        "recommended_action": "Pick the best VFR-margin destination.",
        "downgrade_decision": None,
        "top_risks": ["Lower ceilings later."],
        "best_options": ["KAAA"],
        "watch_items": ["TAF timing"],
        "pilot_questions": ["How much daylight remains?"],
        "limitations": ["AI is advisory."],
    }
    payload.update(overrides)
    return payload


def test_generate_ai_briefing_returns_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    payload = generate_ai_briefing({"summary_decision": "go"})

    assert payload["status"] == "unavailable"
    assert "OPENAI_API_KEY" in payload["limitations"][0]


def test_ai_timeout_seconds_uses_env_with_floor(monkeypatch) -> None:
    monkeypatch.delenv("TEMPEST_AI_TIMEOUT_SECONDS", raising=False)
    assert _ai_timeout_seconds(default=45) == 45

    monkeypatch.setenv("TEMPEST_AI_TIMEOUT_SECONDS", "60")
    assert _ai_timeout_seconds(default=45) == 60

    monkeypatch.setenv("TEMPEST_AI_TIMEOUT_SECONDS", "2")
    assert _ai_timeout_seconds(default=45) == 5

    monkeypatch.setenv("TEMPEST_AI_TIMEOUT_SECONDS", "invalid")
    assert _ai_timeout_seconds(default=45) == 45


def test_generate_ai_briefing_reports_quota_429(monkeypatch) -> None:
    body = b'{"error":{"message":"You exceeded your current quota.","code":"insufficient_quota"}}'

    def raise_quota(*args, **kwargs):
        raise HTTPError(
            url="https://api.openai.com/v1/responses",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(body),
        )

    monkeypatch.setattr("tempest.ai.urlopen", raise_quota)

    with pytest.raises(AIBriefingError, match="quota or billing limit"):
        generate_ai_briefing({"summary_decision": "go"}, api_key="test-key")


def test_generate_ai_briefing_reports_rate_limit_429(monkeypatch) -> None:
    body = b'{"error":{"message":"Rate limit reached.","code":"rate_limit_exceeded"}}'

    def raise_rate_limit(*args, **kwargs):
        raise HTTPError(
            url="https://api.openai.com/v1/responses",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(body),
        )

    monkeypatch.setattr("tempest.ai.urlopen", raise_rate_limit)

    with pytest.raises(AIBriefingError, match="rate limit reached"):
        generate_ai_briefing({"summary_decision": "go"}, api_key="test-key")


def test_generate_ai_briefing_reports_timeout(monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("tempest.ai.urlopen", raise_timeout)

    with pytest.raises(AIBriefingError, match="request timed out"):
        generate_ai_briefing({"summary_decision": "go"}, api_key="test-key")


def test_validate_ai_briefing_requires_schema_fields() -> None:
    with pytest.raises(AIBriefingError, match="missing required field"):
        validate_ai_briefing({"summary": "short"})

    payload = validate_ai_briefing(_briefing(downgrade_decision="caution"))
    assert payload["status"] == "completed"
    assert payload["downgrade_decision"] == "caution"


def test_ai_briefing_decision_application_is_downgrade_only() -> None:
    assert (
        apply_ai_briefing_to_decision(
            base_decision="go",
            briefing=validate_ai_briefing(_briefing(downgrade_decision="caution")),
        )
        == "caution"
    )
    assert (
        apply_ai_briefing_to_decision(
            base_decision="no-go",
            briefing=validate_ai_briefing(_briefing(downgrade_decision="go")),
        )
        == "no-go"
    )
