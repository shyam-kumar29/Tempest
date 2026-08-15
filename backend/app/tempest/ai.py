"""OpenAI-backed advisory briefing support."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import DEFAULT_AI_TIMEOUT_SECONDS
from .recommendations import apply_ai_downgrade


AI_BRIEFING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "recommended_action": {"type": "string"},
        "downgrade_decision": {"type": ["string", "null"], "enum": ["go", "caution", "no-go", None]},
        "top_risks": {"type": "array", "items": {"type": "string"}},
        "best_options": {"type": "array", "items": {"type": "string"}},
        "watch_items": {"type": "array", "items": {"type": "string"}},
        "pilot_questions": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary",
        "recommended_action",
        "downgrade_decision",
        "top_risks",
        "best_options",
        "watch_items",
        "pilot_questions",
        "limitations",
    ],
}

AI_MAX_OUTPUT_TOKENS = 1400
AI_RETRY_MAX_OUTPUT_TOKENS = 2600


class AIBriefingError(RuntimeError):
    """Raised when AI briefing generation fails."""


def _ai_timeout_seconds(default: int = DEFAULT_AI_TIMEOUT_SECONDS) -> int:
    raw_value = os.environ.get("TEMPEST_AI_TIMEOUT_SECONDS")
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return max(5, parsed)


def _ai_reasoning_effort() -> str:
    effort = os.environ.get("TEMPEST_AI_REASONING_EFFORT", "minimal").strip().lower()
    if effort not in {"none", "minimal", "low", "medium", "high"}:
        return "minimal"
    return effort


def _openai_http_error_message(exc: HTTPError) -> str:
    try:
        raw_body = exc.read().decode("utf-8")
    except Exception:
        raw_body = ""

    error_payload: dict[str, Any] = {}
    if raw_body:
        try:
            decoded = json.loads(raw_body)
        except json.JSONDecodeError:
            decoded = {}
        if isinstance(decoded, dict) and isinstance(decoded.get("error"), dict):
            error_payload = decoded["error"]

    api_message = str(error_payload.get("message") or "").strip()
    api_code = str(error_payload.get("code") or error_payload.get("type") or "").strip()

    if exc.code == 401:
        return (
            "OpenAI API authentication failed. Check that OPENAI_API_KEY in .env.local "
            "is correct and belongs to the project you intend to use."
        )
    if exc.code == 429 and ("quota" in api_code.lower() or "quota" in api_message.lower()):
        return (
            "OpenAI API quota or billing limit reached. Check the OpenAI project billing, "
            "usage limits, and model access. Deterministic Tempest recommendations still work."
        )
    if exc.code == 429:
        return (
            "OpenAI API rate limit reached. Wait a minute and retry, or reduce the "
            "recommendation count/range. Deterministic Tempest recommendations still work."
        )

    if api_message:
        return f"OpenAI briefing request failed ({exc.code}): {api_message}"
    return f"OpenAI briefing request failed: HTTP {exc.code}"


def unavailable_ai_payload(message: str = "AI briefing is not configured.") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "summary": None,
        "recommended_action": None,
        "downgrade_decision": None,
        "top_risks": [],
        "best_options": [],
        "watch_items": [],
        "pilot_questions": [],
        "limitations": [message],
    }


def error_ai_payload(message: str) -> dict[str, Any]:
    payload = unavailable_ai_payload(message)
    payload["status"] = "error"
    return payload


def _extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)


def _response_incomplete_reason(response: dict[str, Any]) -> str | None:
    details = response.get("incomplete_details")
    if isinstance(details, dict) and details.get("reason"):
        return str(details["reason"])
    return None


def _response_error_message(response: dict[str, Any]) -> str | None:
    error = response.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    code = error.get("code")
    if message and code:
        return f"OpenAI briefing response failed ({code}): {message}"
    if message:
        return f"OpenAI briefing response failed: {message}"
    return "OpenAI briefing response failed."


def _briefing_request_payload(
    *,
    model: str,
    context: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are an advisory aviation weather briefing assistant for Tempest. "
                    "Use only the provided deterministic weather/minimums results. "
                    "Never upgrade a deterministic decision. You may recommend a conservative downgrade. "
                    "Do not provide regulatory clearance or imply the flight is safe. "
                    "Return concise JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(context, sort_keys=True),
            },
        ],
        "reasoning": {"effort": _ai_reasoning_effort()},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "tempest_ai_briefing",
                "strict": True,
                "schema": AI_BRIEFING_SCHEMA,
            },
        },
        "max_output_tokens": max_output_tokens,
    }


def _post_openai_response(
    *,
    api_key: str,
    request_payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise AIBriefingError(_openai_http_error_message(exc)) from exc
    except TimeoutError as exc:
        raise AIBriefingError(
            "OpenAI briefing request timed out. Deterministic Tempest recommendations still work. "
            "Retry with fewer destinations, a smaller range, or increase TEMPEST_AI_TIMEOUT_SECONDS."
        ) from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        if "timed out" in str(exc).lower():
            raise AIBriefingError(
                "OpenAI briefing request timed out. Deterministic Tempest recommendations still work. "
                "Retry with fewer destinations, a smaller range, or increase TEMPEST_AI_TIMEOUT_SECONDS."
            ) from exc
        raise AIBriefingError(f"OpenAI briefing request failed: {exc}") from exc


def validate_ai_briefing(payload: dict[str, Any]) -> dict[str, Any]:
    for field in AI_BRIEFING_SCHEMA["required"]:
        if field not in payload:
            raise AIBriefingError(f"AI briefing missing required field: {field}")

    text_fields = ["summary", "recommended_action"]
    for field in text_fields:
        if not isinstance(payload[field], str):
            raise AIBriefingError(f"AI briefing field must be text: {field}")

    if payload["downgrade_decision"] not in {"go", "caution", "no-go", None}:
        raise AIBriefingError("AI briefing downgrade_decision is invalid")

    for field in ("top_risks", "best_options", "watch_items", "pilot_questions", "limitations"):
        if not isinstance(payload[field], list) or not all(
            isinstance(item, str) for item in payload[field]
        ):
            raise AIBriefingError(f"AI briefing field must be a list of strings: {field}")

    return {
        "status": "completed",
        "summary": payload["summary"],
        "recommended_action": payload["recommended_action"],
        "downgrade_decision": payload["downgrade_decision"],
        "top_risks": payload["top_risks"],
        "best_options": payload["best_options"],
        "watch_items": payload["watch_items"],
        "pilot_questions": payload["pilot_questions"],
        "limitations": payload["limitations"],
    }


def generate_ai_briefing(
    context: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return unavailable_ai_payload("OPENAI_API_KEY is not configured.")

    model = model or os.environ.get("TEMPEST_AI_MODEL", "gpt-5-mini")
    timeout_seconds = timeout_seconds or _ai_timeout_seconds()

    response_payload: dict[str, Any] | None = None
    for max_output_tokens in (AI_MAX_OUTPUT_TOKENS, AI_RETRY_MAX_OUTPUT_TOKENS):
        response_payload = _post_openai_response(
            api_key=api_key,
            request_payload=_briefing_request_payload(
                model=model,
                context=context,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        )
        output_text = _extract_output_text(response_payload)
        if output_text:
            break
        incomplete_reason = _response_incomplete_reason(response_payload)
        if incomplete_reason not in {"max_output_tokens", "max_tokens"}:
            break
    else:
        output_text = ""

    if response_payload is None:
        raise AIBriefingError("OpenAI briefing response was unavailable")

    response_error = _response_error_message(response_payload)
    if response_error:
        raise AIBriefingError(response_error)

    incomplete_reason = _response_incomplete_reason(response_payload)
    output_text = _extract_output_text(response_payload)
    if not output_text:
        if incomplete_reason in {"max_output_tokens", "max_tokens"}:
            raise AIBriefingError(
                "OpenAI briefing response ran out of output tokens before producing visible JSON. "
                "Retry with fewer destinations or set TEMPEST_AI_REASONING_EFFORT=none if your model supports it."
            )
        if incomplete_reason:
            raise AIBriefingError(
                f"OpenAI briefing response was incomplete before producing visible JSON: {incomplete_reason}"
            )
        raise AIBriefingError("OpenAI briefing response did not include output text")

    try:
        briefing = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise AIBriefingError("OpenAI briefing response was not valid JSON") from exc
    if not isinstance(briefing, dict):
        raise AIBriefingError("OpenAI briefing response was not an object")
    return validate_ai_briefing(briefing)


def apply_ai_briefing_to_decision(
    *,
    base_decision: str,
    briefing: dict[str, Any],
) -> str:
    if briefing.get("status") != "completed":
        return base_decision
    return apply_ai_downgrade(
        base_decision=base_decision,
        ai_decision=briefing.get("downgrade_decision"),
    )
