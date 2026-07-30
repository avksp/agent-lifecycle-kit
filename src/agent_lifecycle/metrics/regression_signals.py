"""Summarize lifecycle regression signals for policy decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest

REGRESSION_SCHEMA = "agent-lifecycle-regression-signals.v1"
BLOCKING_SIGNAL_TYPES = {
    "failedFinalAudit",
    "reopenedWork",
    "rollback",
    "repeatedRemediation",
}


def summarize_regression_signals(signals: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, signal in enumerate(signals or []):
        item = _normalize_signal(index, signal, blockers)
        if item is not None:
            normalized.append(item)
    blocking_signals = [
        item
        for item in normalized
        if item["count"] > 0 and (item["type"] in BLOCKING_SIGNAL_TYPES or item["severity"] in {"HIGH", "BLOCKER"})
    ]
    body = {
        "schemaVersion": REGRESSION_SCHEMA,
        "status": "FAIL" if blockers else ("BLOCK" if blocking_signals else "PASS"),
        "signalCount": len(normalized),
        "signals": normalized,
        "blockingSignals": blocking_signals,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "signalsDigest": canonical_digest(body)}


def _normalize_signal(index: int, signal: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(signal, dict):
        blockers.append({"code": "regression-signal-type", "index": index})
        return None
    signal_type = signal.get("type")
    if not isinstance(signal_type, str) or not signal_type:
        blockers.append({"code": "regression-signal-missing-type", "index": index})
        return None
    count = signal.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        blockers.append({"code": "regression-signal-count", "index": index, "type": signal_type})
        return None
    severity = signal.get("severity", "MEDIUM")
    if severity not in {"LOW", "MEDIUM", "HIGH", "BLOCKER"}:
        blockers.append({"code": "regression-signal-severity", "index": index, "type": signal_type})
        return None
    return {
        "type": signal_type,
        "count": count,
        "severity": severity,
        "source": signal.get("source"),
        "note": signal.get("note"),
    }
