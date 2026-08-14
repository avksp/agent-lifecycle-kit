"""Local task outcome indexes from lifecycle receipts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

OUTCOME_INDEX_SCHEMA = "agent-task-outcome-index.v1"
QUALITY_COST_SIGNALS_SCHEMA = "agent-quality-cost-signals.v1"
QUALITY_COST_SIGNAL_SUMMARY_SCHEMA = "agent-quality-cost-signals-summary.v1"

SUCCESS_STATUSES = {"PASS", "ACCEPTED", "READY_FOR_FINALIZATION", "STOP", "FOLLOW_UP"}
FAIL_STATUSES = {"FAIL", "BLOCK", "BLOCKED", "REJECTED"}


def build_task_outcome_index(
    artifacts: list[dict[str, Any]],
    *,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a local, rebuildable index of task outcomes from explicit receipts."""

    if not isinstance(artifacts, list):
        raise LifecycleError("invalid-outcome-index-input", "artifacts must be a list")
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    source_digests: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            blockers.append({"code": "outcome-artifact-type", "index": index})
            continue
        source_digests.append(
            {
                "index": index,
                "path": (source_paths or [None] * len(artifacts))[index] if source_paths and index < len(source_paths) else None,
                "schemaVersion": artifact.get("schemaVersion"),
                "sha256": canonical_digest(artifact),
            }
        )
        task_key = _task_key(artifact, index)
        record = records.setdefault(task_key, _empty_record(artifact, task_key))
        _merge_artifact(record, artifact)
    ordered_records = sorted(records.values(), key=lambda item: (item["packageId"], item["runId"], item["taskId"]))
    groups = _groups(ordered_records)
    body = {
        "schemaVersion": OUTCOME_INDEX_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sourceCount": len(artifacts),
        "sourceDigests": source_digests,
        "taskCount": len(ordered_records),
        "tasks": ordered_records,
        "groups": groups,
        "blockers": blockers,
        "telemetryStarted": False,
        "providerModelLeaderboard": False,
        "monetaryFieldsUsed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "indexDigest": canonical_digest(body)}


def build_quality_cost_signals(index: dict[str, Any]) -> dict[str, Any]:
    """Summarize quality/cost signals by task shape, mode, route class and profile."""

    if not isinstance(index, dict) or index.get("schemaVersion") != OUTCOME_INDEX_SCHEMA:
        raise LifecycleError("invalid-outcome-index", "agent-task-outcome-index.v1 is required")
    groups = index.get("groups")
    if not isinstance(groups, list):
        raise LifecycleError("invalid-outcome-index", "outcome index groups must be an array")
    signals = [_signal_from_group(group) for group in groups if isinstance(group, dict)]
    body = {
        "schemaVersion": QUALITY_COST_SIGNALS_SCHEMA,
        "status": "PASS" if index.get("status") == "PASS" else "FAIL",
        "outcomeIndexDigest": index.get("indexDigest") or canonical_digest(index),
        "taskCount": index.get("taskCount", 0),
        "groupCount": len(signals),
        "signals": signals,
        "blockers": list(index.get("blockers", [])),
        "advisoryOnly": True,
        "autoApply": False,
        "telemetryStarted": False,
        "providerModelLeaderboard": False,
        "monetaryFieldsUsed": False,
        "productionPromotionClaimed": False,
    }
    body["compactSummary"] = build_quality_cost_signal_summary(body)
    return {**body, "signalsDigest": canonical_digest(body)}


def build_quality_cost_signal_summary(signals: dict[str, Any]) -> dict[str, Any]:
    rows = signals.get("signals") if isinstance(signals.get("signals"), list) else []
    best = _best_signal(rows)
    body = {
        "schemaVersion": QUALITY_COST_SIGNAL_SUMMARY_SCHEMA,
        "latestUserIntent": "Use local receipt history to improve future lifecycle routing without auto-applying policy.",
        "activeDecisions": [
            f"groupCount={signals.get('groupCount', 0)}",
            f"taskCount={signals.get('taskCount', 0)}",
            f"bestTaskShape={best.get('taskShape') if best else None}",
            f"bestLifecycleMode={best.get('lifecycleMode') if best else None}",
        ],
        "openBlockers": list(signals.get("blockers", [])),
        "acceptedEvidence": [
            {
                "id": "quality-cost-signals",
                "status": signals.get("status"),
                "signalsDigest": signals.get("signalsDigest"),
            }
        ],
        "changedFiles": [],
        "nextRequiredAction": "review advisory learning signals before proposing policy changes",
        "doNotDo": [
            "Do not auto-apply learned policy changes.",
            "Do not compare provider or model names in core.",
            "Do not use USD cost as a required learning field.",
        ],
        "topSignals": rows[:8],
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def summarize_audit_quality(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize quality outcomes from the audit-optimization sample shape."""

    total = len(samples)
    successful = 0
    blockers = 0
    false_acceptances = 0
    corrections = 0
    disagreements = 0
    retries = 0
    timeouts = 0
    for sample in samples:
        quality = sample.get("quality") if isinstance(sample.get("quality"), dict) else {}
        status = str(quality.get("status", "UNKNOWN"))
        if status in SUCCESS_STATUSES:
            successful += 1
        if quality.get("blocker") is True:
            blockers += 1
        if quality.get("falseAcceptance") is True:
            false_acceptances += 1
        corrections += _non_negative_value(quality.get("correctionCount"))
        disagreements += _non_negative_value(quality.get("disagreementCount"))
        attempts = sample.get("attempts") if isinstance(sample.get("attempts"), dict) else {}
        retries += _non_negative_value(attempts.get("retryCount"))
        timeouts += _non_negative_value(attempts.get("timeoutCount"))
    return {
        "sampleCount": total,
        "successCount": successful,
        "blockerCount": blockers,
        "falseAcceptanceCount": false_acceptances,
        "correctionCount": corrections,
        "disagreementCount": disagreements,
        "retryCount": retries,
        "timeoutCount": timeouts,
        "successRate": _rate(successful, total),
        "blockerRate": _rate(blockers, total),
        "falseAcceptanceRate": _rate(false_acceptances, total),
        "correctionRate": _rate(corrections, total),
        "disagreementRate": _rate(disagreements, total),
        "retryRate": _rate(retries, total),
        "timeoutRate": _rate(timeouts, total),
    }


def _task_key(artifact: dict[str, Any], index: int) -> tuple[str, str, str]:
    run_id = _string_at(artifact, "runId") or _string_at(artifact, "lineage.runId") or "run-unknown"
    package_id = _string_at(artifact, "packageId") or _string_at(artifact, "lineage.packageId") or "package-unknown"
    task_id = _string_at(artifact, "taskId") or _string_at(artifact, "task.id") or _string_at(artifact, "task") or f"task-{index}"
    return run_id, package_id, task_id


def _empty_record(artifact: dict[str, Any], key: tuple[str, str, str]) -> dict[str, Any]:
    run_id, package_id, task_id = key
    return {
        "runId": run_id,
        "packageId": package_id,
        "taskId": task_id,
        "taskShape": _string_at(artifact, "taskShape") or _shape_from_artifact(artifact),
        "lifecycleMode": _string_at(artifact, "lifecycleMode") or _string_at(artifact, "mode") or "standard",
        "routeClass": _string_at(artifact, "routeClass") or _string_at(artifact, "modelClass") or _string_at(artifact, "modelRoute.modelClass") or "unknown",
        "profile": _string_at(artifact, "profile") or _string_at(artifact, "contextProfile") or "default",
        "attempts": 0,
        "retries": 0,
        "validationOutcome": "UNKNOWN",
        "completionOutcome": "UNKNOWN",
        "tokens": {"input": 0, "output": 0, "billable": 0, "total": 0},
        "wallSeconds": 0.0,
        "toolCalls": 0,
        "remediationLoops": 0,
        "blocker": False,
        "artifactSchemas": [],
        "artifactDigests": [],
    }


def _merge_artifact(record: dict[str, Any], artifact: dict[str, Any]) -> None:
    schema = artifact.get("schemaVersion")
    if isinstance(schema, str):
        record["artifactSchemas"].append(schema)
    record["artifactDigests"].append(canonical_digest(artifact))
    record["taskShape"] = _string_at(artifact, "taskShape") or record["taskShape"]
    record["lifecycleMode"] = _string_at(artifact, "lifecycleMode") or _string_at(artifact, "mode") or record["lifecycleMode"]
    record["routeClass"] = _string_at(artifact, "routeClass") or _string_at(artifact, "modelClass") or _string_at(artifact, "modelRoute.modelClass") or record["routeClass"]
    record["profile"] = _string_at(artifact, "profile") or _string_at(artifact, "contextProfile") or record["profile"]
    attempt = artifact.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool):
        record["attempts"] = max(record["attempts"], attempt)
        record["retries"] = max(record["retries"], max(0, attempt - 1))
    record["validationOutcome"] = _validation_outcome(record["validationOutcome"], artifact)
    record["completionOutcome"] = _completion_outcome(record["completionOutcome"], artifact)
    usage = _usage(artifact)
    record["tokens"]["input"] += usage["input"]
    record["tokens"]["output"] += usage["output"]
    record["tokens"]["billable"] += usage["billable"]
    record["tokens"]["total"] += usage["total"]
    record["wallSeconds"] += usage["wallSeconds"]
    record["toolCalls"] += usage["toolCalls"]
    record["remediationLoops"] += _int_at(artifact, "remediationLoops")
    if artifact.get("blocker") or artifact.get("status") in FAIL_STATUSES:
        record["blocker"] = True


def _groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["taskShape"], record["lifecycleMode"], record["routeClass"], record["profile"])].append(record)
    result = []
    for (task_shape, mode, route_class, profile), rows in grouped.items():
        result.append(
            {
                "taskShape": task_shape,
                "lifecycleMode": mode,
                "routeClass": route_class,
                "profile": profile,
                "sampleCount": len(rows),
                "successCount": sum(1 for item in rows if _successful(item)),
                "blockerCount": sum(1 for item in rows if item["blocker"]),
                "totalTokens": sum(item["tokens"]["total"] for item in rows),
                "totalWallSeconds": round(sum(float(item["wallSeconds"]) for item in rows), 6),
                "totalToolCalls": sum(int(item["toolCalls"]) for item in rows),
                "totalRetries": sum(int(item["retries"]) for item in rows),
                "totalRemediationLoops": sum(int(item["remediationLoops"]) for item in rows),
                "taskIds": sorted(item["taskId"] for item in rows),
            }
        )
    return sorted(result, key=lambda item: (item["taskShape"], item["lifecycleMode"], item["routeClass"], item["profile"]))


def _signal_from_group(group: dict[str, Any]) -> dict[str, Any]:
    samples = int(group.get("sampleCount", 0))
    success = int(group.get("successCount", 0))
    blockers = int(group.get("blockerCount", 0))
    return {
        "taskShape": group.get("taskShape"),
        "lifecycleMode": group.get("lifecycleMode"),
        "routeClass": group.get("routeClass"),
        "profile": group.get("profile"),
        "sampleCount": samples,
        "successRate": _rate(success, samples),
        "blockerRate": _rate(blockers, samples),
        "averageTokens": _average(int(group.get("totalTokens", 0)), samples),
        "averageWallSeconds": _average_float(float(group.get("totalWallSeconds", 0.0)), samples),
        "averageToolCalls": _average(int(group.get("totalToolCalls", 0)), samples),
        "averageRetries": _average(int(group.get("totalRetries", 0)), samples),
        "averageRemediationLoops": _average(int(group.get("totalRemediationLoops", 0)), samples),
        "taskIds": list(group.get("taskIds", [])),
    }


def _best_signal(rows: list[Any]) -> dict[str, Any] | None:
    candidates = [item for item in rows if isinstance(item, dict)]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (-float(item.get("successRate", 0.0)), float(item.get("averageTokens", 0.0)), -int(item.get("sampleCount", 0))))


def _successful(record: dict[str, Any]) -> bool:
    return record["completionOutcome"] in SUCCESS_STATUSES or record["validationOutcome"] in SUCCESS_STATUSES


def _validation_outcome(current: str, artifact: dict[str, Any]) -> str:
    commands = artifact.get("commands")
    if isinstance(commands, list) and commands:
        exit_codes = [item.get("exitCode") for item in commands if isinstance(item, dict)]
        if exit_codes and all(code == 0 for code in exit_codes):
            return "PASS"
        if any(isinstance(code, int) and code != 0 for code in exit_codes):
            return "FAIL"
    status = artifact.get("status")
    if status in SUCCESS_STATUSES | FAIL_STATUSES:
        return str(status)
    return current


def _completion_outcome(current: str, artifact: dict[str, Any]) -> str:
    if artifact.get("schemaVersion") == "agent-completion-gate-receipt.v1":
        return str(artifact.get("decision") or current)
    semantic = artifact.get("semanticStatus")
    if semantic == "READY_FOR_FINALIZATION":
        return "READY_FOR_FINALIZATION"
    status = artifact.get("status")
    if status in SUCCESS_STATUSES | FAIL_STATUSES:
        return str(status)
    return current


def _usage(artifact: dict[str, Any]) -> dict[str, Any]:
    usage = artifact.get("usage") if isinstance(artifact.get("usage"), dict) else {}
    input_tokens = _int_from(usage, "inputTokens") + _int_at(artifact, "inputTokens")
    output_tokens = _int_from(usage, "outputTokens") + _int_at(artifact, "outputTokens")
    billable = _int_from(usage, "billableTokens") + _int_at(artifact, "billableTokens")
    total = input_tokens + output_tokens
    if not total:
        total = billable
    return {
        "input": input_tokens,
        "output": output_tokens,
        "billable": billable,
        "total": total,
        "wallSeconds": float(_int_from(usage, "wallSeconds") + _int_at(artifact, "wallSeconds")),
        "toolCalls": _int_from(usage, "toolCalls") + _int_at(artifact, "toolCalls"),
    }


def _shape_from_artifact(artifact: dict[str, Any]) -> str:
    title = " ".join(str(value).lower() for value in (artifact.get("title"), artifact.get("summary")) if isinstance(value, str))
    if "bug" in title or "fix" in title:
        return "small-fix"
    if "adapter" in title:
        return "adapter"
    return "feature"


def _string_at(payload: dict[str, Any], path: str) -> str | None:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) and value else None


def _int_at(payload: dict[str, Any], path: str) -> int:
    value = _value_at(payload, path)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _int_from(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _value_at(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _rate(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _average(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _average_float(value: float, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _non_negative_value(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
