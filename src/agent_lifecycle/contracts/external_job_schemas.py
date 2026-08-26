"""Provider-neutral contracts for bounded asynchronous external-tool jobs."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.schema_builders import open_object_schema

EXTERNAL_JOB_REQUEST_SCHEMA = "agent-external-job-request.v1"
EXTERNAL_JOB_STATUS_SCHEMA = "agent-external-job-status.v1"
EXTERNAL_JOB_ARTIFACT_SCHEMA = "agent-external-job-artifact.v1"
EXTERNAL_JOB_RESULT_SCHEMA = "agent-external-job-result.v1"
EXTERNAL_JOB_VALIDATION_SCHEMA = "agent-external-job-validation.v1"
EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA = "agent-external-job-transition-validation.v1"

JOB_STATES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")
TERMINAL_JOB_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"})
JOB_VERDICTS = ("PASS", "FAIL", "NO_FINAL_VERDICT")
EXECUTION_KINDS = ("PROCESS", "NETWORK")
CLEANUP_STATUSES = ("PASS", "FAIL", "NOT_REQUIRED", "UNAVAILABLE")
MAX_CHILDREN = 64
MAX_ARTIFACTS = 128
MAX_ATTEMPTS = 1000
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_WALL_SECONDS = 24 * 60 * 60
MAX_CANCEL_GRACE_SECONDS = 60
MAX_COST_MICROS = 10**12
MAX_REPORTED_TOKENS = 10**9
MAX_TEXT_BYTES = 8192

_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TEXT = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_BYTES}
_BLOCKERS = {"type": "array", "maxItems": 128, "items": {"type": "object"}}
_LIMIT_RANGES = {
    "maxWallSeconds": (1, MAX_WALL_SECONDS), "maxAttempts": (1, MAX_ATTEMPTS),
    "maxOutputBytes": (1, MAX_OUTPUT_BYTES), "maxArtifactBytes": (1, MAX_ARTIFACT_BYTES),
    "maxArtifacts": (0, MAX_ARTIFACTS), "maxCostMicros": (0, MAX_COST_MICROS),
    "maxReportedTokens": (0, MAX_REPORTED_TOKENS), "cancelGraceSeconds": (0, MAX_CANCEL_GRACE_SECONDS),
}
_LIMITS = {
    "type": "object",
    "required": list(_LIMIT_RANGES),
    "properties": {
        key: {"type": "integer", "minimum": low, "maximum": high}
        for key, (low, high) in _LIMIT_RANGES.items()
    },
}
_USAGE_FIELDS = ("wallMilliseconds", "outputBytes", "artifactBytes", "costMicros", "reportedTokens")
_USAGE = {
    "type": "object",
    "required": list(_USAGE_FIELDS),
    "properties": {key: {"type": "integer", "minimum": 0} for key in _USAGE_FIELDS},
}
_CHILD_REF = {
    "type": "object",
    "required": ["jobId", "attempt", "requestDigest", "parentRequestDigest"],
    "properties": {
        "jobId": _TEXT, "attempt": {"type": "integer", "minimum": 1, "maximum": MAX_ATTEMPTS},
        "requestDigest": _DIGEST, "parentRequestDigest": _DIGEST,
    },
}

_REQUEST_FIELDS = [
    "schemaVersion", "jobId", "attempt", "parentJobId", "parentAttempt", "parentRequestDigest",
    "adapterId", "operation",
    "executionKind", "descriptorDigest", "planDigest", "planLockDigest", "sourceRevision",
    "sourceSnapshotDigest", "limits", "shell", "secretsWritten", "authorityClaimed",
    "productionPromotionClaimed", "requestDigest",
]
_STATUS_FIELDS = [
    "schemaVersion", "jobId", "attempt", "requestDigest", "state", "sequence", "observedAt", "startedAt",
    "endedAt", "children", "usage", "cancelRequested", "processCleanupStatus", "postTerminalWriteDetected",
    "authorityClaimed", "productionPromotionClaimed", "statusDigest",
]
_ARTIFACT_FIELDS = [
    "schemaVersion", "artifactId", "jobId", "attempt", "requestDigest", "mediaType", "bytes", "sha256",
    "locator", "sensitiveContentStored",
    "productionPromotionClaimed", "artifactDigest",
]
_RESULT_FIELDS = [
    "schemaVersion", "resultId", "jobId", "attempt", "requestDigest", "statusDigest", "state", "verdict",
    "complete", "blockingEligible", "outputDigest", "outputBytes", "artifacts", "usage", "blockers",
    "authorityClaimed", "productionPromotionClaimed", "resultDigest",
]
_VALIDATION_FIELDS = (
    "schemaVersion", "status", "subject", "subjectState", "blockingEligible", "blockers",
    "productionPromotionClaimed", "validationDigest",
)
_TRANSITION_FIELDS = (
    "schemaVersion", "status", "previousState", "nextState", "idempotent", "blockers",
    "productionPromotionClaimed", "validationDigest",
)

EXTERNAL_JOB_SCHEMAS: dict[str, dict[str, Any]] = {
    EXTERNAL_JOB_REQUEST_SCHEMA: open_object_schema(
        EXTERNAL_JOB_REQUEST_SCHEMA,
        required=list(_REQUEST_FIELDS),
        properties={
            "jobId": _TEXT, "attempt": {"type": "integer", "minimum": 1, "maximum": 1000},
            "parentJobId": {"type": ["string", "null"], "maxLength": MAX_TEXT_BYTES},
            "parentAttempt": {"type": ["integer", "null"], "minimum": 1, "maximum": MAX_ATTEMPTS},
            "parentRequestDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "adapterId": _TEXT, "operation": _TEXT,
            "executionKind": {"enum": list(EXECUTION_KINDS)}, "descriptorDigest": _DIGEST,
            "planDigest": _DIGEST, "planLockDigest": _DIGEST, "sourceRevision": _TEXT,
            "sourceSnapshotDigest": _DIGEST, "limits": _LIMITS, "shell": {"const": False},
            "secretsWritten": {"const": False}, "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "requestDigest": _DIGEST,
        },
    ),
    EXTERNAL_JOB_STATUS_SCHEMA: open_object_schema(
        EXTERNAL_JOB_STATUS_SCHEMA,
        required=list(_STATUS_FIELDS),
        properties={
            "jobId": _TEXT, "attempt": {"type": "integer", "minimum": 1, "maximum": 1000},
            "requestDigest": _DIGEST, "state": {"enum": list(JOB_STATES)},
            "sequence": {"type": "integer", "minimum": 0, "maximum": 10**9},
            "observedAt": _TEXT, "startedAt": {"type": ["string", "null"], "maxLength": MAX_TEXT_BYTES},
            "endedAt": {"type": ["string", "null"], "maxLength": MAX_TEXT_BYTES},
            "children": {"type": "array", "maxItems": MAX_CHILDREN, "items": _CHILD_REF},
            "usage": _USAGE, "cancelRequested": {"type": "boolean"},
            "processCleanupStatus": {"enum": list(CLEANUP_STATUSES)},
            "postTerminalWriteDetected": {"type": "boolean"}, "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "statusDigest": _DIGEST,
        },
    ),
    EXTERNAL_JOB_ARTIFACT_SCHEMA: open_object_schema(
        EXTERNAL_JOB_ARTIFACT_SCHEMA,
        required=list(_ARTIFACT_FIELDS),
        properties={
            "artifactId": _TEXT, "jobId": _TEXT,
            "attempt": {"type": "integer", "minimum": 1, "maximum": MAX_ATTEMPTS},
            "requestDigest": _DIGEST, "mediaType": _TEXT,
            "bytes": {"type": "integer", "minimum": 0, "maximum": MAX_ARTIFACT_BYTES},
            "sha256": _DIGEST, "locator": {"type": "string", "minLength": 1, "maxLength": 4096},
            "sensitiveContentStored": {"const": False}, "productionPromotionClaimed": {"const": False},
            "artifactDigest": _DIGEST,
        },
    ),
    EXTERNAL_JOB_RESULT_SCHEMA: open_object_schema(
        EXTERNAL_JOB_RESULT_SCHEMA,
        required=list(_RESULT_FIELDS),
        properties={
            "resultId": _TEXT, "jobId": _TEXT,
            "attempt": {"type": "integer", "minimum": 1, "maximum": 1000},
            "requestDigest": _DIGEST, "statusDigest": _DIGEST,
            "state": {"enum": sorted(TERMINAL_JOB_STATES)}, "verdict": {"enum": list(JOB_VERDICTS)},
            "complete": {"type": "boolean"}, "blockingEligible": {"type": "boolean"},
            "outputDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "outputBytes": {"type": "integer", "minimum": 0, "maximum": MAX_OUTPUT_BYTES},
            "artifacts": {"type": "array", "maxItems": MAX_ARTIFACTS, "items": {"type": "object"}},
            "usage": _USAGE, "blockers": _BLOCKERS, "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "resultDigest": _DIGEST,
        },
    ),
    EXTERNAL_JOB_VALIDATION_SCHEMA: open_object_schema(
        EXTERNAL_JOB_VALIDATION_SCHEMA,
        required=list(_VALIDATION_FIELDS),
        properties={
            "status": {"enum": ["PASS", "FAIL"]}, "subject": {"enum": ["REQUEST", "STATUS", "ARTIFACT", "RESULT"]},
            "subjectState": {"type": ["string", "null"]}, "blockingEligible": {"type": "boolean"},
            "blockers": _BLOCKERS, "productionPromotionClaimed": {"const": False}, "validationDigest": _DIGEST,
        },
    ),
    EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA: open_object_schema(
        EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA,
        required=list(_TRANSITION_FIELDS),
        properties={
            "status": {"enum": ["PASS", "FAIL"]}, "previousState": {"type": ["string", "null"]},
            "nextState": {"type": ["string", "null"]}, "idempotent": {"type": "boolean"},
            "blockers": _BLOCKERS, "productionPromotionClaimed": {"const": False}, "validationDigest": _DIGEST,
        },
    ),
}


def build_external_job_request(
    *,
    job_id: str,
    attempt: int,
    adapter_id: str,
    operation: str,
    execution_kind: str,
    descriptor_digest: str,
    plan_digest: str,
    plan_lock_digest: str,
    source_revision: str,
    source_snapshot_digest: str,
    limits: dict[str, int],
    parent_job_id: str | None = None,
    parent_attempt: int | None = None,
    parent_request_digest: str | None = None,
) -> dict[str, Any]:
    checked_attempt = _attempt(attempt, "attempt")
    checked_limits = _limits(limits)
    if checked_attempt > checked_limits["maxAttempts"]:
        raise LifecycleError("external-job-attempt-limit-exceeded", "attempt exceeds maxAttempts")
    body = {
        "schemaVersion": EXTERNAL_JOB_REQUEST_SCHEMA,
        "jobId": _identity(job_id, "jobId"),
        "attempt": checked_attempt,
        "parentJobId": _optional_identity(parent_job_id, "parentJobId"),
        "parentAttempt": parent_attempt,
        "parentRequestDigest": _optional_digest(parent_request_digest, "parentRequestDigest"),
        "adapterId": _text(adapter_id, "adapterId"),
        "operation": _text(operation, "operation"),
        "executionKind": _enum(execution_kind, EXECUTION_KINDS, "executionKind"),
        "descriptorDigest": _digest(descriptor_digest, "descriptorDigest"),
        "planDigest": _digest(plan_digest, "planDigest"),
        "planLockDigest": _digest(plan_lock_digest, "planLockDigest"),
        "sourceRevision": _text(source_revision, "sourceRevision"),
        "sourceSnapshotDigest": _digest(source_snapshot_digest, "sourceSnapshotDigest"),
        "limits": checked_limits,
        "shell": False,
        "secretsWritten": False,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    _require_parent_lineage(body)
    return {**body, "requestDigest": canonical_digest(body)}


def validate_external_job_request(request: Any) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = request if isinstance(request, dict) else {}
    if not isinstance(request, dict):
        blockers.append({"code": "external-job-request-not-object"})
    _check_schema(value, EXTERNAL_JOB_REQUEST_SCHEMA, "request", blockers)
    _check_identity(value.get("jobId"), "external-job-job-id-invalid", blockers)
    _check_attempt(value.get("attempt"), "external-job-attempt-invalid", blockers)
    _check_parent(value, blockers)
    for field in ("adapterId", "operation", "sourceRevision"):
        _check_text(value.get(field), f"external-job-{_label(field)}-invalid", blockers)
    if value.get("executionKind") not in EXECUTION_KINDS:
        blockers.append({"code": "external-job-execution-kind-invalid"})
    for field in ("descriptorDigest", "planDigest", "planLockDigest", "sourceSnapshotDigest"):
        _check_digest(value.get(field), f"external-job-{_label(field)}-invalid", blockers)
    _check_limits(value.get("limits"), blockers)
    if (
        isinstance(value.get("attempt"), int)
        and isinstance(value.get("limits"), dict)
        and isinstance(value["limits"].get("maxAttempts"), int)
        and value["attempt"] > value["limits"]["maxAttempts"]
    ):
        blockers.append({"code": "external-job-attempt-limit-exceeded"})
    _check_false_fields(value, ("shell", "secretsWritten", "authorityClaimed", "productionPromotionClaimed"), blockers)
    _check_contract_digest(value, "requestDigest", "external-job-request-digest-mismatch", blockers)
    return _validation("REQUEST", None, blockers, blocking_eligible=not blockers)


def build_external_job_artifact(
    *, request: dict[str, Any], artifact_id: str, media_type: str, bytes_count: int, sha256: str, locator: str
) -> dict[str, Any]:
    require_external_job_pass(validate_external_job_request(request), "request")
    normalized = normalize_repo_path(locator, label="artifact locator")
    if not normalized.startswith("artifacts/"):
        raise LifecycleError("external-job-artifact-locator-invalid", "artifact locator must be below artifacts/")
    body = {
        "schemaVersion": EXTERNAL_JOB_ARTIFACT_SCHEMA,
        "artifactId": _identity(artifact_id, "artifactId"),
        "jobId": request["jobId"],
        "attempt": request["attempt"],
        "requestDigest": request["requestDigest"],
        "mediaType": _text(media_type, "mediaType"),
        "bytes": _bounded_int(bytes_count, 0, MAX_ARTIFACT_BYTES, "bytes"),
        "sha256": _digest(sha256, "sha256"),
        "locator": normalized,
        "sensitiveContentStored": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "artifactDigest": canonical_digest(body)}


def validate_external_job_artifact(
    artifact: Any, *, request: dict[str, Any] | None = None
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = artifact if isinstance(artifact, dict) else {}
    if not isinstance(artifact, dict):
        blockers.append({"code": "external-job-artifact-not-object"})
    _check_schema(value, EXTERNAL_JOB_ARTIFACT_SCHEMA, "artifact", blockers)
    _check_identity(value.get("artifactId"), "external-job-artifact-id-invalid", blockers)
    _check_identity(value.get("jobId"), "external-job-job-id-invalid", blockers)
    _check_attempt(value.get("attempt"), "external-job-attempt-invalid", blockers)
    _check_digest(value.get("requestDigest"), "external-job-request-digest-invalid", blockers)
    _check_text(value.get("mediaType"), "external-job-artifact-media-type-invalid", blockers)
    _check_int(value.get("bytes"), 0, MAX_ARTIFACT_BYTES, "external-job-artifact-bytes-invalid", blockers)
    _check_digest(value.get("sha256"), "external-job-artifact-sha256-invalid", blockers)
    try:
        locator_value = value.get("locator")
        if not isinstance(locator_value, str):
            raise LifecycleError("external-job-artifact-locator-invalid", "artifact locator must be text")
        locator = normalize_repo_path(locator_value, label="artifact locator")
        if not locator.startswith("artifacts/"):
            raise LifecycleError("external-job-artifact-locator-invalid", "artifact locator must be below artifacts/")
    except LifecycleError:
        blockers.append({"code": "external-job-artifact-locator-invalid"})
    _check_false_fields(value, ("sensitiveContentStored", "productionPromotionClaimed"), blockers)
    _check_contract_digest(value, "artifactDigest", "external-job-artifact-digest-mismatch", blockers)
    if request is not None:
        if validate_external_job_request(request)["status"] != "PASS":
            blockers.append({"code": "external-job-request-invalid"})
        elif any(value.get(key) != request.get(key) for key in ("jobId", "attempt", "requestDigest")):
            blockers.append({"code": "external-job-artifact-lineage-mismatch"})
    return _validation("ARTIFACT", None, blockers, blocking_eligible=not blockers and request is not None)


def build_external_job_status(
    *,
    request: dict[str, Any],
    state: str,
    sequence: int,
    observed_at: str,
    usage: dict[str, int] | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    children: list[dict[str, Any]] | None = None,
    cancel_requested: bool = False,
    process_cleanup_status: str = "NOT_REQUIRED",
    post_terminal_write_detected: bool = False,
) -> dict[str, Any]:
    require_external_job_pass(validate_external_job_request(request), "request")
    body = {
        "schemaVersion": EXTERNAL_JOB_STATUS_SCHEMA,
        "jobId": request["jobId"],
        "attempt": request["attempt"],
        "requestDigest": request["requestDigest"],
        "state": _enum(state, JOB_STATES, "state"),
        "sequence": _bounded_int(sequence, 0, 10**9, "sequence"),
        "observedAt": _text(observed_at, "observedAt"),
        "startedAt": _optional_text(started_at, "startedAt"),
        "endedAt": _optional_text(ended_at, "endedAt"),
        "children": _children(children or []),
        "usage": _usage(usage or {}, fill_defaults=True),
        "cancelRequested": _boolean(cancel_requested, "cancelRequested"),
        "processCleanupStatus": _enum(process_cleanup_status, CLEANUP_STATUSES, "processCleanupStatus"),
        "postTerminalWriteDetected": _boolean(post_terminal_write_detected, "postTerminalWriteDetected"),
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    result = {**body, "statusDigest": canonical_digest(body)}
    require_external_job_pass(validate_external_job_status(result, request=request), "status")
    return result


def validate_external_job_status(status: Any, *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = status if isinstance(status, dict) else {}
    if not isinstance(status, dict):
        blockers.append({"code": "external-job-status-not-object"})
    _check_schema(value, EXTERNAL_JOB_STATUS_SCHEMA, "status", blockers)
    _check_identity(value.get("jobId"), "external-job-job-id-invalid", blockers)
    _check_attempt(value.get("attempt"), "external-job-attempt-invalid", blockers)
    _check_digest(value.get("requestDigest"), "external-job-request-digest-invalid", blockers)
    state = value.get("state")
    if state not in JOB_STATES:
        blockers.append({"code": "external-job-state-invalid"})
    _check_int(value.get("sequence"), 0, 10**9, "external-job-sequence-invalid", blockers)
    _check_text(value.get("observedAt"), "external-job-observed-at-invalid", blockers)
    _check_status_times(value, blockers)
    _check_children(value.get("children"), blockers)
    _check_usage(value.get("usage"), blockers)
    if not isinstance(value.get("cancelRequested"), bool):
        blockers.append({"code": "external-job-cancel-request-invalid"})
    if value.get("processCleanupStatus") not in CLEANUP_STATUSES:
        blockers.append({"code": "external-job-cleanup-status-invalid"})
    if not isinstance(value.get("postTerminalWriteDetected"), bool):
        blockers.append({"code": "external-job-post-terminal-write-invalid"})
    if state == "SUCCEEDED" and value.get("postTerminalWriteDetected") is True:
        blockers.append({"code": "external-job-success-after-terminal-write"})
    _check_false_fields(value, ("authorityClaimed", "productionPromotionClaimed"), blockers)
    _check_contract_digest(value, "statusDigest", "external-job-status-digest-mismatch", blockers)
    if request is not None:
        request_validation = validate_external_job_request(request)
        if request_validation["status"] != "PASS":
            blockers.append({"code": "external-job-request-invalid"})
        elif any(
            value.get(key) != request.get(key)
            for key in ("jobId", "attempt", "requestDigest")
        ):
            blockers.append({"code": "external-job-status-lineage-mismatch"})
        else:
            for child in value.get("children", []):
                if child.get("parentRequestDigest") != request.get("requestDigest"):
                    blockers.append({"code": "external-job-child-parent-lineage-mismatch"})
            _check_usage_limits(value.get("usage"), request.get("limits"), blockers)
    eligible = (
        not blockers
        and request is not None
        and state == "SUCCEEDED"
        and value.get("processCleanupStatus") in {"PASS", "NOT_REQUIRED"}
        and value.get("postTerminalWriteDetected") is False
    )
    return _validation("STATUS", state if isinstance(state, str) else None, blockers, blocking_eligible=eligible)


def build_external_job_result(
    *,
    result_id: str,
    request: dict[str, Any],
    status: dict[str, Any],
    verdict: str,
    complete: bool,
    artifacts: list[dict[str, Any]],
    output_digest: str | None,
    output_bytes: int,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    require_external_job_pass(validate_external_job_request(request), "request")
    require_external_job_pass(validate_external_job_status(status, request=request), "status")
    if status["state"] not in TERMINAL_JOB_STATES:
        raise LifecycleError("external-job-result-not-terminal", "result requires a terminal status")
    checked_artifacts = []
    for artifact in artifacts:
        require_external_job_pass(validate_external_job_artifact(artifact, request=request), "artifact")
        checked_artifacts.append(dict(artifact))
    body = {
        "schemaVersion": EXTERNAL_JOB_RESULT_SCHEMA,
        "resultId": _identity(result_id, "resultId"),
        "jobId": request["jobId"],
        "attempt": request["attempt"],
        "requestDigest": request["requestDigest"],
        "statusDigest": status["statusDigest"],
        "state": status["state"],
        "verdict": _enum(verdict, JOB_VERDICTS, "verdict"),
        "complete": _boolean(complete, "complete"),
        "blockingEligible": _blocking_eligible(status, verdict, complete),
        "outputDigest": _optional_digest(output_digest, "outputDigest"),
        "outputBytes": _bounded_int(output_bytes, 0, MAX_OUTPUT_BYTES, "outputBytes"),
        "artifacts": checked_artifacts,
        "usage": dict(status["usage"]),
        "blockers": list(blockers or []),
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    result = {**body, "resultDigest": canonical_digest(body)}
    require_external_job_pass(validate_external_job_result(result, request=request, status=status), "result")
    return result


def validate_external_job_result(
    result: Any,
    *,
    request: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = result if isinstance(result, dict) else {}
    if not isinstance(result, dict):
        blockers.append({"code": "external-job-result-not-object"})
    _check_schema(value, EXTERNAL_JOB_RESULT_SCHEMA, "result", blockers)
    _check_identity(value.get("resultId"), "external-job-result-id-invalid", blockers)
    _check_identity(value.get("jobId"), "external-job-job-id-invalid", blockers)
    _check_attempt(value.get("attempt"), "external-job-attempt-invalid", blockers)
    for field in ("requestDigest", "statusDigest"):
        _check_digest(value.get(field), f"external-job-{_label(field)}-invalid", blockers)
    state = value.get("state")
    verdict_value = value.get("verdict")
    verdict = verdict_value if isinstance(verdict_value, str) else None
    if state not in TERMINAL_JOB_STATES:
        blockers.append({"code": "external-job-result-not-terminal"})
    if verdict not in JOB_VERDICTS:
        blockers.append({"code": "external-job-verdict-invalid"})
    if not isinstance(value.get("complete"), bool) or not isinstance(value.get("blockingEligible"), bool):
        blockers.append({"code": "external-job-result-flags-invalid"})
    _check_optional_digest(value.get("outputDigest"), "external-job-output-digest-invalid", blockers)
    _check_int(value.get("outputBytes"), 0, MAX_OUTPUT_BYTES, "external-job-output-bytes-invalid", blockers)
    if (
        isinstance(value.get("outputBytes"), int)
        and value.get("outputBytes", 0) > 0
        and value.get("outputDigest") is None
    ):
        blockers.append({"code": "external-job-output-digest-required"})
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS:
        blockers.append({"code": "external-job-artifacts-invalid"})
        artifacts = []
    for artifact in artifacts:
        if validate_external_job_artifact(artifact, request=request)["status"] != "PASS":
            blockers.append({"code": "external-job-artifact-invalid"})
    _check_usage(value.get("usage"), blockers)
    if not isinstance(value.get("blockers"), list) or len(value.get("blockers", [])) > 128:
        blockers.append({"code": "external-job-blockers-invalid"})
    _check_false_fields(value, ("authorityClaimed", "productionPromotionClaimed"), blockers)
    if state == "SUCCEEDED" and verdict == "NO_FINAL_VERDICT":
        blockers.append({"code": "external-job-success-without-verdict"})
    if state != "SUCCEEDED" and verdict != "NO_FINAL_VERDICT":
        blockers.append({"code": "external-job-terminal-verdict-invalid"})
    if value.get("blockingEligible") is True and not (
        state == "SUCCEEDED" and value.get("complete") is True and verdict in {"PASS", "FAIL"}
    ):
        blockers.append({"code": "external-job-result-eligibility-invalid"})
    if value.get("blockingEligible") is True and (request is None or status is None):
        blockers.append({"code": "external-job-result-source-context-required"})
    _check_contract_digest(value, "resultDigest", "external-job-result-digest-mismatch", blockers)
    if request is not None:
        if validate_external_job_request(request)["status"] != "PASS":
            blockers.append({"code": "external-job-request-invalid"})
        elif any(value.get(key) != request.get(key) for key in ("jobId", "attempt", "requestDigest")):
            blockers.append({"code": "external-job-result-lineage-mismatch"})
        else:
            limits = request["limits"]
            if len(artifacts) > limits["maxArtifacts"] or sum(item.get("bytes", 0) for item in artifacts) > limits[
                "maxArtifactBytes"
            ]:
                blockers.append({"code": "external-job-artifact-limit-exceeded"})
            if value.get("outputBytes", 0) > limits["maxOutputBytes"]:
                blockers.append({"code": "external-job-output-limit-exceeded"})
            _check_usage_limits(value.get("usage"), limits, blockers)
    if status is not None:
        if validate_external_job_status(status, request=request)["status"] != "PASS":
            blockers.append({"code": "external-job-status-invalid"})
        elif any(
            value.get(key) != status.get(source)
            for key, source in (
                ("jobId", "jobId"),
                ("attempt", "attempt"),
                ("statusDigest", "statusDigest"),
                ("state", "state"),
            )
        ):
            blockers.append({"code": "external-job-result-status-mismatch"})
        elif value.get("usage") != status.get("usage"):
            blockers.append({"code": "external-job-result-usage-mismatch"})
        expected_eligible = _blocking_eligible(status, verdict, bool(value.get("complete")))
        if value.get("blockingEligible") != expected_eligible:
            blockers.append({"code": "external-job-result-eligibility-mismatch"})
    eligible = not blockers and request is not None and status is not None and value.get("blockingEligible") is True
    return _validation("RESULT", state if isinstance(state, str) else None, blockers, blocking_eligible=eligible)


def require_external_job_pass(validation: dict[str, Any], label: str) -> None:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "external-job-invalid",
            f"external job {label} is invalid",
            {"blockers": validation.get("blockers")},
        )


def _validation(
    subject: str,
    state: str | None,
    blockers: list[dict[str, Any]],
    *,
    blocking_eligible: bool,
) -> dict[str, Any]:
    body = {
        "schemaVersion": EXTERNAL_JOB_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "subject": subject,
        "subjectState": state,
        "blockingEligible": bool(blocking_eligible and not blockers),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _limits(value: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError("external-job-limits-invalid", "limits must be an object")
    if set(value) != set(_LIMIT_RANGES):
        raise LifecycleError("external-job-limits-invalid", "limits fields are invalid")
    return {key: _bounded_int(value[key], low, high, key) for key, (low, high) in _LIMIT_RANGES.items()}


def _usage(value: Any, *, fill_defaults: bool = False) -> dict[str, int]:
    defaults = dict.fromkeys(_USAGE_FIELDS, 0)
    if not isinstance(value, dict) or not set(value).issubset(defaults):
        raise LifecycleError("external-job-usage-invalid", "usage fields are invalid")
    if not fill_defaults and set(value) != set(defaults):
        raise LifecycleError("external-job-usage-invalid", "all usage fields are required")
    merged = {**defaults, **value}
    return {key: _bounded_int(item, 0, 10**15, key) for key, item in merged.items()}


def _children(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_CHILDREN:
        raise LifecycleError("external-job-children-invalid", "children are invalid")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for child in value:
        if not isinstance(child, dict) or set(child) != {"jobId", "attempt", "requestDigest", "parentRequestDigest"}:
            raise LifecycleError("external-job-child-invalid", "child reference is invalid")
        child_job_id = _identity(child["jobId"], "child.jobId")
        child_attempt = _attempt(child["attempt"], "child.attempt")
        item = {
            "jobId": child_job_id,
            "attempt": child_attempt,
            "requestDigest": _digest(child["requestDigest"], "child.requestDigest"),
            "parentRequestDigest": _digest(child["parentRequestDigest"], "child.parentRequestDigest"),
        }
        identity = (child_job_id, child_attempt)
        if identity in seen:
            raise LifecycleError("external-job-child-duplicate", "child reference is duplicated")
        seen.add(identity)
        result.append(item)
    return result


def _blocking_eligible(status: dict[str, Any], verdict: str | None, complete: bool) -> bool:
    return bool(
        status.get("state") == "SUCCEEDED"
        and verdict in {"PASS", "FAIL"}
        and complete
        and status.get("processCleanupStatus") in {"PASS", "NOT_REQUIRED"}
        and status.get("postTerminalWriteDetected") is False
    )


def _check_schema(value: dict[str, Any], expected: str, label: str, blockers: list[dict[str, Any]]) -> None:
    if value.get("schemaVersion") != expected:
        blockers.append({"code": f"external-job-{label}-schema-invalid"})


def _check_status_times(value: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    state = value.get("state")
    started = value.get("startedAt")
    ended = value.get("endedAt")
    if state == "QUEUED" and (started is not None or ended is not None):
        blockers.append({"code": "external-job-queued-timestamps-invalid"})
    if state == "RUNNING" and (not _is_text(started) or ended is not None):
        blockers.append({"code": "external-job-running-timestamps-invalid"})
    if state in TERMINAL_JOB_STATES and not _is_text(ended):
        blockers.append({"code": "external-job-terminal-ended-at-required"})


def _check_parent(value: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    parent_id = value.get("parentJobId")
    parent_attempt = value.get("parentAttempt")
    parent_digest = value.get("parentRequestDigest")
    try:
        if parent_id is not None:
            _identity(parent_id, "parentJobId")
        if parent_digest is not None:
            _digest(parent_digest, "parentRequestDigest")
        _require_parent_lineage(value)
        if parent_attempt is not None:
            _attempt(parent_attempt, "parentAttempt")
    except LifecycleError:
        blockers.append({"code": "external-job-parent-lineage-invalid"})


def _check_limits(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        _limits(value)
    except LifecycleError:
        blockers.append({"code": "external-job-limits-invalid"})


def _check_usage(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        _usage(value)
    except LifecycleError:
        blockers.append({"code": "external-job-usage-invalid"})


def _check_usage_limits(usage: Any, limits: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(usage, dict) or not isinstance(limits, dict):
        return
    comparisons = (
        ("wallMilliseconds", "maxWallSeconds", 1000, "external-job-wall-limit-exceeded"),
        ("outputBytes", "maxOutputBytes", 1, "external-job-output-limit-exceeded"),
        ("artifactBytes", "maxArtifactBytes", 1, "external-job-artifact-limit-exceeded"),
        ("costMicros", "maxCostMicros", 1, "external-job-cost-limit-exceeded"),
        ("reportedTokens", "maxReportedTokens", 1, "external-job-token-limit-exceeded"),
    )
    for usage_key, limit_key, multiplier, code in comparisons:
        if (
            isinstance(usage.get(usage_key), int)
            and isinstance(limits.get(limit_key), int)
            and usage[usage_key] > limits[limit_key] * multiplier
        ):
            blockers.append({"code": code})


def _check_children(value: Any, blockers: list[dict[str, Any]]) -> None:
    try:
        _children(value)
    except LifecycleError:
        blockers.append({"code": "external-job-children-invalid"})


def _check_false_fields(value: dict[str, Any], fields: tuple[str, ...], blockers: list[dict[str, Any]]) -> None:
    for field in fields:
        if value.get(field) is not False:
            blockers.append({"code": f"external-job-{_label(field)}-invalid"})


def _check_contract_digest(value: dict[str, Any], field: str, code: str, blockers: list[dict[str, Any]]) -> None:
    actual = value.get(field)
    body = {key: item for key, item in value.items() if key != field}
    if not isinstance(actual, str) or actual != canonical_digest(body):
        blockers.append({"code": code})


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _check_optional_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if value is not None and not _is_digest(value):
        blockers.append({"code": code})


def _check_text(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_text(value):
        blockers.append({"code": code})


def _check_identity(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    try:
        _identity(value, "identity")
    except LifecycleError:
        blockers.append({"code": code})


def _check_attempt(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
        blockers.append({"code": code})


def _check_int(value: Any, low: int, high: int, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        blockers.append({"code": code})


def _identity(value: Any, label: str) -> str:
    text = _text(value, label)
    if text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise LifecycleError("external-job-identity-invalid", f"{label} is invalid")
    return text


def _optional_identity(value: Any, label: str) -> str | None:
    return None if value is None else _identity(value, label)


def _attempt(value: Any, label: str) -> int:
    return _bounded_int(value, 1, 1000, label)


def _text(value: Any, label: str) -> str:
    if not _is_text(value):
        raise LifecycleError("external-job-text-invalid", f"{label} is invalid")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise LifecycleError("external-job-boolean-invalid", f"{label} is invalid")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _digest(value: Any, label: str) -> str:
    if not _is_digest(value):
        raise LifecycleError("external-job-digest-invalid", f"{label} is invalid")
    return value


def _optional_digest(value: Any, label: str) -> str | None:
    return None if value is None else _digest(value, label)


def _enum(value: Any, values: tuple[str, ...], label: str) -> str:
    if value not in values:
        raise LifecycleError("external-job-value-invalid", f"{label} is invalid")
    return value


def _bounded_int(value: Any, low: int, high: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise LifecycleError("external-job-integer-invalid", f"{label} is invalid")
    return value


def _require_parent_lineage(value: dict[str, Any]) -> None:
    parent = (value.get("parentJobId"), value.get("parentAttempt"), value.get("parentRequestDigest"))
    if any(item is None for item in parent) and any(item is not None for item in parent):
        raise LifecycleError("external-job-parent-lineage-invalid", "parent lineage fields must be paired")
    if parent[0] == value.get("jobId") and parent[1] == value.get("attempt"):
        raise LifecycleError("external-job-parent-lineage-invalid", "job cannot be its own parent attempt")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _is_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\x00" not in value
        and len(value.encode("utf-8")) <= MAX_TEXT_BYTES
    )


def _label(value: str) -> str:
    result = []
    for character in value:
        result.append(f"-{character.lower()}" if character.isupper() else character)
    return "".join(result)


__all__ = [
    "CLEANUP_STATUSES", "EXECUTION_KINDS", "EXTERNAL_JOB_ARTIFACT_SCHEMA", "EXTERNAL_JOB_REQUEST_SCHEMA",
    "EXTERNAL_JOB_RESULT_SCHEMA", "EXTERNAL_JOB_SCHEMAS", "EXTERNAL_JOB_STATUS_SCHEMA",
    "EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA", "EXTERNAL_JOB_VALIDATION_SCHEMA", "JOB_STATES", "JOB_VERDICTS",
    "TERMINAL_JOB_STATES", "build_external_job_artifact", "build_external_job_request", "build_external_job_result",
    "build_external_job_status", "require_external_job_pass", "validate_external_job_artifact",
    "validate_external_job_request", "validate_external_job_result", "validate_external_job_status",
]
