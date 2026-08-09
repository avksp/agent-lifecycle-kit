"""Bounded Kimi Code stream-json usage normalizer."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.host_protocol import NormalizedUsage, parse_bounded_jsonl_objects, safe_session_identifier

RESULT_TYPES = {"result", "final", "response.completed"}


def parse_usage(source: str | bytes, *, wall_seconds: float = 0.0, max_bytes: int = 8 * 1024 * 1024) -> NormalizedUsage:
    events = parse_bounded_jsonl_objects(source, max_bytes=max_bytes)
    fallback: dict[str, Any] = {}
    final: dict[str, Any] = {}
    session_id: str | None = None
    tool_calls = 0
    result_wall_seconds = 0.0
    for event in events:
        session_id = session_id or _session_id(event)
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else event.get("usageMetadata")
        if isinstance(usage, dict):
            fallback = usage
            if event.get("type") in RESULT_TYPES:
                final = usage
                result_wall_seconds = _duration_seconds(event)
        tool_calls += _tool_call_count(event)
    return _normalized(final or fallback, session_id, tool_calls, result_wall_seconds or wall_seconds, len(events))


def _normalized(usage: dict[str, Any], session_id: str | None, tool_calls: int, wall_seconds: float, event_count: int) -> NormalizedUsage:
    input_tokens = _counter(usage, ("inputTokens", "input_tokens", "prompt_tokens", "promptTokens", "promptTokenCount"))
    output_tokens = _counter(usage, ("outputTokens", "output_tokens", "completion_tokens", "completionTokens", "candidatesTokenCount"))
    total_tokens = _counter(usage, ("billableTokens", "billable_tokens", "total_tokens", "totalTokens", "totalTokenCount"))
    context_bytes = _counter(usage, ("cumulativeContextBytes", "cumulative_context_bytes", "contextBytes", "context_bytes"))
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=max(total_tokens, input_tokens + output_tokens),
        cumulative_context_bytes=context_bytes or None,
        cumulative_context_bytes_source="host-jsonl" if context_bytes else None,
        tool_calls=tool_calls,
        wall_seconds=max(0.0, round(wall_seconds, 3)),
        session_id=session_id,
        event_count=event_count,
    )


def _session_id(event: dict[str, Any]) -> str | None:
    for key in ("session_id", "sessionId", "sessionID", "conversation_id", "conversationId"):
        value = safe_session_identifier(event.get(key))
        if value:
            return value
    return None


def _counter(value: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            return item
        if isinstance(item, float) and item >= 0:
            return int(item)
    return 0


def _duration_seconds(event: dict[str, Any]) -> float:
    value = event.get("duration_ms")
    return float(value) / 1000 if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 0.0


def _tool_call_count(event: dict[str, Any]) -> int:
    if event.get("type") in {"tool_use", "tool_call", "tool.call", "tool.started"}:
        return 1
    calls = event.get("tool_calls")
    return len(calls) if isinstance(calls, list) else 0
