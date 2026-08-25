"""Optional, provider-neutral security-analysis profile."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, normalize_repo_path
from agent_lifecycle.contracts.public_locators import normalize_public_locator
from agent_lifecycle.contracts.redaction import contains_local_absolute_path, redact_text
from agent_lifecycle.contracts.security_analysis_schemas import (
    SECURITY_ANALYSIS_AUDIT_SCHEMA,
    SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA,
    SECURITY_ANALYSIS_PROFILE_SCHEMA,
    SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA,
    SECURITY_CONFIDENCES,
    SECURITY_EXECUTION_GATE_SCHEMA,
    SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA,
    SECURITY_FINDING_SCHEMA,
    SECURITY_FINDING_STATUSES,
    SECURITY_FINDING_VALIDATION_SCHEMA,
    SECURITY_SEVERITIES,
    SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA,
    SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA,
)

SECURITY_ANALYSIS_PROFILE_ID = "security-analysis"
SECURITY_ANALYSIS_STAGES = (
    "threat-model",
    "finding-normalization",
    "exploitability-evidence",
    "deduplication",
    "remediation",
    "verification",
)
HIGH_SEVERITIES = {"BLOCKER", "CRITICAL", "HIGH"}
DEFAULT_SECURITY_EXECUTION_LIMITS = {
    "maxAttempts": 1,
    "maxInvocations": 1,
    "maxWallSeconds": 60,
    "maxEvidenceBytes": 262144,
}


def build_security_analysis_profile(
    *,
    implementation_audit: dict[str, Any] | None = None,
    execution_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build the disabled-by-default profile without granting authority."""

    limits = dict(DEFAULT_SECURITY_EXECUTION_LIMITS)
    if execution_limits is not None:
        limits.update(execution_limits)
    audit = dict(
        implementation_audit
        or {
            "required": True,
            "minimumSeverity": "HIGH",
            "independentVerificationRequired": True,
            "enforcedAt": "task-acceptance",
            "propagation": "manifest-to-adopted-task",
        }
    )
    body = {
        "schemaVersion": SECURITY_ANALYSIS_PROFILE_SCHEMA,
        "profileId": SECURITY_ANALYSIS_PROFILE_ID,
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "activationMode": "explicit-task-trigger",
        "stages": list(SECURITY_ANALYSIS_STAGES),
        "findingsPolicy": {
            "trustedByDefault": False,
            "authorityClaimed": False,
            "sourceRevisionRequired": True,
            "redactionRequired": True,
        },
        "executionPolicy": {
            "explicitPlanOptInRequired": True,
            "sandboxReceiptRequired": True,
            "authorizationRequired": True,
            "limits": limits,
            "liveCallsAllowedByDefault": False,
        },
        "implementationAudit": audit,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def validate_security_analysis_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-security-analysis-profile", "security-analysis profile must be an object")
    if profile.get("schemaVersion") != SECURITY_ANALYSIS_PROFILE_SCHEMA:
        blockers.append({"code": "security-analysis-profile-schema-invalid"})
    if profile.get("profileId") != SECURITY_ANALYSIS_PROFILE_ID:
        blockers.append({"code": "security-analysis-profile-id-invalid"})
    if profile.get("status") != "OPTIONAL":
        blockers.append({"code": "security-analysis-profile-status-invalid"})
    if profile.get("enabledByDefault") is not False:
        blockers.append({"code": "security-analysis-profile-default-enabled"})
    if profile.get("activationMode") != "explicit-task-trigger":
        blockers.append({"code": "security-analysis-profile-activation-invalid"})
    if profile.get("stages") != list(SECURITY_ANALYSIS_STAGES):
        blockers.append({"code": "security-analysis-profile-stages-invalid"})
    findings_policy = profile.get("findingsPolicy")
    if not isinstance(findings_policy, dict):
        blockers.append({"code": "security-analysis-profile-findings-policy-invalid"})
    else:
        for key, expected in {
            "trustedByDefault": False,
            "authorityClaimed": False,
            "sourceRevisionRequired": True,
            "redactionRequired": True,
        }.items():
            if findings_policy.get(key) is not expected:
                blockers.append({"code": "security-analysis-profile-policy-invalid", "field": key})
    execution = profile.get("executionPolicy")
    if not isinstance(execution, dict):
        blockers.append({"code": "security-analysis-profile-execution-policy-invalid"})
    else:
        for key in ("explicitPlanOptInRequired", "sandboxReceiptRequired", "authorizationRequired"):
            if execution.get(key) is not True:
                blockers.append({"code": "security-analysis-profile-execution-policy-invalid", "field": key})
        if execution.get("liveCallsAllowedByDefault") is not False:
            blockers.append({"code": "security-analysis-profile-live-calls-default"})
        _validate_limits(execution.get("limits"), blockers)
    audit = profile.get("implementationAudit")
    if not isinstance(audit, dict):
        blockers.append({"code": "security-analysis-profile-audit-policy-invalid"})
    else:
        if audit.get("required") is not True or audit.get("independentVerificationRequired") is not True:
            blockers.append({"code": "security-analysis-profile-audit-policy-invalid"})
        minimum_severity = audit.get("minimumSeverity")
        if not isinstance(minimum_severity, str) or minimum_severity.upper() not in HIGH_SEVERITIES:
            blockers.append({"code": "security-analysis-profile-audit-threshold-invalid"})
        if audit.get("enforcedAt") != "task-acceptance":
            blockers.append({"code": "security-analysis-profile-audit-boundary-invalid"})
        if audit.get("propagation") != "manifest-to-adopted-task":
            blockers.append({"code": "security-analysis-profile-audit-propagation-invalid"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "security-analysis-profile-production-claim"})
    if profile.get("profileDigest") != canonical_digest(_without(profile, "profileDigest")):
        blockers.append({"code": "security-analysis-profile-digest-mismatch"})
    body = {
        "schemaVersion": SECURITY_ANALYSIS_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileId": profile.get("profileId") if isinstance(profile.get("profileId"), str) else None,
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_security_finding(
    *,
    title: str,
    severity: str,
    confidence: str = "UNKNOWN",
    source_revision: str,
    source_lineage_digest: str,
    locations: list[dict[str, Any]] | None = None,
    description: str = "",
    finding_id: str | None = None,
    source: dict[str, Any] | None = None,
    remediation: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize one finding while keeping it explicitly untrusted."""

    if severity not in SECURITY_SEVERITIES:
        raise LifecycleError("security-analysis-severity-invalid", "unsupported security finding severity")
    if confidence not in SECURITY_CONFIDENCES:
        raise LifecycleError("security-analysis-confidence-invalid", "unsupported security finding confidence")
    clean_locations = [_sanitize_location(item) for item in (locations or [])]
    body = {
        "schemaVersion": SECURITY_FINDING_SCHEMA,
        "findingId": finding_id or "",
        "title": _safe_text(title, "security-analysis-title-required"),
        "description": _safe_text(description, "security-analysis-description-invalid", allow_empty=True),
        "severity": severity,
        "confidence": confidence,
        "status": "UNTRUSTED",
        "source": dict(source or {}),
        "sourceRevision": _required_text(source_revision, "security-analysis-source-revision-required"),
        "sourceLineageDigest": _digest(source_lineage_digest, "security-analysis-source-lineage-invalid"),
        "locations": clean_locations,
        "remediation": dict(remediation) if isinstance(remediation, dict) else None,
        "trusted": False,
        "authorityClaimed": False,
        "evidenceIds": list(evidence_ids or []),
        "productionPromotionClaimed": False,
    }
    if not body["findingId"]:
        body["findingId"] = f"SEC-{canonical_digest(body)[:16]}"
    return {**body, "findingDigest": canonical_digest(body)}


def validate_security_finding(
    finding: dict[str, Any],
    *,
    expected_source_revision: str | None = None,
    expected_source_lineage_digest: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(finding, dict):
        raise LifecycleError("invalid-security-finding", "security finding must be an object")
    if finding.get("schemaVersion") != SECURITY_FINDING_SCHEMA:
        blockers.append({"code": "security-analysis-finding-schema-invalid"})
    if not isinstance(finding.get("findingId"), str) or not finding["findingId"]:
        blockers.append({"code": "security-analysis-finding-id-invalid"})
    if finding.get("severity") not in SECURITY_SEVERITIES:
        blockers.append({"code": "security-analysis-severity-invalid"})
    if finding.get("confidence") not in SECURITY_CONFIDENCES:
        blockers.append({"code": "security-analysis-confidence-invalid"})
    if finding.get("status") not in SECURITY_FINDING_STATUSES:
        blockers.append({"code": "security-analysis-finding-status-invalid"})
    _check_text(finding.get("title"), "security-analysis-title-invalid", blockers)
    _reject_redacted_text(finding.get("title"), "security-analysis-secret-value", blockers, field="title")
    if "description" in finding:
        _reject_redacted_text(
            finding.get("description"), "security-analysis-secret-value", blockers, field="description"
        )
    _check_text(finding.get("sourceRevision"), "security-analysis-source-revision-required", blockers)
    _check_digest_value(finding.get("sourceLineageDigest"), "security-analysis-source-lineage-invalid", blockers)
    if expected_source_revision is not None and finding.get("sourceRevision") != expected_source_revision:
        blockers.append({"code": "security-analysis-source-revision-mismatch"})
    if (
        expected_source_lineage_digest is not None
        and finding.get("sourceLineageDigest") != expected_source_lineage_digest
    ):
        blockers.append({"code": "security-analysis-source-lineage-mismatch"})
    locations = finding.get("locations")
    if not isinstance(locations, list) or not all(isinstance(item, dict) for item in locations):
        blockers.append({"code": "security-analysis-locations-invalid"})
    else:
        for index, location in enumerate(locations):
            _validate_location(location, index, blockers)
    if finding.get("trusted") is not False:
        blockers.append({"code": "security-analysis-finding-trust-claim"})
    if finding.get("authorityClaimed") is not False:
        blockers.append({"code": "security-analysis-finding-authority-claim"})
    if finding.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "security-analysis-finding-production-claim"})
    expected_digest = canonical_digest(_without(finding, "findingDigest"))
    if finding.get("findingDigest") != expected_digest:
        blockers.append({"code": "security-analysis-finding-digest-mismatch"})
    body = {
        "schemaVersion": SECURITY_FINDING_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "findingId": finding.get("findingId") if isinstance(finding.get("findingId"), str) else None,
        "findingStatus": finding.get("status") if isinstance(finding.get("status"), str) else None,
        "blockers": blockers,
        "findingDigest": finding.get("findingDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_security_execution_gate_receipt(
    *,
    task: dict[str, Any],
    explicit_opt_in: bool | None = None,
    sandbox_receipt_digest: str | None = None,
    authorization_granted: bool | None = None,
    limits: dict[str, Any] | None = None,
    live_calls_started: bool = False,
) -> dict[str, Any]:
    """Record authorization prerequisites without starting execution."""

    config = task.get("securityAnalysis") if isinstance(task, dict) else None
    activated = security_analysis_activated(task)
    explicit = bool(
        explicit_opt_in if explicit_opt_in is not None else isinstance(config, dict) and config.get("explicitOptIn")
    )
    authorized = bool(
        authorization_granted if authorization_granted is not None else task.get("authorizationGranted") is True
    )
    selected_limits = dict(DEFAULT_SECURITY_EXECUTION_LIMITS)
    if isinstance(config, dict) and isinstance(config.get("limits"), dict):
        selected_limits.update(config["limits"])
    if isinstance(limits, dict):
        selected_limits.update(limits)
    blockers: list[dict[str, Any]] = []
    if activated and not explicit:
        blockers.append({"code": "security-analysis-execution-authorization-required"})
    if activated and not sandbox_receipt_digest:
        blockers.append({"code": "security-analysis-sandbox-required"})
    if activated and not authorized:
        blockers.append({"code": "security-analysis-execution-authorization-required"})
    if live_calls_started:
        blockers.append({"code": "security-analysis-live-calls-forbidden"})
    _validate_limits(selected_limits, blockers)
    status = "SKIPPED" if not activated else "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": SECURITY_EXECUTION_GATE_SCHEMA,
        "status": status,
        "taskId": task.get("id") or task.get("taskId"),
        "activated": activated,
        "explicitOptIn": explicit,
        "sandboxReceiptDigest": sandbox_receipt_digest,
        "authorizationGranted": authorized,
        "limits": selected_limits,
        "liveCallsStarted": False,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_security_execution_gate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SECURITY_EXECUTION_GATE_SCHEMA:
        blockers.append({"code": "security-analysis-execution-gate-schema-invalid"})
    if isinstance(receipt, dict):
        status = receipt.get("status")
        activated = receipt.get("activated")
        if status not in {"PASS", "FAIL", "SKIPPED"}:
            blockers.append({"code": "security-analysis-execution-gate-status-invalid"})
        if not isinstance(activated, bool):
            blockers.append({"code": "security-analysis-execution-gate-activation-invalid"})
        if not isinstance(receipt.get("explicitOptIn"), bool):
            blockers.append({"code": "security-analysis-execution-gate-opt-in-invalid"})
        if not isinstance(receipt.get("authorizationGranted"), bool):
            blockers.append({"code": "security-analysis-execution-gate-authorization-invalid"})
        if activated is True:
            if status == "SKIPPED":
                blockers.append({"code": "security-analysis-execution-gate-skipped-while-activated"})
            prerequisite_codes: list[str] = []
            if receipt.get("explicitOptIn") is not True or receipt.get("authorizationGranted") is not True:
                prerequisite_codes.append("security-analysis-execution-authorization-required")
            sandbox_digest = receipt.get("sandboxReceiptDigest")
            if sandbox_digest is None:
                prerequisite_codes.append("security-analysis-sandbox-required")
            elif not _is_digest(sandbox_digest):
                blockers.append({"code": "security-analysis-sandbox-digest-invalid"})
            recorded_codes = {item.get("code") for item in receipt.get("blockers", []) if isinstance(item, dict)}
            for code in prerequisite_codes:
                if status == "PASS" or code not in recorded_codes:
                    blockers.append({"code": code if status == "PASS" else f"{code}-not-recorded"})
        elif activated is False and status != "SKIPPED":
            blockers.append({"code": "security-analysis-execution-gate-unactivated-status-invalid"})
        if not isinstance(receipt.get("taskId"), str) or not receipt["taskId"]:
            blockers.append({"code": "security-analysis-execution-gate-task-id-invalid"})
        _validate_limits(receipt.get("limits"), blockers)
        if not isinstance(receipt.get("blockers"), list) or not all(
            isinstance(item, dict) for item in receipt.get("blockers", [])
        ):
            blockers.append({"code": "security-analysis-execution-gate-blockers-invalid"})
        if receipt.get("liveCallsStarted") is not False:
            blockers.append({"code": "security-analysis-live-calls-forbidden"})
        if receipt.get("productionPromotionClaimed") is not False:
            blockers.append({"code": "security-analysis-execution-gate-production-claim"})
        if receipt.get("receiptDigest") != canonical_digest(_without(receipt, "receiptDigest")):
            blockers.append({"code": "security-analysis-execution-gate-digest-mismatch"})
        if status == "FAIL" and not receipt.get("blockers"):
            blockers.append({"code": "security-analysis-execution-gate-fail-without-blockers"})
        if status == "PASS" and receipt.get("blockers"):
            blockers.append({"code": "security-analysis-execution-gate-pass-with-blockers"})
    body = {
        "schemaVersion": SECURITY_EXECUTION_GATE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "gateStatus": receipt.get("status") if isinstance(receipt, dict) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest") if isinstance(receipt, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def security_analysis_activated(task: dict[str, Any]) -> bool:
    if not isinstance(task, dict):
        return False
    if task.get("securityAnalysisProfile") in {SECURITY_ANALYSIS_PROFILE_ID, f"{SECURITY_ANALYSIS_PROFILE_ID}.v1"}:
        return True
    config = task.get("securityAnalysis")
    return isinstance(config, dict) and config.get("enabled") is True


def security_analysis_high_severity(task: dict[str, Any]) -> bool:
    config = task.get("securityAnalysis") if isinstance(task, dict) else None
    if isinstance(config, dict):
        severity = config.get("severity") or config.get("minimumSeverity")
        if isinstance(severity, str) and severity.upper() in HIGH_SEVERITIES:
            return True
        findings = config.get("findings")
        if isinstance(findings, list) and any(
            isinstance(item, dict)
            and isinstance(item.get("severity"), str)
            and item["severity"].upper() in HIGH_SEVERITIES
            for item in findings
        ):
            return True
    return any(
        isinstance(task.get(key), str) and task[key].upper() in HIGH_SEVERITIES
        for key in ("securitySeverity", "riskSeverity")
    )


def security_analysis_acceptance_blocker(task: dict[str, Any]) -> str:
    """Return the stable acceptance error for a required security audit."""

    if isinstance(task.get("securityAnalysis"), dict) and security_analysis_high_severity(task):
        return "security-analysis-verification-required"
    return "implementation-audit-required"


def _sanitize_location(location: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(location, dict):
        raise LifecycleError("security-analysis-location-invalid", "security finding location must be an object")
    raw = location.get("path") or location.get("uri") or location.get("artifactLocation")
    if not isinstance(raw, str) or not raw:
        raise LifecycleError("security-analysis-location-invalid", "security finding location requires path or uri")
    if contains_local_absolute_path(raw) or raw.startswith("file:"):
        raise LifecycleError("security-analysis-private-locator", "private absolute locators are not allowed")
    redacted_locator, locator_changed = redact_text(raw)
    if locator_changed and redacted_locator != raw:
        raise LifecycleError("security-analysis-secret-value", "secret-like locator values are not allowed")
    if raw.startswith(("http://", "https://")):
        normalized = normalize_public_locator(raw, label="security finding locator")
    else:
        normalized = normalize_repo_path(raw, label="security finding locator")
    result: dict[str, Any] = {"path": normalized, "redacted": False}
    for key in ("startLine", "endLine", "startColumn", "endColumn"):
        if key in location:
            result[key] = location[key]
    if isinstance(location.get("message"), str):
        result["message"], changed = redact_text(location["message"])
        result["redacted"] = changed
    return result


def _validate_location(location: dict[str, Any], index: int, blockers: list[dict[str, Any]]) -> None:
    try:
        _sanitize_location(location)
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "index": index})
        return
    message = location.get("message")
    if isinstance(message, str):
        _reject_redacted_text(message, "security-analysis-secret-value", blockers, field=f"locations[{index}].message")


def _validate_limits(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "security-analysis-limits-invalid"})
        return
    bounds = {"maxAttempts": 10, "maxInvocations": 100, "maxWallSeconds": 86400, "maxEvidenceBytes": 16 * 1024 * 1024}
    for key, maximum in bounds.items():
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= maximum:
            blockers.append({"code": "security-analysis-limit-invalid", "field": key})


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, "required text is missing")
    return value


def _safe_text(value: Any, code: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise LifecycleError(code, "security finding text is invalid")
    redacted, _changed = redact_text(value)
    return redacted


def _check_text(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code})


def _reject_redacted_text(value: Any, code: str, blockers: list[dict[str, Any]], *, field: str) -> None:
    if not isinstance(value, str):
        return
    _redacted, changed = redact_text(value)
    if changed:
        blockers.append({"code": code, "field": field})


def _digest(value: Any, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LifecycleError(code, "digest is invalid")
    return value


def _check_digest_value(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and not any(char not in "0123456789abcdef" for char in value)


def build_security_verification_assignment(
    *,
    assignment_id: str,
    run_id: str,
    task_id: str,
    attempt: int,
    plan_digest: str,
    source_revision: str,
    reviewer: dict[str, Any],
    independent_evidence_ids: list[str],
) -> dict[str, Any]:
    """Build an independent, lineage-bound verification assignment."""

    body = {
        "schemaVersion": SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA,
        "status": "READY",
        "assignmentId": _security_required(assignment_id, "assignmentId"),
        "runId": _security_required(run_id, "runId"),
        "taskId": _security_required(task_id, "taskId"),
        "attempt": _security_attempt(attempt),
        "planDigest": _security_digest(plan_digest, "planDigest"),
        "sourceRevision": _security_required(source_revision, "sourceRevision"),
        "reviewer": _security_reviewer(reviewer),
        "independentEvidenceIds": _security_ids(independent_evidence_ids),
        "productionPromotionClaimed": False,
    }
    return {**body, "assignmentDigest": canonical_digest(body)}


def validate_security_verification_assignment(
    assignment: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    implementer_identity: str | None = None,
) -> dict[str, Any]:
    """Validate verification assignment authority, independence, and lineage."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(assignment, dict) or assignment.get("schemaVersion") != SECURITY_VERIFICATION_ASSIGNMENT_SCHEMA:
        blockers.append({"code": "security-analysis-verification-assignment-schema-invalid"})
    if not isinstance(assignment, dict):
        return _security_assignment_validation(assignment, blockers)
    if assignment.get("status") not in {"READY", "PASS"}:
        blockers.append({"code": "security-analysis-verification-assignment-status-invalid"})
    for key in ("assignmentId", "runId", "taskId", "sourceRevision"):
        if not isinstance(assignment.get(key), str) or not assignment[key]:
            blockers.append({"code": "security-analysis-verification-assignment-field-invalid", "field": key})
    _security_digest_check(
        assignment.get("planDigest"), "security-analysis-verification-assignment-plan-invalid", blockers
    )
    if (
        not isinstance(assignment.get("attempt"), int)
        or isinstance(assignment.get("attempt"), bool)
        or assignment["attempt"] < 1
    ):
        blockers.append({"code": "security-analysis-verification-assignment-attempt-invalid"})
    reviewer = assignment.get("reviewer")
    if not isinstance(reviewer, dict):
        blockers.append({"code": "security-analysis-verification-assignment-reviewer-invalid"})
    else:
        if reviewer.get("independent") is not True:
            blockers.append({"code": "security-analysis-verification-not-independent"})
        if reviewer.get("producerClass") in {"implementer", "primary-implementer"}:
            blockers.append({"code": "security-analysis-verification-not-independent"})
        if not isinstance(reviewer.get("id"), str) or not reviewer["id"]:
            blockers.append({"code": "security-analysis-verification-reviewer-id-invalid"})
        if implementer_identity and reviewer.get("id") == implementer_identity:
            blockers.append({"code": "security-analysis-verification-reviewer-collision"})
    ids = assignment.get("independentEvidenceIds")
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item for item in ids):
        blockers.append({"code": "security-analysis-verification-evidence-missing"})
    if assignment.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "security-analysis-verification-production-claim"})
    if assignment.get("assignmentDigest") != canonical_digest(_without(assignment, "assignmentDigest")):
        blockers.append({"code": "security-analysis-verification-assignment-digest-mismatch"})
    expected = {
        "runId": state.get("runId") if state else None,
        "taskId": task.get("id") if task else None,
        "attempt": task.get("attempt") if task else None,
        "planDigest": state.get("planDigest") if state else None,
        "sourceRevision": state.get("sourceRevision") if state else None,
    }
    for key, value in expected.items():
        if value is not None and assignment.get(key) != value:
            blockers.append({"code": "security-analysis-verification-lineage-mismatch", "field": key})
    return _security_assignment_validation(assignment, blockers)


