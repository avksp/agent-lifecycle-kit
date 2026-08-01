"""Sandbox boundary receipts for runtime containment evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

SANDBOX_RECEIPT_SCHEMA = "agent-sandbox-receipt.v1"
SANDBOX_RECEIPT_VALIDATION_SCHEMA = "agent-sandbox-receipt-validation.v1"
SANDBOX_CAPABILITY_SCHEMA = "agent-sandbox-capability.v1"
SANDBOX_CAPABILITY_VALIDATION_SCHEMA = "agent-sandbox-capability-validation.v1"

BOUNDARY_NAMES = ("filesystem", "network", "process", "environment")
BOUNDARY_MODES = {"ENFORCED", "DECLARED", "HOST_DEFAULT", "UNKNOWN", "UNSUPPORTED"}
UNKNOWN_BOUNDARY_MODES = {"UNKNOWN", "UNSUPPORTED"}
ENFORCEMENT_SOURCES = {"HOST", "OS", "CONTAINER", "ADAPTER", "EXTERNAL", "UNKNOWN", "UNSUPPORTED"}
UNKNOWN_ENFORCEMENT_SOURCES = {"UNKNOWN", "UNSUPPORTED"}
SANDBOX_STATUSES = {"PASS", "FAIL", "UNKNOWN", "UNSUPPORTED"}
CAPABILITY_STATUSES = {"VERIFIED", "DECLARED", "UNKNOWN", "UNSUPPORTED"}
LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
PARTIAL_CONTAINMENT_KEY = "partialContainment"
CREDENTIAL_PROXY_KEY = "credentialProxy"
CREDENTIAL_PROXY_PLACEHOLDERS = {"<redacted>", "<credential-proxy>", "<host-local>"}
CREDENTIAL_PROXY_SOURCES = {"HOST_ENV", "HOST_CREDENTIAL_STORE", "HOST_APPROVED_ENV_FILE", "HOST_INTERACTIVE_LOGIN", "UNKNOWN"}
SENSITIVE_VALUE_MARKERS = ("BEGIN PRIVATE KEY", "sk-", "xai-", "ghp_", "not-redacted-credential")


def build_sandbox_receipt(
    *,
    lineage: dict[str, Any],
    task_id: str,
    attempt: int,
    boundaries: dict[str, Any],
    enforcement: dict[str, Any],
    verifier: dict[str, Any],
    status: str | None = None,
    evidence_ids: list[str] | None = None,
    policy_digest: str | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a portable sandbox receipt without claiming production promotion."""

    normalized_boundaries = _normalize_boundaries(boundaries, code="invalid-sandbox-receipt")
    normalized_enforcement = _normalize_enforcement(enforcement, code="invalid-sandbox-receipt")
    sandbox_status = status or _derived_sandbox_status(normalized_boundaries, normalized_enforcement, blockers or [])
    body = {
        "schemaVersion": SANDBOX_RECEIPT_SCHEMA,
        "status": _enum(sandbox_status, SANDBOX_STATUSES, label="status", code="invalid-sandbox-receipt"),
        "lineage": _lineage(lineage, code="invalid-sandbox-receipt"),
        "taskId": _required_string(task_id, label="taskId", code="invalid-sandbox-receipt"),
        "attempt": _positive_int(attempt, label="attempt", code="invalid-sandbox-receipt"),
        "boundaries": normalized_boundaries,
        "enforcement": normalized_enforcement,
        "writeScopeBoundary": _write_scope_boundary(),
        "evidenceIds": _string_list(evidence_ids or [], label="evidenceIds", code="invalid-sandbox-receipt", allow_empty=True),
        "policyDigest": _optional_digest(policy_digest, label="policyDigest", code="invalid-sandbox-receipt"),
        "blockers": list(blockers or []),
        "verifier": _verifier(verifier, code="invalid-sandbox-receipt"),
        "createdAt": _now_iso(),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_sandbox_receipt(
    receipt: dict[str, Any],
    *,
    expected_lineage: dict[str, Any] | None = None,
    task_id: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Validate receipt structure and overclaim rules without requiring PASS."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-sandbox-receipt", "sandbox receipt must be an object")
    if receipt.get("schemaVersion") != SANDBOX_RECEIPT_SCHEMA:
        blockers.append({"code": "sandbox-receipt-schema-invalid"})
    sandbox_status = receipt.get("status")
    if sandbox_status not in SANDBOX_STATUSES:
        blockers.append({"code": "sandbox-status-invalid", "status": sandbox_status})
    lineage = _checked_lineage(receipt.get("lineage"), blockers, code="sandbox-lineage")
    if expected_lineage is not None and lineage is not None:
        _compare_lineage(lineage, expected_lineage, blockers)
    actual_task_id = _checked_required_string(receipt.get("taskId"), blockers, label="taskId", code="sandbox-task-id-missing")
    if task_id is not None and actual_task_id != task_id:
        blockers.append({"code": "sandbox-task-id-mismatch", "expected": task_id, "actual": actual_task_id})
    actual_attempt = _checked_positive_int(receipt.get("attempt"), blockers, label="attempt", code="sandbox-attempt-invalid")
    if attempt is not None and actual_attempt != attempt:
        blockers.append({"code": "sandbox-attempt-mismatch", "expected": attempt, "actual": actual_attempt})
    boundaries, unknown_boundary_count = _checked_boundaries(receipt.get("boundaries"), blockers)
    enforcement = _checked_enforcement(receipt.get("enforcement"), blockers)
    partial_boundary_count = _check_partial_boundaries(boundaries, blockers)
    credential_proxy_count = _check_credential_proxy_boundaries(boundaries, enforcement, blockers)
    _check_write_scope_boundary(receipt.get("writeScopeBoundary"), blockers)
    _check_string_list(receipt.get("evidenceIds", []), "sandbox-evidence-ids", blockers, allow_empty=True)
    policy_digest = receipt.get("policyDigest")
    if policy_digest is not None:
        _check_digest(policy_digest, "sandbox-policy-digest-invalid", blockers)
    _check_object_list(receipt.get("blockers", []), "sandbox-blockers-invalid", blockers)
    _check_verifier(receipt.get("verifier"), "sandbox-verifier", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "sandbox-production-claim"})
    if sandbox_status == "PASS":
        _check_pass_not_overclaimed(boundaries, enforcement, blockers)
    expected_digest = canonical_digest(_without_digest(receipt, "receiptDigest"))
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "sandbox-receipt-digest-mismatch"})
    body = {
        "schemaVersion": SANDBOX_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sandboxStatus": sandbox_status if isinstance(sandbox_status, str) else None,
        "taskId": actual_task_id,
        "attempt": actual_attempt,
        "unknownBoundaryCount": unknown_boundary_count,
        "partialBoundaryCount": partial_boundary_count,
        "credentialProxyCount": credential_proxy_count,
        "credentialProxyRedacted": not _has_credential_proxy_redaction_blocker(blockers),
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_sandbox_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a caller requires proven sandbox containment."""

    if validation.get("status") != "PASS" or validation.get("sandboxStatus") != "PASS":
        raise LifecycleError("sandbox-validation-failed", "required sandbox receipt did not pass", {"validation": validation})
    return validation


def build_unknown_sandbox_capability(*, notes: list[str] | None = None) -> dict[str, Any]:
    """Build an explicit unknown adapter sandbox capability declaration."""

    boundary = {"mode": "UNKNOWN", "evidenceIds": [], "details": {}}
    return {
        "schemaVersion": SANDBOX_CAPABILITY_SCHEMA,
        "status": "UNKNOWN",
        "boundaries": {name: dict(boundary) for name in BOUNDARY_NAMES},
        "enforcement": {"source": "UNKNOWN", "verified": False, "evidenceIds": [], "details": {}},
        "writeScopeBoundary": _write_scope_boundary(),
        "verified": False,
        "evidenceIds": [],
        "notes": list(notes or ["Sandbox support is not live-verified; host-specific containment is unknown."]),
        "productionPromotionClaimed": False,
    }


def build_partial_process_boundary(
    *,
    evidence_ids: list[str],
    covered: list[str],
    limitations: list[str],
    platforms: list[str] | None = None,
    summary: str = "Process containment is partially enforced by the host.",
) -> dict[str, Any]:
    """Build a process boundary that is explicit about partial containment."""

    return {
        "mode": "DECLARED",
        "summary": summary,
        "evidenceIds": _string_list(evidence_ids, label="boundary.evidenceIds", code="invalid-sandbox-receipt", allow_empty=False),
        "details": {
            PARTIAL_CONTAINMENT_KEY: {
                "status": "PARTIAL",
                "covered": _string_list(covered, label="partialContainment.covered", code="invalid-sandbox-receipt", allow_empty=False),
                "limitations": _string_list(
                    limitations,
                    label="partialContainment.limitations",
                    code="invalid-sandbox-receipt",
                    allow_empty=False,
                ),
                "platforms": _string_list(
                    platforms or [],
                    label="partialContainment.platforms",
                    code="invalid-sandbox-receipt",
                    allow_empty=True,
                ),
            }
        },
    }


def build_credential_proxy_details(
    *,
    source: str,
    attachment: str,
    egress_boundary: str,
    allowed_env_names: list[str] | None = None,
    sandbox_credential_value: str = "<credential-proxy>",
) -> dict[str, Any]:
    """Build redacted credential-proxy details for a sandbox boundary."""

    return {
        CREDENTIAL_PROXY_KEY: {
            "source": _enum(source, CREDENTIAL_PROXY_SOURCES, label="credentialProxy.source", code="invalid-sandbox-receipt"),
            "attachment": _required_string(attachment, label="credentialProxy.attachment", code="invalid-sandbox-receipt"),
            "egressBoundary": _required_string(egress_boundary, label="credentialProxy.egressBoundary", code="invalid-sandbox-receipt"),
            "allowedEnvNames": _string_list(
                allowed_env_names or [],
                label="credentialProxy.allowedEnvNames",
                code="invalid-sandbox-receipt",
                allow_empty=True,
            ),
            "sandboxCredentialValue": _enum(
                sandbox_credential_value,
                CREDENTIAL_PROXY_PLACEHOLDERS,
                label="credentialProxy.sandboxCredentialValue",
                code="invalid-sandbox-receipt",
            ),
            "secretValueStoredInReceipt": False,
        }
    }


def validate_sandbox_capability(capability: dict[str, Any]) -> dict[str, Any]:
    """Validate an adapter sandbox capability declaration without requiring verification."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(capability, dict):
        raise LifecycleError("invalid-sandbox-capability", "sandbox capability must be an object")
    if capability.get("schemaVersion") != SANDBOX_CAPABILITY_SCHEMA:
        blockers.append({"code": "sandbox-capability-schema-invalid"})
    sandbox_status = capability.get("status")
    if sandbox_status not in CAPABILITY_STATUSES:
        blockers.append({"code": "sandbox-capability-status-invalid", "status": sandbox_status})
    boundaries, unknown_boundary_count = _checked_boundaries(capability.get("boundaries"), blockers)
    enforcement = _checked_enforcement(capability.get("enforcement"), blockers)
    partial_boundary_count = _check_partial_boundaries(boundaries, blockers)
    credential_proxy_count = _check_credential_proxy_boundaries(boundaries, enforcement, blockers)
    _check_write_scope_boundary(capability.get("writeScopeBoundary"), blockers)
    if not isinstance(capability.get("verified"), bool):
        blockers.append({"code": "sandbox-capability-verified-invalid"})
    _check_string_list(capability.get("evidenceIds", []), "sandbox-capability-evidence-ids", blockers, allow_empty=True)
    notes = capability.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(item, str) and item for item in notes):
        blockers.append({"code": "sandbox-capability-notes-invalid"})
    if capability.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "sandbox-capability-production-claim"})
    if sandbox_status in {"VERIFIED", "DECLARED"}:
        _check_capability_not_overclaimed(boundaries, enforcement, capability, blockers)
    body = {
        "schemaVersion": SANDBOX_CAPABILITY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sandboxStatus": sandbox_status if isinstance(sandbox_status, str) else None,
        "unknownBoundaryCount": unknown_boundary_count,
        "partialBoundaryCount": partial_boundary_count,
        "credentialProxyCount": credential_proxy_count,
        "credentialProxyRedacted": not _has_credential_proxy_redaction_blocker(blockers),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _normalize_boundaries(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "sandbox boundaries must be an object")
    result: dict[str, Any] = {}
    for name in BOUNDARY_NAMES:
        boundary = value.get(name)
        if not isinstance(boundary, dict):
            raise LifecycleError(code, f"sandbox boundary {name} is required")
        result[name] = _normalize_boundary(boundary, code=code)
    return result


def _normalize_boundary(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    mode = _enum(value.get("mode"), BOUNDARY_MODES, label="boundary.mode", code=code)
    return {
        "mode": mode,
        "summary": _optional_string(value.get("summary")),
        "evidenceIds": _string_list(value.get("evidenceIds", []), label="boundary.evidenceIds", code=code, allow_empty=True),
        "details": _optional_object(value.get("details")),
    }


def _normalize_enforcement(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "sandbox enforcement must be an object")
    return {
        "source": _enum(value.get("source"), ENFORCEMENT_SOURCES, label="enforcement.source", code=code),
        "verified": _required_bool(value.get("verified"), label="enforcement.verified", code=code),
        "evidenceIds": _string_list(value.get("evidenceIds", []), label="enforcement.evidenceIds", code=code, allow_empty=True),
        "details": _optional_object(value.get("details")),
    }


def _derived_sandbox_status(
    boundaries: dict[str, Any],
    enforcement: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> str:
    if blockers:
        return "FAIL"
    if any(boundary.get("mode") == "UNSUPPORTED" for boundary in boundaries.values()) or enforcement.get("source") == "UNSUPPORTED":
        return "UNSUPPORTED"
    if any(boundary.get("mode") == "UNKNOWN" for boundary in boundaries.values()):
        return "UNKNOWN"
    if any(_boundary_is_partial(boundary) for boundary in boundaries.values()):
        return "UNKNOWN"
    if enforcement.get("source") == "UNKNOWN" or enforcement.get("verified") is not True:
        return "UNKNOWN"
    return "PASS"


def _checked_boundaries(value: Any, blockers: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    if not isinstance(value, dict):
        blockers.append({"code": "sandbox-boundaries-missing"})
        return {}, len(BOUNDARY_NAMES)
    result: dict[str, Any] = {}
    unknown_count = 0
    for name in BOUNDARY_NAMES:
        boundary = value.get(name)
        if not isinstance(boundary, dict):
            blockers.append({"code": "sandbox-boundary-missing", "boundary": name})
            unknown_count += 1
            continue
        mode = boundary.get("mode")
        if mode not in BOUNDARY_MODES:
            blockers.append({"code": "sandbox-boundary-mode-invalid", "boundary": name, "mode": mode})
        elif mode in UNKNOWN_BOUNDARY_MODES:
            unknown_count += 1
        _check_string_list(boundary.get("evidenceIds", []), f"sandbox-boundary-{name}-evidence-ids", blockers, allow_empty=True)
        details = boundary.get("details", {})
        if details is not None and not isinstance(details, dict):
            blockers.append({"code": "sandbox-boundary-details-invalid", "boundary": name})
        result[name] = boundary
    return result, unknown_count


def _checked_enforcement(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append({"code": "sandbox-enforcement-missing"})
        return {}
    source = value.get("source")
    if source not in ENFORCEMENT_SOURCES:
        blockers.append({"code": "sandbox-enforcement-source-invalid", "source": source})
    if not isinstance(value.get("verified"), bool):
        blockers.append({"code": "sandbox-enforcement-verified-invalid"})
    _check_string_list(value.get("evidenceIds", []), "sandbox-enforcement-evidence-ids", blockers, allow_empty=True)
    details = value.get("details", {})
    if details is not None and not isinstance(details, dict):
        blockers.append({"code": "sandbox-enforcement-details-invalid"})
    return value


def _check_pass_not_overclaimed(
    boundaries: dict[str, Any],
    enforcement: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    for name, boundary in boundaries.items():
        if boundary.get("mode") in UNKNOWN_BOUNDARY_MODES:
            blockers.append({"code": "sandbox-pass-overclaims-unknown-boundary", "boundary": name})
        if _boundary_is_partial(boundary):
            blockers.append({"code": "sandbox-pass-overclaims-partial-boundary", "boundary": name})
    if enforcement.get("source") in UNKNOWN_ENFORCEMENT_SOURCES:
        blockers.append({"code": "sandbox-pass-overclaims-enforcement-source", "source": enforcement.get("source")})
    if enforcement.get("verified") is not True:
        blockers.append({"code": "sandbox-pass-overclaims-unverified-enforcement"})


def _check_partial_boundaries(boundaries: dict[str, Any], blockers: list[dict[str, Any]]) -> int:
    count = 0
    for name, boundary in boundaries.items():
        details = boundary.get("details") if isinstance(boundary, dict) else None
        if not isinstance(details, dict) or PARTIAL_CONTAINMENT_KEY not in details:
            continue
        count += 1
        partial = details.get(PARTIAL_CONTAINMENT_KEY)
        if not isinstance(partial, dict):
            blockers.append({"code": "sandbox-partial-containment-invalid", "boundary": name})
            continue
        if partial.get("status") != "PARTIAL":
            blockers.append({"code": "sandbox-partial-containment-status-invalid", "boundary": name})
        _check_string_list(partial.get("covered"), "sandbox-partial-containment-covered-invalid", blockers, allow_empty=False)
        _check_string_list(partial.get("limitations"), "sandbox-partial-containment-limitations-invalid", blockers, allow_empty=False)
        if "platforms" in partial:
            _check_string_list(partial.get("platforms"), "sandbox-partial-containment-platforms-invalid", blockers, allow_empty=True)
    return count


def _check_credential_proxy_boundaries(
    boundaries: dict[str, Any],
    enforcement: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> int:
    details_items = [
        (f"boundary:{name}", boundary.get("details"))
        for name, boundary in boundaries.items()
        if isinstance(boundary, dict)
    ]
    details_items.append(("enforcement", enforcement.get("details") if isinstance(enforcement, dict) else None))
    count = 0
    for location, details in details_items:
        if not isinstance(details, dict) or CREDENTIAL_PROXY_KEY not in details:
            continue
        count += 1
        proxy = details.get(CREDENTIAL_PROXY_KEY)
        if not isinstance(proxy, dict):
            blockers.append({"code": "sandbox-credential-proxy-invalid", "location": location})
            continue
        if proxy.get("source") not in CREDENTIAL_PROXY_SOURCES:
            blockers.append({"code": "sandbox-credential-proxy-source-invalid", "location": location})
        for field in ("attachment", "egressBoundary"):
            if not isinstance(proxy.get(field), str) or not proxy[field]:
                blockers.append({"code": "sandbox-credential-proxy-field-missing", "location": location, "field": field})
        if proxy.get("sandboxCredentialValue") not in CREDENTIAL_PROXY_PLACEHOLDERS:
            blockers.append({"code": "sandbox-credential-proxy-placeholder-invalid", "location": location})
        if proxy.get("secretValueStoredInReceipt") is not False:
            blockers.append({"code": "sandbox-credential-proxy-secret-stored", "location": location})
        _check_string_list(proxy.get("allowedEnvNames", []), "sandbox-credential-proxy-env-names-invalid", blockers, allow_empty=True)
        if _contains_secret_value(proxy):
            blockers.append({"code": "sandbox-credential-proxy-secret-value", "location": location})
    return count


def _boundary_is_partial(boundary: dict[str, Any]) -> bool:
    details = boundary.get("details") if isinstance(boundary, dict) else None
    return isinstance(details, dict) and PARTIAL_CONTAINMENT_KEY in details


def _contains_secret_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_secret_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_value(item) for item in value)
    if not isinstance(value, str):
        return False
    if value in CREDENTIAL_PROXY_PLACEHOLDERS:
        return False
    return any(marker in value for marker in SENSITIVE_VALUE_MARKERS)


def _has_credential_proxy_redaction_blocker(blockers: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("code", "")).startswith("sandbox-credential-proxy")
        for item in blockers
        if isinstance(item, dict)
    )


def _check_capability_not_overclaimed(
    boundaries: dict[str, Any],
    enforcement: dict[str, Any],
    capability: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    _check_pass_not_overclaimed(boundaries, enforcement, blockers)
    if capability.get("verified") is not True:
        blockers.append({"code": "sandbox-capability-overclaims-verification"})


def _write_scope_boundary() -> dict[str, Any]:
    return {
        "gitWriteScopeGovernedSeparately": True,
        "osSandboxContainmentGovernedBy": "agent-sandbox-receipt.v1",
        "statement": "Git write scope limits repository paths; sandbox containment limits runtime filesystem, network, process and environment access.",
    }


def _check_write_scope_boundary(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "sandbox-write-scope-boundary-missing"})
        return
    if value.get("gitWriteScopeGovernedSeparately") is not True:
        blockers.append({"code": "sandbox-write-scope-boundary-not-separate"})
    governed_by = value.get("osSandboxContainmentGovernedBy")
    if not isinstance(governed_by, str) or not governed_by:
        blockers.append({"code": "sandbox-containment-authority-missing"})


def _lineage(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "sandbox lineage is required")
    result = {key: value.get(key) for key in LINEAGE_KEYS}
    for key, item in result.items():
        if key == "planRevision":
            _positive_int(item, label="lineage.planRevision", code=code)
        elif not isinstance(item, str) or not item:
            raise LifecycleError(code, f"sandbox lineage.{key} is required")
    return result


def _checked_lineage(value: Any, blockers: list[dict[str, Any]], *, code: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        blockers.append({"code": code, "message": "sandbox lineage is required"})
        return None
    result: dict[str, Any] = {}
    for key in LINEAGE_KEYS:
        item = value.get(key)
        result[key] = item
        if key == "planRevision":
            if not isinstance(item, int) or isinstance(item, bool) or item < 1:
                blockers.append({"code": f"{code}-plan-revision-invalid"})
        elif not isinstance(item, str) or not item:
            blockers.append({"code": f"{code}-{key}-missing"})
    return result


def _compare_lineage(actual: dict[str, Any], expected: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for key in LINEAGE_KEYS:
        if actual.get(key) != expected.get(key):
            blockers.append({"code": "sandbox-lineage-mismatch", "field": key, "expected": expected.get(key), "actual": actual.get(key)})


def _verifier(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "sandbox verifier must be an object")
    if not isinstance(value.get("tool"), str) or not value["tool"]:
        raise LifecycleError(code, "sandbox verifier.tool is required")
    return dict(value)


def _check_verifier(value: Any, label: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": f"{label}-invalid"})
        return
    if not isinstance(value.get("tool"), str) or not value["tool"]:
        blockers.append({"code": f"{label}-tool-missing"})


def _optional_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LifecycleError("invalid-sandbox-receipt", "sandbox details must be an object")
    return dict(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LifecycleError("invalid-sandbox-receipt", "sandbox summary must be a string")
    return value


def _optional_digest(value: Any, *, label: str, code: str) -> str | None:
    if value is None:
        return None
    if not _is_digest(value):
        raise LifecycleError(code, f"{label} must be a 64-character hex digest")
    return str(value)


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _object_list(value: Any, *, label: str, code: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise LifecycleError(code, f"{label} must be a list of objects")
    return [dict(item) for item in value]


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})


def _string_list(value: Any, *, label: str, code: str, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError(code, f"{label} must not be empty")
    return list(value)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})
    elif not value and not allow_empty:
        blockers.append({"code": code})


def _enum(value: Any, allowed: set[str], *, label: str, code: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is unsupported")
    return str(value)


def _required_string(value: Any, *, label: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value


def _checked_required_string(value: Any, blockers: list[dict[str, Any]], *, label: str, code: str) -> str | None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code, "field": label})
        return None
    return value


def _required_bool(value: Any, *, label: str, code: str) -> bool:
    if not isinstance(value, bool):
        raise LifecycleError(code, f"{label} must be boolean")
    return value


def _positive_int(value: Any, *, label: str, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError(code, f"{label} must be a positive integer")
    return value


def _checked_positive_int(value: Any, blockers: list[dict[str, Any]], *, label: str, code: str) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        blockers.append({"code": code, "field": label})
        return None
    return value


def _without_digest(value: dict[str, Any], digest_field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != digest_field}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
