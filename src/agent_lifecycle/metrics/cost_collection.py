"""Generate lifecycle cost reports from explicit local artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.metrics.costs import (
    COST_REPORT_SCHEMA,
    COST_SUMMARY_SCHEMA,
    cost_entry_totals,
    cost_ratios,
    summarize_usage_confidence,
)


def generate_lifecycle_cost_report(
    *,
    artifact_paths: list[Path],
    mode: str = "standard",
    root: Path | None = None,
) -> dict[str, Any]:
    """Generate a cost report from explicit JSON artifacts without host calls."""

    if not artifact_paths:
        raise LifecycleError("cost-report-artifacts-required", "at least one artifact path is required")
    project_root = (root or Path.cwd()).resolve()
    source_artifacts: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for index, raw_path in enumerate(artifact_paths):
        payload, source = _load_source_artifact(raw_path, project_root)
        source_artifacts.append(source)
        entries.append(_entry_from_artifact(index, source, payload))
        payloads.append(payload)

    report = {
        "schemaVersion": COST_REPORT_SCHEMA,
        "mode": mode,
        "generatedBy": "agent-lifecycle metrics cost-report",
        "sourceArtifacts": source_artifacts,
        "lineage": _lineage(source_artifacts, payloads),
        "entries": entries,
        "usageConfidence": summarize_usage_confidence(entries),
        "productionPromotionClaimed": False,
    }
    report["compactSummary"] = build_lifecycle_cost_summary(report)
    return report


def build_lifecycle_cost_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Build a small-context summary from a lifecycle cost report."""

    raw_entries = report.get("entries")
    entries: list[Any] = raw_entries if isinstance(raw_entries, list) else []
    totals = cost_entry_totals(entries)
    ratios = cost_ratios(totals)
    usage_confidence = summarize_usage_confidence(entries)
    source_paths = _source_paths(report)
    missing_usage = usage_confidence["missingEntries"]
    next_action = "review missing usage entries" if missing_usage else "continue with the selected lifecycle policy"
    return {
        "schemaVersion": COST_SUMMARY_SCHEMA,
        "mode": report.get("mode"),
        "latestUserIntent": "Keep lifecycle overhead visible without reducing task quality.",
        "activeDecisions": [
            f"pipelineTokenShare={ratios['pipelineTokenShare']}",
            f"pipelineStepShare={ratios['pipelineStepShare']}",
            f"missingUsageEntries={missing_usage}",
        ],
        "openBlockers": [],
        "acceptedEvidence": [
            {
                "id": "lifecycle-cost-report",
                "status": "generated",
                "sourceArtifactCount": len(source_paths),
            }
        ],
        "changedFiles": source_paths[:20],
        "nextRequiredAction": next_action,
        "doNotDo": [
            "Do not treat missing usage as zero.",
            "Do not reduce required validation solely to improve cost ratios.",
        ],
        "categoryTotals": totals,
        "ratios": ratios,
        "usageConfidence": usage_confidence,
        "usefulWorkTokens": totals["implementation"]["tokens"] + totals["productValidation"]["tokens"],
        "processOverheadTokens": totals["pipelineCompliance"]["tokens"] + totals["coordination"]["tokens"],
    }