def build_security_analysis_audit(
    *,
    run_id: str,
    task_id: str,
    attempt: int,
    plan_digest: str,
    source_revision: str,
    auditor: dict[str, Any],
    verdict: str,
    findings: list[dict[str, Any]] | None = None,
    independent_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded security audit; no audit output grants workflow authority."""

    status = (
        "PASS"
        if verdict == "ACCEPTED"
        else "FAIL"
        if verdict in {"REWORK", "CONTRACT_CHANGE", "BLOCKED"}
        else "DISPUTED"
    )
    body = {
        "schemaVersion": SECURITY_ANALYSIS_AUDIT_SCHEMA,
        "status": status,
        "verdict": verdict,
        "runId": _security_required(run_id, "runId"),
        "taskId": _security_required(task_id, "taskId"),
        "attempt": _security_attempt(attempt),
        "planDigest": _security_digest(plan_digest, "planDigest"),
        "sourceRevision": _security_required(source_revision, "sourceRevision"),
        "auditor": dict(auditor),
        "findings": list(findings or []),
        "independentEvidenceIds": _security_ids(independent_evidence_ids or []),
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


def validate_security_analysis_audit(
    audit: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    required_assignment: dict[str, Any] | None = None,
    implementer_identity: str | None = None,
) -> dict[str, Any]:
    """Validate independent security-audit evidence without granting authority."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(audit, dict) or audit.get("schemaVersion") != SECURITY_ANALYSIS_AUDIT_SCHEMA:
        blockers.append({"code": "security-analysis-audit-schema-invalid"})
    if not isinstance(audit, dict):
        return _security_audit_validation(audit, blockers)
    if audit.get("status") not in {"PASS", "FAIL", "DISPUTED"}:
        blockers.append({"code": "security-analysis-audit-status-invalid"})
    if audit.get("verdict") not in {"ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"}:
        blockers.append({"code": "security-analysis-audit-verdict-invalid"})
    auditor = audit.get("auditor")
    if (
        not isinstance(auditor, dict)
        or auditor.get("independent") is not True
        or auditor.get("producerClass") in {"implementer", "primary-implementer"}
    ):
        blockers.append({"code": "security-analysis-verification-not-independent"})
    common = {
        "runId": state.get("runId") if state else None,
        "taskId": task.get("id") if task else None,
        "attempt": task.get("attempt") if task else None,
        "planDigest": state.get("planDigest") if state else None,
        "sourceRevision": state.get("sourceRevision") if state else None,
    }
    for key, value in common.items():
        if value is not None and audit.get(key) != value:
            blockers.append({"code": "security-analysis-audit-lineage-mismatch", "field": key})
    if implementer_identity and isinstance(auditor, dict) and auditor.get("id") == implementer_identity:
        blockers.append({"code": "security-analysis-verification-reviewer-collision"})
    ids = audit.get("independentEvidenceIds")
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item for item in ids):
        blockers.append({"code": "security-analysis-verification-evidence-missing"})
    expected_status = (
        "PASS"
        if audit.get("verdict") == "ACCEPTED"
        else "FAIL"
        if audit.get("verdict")
        in {
            "REWORK",
            "CONTRACT_CHANGE",
            "BLOCKED",
        }
        else "DISPUTED"
    )
    if audit.get("status") != expected_status:
        blockers.append({"code": "security-analysis-audit-status-verdict-mismatch"})
    if required_assignment is not None:
        assignment_validation = validate_security_verification_assignment(
            required_assignment,
            state=state,
            task=task,
            implementer_identity=implementer_identity,
        )
        if assignment_validation["status"] != "PASS":
            blockers.append(
                {"code": "security-analysis-verification-assignment-invalid", "validation": assignment_validation}
            )
        elif not set(required_assignment.get("independentEvidenceIds", [])).intersection(ids or []):
            blockers.append({"code": "security-analysis-verification-evidence-mismatch"})
        else:
            assigned_reviewer = required_assignment.get("reviewer")
            if (
                isinstance(auditor, dict)
                and isinstance(assigned_reviewer, dict)
                and auditor.get("id") != assigned_reviewer.get("id")
            ):
                blockers.append({"code": "security-analysis-verification-auditor-assignment-mismatch"})
    if audit.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "security-analysis-audit-production-claim"})
    if audit.get("auditDigest") != canonical_digest(_without(audit, "auditDigest")):
        blockers.append({"code": "security-analysis-audit-digest-mismatch"})
    if audit.get("status") == "PASS" and audit.get("verdict") != "ACCEPTED":
        blockers.append({"code": "security-analysis-audit-status-verdict-mismatch"})
    return _security_audit_validation(audit, blockers)


