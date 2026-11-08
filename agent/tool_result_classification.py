"""Shared helpers for classifying tool result payloads."""

from __future__ import annotations

import json
from typing import Any


FILE_MUTATING_TOOL_NAMES = frozenset({"write_file", "patch"})


# Tools whose interrupted/dangling execution is safe to discard because they
# cannot mutate either external state or Hermes session state. Unknown/plugin/
# MCP tools stay effect-capable by default.
NO_EFFECT_TOOL_NAMES = frozenset({
    "read_file", "search_files", "session_search", "skill_view", "skills_list",
    "web_extract", "web_search", "vision_analyze", "browser_snapshot",
    "browser_get_images", "browser_console", "read_terminal",
})


def tool_may_have_side_effect(tool_name: str) -> bool:
    return tool_name not in NO_EFFECT_TOOL_NAMES


# Set by a tool that REFUSED a call the harness judged redundant (repeated identical
# read/search). The body still carries ``"error"`` so the model reads it as a stop
# signal, but nothing failed: failure classifiers must not count it, or the cheap
# refusal feeds the streak that fires ``repeated_exact_failure_block``.
GUARDRAIL_REFUSAL_KEY = "guardrail_refusal"


def error_value_is_present(value: Any) -> bool:
    """True when an ``error`` field carries a failure, not a null or empty slot.

    ``None``, ``False``, ``""`` and empty containers are the explicit "no error"
    values tools put next to a successful row (web_extract writes ``"error": null``
    on every page). A non-empty string, or a container that itself holds one, is
    a failure. Page text is not inspected.
    """
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        if not value:
            return False
        message = value.get("message") if "message" in value else value.get("error")
        if message is None:
            return True
        return error_value_is_present(message)
    if isinstance(value, (list, tuple)):
        return any(error_value_is_present(item) for item in value)
    return False


def _declared_error_values(data: Any, depth: int = 0):
    """Yield ``error`` field values on this object and its result rows.

    Recurses only through ``results`` / ``data`` / ``pages``. String content is
    not parsed, so a page that mentions the word error is not an error field.
    """
    if not isinstance(data, dict) or depth > 3:
        return
    if "error" in data:
        yield data.get("error")
    for key in ("results", "data", "pages"):
        child = data.get(key)
        if isinstance(child, dict):
            yield from _declared_error_values(child, depth + 1)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    yield from _declared_error_values(item, depth + 1)


def payload_error_verdict(data: Any) -> tuple[bool, str] | None:
    """Classify declared error fields on a parsed tool payload.

    ``None`` when the payload has no error field (other heuristics still apply).
    ``(False, "")`` when every declared error field is null or empty.
    ``(True, message)`` when any declared field carries a real failure. A
    successful row's text does not clear a sibling row's error.
    """
    if not isinstance(data, dict):
        return None
    values = list(_declared_error_values(data))
    if not values:
        return None
    for value in values:
        if error_value_is_present(value):
            if isinstance(value, str):
                return True, value.strip()
            if isinstance(value, dict):
                message = value.get("message") or value.get("error")
                if isinstance(message, str) and message.strip():
                    return True, message.strip()
            return True, str(value)
    return False, ""


def is_guardrail_refusal(result: Any) -> bool:
    """Return True when ``result`` (JSON string or parsed dict) is a harness refusal."""
    data = result
    if isinstance(result, str):
        try:
            data = json.loads(result.strip())
        except Exception:
            return False
    return isinstance(data, dict) and data.get(GUARDRAIL_REFUSAL_KEY) is True


def file_mutation_result_landed(tool_name: str, result: Any) -> bool:
    """Return True when a file mutation result proves the write landed."""
    if tool_name not in FILE_MUTATING_TOOL_NAMES or not isinstance(result, str):
        return False
    try:
        data = json.loads(result.strip())
    except Exception:
        return False
    if not isinstance(data, dict) or data.get("error"):
        return False
    if tool_name == "write_file":
        return "bytes_written" in data
    if tool_name == "patch":
        return data.get("success") is True
    return False