def _load_source_artifact(raw_path: Path, project_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = raw_path if raw_path.is_absolute() else project_root / raw_path
    display_path = _display_path(path, project_root)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LifecycleError(
            "cost-report-artifact-unavailable",
            "cost report artifact cannot be read",
            {"path": display_path, "reason": type(exc).__name__},
        ) from exc
    payload = load_json_object(data, label=display_path)
    source = {
        "path": display_path,
        "sha256": sha256_hex(data),
        "bytes": len(data),
        "schemaVersion": payload.get("schemaVersion"),
        "payloadDigest": canonical_digest(payload),
    }
    return payload, source


def _source_paths(report: dict[str, Any]) -> list[str]:
    raw_artifacts = report.get("sourceArtifacts")
    artifacts = raw_artifacts if isinstance(raw_artifacts, list) else []
    return [item["path"] for item in artifacts if isinstance(item, dict) and isinstance(item.get("path"), str)]


def _entry_from_artifact(index: int, source: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    usage = _usage_from_payload(payload)
    entry = {
        "id": f"artifact-{index + 1}",
        "category": _classify_artifact(str(source.get("path")), payload),
        "tokens": usage["tokens"],
        "steps": usage["steps"],
        "usageConfidence": usage["confidence"],
        "sourcePath": source["path"],
        "sourceSchemaVersion": source.get("schemaVersion"),
        "sourceDigest": source["payloadDigest"],
    }
    for field in ("runId", "packageId", "taskId", "operationId", "planDigest", "sourceRevision"):
        value = payload.get(field)
        if isinstance(value, (str, int)):
            entry[field] = value
    return entry


def _usage_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    if isinstance(usage, dict):
        billable = _int_value(usage.get("billableTokens"))
        steps = _int_value(usage.get("toolCalls")) or 1
        if billable is not None:
            confidence = "ATTESTED" if _attested(payload.get("attestation")) else "ESTIMATED"
            return {"tokens": billable, "steps": max(1, steps), "confidence": confidence}
        return {"tokens": 0, "steps": 1, "confidence": "MISSING"}
    for key in ("usageTotals", "counters"):
        totals = payload.get(key)
        if not isinstance(totals, dict):
            continue
        tokens = _first_int(totals, ("reportedTokens", "billableTokens", "tokens"))
        if tokens is not None and tokens > 0:
            steps = _first_int(totals, ("toolCalls", "validationRuns", "iterations", "steps")) or 1
            return {"tokens": tokens, "steps": max(1, steps), "confidence": "ESTIMATED"}
    if payload.get("schemaVersion") == "agent-lifecycle-model-usage-receipt.v1":
        return {"tokens": 0, "steps": 1, "confidence": "MISSING"}
    if _contains_pair(payload, "usageReceiptRequired", True):
        return {"tokens": 0, "steps": 1, "confidence": "MISSING"}
    return {"tokens": _estimate_tokens(payload), "steps": 1, "confidence": "ESTIMATED"}


def _classify_artifact(path: str, payload: dict[str, Any]) -> str:
    schema = str(payload.get("schemaVersion") or "")
    if schema == "agent-lifecycle-model-usage-receipt.v1":
        return _classify_usage_receipt(payload)
    text = _classification_text(path, payload)
    if schema in {"agent-workflow-state.v3", "agent-runner-state.v1"}:
        return "coordination"
    if schema == "agent-task-result.v2":
        return "implementation"
    if any(marker in text for marker in _PRODUCT_VALIDATION_MARKERS):
        return "productValidation"
    if any(marker in text for marker in _PIPELINE_MARKERS):
        return "pipelineCompliance"
    return "implementation"


def _classify_usage_receipt(payload: dict[str, Any]) -> str:
    text = _classification_text("", payload)
    if any(marker in text for marker in _PRODUCT_VALIDATION_MARKERS):
        return "productValidation"
    if any(marker in text for marker in _PIPELINE_MARKERS):
        return "pipelineCompliance"
    return "implementation"


def _classification_text(path: str, payload: dict[str, Any]) -> str:
    return " ".join(
        str(item)
        for item in (
            path,
            payload.get("schemaVersion"),
            payload.get("operationId"),
            payload.get("modelClass"),
            payload.get("stage"),
            payload.get("role"),
            payload.get("kind"),
        )
        if item is not None
    ).lower()


_PRODUCT_VALIDATION_MARKERS = (
    "task-review",
    "quality",
    "test",
    "security-review",
    "performance-review",
    "specialist-review",
)

_PIPELINE_MARKERS = (
    "plan",
    "workflow",
    "runner",
    "gate",
    "neutrality",
    "diagnostic",
    "contract",
    "release",
    "cost",
    "final-proof",
    "handoff",
    "followup",
    "worktree",
    "completion-check",
)


def _lineage(source_artifacts: list[dict[str, Any]], payloads: list[dict[str, Any]]) -> dict[str, list[Any]]:
    values = {
        "runIds": set(),
        "packageIds": set(),
        "taskIds": set(),
        "planDigests": set(),
        "sourceRevisions": set(),
        "evidenceDigests": set(),
        "sourceArtifactDigests": {item["sha256"] for item in source_artifacts},
    }
    for payload in payloads:
        _collect_lineage_values(payload, values)
    return {key: sorted(value) for key, value in values.items()}


def _collect_lineage_values(value: Any, found: dict[str, set[Any]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "runId" and isinstance(item, str):
                found["runIds"].add(item)
            elif key == "packageId" and isinstance(item, str):
                found["packageIds"].add(item)
            elif (key == "taskId" and isinstance(item, str)) or (
                key == "id" and isinstance(item, str) and item.startswith("WS-")
            ):
                found["taskIds"].add(item)
            elif key == "planDigest" and isinstance(item, str):
                found["planDigests"].add(item)
            elif key == "sourceRevision" and isinstance(item, str):
                found["sourceRevisions"].add(item)
            elif _is_evidence_digest(key, item):
                found["evidenceDigests"].add(item)
            _collect_lineage_values(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_lineage_values(item, found)


def _is_evidence_digest(key: str, value: Any) -> bool:
    keys = {"evidenceDigest", "resultDigest", "reviewDigest", "validationDigest", "finalProofDigest", "sha256"}
    return key in keys and isinstance(value, str)


def _contains_pair(value: Any, key: str, expected: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (item_key == key and item_value == expected) or _contains_pair(item_value, key, expected)
            for item_key, item_value in value.items()
        )
    if isinstance(value, list):
        return any(_contains_pair(item, key, expected) for item in value)
    return False


def _attested(value: Any) -> bool:
    return isinstance(value, dict) and value.get("source") == "host" and value.get("status") == "ATTESTED"


def _first_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _int_value(payload.get(key))
        if value is not None:
            return value
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _estimate_tokens(value: Any) -> int:
    return max(1, (len(canonical_bytes(value)) + 3) // 4)


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name
