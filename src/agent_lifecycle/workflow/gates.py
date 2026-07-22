"""Controller gate receipt validation for workflow transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root


def validate_controller_gates(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    phase: str,
    operation_id: str,
    attempt: int,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    satisfied_gate_ids = _satisfied_gate_ids(state, task)
    for gate in _phase_gates(task, phase):
        _require_gate_dependencies(gate, satisfied_gate_ids)
        receipt_path = _receipt_path(state, task, gate, phase=phase, operation_id=operation_id, attempt=attempt)
        root = package_root(state_path, state)
        if not (root / receipt_path).exists():
            raise LifecycleError(
                "controller-gate-receipt-missing",
                "controller gate receipt is required before transition",
                {"gateId": gate.get("id"), "phase": phase, "receiptPath": receipt_path},
            )
        receipt = read_json_object(root / receipt_path, label="controller gate receipt")
        _validate_receipt(state, task, gate, receipt, phase=phase, operation_id=operation_id, attempt=attempt)
        identity = artifact_identity(root, receipt_path, receipt)
        receipts.append({
            **identity,
            "gateId": gate["id"],
            "phase": phase,
            "operationId": operation_id,
            "attempt": attempt,
        })
        satisfied_gate_ids.add(str(gate["id"]))
    return receipts


def record_gate_receipts(task: dict[str, Any], receipts: list[dict[str, Any]]) -> None:
    if not receipts:
        return
    existing = list(task.get("controllerGateReceipts", []))
    task["controllerGateReceipts"] = existing + receipts


def _phase_gates(task: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    gates = task.get("controllerGates", [])
    if not isinstance(gates, list):
        raise LifecycleError("invalid-controller-gates", "task controllerGates must be an array")
    return [gate for gate in gates if isinstance(gate, dict) and phase in gate.get("phases", [])]


def _satisfied_gate_ids(state: dict[str, Any], task: dict[str, Any]) -> set[str]:
    receipts: list[Any] = []
    receipts.extend(task.get("controllerGateReceipts", []))
    receipts.extend(state.get("controllerGateReceipts", []))
    preflight = state.get("authorizationPreflight")
    if isinstance(preflight, dict):
        receipts.extend(preflight.get("receipts", []))
    return {
        str(receipt.get("gateId"))
        for receipt in receipts
        if isinstance(receipt, dict) and isinstance(receipt.get("gateId"), str)
    }


def _require_gate_dependencies(gate: dict[str, Any], satisfied_gate_ids: set[str]) -> None:
    required = set(gate.get("dependsOnGateIds", []))
    if not required:
        return
    missing = sorted(required.difference(satisfied_gate_ids))
    if missing:
        raise LifecycleError("controller-gate-dependency-missing", "controller gate dependencies are missing", {"missing": missing})


def _receipt_path(
    state: dict[str, Any],
    task: dict[str, Any],
    gate: dict[str, Any],
    *,
    phase: str,
    operation_id: str,
    attempt: int,
) -> str:
    template = gate.get("receiptPath")
    gate_id = gate.get("id")
    if not isinstance(gate_id, str) or not gate_id:
        raise LifecycleError("invalid-controller-gate", "controller gate id is required")
    if not isinstance(template, str) or not template:
        raise LifecycleError("invalid-controller-gate", "controller gate receiptPath is required")
    values = {
        "gateId": gate_id,
        "runId": str(state.get("runId")),
        "packageId": str(state.get("packageId")),
        "taskId": str(task.get("id")),
        "attempt": str(attempt),
        "phase": phase,
        "operationId": operation_id,
        "planDigest": str(state.get("planDigest")),
        "sourceRevision": str(state.get("sourceRevision")),
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    if "{" in rendered or "}" in rendered:
        raise LifecycleError("invalid-controller-gate", "controller gate receiptPath has unresolved placeholders")
    return normalize_repo_path(rendered, label="controller gate receiptPath")


def _validate_receipt(
    state: dict[str, Any],
    task: dict[str, Any],
    gate: dict[str, Any],
    receipt: dict[str, Any],
    *,
    phase: str,
    operation_id: str,
    attempt: int,
) -> None:
    expected = {
        "schemaVersion": "agent-controller-gate-receipt.v1",
        "gateId": gate.get("id"),
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": attempt,
        "phase": phase,
        "operationId": operation_id,
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "verdict": "PASS",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("controller-gate-binding-mismatch", f"controller gate receipt {key} mismatch")
    _validate_freshness(gate, receipt)
    if gate.get("attestationRequired") is True:
        _validate_attestation(receipt)


def _validate_freshness(gate: dict[str, Any], receipt: dict[str, Any]) -> None:
    generated_at = receipt.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise LifecycleError("controller-gate-stale", "controller gate receipt generatedAt is missing")
    max_age = gate.get("maxAgeSeconds")
    if max_age is None:
        return
    if not isinstance(max_age, int) or max_age < 0:
        raise LifecycleError("invalid-controller-gate", "controller gate maxAgeSeconds must be a non-negative integer")
    timestamp = _parse_timestamp(generated_at)
    age = (datetime.now(UTC) - timestamp).total_seconds()
    if age > max_age:
        raise LifecycleError("controller-gate-stale", "controller gate receipt is stale", {"ageSeconds": int(age)})


def _validate_attestation(receipt: dict[str, Any]) -> None:
    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict):
        raise LifecycleError("controller-gate-attestation-missing", "controller gate attestation is missing")
    if attestation.get("schemaVersion") != "agent-controller-gate-attestation.v1":
        raise LifecycleError("controller-gate-attestation-invalid", "controller gate attestation schemaVersion is invalid")
    required = ("claimsDigest", "subjectDigest", "scopeDigest", "authorityDigest", "signature")
    missing = [key for key in required if not isinstance(attestation.get(key), str) or not attestation[key]]
    if missing:
        raise LifecycleError("controller-gate-attestation-invalid", "controller gate attestation is incomplete", {"missing": missing})


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("controller-gate-stale", "controller gate receipt generatedAt is invalid") from exc
    if parsed.tzinfo is None:
        raise LifecycleError("controller-gate-stale", "controller gate receipt generatedAt must include timezone")
    return parsed.astimezone(UTC)
