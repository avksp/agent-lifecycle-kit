"""Read-only lifecycle progress projection."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest, read_json_object
from agent_lifecycle.workflow.state import TERMINAL_PHASES, load_state, state_identity

PROGRESS_VIEW_SCHEMA = "agent-lifecycle-progress-view.v1"


def build_lifecycle_progress_view(
    *,
    state_path: Path,
    usage_receipt_paths: list[Path] | None = None,
    change_summary_path: Path | None = None,
) -> dict[str, Any]:
    """Render one-line lifecycle progress rows from existing state and receipts."""

    state = load_state(state_path)
    usage_receipts = _load_usage_receipts(usage_receipt_paths or [])
    change_summary = _load_change_summary(change_summary_path, state)
    steps = _progress_steps(state)
    rows = [
        _progress_row(step, usage_receipts=usage_receipts, change_summary=change_summary)
        for step in steps
    ]
    totals = _usage_totals(usage_receipts)
    terminal = str(state.get("phase")) in TERMINAL_PHASES
    aggregate_line = _aggregate_line(change_summary)
    total_duration = sum(row["durationSeconds"] for row in rows)
    body = {
        "schemaVersion": PROGRESS_VIEW_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "tokenSpendForProgress": False,
        "stateIdentity": state_identity(state_path, state),
        "columnWidths": {"step": 22, "status": 10, "duration": 8, "tokens": 15},
        "rowCount": len(rows),
        "rows": rows,
        "lines": [row["line"] for row in rows],
        "terminal": terminal,
        "terminalSummary": {
            "duration": _format_duration_seconds(total_duration),
            "tokens": _format_token_pair(totals),
            "changeSummary": aggregate_line,
            "line": f"TOTAL                  {'DONE' if terminal else 'OPEN':<10} "
            f"{_format_duration_seconds(total_duration):<8} "
            f"{_format_token_pair(totals):<15} {aggregate_line}",
        },
        "productionPromotionClaimed": False,
    }
    return {**body, "progressDigest": canonical_digest(body)}


def _load_usage_receipts(paths: list[Path]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for path in paths:
        payload = read_json_object(path, label="usage receipt")
        receipts.append(payload)
    return receipts


def _load_change_summary(path: Path | None, state: dict[str, Any]) -> dict[str, int]:
    if path is not None:
        payload = read_json_object(path, label="change summary")
    else:
        payload = state.get("changeSummary") if isinstance(state.get("changeSummary"), dict) else {}
    return {
        "filesChanged": _int_value(payload, "filesChanged"),
        "insertions": _int_value(payload, "insertions"),
        "deletions": _int_value(payload, "deletions"),
        "modified": _int_value(payload, "modified"),
        "added": _int_value(payload, "added"),
        "deleted": _int_value(payload, "deleted"),
    }


def _progress_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    configured = state.get("lifecycleProgressSteps")
    if isinstance(configured, list) and configured:
        return [item for item in configured if isinstance(item, dict)]
    phase = str(state.get("phase"))
    return [
        {
            "name": phase,
            "status": "DONE" if phase in TERMINAL_PHASES else "ACTIVE",
            "startedAt": state.get("runStartedAt"),
            "completedAt": state.get("runCompletedAt"),
            "durationSeconds": state.get("durationSeconds"),
        }
    ]


def _progress_row(
    step: dict[str, Any],
    *,
    usage_receipts: list[dict[str, Any]],
    change_summary: dict[str, int],
) -> dict[str, Any]:
    name = _compact_text(str(step.get("name") or step.get("id") or "step"), 22)
    status = _compact_text(str(step.get("status") or "UNKNOWN"), 10)
    duration = _duration_seconds(step)
    totals = _usage_totals(_receipts_for_step(step, usage_receipts))
    token_text = _format_token_pair(totals)
    change_text = _compact_change_line(change_summary)
    line = f"{name:<22} {status:<10} {_format_duration_seconds(duration):<8} {token_text:<15} {change_text}"
    return {
        "name": name,
        "status": status,
        "durationSeconds": duration,
        "tokens": totals,
        "changeSummary": change_summary,
        "line": line,
    }


def _receipts_for_step(step: dict[str, Any], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_ids = step.get("taskIds")
    if not isinstance(task_ids, list) or not task_ids:
        return receipts
    allowed = {str(item) for item in task_ids if isinstance(item, str) and item}
    return [receipt for receipt in receipts if str(receipt.get("taskId")) in allowed]


def _usage_totals(receipts: list[dict[str, Any]]) -> dict[str, int | None]:
    if not receipts:
        return {"outputTokens": None, "inputTokens": None}
    output_tokens = 0
    input_tokens = 0
    seen_attested = False
    for receipt in receipts:
        if not _is_attested_usage(receipt):
            continue
        usage = receipt.get("usage")
        if not isinstance(usage, dict):
            continue
        output_tokens += _int_value(usage, "outputTokens")
        input_tokens += _int_value(usage, "inputTokens")
        seen_attested = True
    if not seen_attested:
        return {"outputTokens": None, "inputTokens": None}
    return {"outputTokens": output_tokens, "inputTokens": input_tokens}


def _is_attested_usage(receipt: dict[str, Any]) -> bool:
    attestation = receipt.get("attestation")
    if isinstance(attestation, dict):
        return attestation.get("source") == "host" and attestation.get("status") == "ATTESTED"
    return receipt.get("usageAttested") is True


def _duration_seconds(step: dict[str, Any]) -> int:
    value = step.get("durationSeconds")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    started_at = step.get("startedAt")
    completed_at = step.get("completedAt")
    if isinstance(started_at, str) and isinstance(completed_at, str):
        start = _parse_iso(started_at)
        end = _parse_iso(completed_at)
        if start is not None and end is not None and end >= start:
            return int((end - start).total_seconds())
    return 0


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_duration_seconds(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_token_pair(tokens: dict[str, int | None]) -> str:
    output_tokens = tokens.get("outputTokens")
    input_tokens = tokens.get("inputTokens")
    if output_tokens is None or input_tokens is None:
        return "↑?/↓? tok"
    return f"↑{_format_token_count(output_tokens)}/↓{_format_token_count(input_tokens)} tok"


def _format_token_count(value: int) -> str:
    value = max(0, value)
    for suffix, size in (("b", 1_000_000_000), ("m", 1_000_000), ("k", 1_000)):
        if value >= size:
            rounded = value / size
            return f"{rounded:.1f}{suffix}".replace(".0", "")
    if value >= 100:
        return f"{value / 1_000:.1f}k"
    return str(value)


def _compact_change_line(summary: dict[str, int]) -> str:
    return f"{summary['filesChanged']} files · +{summary['insertions']} -{summary['deletions']}"


def _aggregate_line(summary: dict[str, int]) -> str:
    return (
        f"{summary['filesChanged']} files changed · {summary['insertions']} insertions · "
        f"{summary['deletions']} deletions · {summary['modified']} modified · "
        f"{summary['added']} added · {summary['deleted']} deleted"
    )


def _compact_text(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(0, width - 1)] + "…"


def _int_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0
