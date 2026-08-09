"""Bounded OpenCode JSON event usage normalizer."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.host_protocol import NormalizedUsage, parse_bounded_jsonl_objects, safe_session_identifier


def parse_usage(source: str | bytes, *, wall_seconds: float = 0.0, max_bytes: int = 8 * 1024 * 1024) -> NormalizedUsage:
    events = parse_bounded_jsonl_objects(source, max_bytes=max_bytes)
    totals: dict[str, Any] = {}
    session_id = None
    tool_calls = 0
    for event in events:
        session_id = session_id or safe_session_identifier(event.get("sessionID")) or safe_session_identifier(event.get("sessionId"))
        part = event.get("part")
        candidate = part.get("tokens") if isinstance(part, dict) else event.get("tokens")
        if isinstance(candidate, dict):
            totals = candidate
        if event.get("type") in {"tool_use", "tool_call", "tool"}:
            tool_calls += 1
    input_tokens = _counter(totals, "input", "inputTokens", "input_tokens")
    output_tokens = _counter(totals, "output", "outputTokens", "output_tokens")
    total = _counter(totals, "total", "totalTokens", "billableTokens")
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
