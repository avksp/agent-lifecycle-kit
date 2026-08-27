"""Privacy-preserving projections of local lifecycle receipts."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.audit_optimization_schemas import (
    AUDIT_OPTIMIZATION_SAMPLE_BATCH_SCHEMA,
    AUDIT_OPTIMIZATION_SAMPLE_SCHEMA,
)
from agent_lifecycle.contracts.process_execution_schemas import (
    PROCESS_EXECUTION_RECEIPT_SCHEMA,
)
from agent_lifecycle.contracts.redaction import contains_local_absolute_path
from agent_lifecycle.review_mesh.results import project_review_result_for_optimization

_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PROMPT_KEYS = ("prompt", "transcript", "requestText", "taskText", "rawInput")
_SECTION_MARKERS = {
    "requirements": re.compile(r"(^|\n)\s*(requirements?|требования)\s*[:#]", re.IGNORECASE),
    "acceptance": re.compile(r"(^|\n)\s*(acceptance|критерии)\s*[:#]", re.IGNORECASE),
    "constraints": re.compile(r"(^|\n)\s*(constraints?|ограничения)\s*[:#]", re.IGNORECASE),
    "evidence": re.compile(r"(^|\n)\s*(evidence|доказательства)\s*[:#]", re.IGNORECASE),
}
_FORBIDDEN_KEYS = {"prompt", "transcript", "provider", "providerName", "model", "modelName", "secret", "token", "password", "path", "cwd", "environment"}
_ROUTE_CLASSES = {
    "code",
    "code-review",
    "general",
    "local",
    "reasoning",
    "release",
    "research",
    "review",
    "small",
    "standard",
    "strong",
    "strong-reasoning",
    "unknown",
}


def build_audit_sample(
    receipt: dict[str, Any],
    *,
    sample_id: str | None = None,
) -> dict[str, Any]:
    """Project one or more related receipts into a bounded portable sample."""

    if not isinstance(receipt, dict):
        raise LifecycleError("audit-sample-input-invalid", "receipt bundle must be an object")
    review = _extract(receipt, "reviewReceipt", "review")
    usage = _extract(receipt, "usageReceipt", "usage")
    process = _extract(receipt, "processReceipt", "process")
    outcome = _extract(receipt, "outcomeReceipt", "outcome")
    sources = [item for item in (review, usage, process, outcome) if isinstance(item, dict)]
    if not sources:
        sources = [receipt]
    lineage = _lineage(receipt, sources)
    request = _request_projection(receipt, sources)
    review_projection = project_review_result_for_optimization(review) if review else _empty_review()
    review_projection["modelRouteClass"] = _route_class(
        review_projection.get("modelRouteClass")
        if isinstance(review_projection.get("modelRouteClass"), str)
        else None
    )
    usage_projection = _usage_projection(usage)
    process_projection = _process_projection(process)
    quality = _quality_projection(receipt, outcome, review_projection)
    attempts = _attempt_projection(receipt, sources, process)
    attestation = _attestation_projection(review_projection, usage_projection, process_projection)
    source_digests = sorted({canonical_digest(item) for item in sources})
    resolved_sample_id = sample_id or canonical_digest({"lineage": lineage, "sourceDigests": source_digests})
    statistical_provenance = _statistical_provenance(
        receipt,
        sources,
        review_projection,
        lineage,
        source_digests,
        resolved_sample_id,
    )
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_SAMPLE_SCHEMA,
        "sampleId": resolved_sample_id,
        "lineage": lineage,
        "statisticalProvenance": statistical_provenance,
        "request": request,
        "review": review_projection,
        "attempts": attempts,
        "usage": usage_projection,
        "process": process_projection,
        "quality": quality,
        "attestation": attestation,
        "sourceDigests": source_digests,
        "rawPromptStored": False,
        "rawOutputStored": False,
        "secretsStored": False,
        "providerModelNamesStored": False,
        "localPathsStored": False,
        "productionPromotionClaimed": False,
    }
    _assert_private_projection(body)
    return {**body, "sampleDigest": canonical_digest(body)}


def build_audit_samples(
    receipts: list[dict[str, Any]],
    *,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic batch from explicit local receipt bundles."""

    if not isinstance(receipts, list):
        raise LifecycleError("audit-samples-input-invalid", "receipts must be a list")
    samples: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts):
        try:
            samples.append(build_audit_sample(receipt))
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "index": index})
    if source_paths and len(source_paths) != len(receipts):
        blockers.append({"code": "audit-samples-source-path-count", "expected": len(receipts), "actual": len(source_paths)})
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_SAMPLE_BATCH_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "sampleCount": len(samples),
        "samples": samples,
        "sourceCount": len(receipts),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "batchDigest": canonical_digest(body)}


