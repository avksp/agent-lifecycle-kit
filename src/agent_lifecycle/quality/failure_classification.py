"""Neutral failure classification receipts for escalation decisions."""

from __future__ import annotations

import json
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

FAILURE_CLASSIFICATION_SCHEMA = "agent-failure-classification-receipt.v1"
FAILURE_CLASSIFICATION_VALIDATION_SCHEMA = "agent-failure-classification-validation.v1"

FAILURE_CLASSES = (
    "edge-case",
    "api-contract",
    "serialization",
    "race",
    "permission",
    "migration",
    "performance",
    "flaky-test",
    "security-bug",
    "unknown",
)
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}
HIGH_RISK_FAILURE_CLASSES = {"security-bug", "race"}
FORBIDDEN_CORE_KEYS = {
    "provider",
    "providerid",
    "providermodel",
    "providermodelhash",
    "providername",
    "modelid",
    "modelname",
}

CLASS_PATTERNS: dict[str, tuple[str, ...]] = {
    "security-bug": ("security", "vulnerability", "xss", "csrf", "sql injection", "token leak", "secret leak"),
    "race": ("race", "deadlock", "concurrent", "mutex", "thread", "lock contention", "async ordering"),
    "flaky-test": ("flaky", "intermittent", "non-deterministic", "rerun passed", "passes on retry"),
    "permission": ("permissionerror", "permission denied", "forbidden", "access denied", "unauthorized"),
    "performance": ("timeout", "latency", "slow", "performance", "oom", "out of memory", "cpu", "memory"),
    "migration": ("migration", "schema version", "database version", "alembic", "migrate"),
    "serialization": ("serialize", "deserialize", "serialization", "jsondecode", "json decode", "yaml", "encoding"),
    "api-contract": ("contract", "schema mismatch", "status code", "http ", "expected", "assertionerror"),
    "edge-case": ("none", "null", "nil", "empty", "missing", "boundary", "indexerror", "out of range"),
}


def build_failure_classification_receipt(
    *,
    failure: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    failure_fingerprint: dict[str, Any] | None = None,
    flake_signal: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
    declared_class: str | None = None,
) -> dict[str, Any]:
    """Classify a failure using neutral evidence, not provider or model names."""

    failure_body = _object(failure, "failure")
    evidence_rows = _evidence_rows(evidence, failure_body=failure_body, flake_signal=flake_signal)
    blockers = _neutrality_blockers({"failure": failure_body, "evidence": evidence_rows, "flakeSignal": flake_signal})
    selected, matched = _classify(failure_body, evidence_rows, flake_signal=flake_signal, declared_class=declared_class)
    confidence = _confidence(selected, matched, failure_fingerprint=failure_fingerprint, flake_signal=flake_signal, declared_class=declared_class)
    if declared_class is not None and declared_class not in FAILURE_CLASSES:
        blockers.append({"code": "failure-classification-declared-class-invalid", "failureClass": declared_class})
    body = {
        "schemaVersion": FAILURE_CLASSIFICATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "failureClass": selected,
        "confidence": confidence,
        "highRiskFailureClass": selected in HIGH_RISK_FAILURE_CLASSES,
        "evidence": {
            "evidenceBacked": bool(evidence_rows),
            "matchedSignals": matched,
            "evidenceCount": len(evidence_rows),
            "flakeStatus": _flake_status(flake_signal),
        },
        "failureFingerprintDigest": _optional_digest(failure_fingerprint, "fingerprintDigest"),
        "evidenceIds": _string_list(evidence_ids or [], allow_empty=True, label="evidenceIds"),
        "reasonCodes": _reason_codes(selected, confidence, matched, declared_class=declared_class),
        "providerModelNamesInCore": False,
        "productionPromotionClaimed": False,
        "blockers": blockers,
    }
    return {**body, "classificationDigest": canonical_digest(body)}


