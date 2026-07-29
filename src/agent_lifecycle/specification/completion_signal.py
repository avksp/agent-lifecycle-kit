"""Completion signal validation for terminal lifecycle decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest


def validate_completion_signal(signal: dict[str, Any], *, state: dict[str, Any]) -> dict[str, Any]:
    """Validate the final completion signal or explicit waiver."""

    if not isinstance(signal, dict):
        raise LifecycleError("completion-signal-required", "final audit requires completionSignal")
    if signal.get("schemaVersion") != "agent-completion-signal.v1":
        raise LifecycleError("invalid-completion-signal", "completionSignal schemaVersion is unsupported")
    status = signal.get("status")
    if status not in {"PASS", "WAIVED", "FAIL"}:
        raise LifecycleError("invalid-completion-signal", "completionSignal status is unsupported")
    _require_lineage(signal, state)
    evidence_ids = _string_list(signal.get("evidenceIds"), label="completionSignal.evidenceIds")
    if not evidence_ids:
        raise LifecycleError("invalid-completion-signal", "completionSignal evidenceIds are required")
    verifier = signal.get("verifier")
    if not isinstance(verifier, dict) or not isinstance(verifier.get("id"), str) or not verifier["id"]:
        raise LifecycleError("invalid-completion-signal", "completionSignal verifier.id is required")
    if status == "FAIL":
        raise LifecycleError("completion-signal-not-ready", "completionSignal status FAIL cannot finalize the run")
    waiver = signal.get("waiver")
    if status == "WAIVED":
        _validate_waiver(waiver)
    elif waiver is not None:
        raise LifecycleError("invalid-completion-signal", "completionSignal waiver is only allowed for WAIVED status")
    return {
        "schemaVersion": "agent-completion-signal-validation.v1",
        "status": "PASS",
        "signalStatus": status,
        "runId": signal.get("runId"),
        "packageId": signal.get("packageId"),
        "planRevision": signal.get("planRevision"),
        "planDigest": signal.get("planDigest"),
        "sourceRevision": signal.get("sourceRevision"),
        "evidenceIds": evidence_ids,
        "waived": status == "WAIVED",
        "signalDigest": canonical_digest(signal),
    }


def _require_lineage(signal: dict[str, Any], state: dict[str, Any]) -> None:
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    for key, value in expected.items():
        if signal.get(key) != value:
            raise LifecycleError("completion-signal-lineage-mismatch", f"completionSignal {key} mismatch")


def _validate_waiver(waiver: Any) -> None:
    if not isinstance(waiver, dict):
        raise LifecycleError("invalid-completion-signal-waiver", "WAIVED completionSignal requires waiver")
    for key in ("reason", "approvedBy"):
        if not isinstance(waiver.get(key), str) or not waiver[key]:
            raise LifecycleError("invalid-completion-signal-waiver", f"waiver.{key} is required")
    if not _string_list(waiver.get("evidenceIds"), label="waiver.evidenceIds"):
        raise LifecycleError("invalid-completion-signal-waiver", "waiver.evidenceIds are required")


def _string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-completion-signal", f"{label} must be a list of non-empty strings")
    return value
