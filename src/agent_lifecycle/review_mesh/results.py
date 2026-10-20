"""Review Mesh reviewer result import helpers."""

from __future__ import annotations

from math import isfinite
from typing import Any, cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.redaction import (
    LOCAL_PATH_REDACTION,
    contains_local_absolute_path,
    is_sensitive_key,
    redact_text_with_stats,
)
from agent_lifecycle.contracts.review_mesh_schemas import (
    RAW_REVIEW_STATUSES,
    require_response_contract,
)
from agent_lifecycle.contracts.thread_bridge_schemas import (
    validate_thread_context_import,
)
from agent_lifecycle.quality.cross_check import USAGE_KEYS
from agent_lifecycle.review_mesh.contracts import (
    _command_outcome_blockers,
    _imported_independence_claimed,
    build_review_mesh_result,
    require_review_mesh_result_pass,
    validate_review_mesh_result,
)


def import_review_mesh_result(
    *,
    profile: dict[str, Any],
    assignment: dict[str, Any],
    reviewer_output: dict[str, Any],
    allow_local_evidence_refs: bool = False,
    session_usage_context: dict[str, Any] | None = None,
    existing_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a reviewer output object into a redacted Review Mesh result."""

    _validate_import_input(reviewer_output)
    _require_safe_bound_metadata(profile, allow_local_evidence_refs=allow_local_evidence_refs)
    _require_safe_bound_metadata(assignment, allow_local_evidence_refs=allow_local_evidence_refs)
    bindings = _validate_import_bindings(reviewer_output, assignment, profile)
    contract = assignment.get("subject", {}).get("responseContract")
    if contract is not None:
        validate_prepared_reviewer_output(reviewer_output, contract, assignment)
    sanitized, redaction = _sanitize_payload(reviewer_output, allow_local_evidence_refs=allow_local_evidence_refs)
    # These exact values have already matched the checked bound authority.
    # Content normalization must not rewrite identity labels or placeholders.
    findings = sanitized.get("findings", [])
    budget_usage = {key: sanitized.get("budgetUsage", {}).get(key) for key in sorted(USAGE_KEYS)}
    commands = sanitized.get("commandOutcomes", [])
    status = sanitized.get("status")
    if any(command["status"] == "FAIL" or command["exitCode"] != 0 for command in commands):
        status = "FAIL"
    result = build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage=budget_usage,
        findings=findings,
        status=status,
        live_calls_started=sanitized.get("liveCallsStarted", False),
        session_usage_context=session_usage_context,
    )
    # Distinct caller-supplied identity hashes are comparison data, not an
    # observed independent review. Retain them without promoting the import.
    unproven_independence = result["independence"].get("status") == "INDEPENDENT"
    if unproven_independence:
        result["independence"] = {**result["independence"], "status": "NOT_PROVEN"}
        cross_receipt = result["crossCheckReceipt"]
        cross_receipt["independence"] = dict(result["independence"])
        cross_receipt["blockers"].append({"code": "cross-check-independence-not-proven"})
        cross_receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in cross_receipt.items() if key != "receiptDigest"}
        )
        result["blockers"].append({"code": "cross-check-independence-not-proven"})
    body = {
        **{key: value for key, value in result.items() if key != "resultDigest"},
        "roundParticipation": {
            "eligible": False,
            "reasonCode": "review-verdict-and-terminal-job-required",
        },
        "commandOutcomes": commands,
        "redaction": redaction,
        "import": {
            "assignmentDigest": assignment["assignmentDigest"],
            "schemaVersion": sanitized.get("schemaVersion") or "reviewer-output.unknown",
            "rawOutputStored": False,
            "outputDigest": canonical_digest(reviewer_output),
            "sanitizedOutputDigest": canonical_digest(sanitized),
            "bindings": bindings,
            **(
                {"responseContractDigest": contract["contractDigest"], "coverage": sanitized.get("coverage")}
                if contract is not None
                else {}
            ),
        },
    }
    normalized = {**body, "resultDigest": canonical_digest(body)}
    validation = validate_review_mesh_result(
        normalized,
        profile=profile,
        session_usage_context=session_usage_context,
        assignment=assignment,
    )
    if normalized.get("budgetUsageStatus") == "UNAVAILABLE" or unproven_independence:
        # Return readable candidates only for these expected proof gaps. The
        # public validator still rejects them; other validation errors survive.
        validation = {
            **validation,
            "blockers": [
                item
                for item in validation["blockers"]
                if not _readable_candidate_gap(item, unproven_independence=unproven_independence)
            ],
        }
        validation["status"] = "FAIL" if validation["blockers"] else "PASS"
    require_review_mesh_result_pass(validation)
    if existing_results is not None:
        return _same_response_once(normalized, existing_results)
    return normalized


def _same_response_once(
    result: dict[str, Any],
    existing: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(existing, list) or len(existing) > 64:
        _invalid_import("recovery input must be a bounded result list")
    found = None
    for candidate in existing:
        if not isinstance(candidate, dict):
            _invalid_import("recovery results must be objects")
        imported = candidate.get("import", {})
        if not isinstance(imported, dict):
            _invalid_import("recovery result import binding is invalid")
        if imported.get("assignmentDigest") != result["import"]["assignmentDigest"]:
            continue
        body = {key: value for key, value in candidate.items() if key != "resultDigest"}
        if candidate.get("resultDigest") != canonical_digest(body):
            _invalid_import("recovery result integrity differs")
        if (
            imported.get("outputDigest") != result["import"]["outputDigest"]
            or any(
                candidate.get(key) != result.get(key)
                for key in (
                    "subject",
                    "reviewer",
                    "profileDigest",
                    "assignmentId",
                    "sessionUsage",
                    "budgetUsage",
                )
            )
            or found is not None
            or candidate != result
        ):
            _invalid_import("recovery cannot replace or duplicate a bound response")
        found = candidate
    return found if found is not None else result


def _readable_candidate_gap(blocker: dict[str, Any], *, unproven_independence: bool) -> bool:
    if blocker["code"] == "review-mesh-result-usage-unavailable":
        return True
    if unproven_independence and blocker["code"] == "review-mesh-result-cross-check-invalid":
        nested = blocker["validation"]["blockers"]
        return bool(nested) and all(
            item["code"] in {"cross-check-independence-not-proven", "cross-check-independence-mismatch"}
            for item in nested
        )
    return False


def _invalid_import(message: str) -> None:
    raise LifecycleError("review-mesh-import-invalid", message)


def _require_json_values(value: Any, ancestors: set[int] | None = None) -> None:
    # Check the original shape before redaction can hide an invalid value or
    # serialization can coerce a dictionary key used in an authority binding.
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not isfinite(value):
            _invalid_import("JSON numbers must be finite")
        return
    if type(value) not in {dict, list}:
        _invalid_import("import inputs must contain only JSON values")
    if type(value) is dict and any(type(key) is not str for key in value):
        _invalid_import("JSON object keys must be strings")
    active = set() if ancestors is None else ancestors
    identity = id(value)
    if identity in active:
        _invalid_import("JSON values must not contain cycles")
    active.add(identity)
    try:
        for item in value.values() if type(value) is dict else value:
            _require_json_values(item, active)
    finally:
        active.remove(identity)


def _require_safe_bound_metadata(value: dict[str, Any], *, allow_local_evidence_refs: bool) -> None:
    _require_json_values(value)
    # Bound metadata must retain its authority identity. Redacting a copy and
    # recomputing its digest would create different, unapproved authority.
    _sanitized, redaction = _sanitize_payload(value, allow_local_evidence_refs=allow_local_evidence_refs)
    if redaction["secretLikeMarkersRedacted"] or redaction["localPathsRedacted"]:
        _invalid_import("bound metadata contains sensitive markers or local paths")


def _binding_values_equal(left: Any, right: Any) -> bool:
    # Python container equality treats nested True and 1 as equal. Bound
    # identities retain their complete JSON values and types at every depth.
    return type(left) is type(right) and canonical_digest(left) == canonical_digest(right)


def _validate_import_input(value: Any) -> None:
    _require_json_values(value)
    if not isinstance(value, dict):
        _invalid_import("reviewer output must be an object")
    if "schemaVersion" in value and (not isinstance(value["schemaVersion"], str) or not value["schemaVersion"].strip()):
        _invalid_import("schemaVersion must be a nonempty string")
    findings = value.get("findings", [])
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        _invalid_import("findings must be a list of objects")
    if "status" in value and (not isinstance(value["status"], str) or value["status"] not in RAW_REVIEW_STATUSES):
        _invalid_import("status must be PASS, FAIL or SKIPPED")
    if "liveCallsStarted" in value and type(value["liveCallsStarted"]) is not bool:
        _invalid_import("liveCallsStarted must be boolean")
    usage = value.get("budgetUsage", {})
    if not isinstance(usage, dict) or set(usage).difference(USAGE_KEYS):
        _invalid_import("budgetUsage must contain only supported resource fields")
    for item in usage.values():
        if item is not None and (type(item) is not int or item < 0):
            _invalid_import("budget usage must be nonnegative integers or unknown null")
    commands = value.get("commandOutcomes", [])
    if _command_outcome_blockers(commands):
        _invalid_import("commandOutcomes require unique commandId, PASS/FAIL status and a compatible integer exitCode")


def validate_prepared_reviewer_output(
    value: dict[str, Any],
    contract: dict[str, Any],
    assignment: dict[str, Any],
) -> dict[str, Any]:
    """Extend the existing raw collector only for an explicitly bound contract."""
    checked = require_response_contract(contract)
    _validate_import_input(value)
    if any(field not in value for field in checked["schema"]["required"]):
        _invalid_import("prepared response is missing required contract fields")
    expected = {
        "schemaVersion": checked["rawSchemaVersion"],
        "contractDigest": checked["contractDigest"],
        "subjectDigest": assignment["subject"]["subjectDigest"],
        "assignmentDigest": assignment["assignmentDigest"],
    }
    if any(not _binding_values_equal(value.get(field), item) for field, item in expected.items()):
        _invalid_import("prepared response contract or subject identity differs")
    coverage = checked["extensions"].get("coverage")
    if coverage is not None:
        supplied = value.get("coverage")
        if (
            type(supplied) is not list
            or any(type(path) is not str for path in supplied)
            or len(set(supplied)) != len(supplied)
            or set(supplied) != set(coverage["paths"])
        ):
            _invalid_import("coverage must contain every declared path exactly once")
    return value


def _validate_import_bindings(
    raw: dict[str, Any], assignment: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    keys = {
        "assignmentId",
        "assignmentDigest",
        "profileId",
        "profileDigest",
        "mode",
        "phase",
        "subject",
        "reviewer",
        "taskId",
        "attempt",
        "runId",
        "planDigest",
        "planRevision",
        "sourceDigest",
        "actorId",
        "sessionId",
    }
    subject = assignment.get("subject", {})
    if not isinstance(subject, dict):
        _invalid_import("bound assignment subject must be an object")
    for key in keys.intersection(subject, assignment):
        if not _binding_values_equal(subject[key], assignment[key]):
            _invalid_import("bound assignment identities conflict")
    expected = {**subject, **assignment, "profileDigest": profile.get("profileDigest")}
    nested = raw.get("bindings", {})
    if not isinstance(nested, dict) or set(nested).difference(keys):
        _invalid_import("bindings must contain only supported identity fields")
    provided = {key: raw[key] for key in keys if key in raw}
    for key, value in nested.items():
        if key in provided and isinstance(value, dict) and isinstance(provided[key], dict):
            previous = provided[key]
            if any(k in previous and not _binding_values_equal(v, previous[k]) for k, v in value.items()):
                _invalid_import("top-level and nested bindings conflict")
            value = {**previous, **value}
        elif key in provided and not _binding_values_equal(value, provided[key]):
            _invalid_import("top-level and nested bindings conflict")
        provided[key] = value
    for key, value in provided.items():
        target = expected.get(key)
        if key in {"subject", "reviewer"} and isinstance(value, dict) and isinstance(target, dict):
            matches = all(k in target and _binding_values_equal(v, target[k]) for k, v in value.items())
        else:
            matches = key in expected and _binding_values_equal(value, target)
        if not matches:
            _invalid_import(f"{key} conflicts with the bound assignment")
    return provided


def build_thread_context_review_input(imported_context: dict[str, Any]) -> dict[str, Any]:
    """Project thread context into a Review Mesh input without elevating authority."""

    validation = validate_thread_context_import(imported_context)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "review-mesh-thread-context-invalid",
            "thread context cannot be used for review",
            {"validation": validation},
        )
    source: dict[str, Any] = (
        cast(dict[str, Any], imported_context.get("source")) if isinstance(imported_context.get("source"), dict) else {}
    )
    body = {
        "schemaVersion": "agent-review-mesh-thread-context-input.v1",
        "sourceRole": "optional-thread-context",
        "sourceId": source.get("sourceId", "redacted"),
        "importDigest": imported_context["importDigest"],
        "content": imported_context.get("content", {}),
        "sourceOfTruth": False,
        "proof": False,
        "promptAuthorityGranted": False,
        "toolApprovalGranted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "inputDigest": canonical_digest(body)}


def project_review_result_for_optimization(result: dict[str, Any]) -> dict[str, Any]:
    """Project a Review Mesh result without copying reviewer output or identity names."""

    if not isinstance(result, dict):
        raise LifecycleError("review-mesh-result-projection-invalid", "Review Mesh result must be an object")
    findings: list[Any] = cast(list[Any], result.get("findings")) if isinstance(result.get("findings"), list) else []
    severity_counts: dict[str, int] = {}
    accepted = 0
    rejected = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity: str = cast(str, finding.get("severity")) if isinstance(finding.get("severity"), str) else "INFO"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        status = str(finding.get("status", "open")).lower()
        if status in {"accepted", "fixed", "closed"}:
            accepted += 1
        if status in {"rejected", "dismissed"}:
            rejected += 1
    reviewer: dict[str, Any] = (
        cast(dict[str, Any], result.get("reviewer")) if isinstance(result.get("reviewer"), dict) else {}
    )
    independence: dict[str, Any] = (
        cast(dict[str, Any], result.get("independence")) if isinstance(result.get("independence"), dict) else {}
    )
    if _imported_independence_claimed(result):
        independence = {"status": "NOT_PROVEN"}
    subject: dict[str, Any] = (
        cast(dict[str, Any], result.get("subject")) if isinstance(result.get("subject"), dict) else {}
    )
    projection = {
        "status": result.get("status") if result.get("status") in {"PASS", "FAIL", "SKIPPED"} else "UNKNOWN",
        "findingCount": len(findings),
        "severityCounts": dict(sorted(severity_counts.items())),
        "acceptedCount": accepted,
        "rejectedCount": rejected,
        "disagreementCount": int(result.get("disagreementCount", 0))
        if isinstance(result.get("disagreementCount"), int)
        else 0,
        "independenceStatus": independence.get("status")
        if independence.get("status") in {"INDEPENDENT", "NOT_REQUIRED", "NOT_PROVEN"}
        else "MISSING",
        "reviewerRole": reviewer.get("role") if isinstance(reviewer.get("role"), str) else "unknown",
        "modelRouteClass": reviewer.get("modelClass") if isinstance(reviewer.get("modelClass"), str) else "unknown",
        "phase": result.get("phase") if isinstance(result.get("phase"), str) else subject.get("phase", "unknown"),
    }
    for field in ("hostIdentityHash", "modelIdentityHash"):
        identity_hash = reviewer.get(field)
        if isinstance(identity_hash, str) and len(identity_hash) == 64:
            projection[field] = identity_hash
    return projection


def _sanitize_payload(value: Any, *, allow_local_evidence_refs: bool) -> tuple[Any, dict[str, Any]]:
    stats = {"secretLikeMarkersRedacted": 0, "localPathsRedacted": 0}
    sanitized = _sanitize_value(value, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path="$")
    status = "REDACTED" if stats["secretLikeMarkersRedacted"] or stats["localPathsRedacted"] else "PASS"
    return sanitized, {
        "status": status,
        "secretLikeMarkersRedacted": stats["secretLikeMarkersRedacted"],
        "localPathsRedacted": stats["localPathsRedacted"],
        "localPathPolicy": "explicit-plan-owned-reference"
        if allow_local_evidence_refs
        else "reject-local-absolute-paths",
    }


def _sanitize_value(value: Any, *, stats: dict[str, int], allow_local_evidence_refs: bool, path: str) -> Any:
    if isinstance(value, str):
        text = value
        path_present = contains_local_absolute_path(text)
        if path_present and not allow_local_evidence_refs:
            raise LifecycleError(
                "review-mesh-local-path-leakage", "reviewer output contains a local absolute path", {"path": path}
            )
        redacted, _changed, counts = redact_text_with_stats(text)
        text = redacted.replace(LOCAL_PATH_REDACTION, "[LOCAL_PATH]").replace("<redacted>", "[REDACTED]")
        stats["localPathsRedacted"] += counts["localPathsRedacted"]
        stats["secretLikeMarkersRedacted"] += counts["secretLikeMarkersRedacted"]
        return text
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if isinstance(key, str):
                _text, _changed, counts = redact_text_with_stats(key)
                if contains_local_absolute_path(key) or counts["secretLikeMarkersRedacted"]:
                    # Renaming keys could merge distinct finding fields.
                    _invalid_import("dictionary keys contain sensitive markers or local paths")
            if isinstance(key, str) and is_sensitive_key(key):
                sanitized[key] = "[REDACTED]"
                stats["secretLikeMarkersRedacted"] += 1
                continue
            sanitized[key] = _sanitize_value(
                item, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path=f"{path}.{key}"
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_value(
                item, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path=f"{path}[{index}]"
            )
            for index, item in enumerate(value)
        ]
    if value is None or type(value) in {bool, int, float}:
        return value
    _invalid_import("nested reviewer output must contain only JSON values")