def _security_assignment_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": SECURITY_VERIFICATION_ASSIGNMENT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "assignmentDigest": value.get("assignmentDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _security_audit_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": SECURITY_ANALYSIS_AUDIT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "verdict": value.get("verdict") if isinstance(value, dict) else None,
        "blockers": blockers,
        "auditDigest": value.get("auditDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _security_reviewer(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("security-analysis-verification-reviewer-invalid", "reviewer must be an object")
    result = dict(value)
    result.setdefault("independent", True)
    if result.get("independent") is not True:
        raise LifecycleError("security-analysis-verification-not-independent", "reviewer must be independent")
    return result


def _security_required(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("security-analysis-audit-field-invalid", f"{label} is required")
    return value


def _security_attempt(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("security-analysis-audit-attempt-invalid", "attempt must be positive")
    return value


def _security_digest(value: Any, label: str) -> str:
    if not _is_digest(value):
        raise LifecycleError("security-analysis-audit-digest-invalid", f"{label} must be a lowercase SHA-256 digest")
    return value


def _security_digest_check(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _security_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("security-analysis-evidence-ids-invalid", "independent evidence IDs must be strings")
    return list(dict.fromkeys(value))


__all__ = [
    "DEFAULT_SECURITY_EXECUTION_LIMITS",
    "HIGH_SEVERITIES",
    "SECURITY_ANALYSIS_PROFILE_ID",
    "SECURITY_ANALYSIS_STAGES",
    "build_security_analysis_audit",
    "build_security_analysis_profile",
    "build_security_execution_gate_receipt",
    "build_security_finding",
    "build_security_verification_assignment",
    "security_analysis_acceptance_blocker",
    "security_analysis_activated",
    "security_analysis_high_severity",
    "validate_security_analysis_audit",
    "validate_security_analysis_profile",
    "validate_security_execution_gate_receipt",
    "validate_security_finding",
    "validate_security_verification_assignment",
]