def validate_audit_sample(sample: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(sample, dict) or sample.get("schemaVersion") != AUDIT_OPTIMIZATION_SAMPLE_SCHEMA:
        blockers.append({"code": "audit-sample-schema"})
    if isinstance(sample, dict):
        for key in ("rawPromptStored", "rawOutputStored", "secretsStored", "providerModelNamesStored", "localPathsStored", "productionPromotionClaimed"):
            if sample.get(key) is not False:
                blockers.append({"code": "audit-sample-safety-flag", "field": key})
        if not _DIGEST_RE.fullmatch(str(sample.get("sampleDigest", ""))):
            blockers.append({"code": "audit-sample-digest"})
        else:
            expected = canonical_digest({key: value for key, value in sample.items() if key != "sampleDigest"})
            if sample.get("sampleDigest") != expected:
                blockers.append({"code": "audit-sample-digest-mismatch"})
        provenance = sample.get("statisticalProvenance")
        if isinstance(provenance, dict):
            if not _DIGEST_RE.fullmatch(str(provenance.get("sampleIdentity", ""))):
                blockers.append({"code": "audit-sample-identity-invalid"})
            for field in ("sourceLineageDigest", "producerIdentityHash"):
                if not _DIGEST_RE.fullmatch(str(provenance.get(field, ""))):
                    blockers.append({"code": "audit-sample-provenance-digest-invalid", "field": field})
            for field in ("sourceClass", "derivation", "sourceRevision", "producerClass"):
                if not isinstance(provenance.get(field), str) or not provenance[field]:
                    blockers.append({"code": "audit-sample-provenance-field-missing", "field": field})
        try:
            _assert_private_projection(sample)
        except LifecycleError as exc:
            blockers.append({"code": exc.code})
    body = {
        "schemaVersion": "agent-audit-optimization-sample-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "sampleId": sample.get("sampleId") if isinstance(sample, dict) else None,
        "blockers": blockers,
        "sampleDigest": sample.get("sampleDigest") if isinstance(sample, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_audit_sample_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("audit-sample-validation-failed", "audit sample validation failed", {"validation": validation})
    return validation


def _extract(bundle: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = bundle.get(key)
        if isinstance(value, dict):
            return value
    schema = bundle.get("schemaVersion")
    if schema == PROCESS_EXECUTION_RECEIPT_SCHEMA and "process" in keys:
        return bundle
    if isinstance(schema, str) and "model-usage-receipt" in schema and "usage" in keys:
        return bundle
    if isinstance(schema, str) and "review-mesh-result" in schema and "review" in keys:
        return bundle
    if "outcome" in keys and isinstance(bundle.get("status"), str):
        return bundle
    return None


def _lineage(bundle: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "operationId": _first_string(bundle, sources, "operationId") or "unbound-operation",
        "runId": _first_string(bundle, sources, "runId", "lineage.runId") or "run-unknown",
        "packageId": _first_string(bundle, sources, "packageId", "lineage.packageId") or "package-unknown",
        "taskId": _first_string(bundle, sources, "taskId", "task.id") or "task-unknown",
    }


def _statistical_provenance(
    bundle: dict[str, Any],
    sources: list[dict[str, Any]],
    review: dict[str, Any],
    lineage: dict[str, Any],
    source_digests: list[str],
    sample_identity: str,
) -> dict[str, Any]:
    source_class = _first_string(bundle, sources, "sourceClass", "statistical.sourceClass") or "UNDECLARED"
    derivation = _first_string(bundle, sources, "derivation", "statistical.derivation") or "receipt-projection"
    source_revision = _first_string(bundle, sources, "sourceRevision", "lineage.sourceRevision") or "UNAVAILABLE"
    source_lineage_digest = _first_digest(
        bundle,
        sources,
        "sourceLineageDigest",
        "lineage.sourceLineageDigest",
    ) or canonical_digest(lineage)
    producer_class = (
        _first_string(bundle, sources, "producerClass", "statistical.producerClass")
        or str(review.get("reviewerRole") or "UNDECLARED")
    )
    producer_identity_hash = _first_digest(
        bundle,
        sources,
        "producerIdentityHash",
        "reviewer.modelIdentityHash",
        "reviewer.hostIdentityHash",
    )
    identity_status = "DECLARED" if producer_identity_hash else "DERIVED_NON_AUTHORITATIVE"
    if not producer_identity_hash:
        producer_identity_hash = canonical_digest(
            {"producerClass": producer_class, "sourceDigests": source_digests}
        )
    statistical_identity = (
        sample_identity
        if _DIGEST_RE.fullmatch(sample_identity)
        else canonical_digest(
            {"sampleId": sample_identity, "lineage": lineage, "sourceDigests": source_digests}
        )
    )
    return {
        "sampleIdentity": statistical_identity,
        "sourceClass": source_class,
        "derivation": derivation,
        "sourceRevision": source_revision,
        "sourceLineageDigest": source_lineage_digest,
        "producerClass": producer_class,
        "producerIdentityHash": producer_identity_hash,
        "producerIdentityStatus": identity_status,
        "independenceClaimed": source_class == "INDEPENDENT_HOLDOUT" and identity_status == "DECLARED",
    }


def _request_projection(bundle: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    task_shape = _first_string(bundle, sources, "taskShape", "request.taskShape") or "unknown"
    phase = _first_string(bundle, sources, "phase", "review.phase") or "unknown"
    lifecycle_mode = _first_string(bundle, sources, "lifecycleMode", "mode") or "unknown"
    route = _route_class(_first_string(bundle, sources, "routeClass", "modelClass", "modelRoute.modelClass"))
    prompt = _first_string(bundle, sources, *_PROMPT_KEYS)
    prompt_bytes = len(prompt.encode("utf-8")) if prompt is not None else _first_int(bundle, sources, "requestBytes", "promptBytes")
    section_flags = {name: bool(pattern.search(prompt or "")) for name, pattern in _SECTION_MARKERS.items()}
    supplied_digest = _first_digest(bundle, sources, "requestShapeDigest", "promptTemplateDigest", "templateDigest")
    shape_digest = supplied_digest or canonical_digest({"taskShape": task_shape, "phase": phase, "routeClass": route, "promptBytes": prompt_bytes, "sectionFlags": section_flags})
    return {
        "taskShape": task_shape,
        "phase": phase,
        "lifecycleMode": lifecycle_mode,
        "routeClass": route,
        "requestShapeDigest": shape_digest,
        "promptBytes": max(0, prompt_bytes),
        "sectionFlags": section_flags,
    }


def _empty_review() -> dict[str, Any]:
    return {"status": "MISSING", "findingCount": 0, "severityCounts": {}, "acceptedCount": 0, "rejectedCount": 0, "disagreementCount": 0, "independenceStatus": "MISSING"}


def _usage_projection(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage_data = usage.get("usage") if isinstance(usage, dict) and isinstance(usage.get("usage"), dict) else usage or {}
    values = {key: _non_negative_int(usage_data.get(key)) for key in ("inputTokens", "outputTokens", "billableTokens", "toolCalls", "wallSeconds")}
    if not values["billableTokens"]:
        values["billableTokens"] = values["inputTokens"] + values["outputTokens"]
    attestation = usage.get("attestation") if isinstance(usage, dict) and isinstance(usage.get("attestation"), dict) else {}
    values["confidence"] = "ATTESTED" if attestation.get("status") == "ATTESTED" else ("ESTIMATED" if usage else "MISSING")
    values["attestationStatus"] = attestation.get("status") if attestation.get("status") in {"ATTESTED", "ESTIMATED", "MISSING"} else "MISSING"
    return values


def _process_projection(process: dict[str, Any] | None) -> dict[str, Any]:
    resources = process.get("resources") if isinstance(process, dict) and isinstance(process.get("resources"), dict) else {}
    result: dict[str, Any] = {}
    for source_key, output_key in (("cpuMs", "cpuMs"), ("peakMemoryMb", "peakMemoryMb"), ("processCount", "processCount")):
        metric = resources.get(source_key) if isinstance(resources.get(source_key), dict) else {}
        result[output_key] = {"value": metric.get("value") if isinstance(metric.get("value"), (int, float)) and not isinstance(metric.get("value"), bool) else None, "availability": metric.get("availability", "UNAVAILABLE") if metric.get("availability") in {"ATTESTED", "ESTIMATED", "UNAVAILABLE"} else "UNAVAILABLE"}
    retry = process.get("retry") if isinstance(process, dict) and isinstance(process.get("retry"), dict) else {}
    result["elapsedMs"] = _non_negative_int(_value_at(process or {}, "timing.elapsedMs"))
    result["retryCount"] = _non_negative_int(retry.get("count"))
    result["timeout"] = bool(process and process.get("timedOut"))
    result["cleanupStatus"] = _safe_status(_value_at(process or {}, "cleanup.status"), "MISSING")
    return result


def _quality_projection(bundle: dict[str, Any], outcome: dict[str, Any] | None, review: dict[str, Any]) -> dict[str, Any]:
    source = outcome or bundle
    status = _safe_status(source.get("status") or source.get("decision"), "UNKNOWN")
    corrections = _non_negative_int(_first_value(bundle, [outcome or {}, bundle], "correctionCount", "corrections", "remediationLoops"))
    disagreements = _non_negative_int(_first_value(bundle, [outcome or {}, bundle], "disagreementCount", "disagreements"))
    false_acceptance = bool(_first_value(bundle, [outcome or {}, bundle], "falseAcceptance", "falseAcceptanceClaim"))
    if corrections and status in {"PASS", "ACCEPTED", "READY_FOR_FINALIZATION"}:
        false_acceptance = bool(_first_value(bundle, [outcome or {}, bundle], "laterRejected", "laterCorrectionRequired"))
    return {
        "status": status,
        "falseAcceptance": false_acceptance,
        "correctionCount": corrections,
        "disagreementCount": max(disagreements, int(review.get("disagreementCount", 0))),
        "blocker": bool(source.get("blocker") or status in {"FAIL", "BLOCK", "BLOCKED", "REJECTED"}),
    }


def _attempt_projection(bundle: dict[str, Any], sources: list[dict[str, Any]], process: dict[str, Any] | None) -> dict[str, Any]:
    attempt = _first_int(bundle, sources, "attempt", "attemptNumber") or 1
    retries = max(_first_int(bundle, sources, "retryCount", "retries"), attempt - 1)
    timeouts = int(bool(process and process.get("timedOut"))) + _first_int(bundle, sources, "timeoutCount")
    return {"count": max(1, attempt), "retryCount": max(0, retries), "timeoutCount": max(0, timeouts)}


def _attestation_projection(review: dict[str, Any], usage: dict[str, Any], process: dict[str, Any]) -> dict[str, Any]:
    statuses = {
        "review": review.get("independenceStatus", "MISSING"),
        "usage": usage.get("attestationStatus", "MISSING"),
        "process": _resource_attestation(process),
    }
    confirmed = [value for value in statuses.values() if value in {"ATTESTED", "INDEPENDENT"}]
    overall = "ATTESTED" if len(confirmed) == len(statuses) else ("MIXED" if confirmed else "MISSING")
    return {"components": statuses, "overall": overall}


def _resource_attestation(process: dict[str, Any]) -> str:
    if not process:
        return "MISSING"
    values = [item.get("availability") for item in process.values() if isinstance(item, dict) and "availability" in item]
    return "ATTESTED" if values and all(value == "ATTESTED" for value in values) else ("MIXED" if values else "MISSING")


def _first_string(root: dict[str, Any], sources: list[dict[str, Any]], *paths: str) -> str | None:
    for payload in [root, *sources]:
        for path in paths:
            value = _value_at(payload, path)
            if isinstance(value, str) and value:
                return value
    return None


def _first_digest(root: dict[str, Any], sources: list[dict[str, Any]], *paths: str) -> str | None:
    value = _first_string(root, sources, *paths)
    return value if value and _DIGEST_RE.fullmatch(value) else None


def _first_int(root: dict[str, Any], sources: list[dict[str, Any]], *paths: str) -> int:
    for payload in [root, *sources]:
        for path in paths:
            value = _value_at(payload, path)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return 0


def _first_value(root: dict[str, Any], sources: list[dict[str, Any]], *paths: str) -> Any:
    for payload in [root, *sources]:
        for path in paths:
            value = _value_at(payload, path)
            if value is not None:
                return value
    return None


def _value_at(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _non_negative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _safe_status(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _route_class(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized if normalized in _ROUTE_CLASSES else "external-neutral"


def _assert_private_projection(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "").replace("_", "").lower()
            if normalized in {item.replace("-", "").replace("_", "").lower() for item in _FORBIDDEN_KEYS}:
                raise LifecycleError("audit-sample-sensitive-field", "audit sample contains a forbidden field", {"field": str(key)})
            if isinstance(item, str) and (contains_local_absolute_path(item) or "-----BEGIN" in item):
                raise LifecycleError("audit-sample-sensitive-value", "audit sample contains a sensitive value")
            _assert_private_projection(item)
    elif isinstance(value, list):
        for item in value:
            _assert_private_projection(item)


__all__ = [
    "build_audit_sample",
    "build_audit_samples",
    "require_audit_sample_pass",
    "validate_audit_sample",
]
