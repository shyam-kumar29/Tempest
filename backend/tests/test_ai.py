from __future__ import annotations

import pytest

from tempest.ai import (
    AIBriefingError,
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
