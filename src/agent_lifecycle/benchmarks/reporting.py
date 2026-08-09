"""Evidence-derived benchmark measurements and safe receipt rendering."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.redaction import redact_value

CONFIDENCE_LEVELS = ("ATTESTED", "ESTIMATED", "MISSING")


def build_measurements(submission: dict[str, Any], oracle_result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = submission.get("evidence") if isinstance(submission.get("evidence"), dict) else {}
    usage_export = evidence.get("usageExport") if isinstance(evidence.get("usageExport"), dict) else {}
    entries = usage_export.get("entries") if isinstance(usage_export.get("entries"), list) else []
    buckets: dict[str, dict[str, Any]] = {
        "ATTESTED": _token_bucket(),
        "ESTIMATED": _token_bucket(),
        "MISSING": {"entryCount": 0},
    }
    blockers: list[dict[str, Any]] = []
    duration_ms = 0
    duration_entries = 0
    for entry in entries:
        if not isinstance(entry, dict):
            blockers.append({"code": "benchmark-usage-entry-invalid"})
            continue
        confidence = entry.get("usageConfidence")
        if confidence not in CONFIDENCE_LEVELS:
            blockers.append({"code": "benchmark-usage-confidence-invalid"})
            continue
        buckets[confidence]["entryCount"] += 1
        if confidence != "MISSING":
            tokens = entry.get("tokens") if isinstance(entry.get("tokens"), dict) else {}
            for key in ("input", "output", "total"):
                buckets[confidence][key] += _non_negative_int(tokens.get(key))
        if _is_non_negative_int(entry.get("durationMs")):
            duration_ms += entry["durationMs"]
            duration_entries += 1
    populated = [key for key in ("ATTESTED", "ESTIMATED") if buckets[key]["entryCount"]]
    missing = buckets["MISSING"]["entryCount"]
    if len(populated) == 1 and not missing:
        headline = {"confidence": populated[0], "total": buckets[populated[0]]["total"]}
    elif populated:
        headline = {"confidence": "MIXED", "total": None}
    else:
        headline = {"confidence": "MISSING", "total": None}
    gaps = []
    if not entries:
        gaps.append("usage-export-missing")
    if missing:
        gaps.append("token-usage-missing")
    if not duration_entries:
        gaps.append("elapsed-time-missing")
    retries = _retries(evidence.get("outcomeIndex"), submission.get("taskId"))
    if retries is None:
        gaps.append("retry-count-missing")
    checks = oracle_result.get("checks") if isinstance(oracle_result.get("checks"), list) else []
    passed = sum(1 for item in checks if isinstance(item, dict) and item.get("passed") is True)
    measurements = {
        "quality": {"oraclePassed": oracle_result.get("status") == "PASS", "criteriaPassed": passed, "criteriaTotal": len(checks)},
        "tokens": {"byConfidence": buckets, "headline": headline},
        "elapsed": {"milliseconds": duration_ms if duration_entries else None, "source": "agent-usage-export.v1" if duration_entries else None},
        "retries": {"count": retries, "source": "agent-task-outcome-index.v1" if retries is not None else None},
        "measurementGaps": sorted(set(gaps)),
    }
    return measurements, blockers


def redact_evaluation_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    redacted, changed = redact_value(payload)
    assert isinstance(redacted, dict)
    return redacted, {
        "status": "APPLIED" if changed else "NOT_REQUIRED",
        "rawContentStored": False,
        "secretsStored": False,
        "localPathsStored": False,
    }


def _retries(outcome_index: Any, task_id: Any) -> int | None:
    if not isinstance(outcome_index, dict) or outcome_index.get("schemaVersion") != "agent-task-outcome-index.v1":
        return None
    records = outcome_index.get("records")
    if not isinstance(records, list):
        return None
    values = [item.get("retries") for item in records if isinstance(item, dict) and item.get("taskId") == task_id]
    valid = [item for item in values if _is_non_negative_int(item)]
    return sum(valid) if valid else None


def _token_bucket() -> dict[str, int]:
    return {"entryCount": 0, "input": 0, "output": 0, "total": 0}


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _non_negative_int(value: Any) -> int:
    return value if _is_non_negative_int(value) else 0
