"""Bounded Codex JSONL usage normalizer."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.host_protocol import NormalizedUsage, parse_bounded_jsonl_objects, safe_session_identifier


def parse_usage(source: str | bytes, *, wall_seconds: float = 0.0, max_bytes: int = 8 * 1024 * 1024) -> NormalizedUsage:
    events = parse_bounded_jsonl_objects(source, max_bytes=max_bytes)
    usage: dict[str, Any] = {}
    session_id = None
    tool_calls = 0
    for event in events:
        session_id = session_id or _session(event)
        candidate = event.get("usage")
        if not isinstance(candidate, dict) and isinstance(event.get("turn"), dict):
            candidate = event["turn"].get("usage")
        if isinstance(candidate, dict):
            usage = candidate
        if event.get("type") in {"tool.call", "tool_call", "item.tool_call"}:
            tool_calls += 1
    input_tokens = _counter(usage, "input_tokens", "inputTokens", "prompt_tokens")
    output_tokens = _counter(usage, "output_tokens", "outputTokens", "completion_tokens")
    total = _counter(usage, "total_tokens", "totalTokens", "billable_tokens")
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=max(total, input_tokens + output_tokens),
        tool_calls=tool_calls,
        wall_seconds=max(0.0, wall_seconds),
        session_id=session_id,
        event_count=len(events),
    )


def _counter(value: dict[str, Any], *keys: str) -> int:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
            return int(item)
    return 0


def _session(event: dict[str, Any]) -> str | None:
    for key in ("session_id", "sessionId", "thread_id", "threadId"):
        value = safe_session_identifier(event.get(key))
        if value:
            return value
    return None