def validate_failure_classification_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-failure-classification-receipt", "failure classification receipt must be an object")
    blockers: list[dict[str, Any]] = []
    if receipt.get("schemaVersion") != FAILURE_CLASSIFICATION_SCHEMA:
        blockers.append({"code": "failure-classification-schema-invalid"})
    status = receipt.get("status")
    if status not in {"PASS", "FAIL"}:
        blockers.append({"code": "failure-classification-status-invalid", "status": status})
    failure_class = receipt.get("failureClass")
    if failure_class not in FAILURE_CLASSES:
        blockers.append({"code": "failure-classification-class-invalid", "failureClass": failure_class})
    confidence = receipt.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        blockers.append({"code": "failure-classification-confidence-invalid", "confidence": confidence})
    if failure_class == "unknown" and confidence != "LOW":
        blockers.append({"code": "failure-classification-unknown-confidence"})
    evidence = receipt.get("evidence")
    if not isinstance(evidence, dict):
        blockers.append({"code": "failure-classification-evidence-invalid"})
    else:
        if evidence.get("evidenceBacked") is not True:
            blockers.append({"code": "failure-classification-evidence-missing"})
        if not isinstance(evidence.get("matchedSignals", []), list):
            blockers.append({"code": "failure-classification-matched-signals-invalid"})
    if receipt.get("failureFingerprintDigest") is not None and not _is_digest(receipt.get("failureFingerprintDigest")):
        blockers.append({"code": "failure-classification-fingerprint-digest-invalid"})
    _check_string_list(receipt.get("evidenceIds", []), "failure-classification-evidence-ids-invalid", blockers)
    if receipt.get("providerModelNamesInCore") is not False:
        blockers.append({"code": "failure-classification-provider-model-core"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "failure-classification-production-claim"})
    embedded_blockers = receipt.get("blockers")
    if not isinstance(embedded_blockers, list) or not all(isinstance(item, dict) for item in embedded_blockers):
        blockers.append({"code": "failure-classification-blockers-invalid"})
        embedded_blockers = []
    if status == "PASS" and embedded_blockers:
        blockers.append({"code": "failure-classification-pass-with-blockers"})
    if status == "FAIL" and not embedded_blockers:
        blockers.append({"code": "failure-classification-fail-without-blockers"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "classificationDigest"})
    if receipt.get("classificationDigest") != expected_digest:
        blockers.append({"code": "failure-classification-digest-mismatch"})
    body = {
        "schemaVersion": FAILURE_CLASSIFICATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": status if isinstance(status, str) else None,
        "failureClass": failure_class if failure_class in FAILURE_CLASSES else None,
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else None,
        "blockers": blockers,
        "classificationDigest": receipt.get("classificationDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_failure_classification_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError("failure-classification-validation-failed", "failure classification did not pass", {"validation": validation})
    return validation


def _classify(
    failure: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    flake_signal: dict[str, Any] | None,
    declared_class: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    search_payload: dict[str, Any] = {"failure": failure, "evidence": evidence}
    if flake_signal is not None:
        search_payload["flakeSignal"] = flake_signal
    text = _search_text(search_payload)
    matches: list[dict[str, Any]] = []
    if _flake_status(flake_signal) == "flaky":
        matches.append({"failureClass": "flaky-test", "signal": "flake-status"})
    for failure_class, patterns in CLASS_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                matches.append({"failureClass": failure_class, "signal": pattern})
    if declared_class in FAILURE_CLASSES:
        matches.append({"failureClass": declared_class, "signal": "declared-class"})
    if not matches:
        return "unknown", []
    selected = sorted(matches, key=lambda item: (_class_priority(str(item["failureClass"])), str(item["signal"])))[0]
    return str(selected["failureClass"]), matches


def _confidence(
    selected: str,
    matches: list[dict[str, Any]],
    *,
    failure_fingerprint: dict[str, Any] | None,
    flake_signal: dict[str, Any] | None,
    declared_class: str | None,
) -> str:
    if selected == "unknown":
        return "LOW"
    if selected == "flaky-test" and _flake_status(flake_signal) == "flaky":
        return "HIGH"
    selected_matches = [item for item in matches if item.get("failureClass") == selected and item.get("signal") != "declared-class"]
    if failure_fingerprint is not None and _optional_digest(failure_fingerprint, "fingerprintDigest") is not None:
        return "HIGH"
    if len(selected_matches) >= 2:
        return "HIGH"
    if selected_matches:
        return "MEDIUM"
    return "LOW" if declared_class == selected else "MEDIUM"


def _reason_codes(selected: str, confidence: str, matches: list[dict[str, Any]], *, declared_class: str | None) -> list[str]:
    reasons = [f"failure-class-{selected}", f"confidence-{confidence.lower()}"]
    if declared_class is not None:
        reasons.append("declared-class-present")
    reasons.extend(f"signal-{item['signal']}" for item in matches[:8] if isinstance(item.get("signal"), str))
    return reasons


def _class_priority(failure_class: str) -> int:
    order = {
        "security-bug": 0,
        "race": 1,
        "flaky-test": 2,
        "permission": 3,
        "performance": 4,
        "migration": 5,
        "serialization": 6,
        "api-contract": 7,
        "edge-case": 8,
        "unknown": 9,
    }
    return order.get(failure_class, 99)


def _evidence_rows(
    evidence: list[dict[str, Any]] | None,
    *,
    failure_body: dict[str, Any],
    flake_signal: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if evidence is None:
        rows: list[dict[str, Any]] = [{"source": "failure", "fields": sorted(failure_body)}]
        if flake_signal is not None:
            rows.append({"source": "flake-signal", "status": _flake_status(flake_signal)})
        return rows
    if not isinstance(evidence, list):
        raise LifecycleError("invalid-failure-classification-receipt", "evidence must be an array")
    if any(not isinstance(item, dict) or not item for item in evidence):
        raise LifecycleError("invalid-failure-classification-receipt", "evidence items must be non-empty objects")
    return [dict(item) for item in evidence]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise LifecycleError("invalid-failure-classification-receipt", f"{label} must be a non-empty object")
    return dict(value)


def _string_list(value: Any, *, allow_empty: bool, label: str) -> list[str]:
    if not isinstance(value, list):
        raise LifecycleError("invalid-failure-classification-receipt", f"{label} must be an array")
    if not value and not allow_empty:
        raise LifecycleError("invalid-failure-classification-receipt", f"{label} must not be empty")
    if not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-failure-classification-receipt", f"{label} must contain non-empty strings")
    return list(value)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})


def _optional_digest(value: dict[str, Any] | None, key: str) -> str | None:
    if value is None:
        return None
    digest = value.get(key)
    if digest is None:
        return None
    if not _is_digest(digest):
        raise LifecycleError("invalid-failure-classification-receipt", f"{key} must be a sha256 digest")
    return str(digest)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _flake_status(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status") or value.get("flakeStatus")
    return status if status in {"stable-fail", "stable-pass", "flaky", "inconclusive"} else None


def _search_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).lower()


def _neutrality_blockers(value: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for path, _item in _walk(value):
        key = path.rsplit(".", 1)[-1]
        normalized = key.replace("_", "").replace("-", "").lower()
        if normalized in FORBIDDEN_CORE_KEYS:
            blockers.append({"code": "failure-classification-provider-model-key", "path": path})
    return blockers


def _walk(value: Any, prefix: str = "$") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            rows.append((path, item))
            rows.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_walk(item, f"{prefix}[{index}]"))
    return rows


__all__ = [
    "FAILURE_CLASSES",
    "FAILURE_CLASSIFICATION_SCHEMA",
    "HIGH_RISK_FAILURE_CLASSES",
    "build_failure_classification_receipt",
    "require_failure_classification_pass",
    "validate_failure_classification_receipt",
]
