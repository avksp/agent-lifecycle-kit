"""Provider-neutral contracts for bounded external verification checks."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.schema_builders import open_object_schema

EXTERNAL_CHECK_DESCRIPTOR_SCHEMA = "agent-external-check-descriptor.v1"
EXTERNAL_CHECK_INVOCATION_SCHEMA = "agent-external-check-invocation.v1"
EXTERNAL_CHECK_FINDING_SCHEMA = "agent-external-check-finding.v1"
EXTERNAL_CHECK_RESULT_SCHEMA = "agent-external-check-result.v1"
EXTERNAL_CHECK_VALIDATION_SCHEMA = "agent-external-check-validation.v1"

CHECK_STATUSES = ("PASS", "FAIL", "UNAVAILABLE", "INVALID")
INVOCATION_STATUSES = ("STARTED", "COMPLETED", "ABORTED")
SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CLEANUP_STATUSES = ("PASS", "FAIL", "UNAVAILABLE")
MAX_FINDINGS = 4096
MAX_ARG_BYTES = 4096
MAX_TEXT_BYTES = 8192
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 3600

_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TEXT = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_BYTES}
_BLOCKERS = {"type": "array", "maxItems": 128, "items": {"type": "object"}}
_SNAPSHOT = {
    "type": "object",
    "required": ["revision", "fileSetDigest"],
    "properties": {
        "revision": {"type": "string", "minLength": 1, "maxLength": 256},
        "fileSetDigest": _DIGEST,
        "workingTreeDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
    },
}

EXTERNAL_CHECK_SCHEMAS: dict[str, dict[str, Any]] = {
    EXTERNAL_CHECK_DESCRIPTOR_SCHEMA: open_object_schema(
        EXTERNAL_CHECK_DESCRIPTOR_SCHEMA,
        required=[
            "schemaVersion",
            "descriptorId",
            "checkId",
            "status",
            "toolId",
            "toolVersion",
            "executable",
            "argv",
            "workingDirectory",
            "configDigest",
            "sourceSnapshot",
            "limits",
            "environment",
            "shell",
            "secretsWritten",
            "planDigest",
            "planLockDigest",
            "authorityClaimed",
            "productionPromotionClaimed",
            "descriptorDigest",
        ],
        properties={
            "descriptorId": _TEXT,
            "checkId": _TEXT,
            "status": {"const": "FROZEN"},
            "toolId": _TEXT,
            "toolVersion": _TEXT,
            "executable": _TEXT,
            "argv": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"type": "string", "maxLength": MAX_ARG_BYTES},
            },
            "workingDirectory": {"type": ["string", "null"], "maxLength": 4096},
            "configDigest": _DIGEST,
            "sourceSnapshot": _SNAPSHOT,
            "limits": {"type": "object", "maxProperties": 8},
            "environment": {"type": "object", "maxProperties": 4},
            "shell": {"const": False},
            "secretsWritten": {"const": False},
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "descriptorDigest": _DIGEST,
        },
    ),
    EXTERNAL_CHECK_INVOCATION_SCHEMA: open_object_schema(
        EXTERNAL_CHECK_INVOCATION_SCHEMA,
        required=[
            "schemaVersion",
            "invocationId",
            "status",
            "descriptorDigest",
            "planDigest",
            "planLockDigest",
            "sourceSnapshot",
            "operationId",
            "startedAt",
            "productionPromotionClaimed",
            "invocationDigest",
        ],
        properties={
            "invocationId": _TEXT,
            "status": {"enum": list(INVOCATION_STATUSES)},
            "descriptorDigest": _DIGEST,
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "sourceSnapshot": _SNAPSHOT,
            "operationId": _TEXT,
            "startedAt": _TEXT,
            "endedAt": {"type": ["string", "null"], "maxLength": 128},
            "productionPromotionClaimed": {"const": False},
            "invocationDigest": _DIGEST,
        },
    ),
    EXTERNAL_CHECK_FINDING_SCHEMA: open_object_schema(
        EXTERNAL_CHECK_FINDING_SCHEMA,
        required=[
            "schemaVersion",
            "findingId",
            "ruleId",
            "severity",
            "message",
            "location",
            "fingerprint",
            "productionPromotionClaimed",
            "findingDigest",
        ],
        properties={
            "findingId": _TEXT,
            "ruleId": _TEXT,
            "severity": {"enum": list(SEVERITIES)},
            "message": _TEXT,
            "location": {
                "type": ["object", "null"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "line": {"type": "integer", "minimum": 1, "maximum": 1000000000},
                    "column": {"type": "integer", "minimum": 1, "maximum": 1000000000},
                    "endLine": {"type": "integer", "minimum": 1, "maximum": 1000000000},
                    "endColumn": {"type": "integer", "minimum": 1, "maximum": 1000000000},
                },
            },
            "fingerprint": _DIGEST,
            "productionPromotionClaimed": {"const": False},
            "findingDigest": _DIGEST,
        },
    ),
    EXTERNAL_CHECK_RESULT_SCHEMA: open_object_schema(
        EXTERNAL_CHECK_RESULT_SCHEMA,
        required=[
            "schemaVersion",
            "resultId",
            "status",
            "descriptorDigest",
            "invocationDigest",
            "planDigest",
            "planLockDigest",
            "toolId",
            "toolVersion",
            "configDigest",
            "sourceSnapshot",
            "findings",
            "outputDigest",
            "outputBytes",
            "complete",
            "timedOut",
            "outputTruncated",
            "processCleanupStatus",
            "exitCode",
            "blockers",
            "blockingEligible",
            "authorityClaimed",
            "productionPromotionClaimed",
            "resultDigest",
        ],
        properties={
            "resultId": _TEXT,
            "status": {"enum": list(CHECK_STATUSES)},
            "descriptorDigest": _DIGEST,
            "invocationDigest": _DIGEST,
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "toolId": _TEXT,
            "toolVersion": _TEXT,
            "configDigest": _DIGEST,
            "sourceSnapshot": _SNAPSHOT,
            "findings": {"type": "array", "maxItems": MAX_FINDINGS, "items": {"type": "object"}},
            "outputDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "outputBytes": {"type": "integer", "minimum": 0, "maximum": MAX_OUTPUT_BYTES},
            "complete": {"type": "boolean"},
            "timedOut": {"type": "boolean"},
            "outputTruncated": {"type": "boolean"},
            "processCleanupStatus": {"enum": list(CLEANUP_STATUSES)},
            "exitCode": {"type": ["integer", "null"]},
            "blockers": _BLOCKERS,
            "blockingEligible": {"type": "boolean"},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "resultDigest": _DIGEST,
        },
    ),
    EXTERNAL_CHECK_VALIDATION_SCHEMA: open_object_schema(
        EXTERNAL_CHECK_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "resultStatus",
            "blockingEligible",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "resultStatus": {"type": ["string", "null"]},
            "blockingEligible": {"type": "boolean"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_external_check_descriptor(
    *,
    descriptor_id: str,
    check_id: str,
    tool_id: str,
    tool_version: str,
    executable: str,
    argv: list[str],
    config_digest: str,
    source_snapshot: dict[str, Any],
    plan_digest: str,
    plan_lock_digest: str,
    working_directory: str | None = None,
    timeout_seconds: int = 300,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    environment_allow: list[str] | None = None,
) -> dict[str, Any]:
    """Build a frozen descriptor without granting process or release authority."""

    _require_digest(config_digest, "configDigest")
    _require_digest(plan_digest, "planDigest")
    _require_digest(plan_lock_digest, "planLockDigest")
    snapshot = _snapshot(source_snapshot)
    args = _argv(argv)
    if working_directory is not None:
        working_directory = normalize_repo_path(working_directory, label="workingDirectory")
    limits = _limits(timeout_seconds, max_output_bytes)
    environment = _environment(environment_allow or [])
    body = {
        "schemaVersion": EXTERNAL_CHECK_DESCRIPTOR_SCHEMA,
        "descriptorId": _text(descriptor_id, "descriptorId"),
        "checkId": _text(check_id, "checkId"),
        "status": "FROZEN",
        "toolId": _text(tool_id, "toolId"),
        "toolVersion": _text(tool_version, "toolVersion"),
        "executable": _text(executable, "executable"),
        "argv": args,
        "workingDirectory": working_directory,
        "configDigest": config_digest,
        "sourceSnapshot": snapshot,
        "limits": limits,
        "environment": environment,
        "shell": False,
        "secretsWritten": False,
        "planDigest": plan_digest,
        "planLockDigest": plan_lock_digest,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "descriptorDigest": canonical_digest(body)}


def validate_external_check_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(descriptor, dict):
        blockers.append({"code": "external-check-descriptor-not-object"})
        descriptor = {}
    _check_schema(descriptor, EXTERNAL_CHECK_DESCRIPTOR_SCHEMA, blockers)
    for field in ("descriptorId", "checkId", "toolId", "toolVersion", "executable"):
        _check_text(descriptor.get(field), f"external-check-descriptor-{_label(field)}-invalid", blockers)
    if descriptor.get("status") != "FROZEN":
        blockers.append({"code": "external-check-descriptor-not-frozen"})
    _check_argv(descriptor.get("argv"), blockers)
    working_directory = descriptor.get("workingDirectory")
    if working_directory is not None:
        _check_repo_path(working_directory, "external-check-descriptor-working-directory-invalid", blockers)
    _check_digest_field(descriptor.get("configDigest"), "external-check-descriptor-config-digest-invalid", blockers)
    _check_digest_field(descriptor.get("planDigest"), "external-check-descriptor-plan-digest-invalid", blockers)
    _check_digest_field(descriptor.get("planLockDigest"), "external-check-descriptor-lock-digest-invalid", blockers)
    _check_snapshot(descriptor.get("sourceSnapshot"), blockers)
    _check_limits(descriptor.get("limits"), blockers)
    _check_environment(descriptor.get("environment"), blockers)
    if descriptor.get("shell") is not False:
        blockers.append({"code": "external-check-descriptor-shell-enabled"})
    if descriptor.get("secretsWritten") is not False:
        blockers.append({"code": "external-check-descriptor-secrets-written"})
    if descriptor.get("authorityClaimed") is not False:
        blockers.append({"code": "external-check-descriptor-authority-claimed"})
    if descriptor.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "external-check-descriptor-production-claim"})
    _check_contract_digest(descriptor, "descriptorDigest", "external-check-descriptor-digest-mismatch", blockers)
    body = {
        "schemaVersion": EXTERNAL_CHECK_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "resultStatus": "FROZEN" if descriptor.get("status") == "FROZEN" else None,
        "blockingEligible": not blockers,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_external_check_invocation(
    *,
    invocation_id: str,
    operation_id: str,
    descriptor: dict[str, Any],
    started_at: str,
    status: str = "STARTED",
    ended_at: str | None = None,
) -> dict[str, Any]:
    require_external_check_pass(validate_external_check_descriptor(descriptor), "descriptor")
    if status not in INVOCATION_STATUSES:
        raise LifecycleError("invalid-external-check-invocation", "invocation status is unsupported")
    body = {
        "schemaVersion": EXTERNAL_CHECK_INVOCATION_SCHEMA,
        "invocationId": _text(invocation_id, "invocationId"),
        "status": status,
        "descriptorDigest": descriptor["descriptorDigest"],
        "planDigest": descriptor["planDigest"],
        "planLockDigest": descriptor["planLockDigest"],
        "sourceSnapshot": dict(descriptor["sourceSnapshot"]),
        "operationId": _text(operation_id, "operationId"),
        "startedAt": _text(started_at, "startedAt"),
        "endedAt": ended_at,
        "productionPromotionClaimed": False,
    }
    return {**body, "invocationDigest": canonical_digest(body)}


def validate_external_check_invocation(
    invocation: dict[str, Any], *, descriptor: dict[str, Any] | None = None
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(invocation, dict):
        blockers.append({"code": "external-check-invocation-not-object"})
        invocation = {}
    _check_schema(invocation, EXTERNAL_CHECK_INVOCATION_SCHEMA, blockers)
    _check_text(invocation.get("invocationId"), "external-check-invocation-id-invalid", blockers)
    _check_text(invocation.get("operationId"), "external-check-invocation-operation-invalid", blockers)
    if invocation.get("status") not in INVOCATION_STATUSES:
        blockers.append({"code": "external-check-invocation-status-invalid"})
    for field, code in (
        ("descriptorDigest", "external-check-invocation-descriptor-digest-invalid"),
        ("planDigest", "external-check-invocation-plan-digest-invalid"),
        ("planLockDigest", "external-check-invocation-lock-digest-invalid"),
    ):
        _check_digest_field(invocation.get(field), code, blockers)
    _check_snapshot(invocation.get("sourceSnapshot"), blockers)
    _check_text(invocation.get("startedAt"), "external-check-invocation-start-time-invalid", blockers)
    if invocation.get("endedAt") is not None:
        _check_text(invocation.get("endedAt"), "external-check-invocation-end-time-invalid", blockers)
    if invocation.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "external-check-invocation-production-claim"})
    _check_contract_digest(invocation, "invocationDigest", "external-check-invocation-digest-mismatch", blockers)
    if descriptor is not None:
        descriptor_validation = validate_external_check_descriptor(descriptor)
        if descriptor_validation["status"] != "PASS":
            blockers.append({"code": "external-check-invocation-descriptor-invalid"})
        for field in ("descriptorDigest", "planDigest", "planLockDigest", "sourceSnapshot"):
            if invocation.get(field) != descriptor.get(field):
                blockers.append({"code": "external-check-invocation-lineage-mismatch", "field": field})
    body = {
        "schemaVersion": EXTERNAL_CHECK_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "resultStatus": invocation.get("status") if isinstance(invocation.get("status"), str) else None,
        "blockingEligible": not blockers,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_external_check_finding(
    *,
    rule_id: str,
    severity: str,
    message: str,
    location: dict[str, Any] | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    rule_id = _text(rule_id, "ruleId")
    message = _text(message, "message")
    if severity not in SEVERITIES:
        raise LifecycleError("invalid-external-check-finding", "finding severity is unsupported")
    normalized_location = _location(location)
    normalized_fingerprint = fingerprint or canonical_digest(
        {"ruleId": rule_id, "location": normalized_location, "message": message}
    )
    _require_digest(normalized_fingerprint, "fingerprint")
    identity = {"ruleId": rule_id, "location": normalized_location, "fingerprint": normalized_fingerprint}
    body = {
        "schemaVersion": EXTERNAL_CHECK_FINDING_SCHEMA,
        "findingId": f"external-{canonical_digest(identity)[:32]}",
        "ruleId": rule_id,
        "severity": severity,
        "message": message,
        "location": normalized_location,
        "fingerprint": normalized_fingerprint,
        "productionPromotionClaimed": False,
    }
    return {**body, "findingDigest": canonical_digest(body)}


def validate_external_check_finding(finding: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(finding, dict):
        blockers.append({"code": "external-check-finding-not-object"})
        finding = {}
    _check_schema(finding, EXTERNAL_CHECK_FINDING_SCHEMA, blockers)
    for field in ("findingId", "ruleId", "message"):
        _check_text(finding.get(field), f"external-check-finding-{_label(field)}-invalid", blockers)
    if finding.get("severity") not in SEVERITIES:
        blockers.append({"code": "external-check-finding-severity-invalid"})
    location = finding.get("location")
    if location is not None:
        _check_location(location, blockers)
    _check_digest_field(finding.get("fingerprint"), "external-check-finding-fingerprint-invalid", blockers)
    if finding.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "external-check-finding-production-claim"})
    _check_contract_digest(finding, "findingDigest", "external-check-finding-digest-mismatch", blockers)
    body = {
        "schemaVersion": EXTERNAL_CHECK_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "resultStatus": None,
        "blockingEligible": not blockers,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_external_check_result(
    *,
    result_id: str,
    descriptor: dict[str, Any],
    invocation: dict[str, Any],
    status: str,
    findings: list[dict[str, Any]],
    output_digest: str | None,
    output_bytes: int,
    complete: bool,
    timed_out: bool,
    output_truncated: bool,
    process_cleanup_status: str,
    exit_code: int | None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    require_external_check_pass(validate_external_check_descriptor(descriptor), "descriptor")
    require_external_check_pass(validate_external_check_invocation(invocation, descriptor=descriptor), "invocation")
    if status not in CHECK_STATUSES:
        raise LifecycleError("invalid-external-check-result", "result status is unsupported")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise LifecycleError("invalid-external-check-result", "findings exceed the configured bound")
    for finding in findings:
        require_external_check_pass(validate_external_check_finding(finding), "finding")
    if output_digest is not None:
        _require_digest(output_digest, "outputDigest")
    if not isinstance(output_bytes, int) or isinstance(output_bytes, bool) or not 0 <= output_bytes <= MAX_OUTPUT_BYTES:
        raise LifecycleError("invalid-external-check-result", "outputBytes exceed the configured bound")
    if process_cleanup_status not in CLEANUP_STATUSES:
        raise LifecycleError("invalid-external-check-result", "process cleanup status is unsupported")
    result_blockers = list(blockers or [])
    eligible = (
        status == "PASS"
        and not findings
        and not result_blockers
        and complete
        and not timed_out
        and not output_truncated
        and process_cleanup_status == "PASS"
    )
    body = {
        "schemaVersion": EXTERNAL_CHECK_RESULT_SCHEMA,
        "resultId": _text(result_id, "resultId"),
        "status": status,
        "descriptorDigest": descriptor["descriptorDigest"],
        "invocationDigest": invocation["invocationDigest"],
        "planDigest": descriptor["planDigest"],
        "planLockDigest": descriptor["planLockDigest"],
        "toolId": descriptor["toolId"],
        "toolVersion": descriptor["toolVersion"],
        "configDigest": descriptor["configDigest"],
        "sourceSnapshot": dict(descriptor["sourceSnapshot"]),
        "findings": list(findings),
        "outputDigest": output_digest,
        "outputBytes": output_bytes,
        "complete": bool(complete),
        "timedOut": bool(timed_out),
        "outputTruncated": bool(output_truncated),
        "processCleanupStatus": process_cleanup_status,
        "exitCode": exit_code,
        "blockers": result_blockers,
        "blockingEligible": eligible,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}


def validate_external_check_result(
    result: dict[str, Any],
    *,
    descriptor: dict[str, Any] | None = None,
    invocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(result, dict):
        blockers.append({"code": "external-check-result-not-object"})
        result = {}
    _check_schema(result, EXTERNAL_CHECK_RESULT_SCHEMA, blockers)
    _check_text(result.get("resultId"), "external-check-result-id-invalid", blockers)
    if result.get("status") not in CHECK_STATUSES:
        blockers.append({"code": "external-check-result-status-invalid"})
    for field, code in (
        ("descriptorDigest", "external-check-result-descriptor-digest-invalid"),
        ("invocationDigest", "external-check-result-invocation-digest-invalid"),
        ("planDigest", "external-check-result-plan-digest-invalid"),
        ("planLockDigest", "external-check-result-lock-digest-invalid"),
        ("configDigest", "external-check-result-config-digest-invalid"),
    ):
        _check_digest_field(result.get(field), code, blockers)
    _check_text(result.get("toolId"), "external-check-result-tool-id-invalid", blockers)
    _check_text(result.get("toolVersion"), "external-check-result-tool-version-invalid", blockers)
    _check_snapshot(result.get("sourceSnapshot"), blockers)
    findings = result.get("findings")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        blockers.append({"code": "external-check-result-findings-invalid"})
    else:
        for index, finding in enumerate(findings):
            validation = validate_external_check_finding(finding)
            if validation["status"] != "PASS":
                blockers.append({"code": "external-check-result-finding-invalid", "index": index})
    output_digest = result.get("outputDigest")
    if output_digest is not None:
        _check_digest_field(output_digest, "external-check-result-output-digest-invalid", blockers)
    _check_non_negative_int(result.get("outputBytes"), "external-check-result-output-bytes-invalid", blockers)
    for field in ("complete", "timedOut", "outputTruncated"):
        if not isinstance(result.get(field), bool):
            blockers.append({"code": "external-check-result-flag-invalid", "field": field})
    if result.get("processCleanupStatus") not in CLEANUP_STATUSES:
        blockers.append({"code": "external-check-result-cleanup-invalid"})
    if result.get("exitCode") is not None and not isinstance(result.get("exitCode"), int):
        blockers.append({"code": "external-check-result-exit-code-invalid"})
    _check_object_list(result.get("blockers"), "external-check-result-blockers-invalid", blockers)
    if result.get("authorityClaimed") is not False:
        blockers.append({"code": "external-check-result-authority-claimed"})
    if result.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "external-check-result-production-claim"})
    if result.get("status") == "PASS" and findings:
        blockers.append({"code": "external-check-result-findings-on-pass"})
    expected_eligible = _eligible(result)
    if result.get("blockingEligible") is not expected_eligible:
        blockers.append({"code": "external-check-result-eligibility-mismatch"})
    _check_contract_digest(result, "resultDigest", "external-check-result-digest-mismatch", blockers)
    if descriptor is not None:
        descriptor_validation = validate_external_check_descriptor(descriptor)
        if descriptor_validation["status"] != "PASS":
            blockers.append({"code": "external-check-result-descriptor-invalid"})
        for field in (
            "descriptorDigest",
            "planDigest",
            "planLockDigest",
            "toolId",
            "toolVersion",
            "configDigest",
            "sourceSnapshot",
        ):
            if result.get(field) != descriptor.get(field):
                blockers.append({"code": "external-check-result-lineage-mismatch", "field": field})
    if invocation is not None:
        invocation_validation = validate_external_check_invocation(invocation, descriptor=descriptor)
        if invocation_validation["status"] != "PASS":
            blockers.append({"code": "external-check-result-invocation-invalid"})
        if result.get("invocationDigest") != invocation.get("invocationDigest"):
            blockers.append({"code": "external-check-result-invocation-lineage-mismatch"})
    body = {
        "schemaVersion": EXTERNAL_CHECK_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "resultStatus": result.get("status") if isinstance(result.get("status"), str) else None,
        "blockingEligible": result.get("blockingEligible") is True and not blockers,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_external_check_pass(validation: dict[str, Any], kind: str) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            f"external-check-{kind}-invalid", f"external check {kind} validation failed", {"validation": validation}
        )
    return validation


def _eligible(result: dict[str, Any]) -> bool:
    return bool(
        result.get("status") == "PASS"
        and not result.get("findings")
        and not result.get("blockers")
        and result.get("complete") is True
        and result.get("timedOut") is False
        and result.get("outputTruncated") is False
        and result.get("processCleanupStatus") == "PASS"
    )


def _snapshot(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-external-check-snapshot", "sourceSnapshot must be an object")
    revision = _text(value.get("revision"), "sourceSnapshot.revision")
    file_set = value.get("fileSetDigest")
    _require_digest(file_set, "sourceSnapshot.fileSetDigest")
    working_tree = value.get("workingTreeDigest")
    if working_tree is not None:
        _require_digest(working_tree, "sourceSnapshot.workingTreeDigest")
    return {"revision": revision, "fileSetDigest": file_set, "workingTreeDigest": working_tree}


def _limits(timeout_seconds: int, max_output_bytes: int) -> dict[str, Any]:
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise LifecycleError("invalid-external-check-limits", "timeoutSeconds is outside the configured bound")
    if (
        not isinstance(max_output_bytes, int)
        or isinstance(max_output_bytes, bool)
        or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES
    ):
        raise LifecycleError("invalid-external-check-limits", "maxOutputBytes is outside the configured bound")
    return {
        "timeoutSeconds": timeout_seconds,
        "maxInputBytes": 0,
        "maxOutputBytes": max_output_bytes,
        "maxProcessCount": 1,
    }


def _environment(allow: list[str]) -> dict[str, Any]:
    if not isinstance(allow, list) or not all(isinstance(item, str) and item for item in allow) or len(allow) > 64:
        raise LifecycleError("invalid-external-check-environment", "environment allow-list is invalid")
    return {"allow": sorted(set(allow)), "allowPatterns": []}


def _argv(value: list[str]) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 64
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise LifecycleError("invalid-external-check-argv", "argv must be a bounded list of strings")
    if any("\x00" in item or len(item.encode("utf-8")) > MAX_ARG_BYTES for item in value):
        raise LifecycleError("invalid-external-check-argv", "argv contains an invalid argument")
    return list(value)


def _location(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LifecycleError("invalid-external-check-location", "finding location must be an object or null")
    raw_path = value.get("path")
    if not isinstance(raw_path, str):
        raise LifecycleError("invalid-external-check-location", "finding location path is invalid")
    result: dict[str, Any] = {"path": normalize_repo_path(raw_path, label="finding.location.path")}
    for field in ("line", "column", "endLine", "endColumn"):
        item = value.get(field)
        if item is not None:
            if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 1_000_000_000:
                raise LifecycleError("invalid-external-check-location", f"finding location {field} is invalid")
            result[field] = item
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise LifecycleError("invalid-external-check-text", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LifecycleError("invalid-external-check-digest", f"{label} must be a lowercase SHA-256 digest")


def _label(field: str) -> str:
    return field.replace("Digest", "-digest").replace("Id", "-id").lower().strip("-")


def _check_schema(value: dict[str, Any], schema_id: str, blockers: list[dict[str, Any]]) -> None:
    if value.get("schemaVersion") != schema_id:
        blockers.append({"code": "external-check-schema-invalid", "expected": schema_id})


def _check_text(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        blockers.append({"code": code})


def _check_digest_field(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    try:
        _require_digest(value, code)
    except LifecycleError:
        blockers.append({"code": code})


def _check_contract_digest(value: dict[str, Any], field: str, code: str, blockers: list[dict[str, Any]]) -> None:
    expected = canonical_digest({key: item for key, item in value.items() if key != field})
    if value.get(field) != expected:
        blockers.append({"code": code})


def _check_argv(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        _argv(value)
    except LifecycleError:
        blockers.append({"code": "external-check-descriptor-argv-invalid"})


def _check_snapshot(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        _snapshot(value)
    except LifecycleError:
        blockers.append({"code": "external-check-snapshot-invalid"})


def _check_repo_path(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    try:
        normalize_repo_path(value, label=code)
    except LifecycleError:
        blockers.append({"code": code})


def _check_limits(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "external-check-limits-invalid"})
        return
    timeout = value.get("timeoutSeconds")
    output = value.get("maxOutputBytes")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        blockers.append({"code": "external-check-timeout-invalid"})
    if not isinstance(output, int) or isinstance(output, bool) or not 1 <= output <= MAX_OUTPUT_BYTES:
        blockers.append({"code": "external-check-output-limit-invalid"})
    if value.get("maxInputBytes") != 0 or value.get("maxProcessCount") != 1:
        blockers.append({"code": "external-check-process-limits-invalid"})


def _check_environment(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("allow"), list) or value.get("allowPatterns") != []:
        blockers.append({"code": "external-check-environment-invalid"})
        return
    if len(value["allow"]) > 64 or not all(isinstance(item, str) and item for item in value["allow"]):
        blockers.append({"code": "external-check-environment-invalid"})


def _check_location(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "external-check-location-invalid"})
        return
    _check_repo_path(value.get("path"), "external-check-location-path-invalid", blockers)
    for field in ("line", "column", "endLine", "endColumn"):
        item = value.get(field)
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 1_000_000_000):
            blockers.append({"code": "external-check-location-coordinate-invalid", "field": field})


def _check_non_negative_int(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or len(value) > 128 or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
