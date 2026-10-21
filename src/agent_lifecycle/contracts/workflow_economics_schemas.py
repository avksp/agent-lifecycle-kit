"""Comparable workload contracts for workflow economics evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_IMPLEMENTATION_REQUIRED = ["role", "sourceRevision", "coreVersion", "publicationVersions"]
_SOURCE_STATUS = ["MEASURED", "ESTIMATED", "TIME_WINDOW_ONLY", "UNAVAILABLE"]
_AGGREGATE_STATUS = [*_SOURCE_STATUS, "MIXED", "PARTIAL"]
_NON_WINDOW_AGGREGATE_STATUS = [status for status in _AGGREGATE_STATUS if status != "TIME_WINDOW_ONLY"]
_WORKFLOW_METRIC_KEYS = (
    "modelInputTokens",
    "modelCachedInputTokens",
    "modelOutputTokens",
    "modelTurns",
    "toolCalls",
    "toolWallMs",
    "toolOutputBytes",
    "packetBytes",
    "controllerTransitions",
    "requiredGateCount",
    "passedGateCount",
    "failedGateCount",
    "elapsedWallMs",
    "parallelComputeMs",
)
_METRIC_VALUE = {"type": ["integer", "null"], "minimum": 0, "maximum": (1 << 63) - 1}
_SOURCE_METRIC = {
    "type": "object",
    "required": ["status", "value"],
    "properties": {"status": {"enum": _SOURCE_STATUS}, "value": _METRIC_VALUE},
    "additionalProperties": False,
}
_AGGREGATE_METRIC = {
    "type": "object",
    "required": ["status", "value"],
    "properties": {"status": {"enum": _AGGREGATE_STATUS}, "value": _METRIC_VALUE},
    "additionalProperties": False,
}


def _aggregate_metric_schema(name: str) -> dict[str, Any]:
    statuses = _AGGREGATE_STATUS if name in {"elapsedWallMs", "toolWallMs"} else _NON_WINDOW_AGGREGATE_STATUS
    return {
        "type": "object",
        "required": ["status", "value"],
        "properties": {"status": {"enum": statuses}, "value": _METRIC_VALUE},
        "additionalProperties": False,
    }


WORKFLOW_ECONOMICS_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-goal-progress-observation.v1": open_object_schema(
        "agent-goal-progress-observation.v1",
        required=[
            "schemaVersion",
            "state",
            "reasonCode",
            "nonproductiveRounds",
            "initialContext",
            "observationCount",
            "historyDigest",
            "goalDigest",
            "phaseDigest",
            "subjectDigest",
            "sourceRevision",
            "stateRevision",
            "qualification",
            "authorityClaimed",
            "productionPromotionClaimed",
            "progressDigest",
        ],
        properties={
            "state": {"enum": ["ADVANCING", "STALLED", "EXPECTED_WAIT", "UNAVAILABLE"]},
            "observationCount": {"type": "integer", "minimum": 0, "maximum": 64},
            "nonproductiveRounds": {"type": "integer", "minimum": 0, "maximum": 64},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "progressDigest": _DIGEST,
        },
    ),
    "agent-workflow-resource-summary.v1": open_object_schema(
        "agent-workflow-resource-summary.v1",
        required=[
            "schemaVersion",
            "status",
            "sourceAvailabilityStatuses",
            "derivedAggregateStatuses",
            "sourceCount",
            "enclosingElapsedWall",
            "metrics",
            "productionPromotionClaimed",
            "summaryDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "sourceAvailabilityStatuses": {"const": _SOURCE_STATUS},
            "derivedAggregateStatuses": {"const": ["MIXED", "PARTIAL"]},
            "sourceCount": {"type": "integer", "minimum": 0, "maximum": 1024},
            "enclosingElapsedWall": _SOURCE_METRIC,
            "metrics": {
                "type": "object",
                "required": list(_WORKFLOW_METRIC_KEYS),
                "properties": {name: _aggregate_metric_schema(name) for name in _WORKFLOW_METRIC_KEYS},
                "additionalProperties": False,
            },
            "productionPromotionClaimed": {"const": False},
            "summaryDigest": _DIGEST,
        },
    ),
    "agent-workflow-resource-summary-validation.v1": open_object_schema(
        "agent-workflow-resource-summary-validation.v1",
        required=["schemaVersion", "status", "blockers", "summaryDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "summaryDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "validationDigest": _DIGEST,
        },
    ),
    "agent-comparable-workload-identity.v1": open_object_schema(
        "agent-comparable-workload-identity.v1",
        required=[
            "schemaVersion",
            "name",
            "fixtureShapeDigest",
            "workloadInputDigest",
            "environmentDigest",
            "requiredGateFloorDigest",
            "workloadIdentityDigest",
        ],
        properties={
            "name": {"type": "string", "minLength": 1, "maxLength": 256},
            "fixtureShapeDigest": _DIGEST,
            "workloadInputDigest": _DIGEST,
            "environmentDigest": _DIGEST,
            "requiredGateFloorDigest": _DIGEST,
            "workloadIdentityDigest": _DIGEST,
        },
    ),
    "agent-workflow-economics-comparison-pair.v1": open_object_schema(
        "agent-workflow-economics-comparison-pair.v1",
        required=[
            "schemaVersion",
            "status",
            "workloadIdentity",
            "before",
            "after",
            "declaredBeforeMeasurements",
            "productionPromotionClaimed",
            "comparisonPairId",
        ],
        properties={
            "status": {"const": "DECLARED"},
            "workloadIdentity": {"type": "object"},
            "before": {"type": "object", "required": _IMPLEMENTATION_REQUIRED},
            "after": {"type": "object", "required": _IMPLEMENTATION_REQUIRED},
            "declaredBeforeMeasurements": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "comparisonPairId": _DIGEST,
        },
    ),
    "agent-workflow-economics-measurement.v1": open_object_schema(
        "agent-workflow-economics-measurement.v1",
        required=[
            "schemaVersion",
            "role",
            "comparisonPairId",
            "workloadIdentityDigest",
            "implementation",
            "commandCount",
            "outputBytes",
            "wallSeconds",
            "tokenUsage",
            "measurementDigest",
        ],
        properties={
            "role": {"enum": ["before", "after"]},
            "comparisonPairId": _DIGEST,
            "workloadIdentityDigest": _DIGEST,
            "implementation": {"type": "object"},
            "commandCount": {"type": "integer", "minimum": 1},
            "outputBytes": {"type": "integer", "minimum": 0},
            "wallSeconds": {"type": "number", "minimum": 0},
            "tokenUsage": {"oneOf": [{"type": "integer", "minimum": 0}, {"const": "UNAVAILABLE"}]},
            "measurementDigest": _DIGEST,
        },
    ),
    "agent-workflow-economics-comparison-validation.v1": open_object_schema(
        "agent-workflow-economics-comparison-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "comparisonPairId",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "NO_COMPARABLE_BASELINE"]},
            "comparisonPairId": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 32},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_comparable_workload_identity(
    *,
    name: str,
    fixture_shape_digest: str,
    workload_input_digest: str,
    environment_digest: str,
    required_gate_floor_digest: str,
) -> dict[str, Any]:
    """Build the implementation-independent identity used by both measurements."""

    body = {
        "schemaVersion": "agent-comparable-workload-identity.v1",
        "name": name,
        "fixtureShapeDigest": fixture_shape_digest,
        "workloadInputDigest": workload_input_digest,
        "environmentDigest": environment_digest,
        "requiredGateFloorDigest": required_gate_floor_digest,
    }
    return {**body, "workloadIdentityDigest": canonical_digest(body)}


def build_workflow_economics_comparison_pair(
    *,
    workload_identity: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Declare the exact before/after pair before either measurement is recorded."""

    body = {
        "schemaVersion": "agent-workflow-economics-comparison-pair.v1",
        "status": "DECLARED",
        "workloadIdentity": workload_identity,
        "before": {**before, "role": "before"},
        "after": {**after, "role": "after"},
        "declaredBeforeMeasurements": True,
        "productionPromotionClaimed": False,
    }
    return {**body, "comparisonPairId": canonical_digest(body)}


def validate_workflow_economics_comparison(
    declaration: dict[str, Any],
    before_measurement: dict[str, Any],
    after_measurement: dict[str, Any],
) -> dict[str, Any]:
    """Validate exact pair membership without substituting missing telemetry."""

    blockers: list[dict[str, Any]] = []
    workload_identity = declaration.get("workloadIdentity")
    if not isinstance(workload_identity, dict):
        workload_identity = {}
        blockers.append({"code": "comparison-workload-identity-invalid"})
    else:
        identity_body = {key: value for key, value in workload_identity.items() if key != "workloadIdentityDigest"}
        if workload_identity.get("workloadIdentityDigest") != canonical_digest(identity_body):
            blockers.append({"code": "comparison-workload-identity-digest-invalid"})

    pair_id = declaration.get("comparisonPairId")
    declaration_body = {key: value for key, value in declaration.items() if key != "comparisonPairId"}
    if pair_id != canonical_digest(declaration_body):
        blockers.append({"code": "comparison-pair-digest-invalid"})

    expected_identity = workload_identity.get("workloadIdentityDigest")
    for role, expected, measurement in (
        ("before", declaration.get("before"), before_measurement),
        ("after", declaration.get("after"), after_measurement),
    ):
        measurement_body = {key: value for key, value in measurement.items() if key != "measurementDigest"}
        if measurement.get("measurementDigest") != canonical_digest(measurement_body):
            blockers.append({"code": "comparison-measurement-digest-invalid", "role": role})
        if measurement.get("role") != role:
            blockers.append({"code": "comparison-role-mismatch", "role": role})
        if measurement.get("comparisonPairId") != pair_id:
            blockers.append({"code": "comparison-pair-mismatch", "role": role})
        if measurement.get("workloadIdentityDigest") != expected_identity:
            blockers.append({"code": "comparison-workload-mismatch", "role": role})
        if measurement.get("implementation") != expected:
            blockers.append({"code": "comparison-implementation-mismatch", "role": role})
        if not _valid_token_usage(measurement.get("tokenUsage")):
            blockers.append({"code": "comparison-token-usage-invalid", "role": role})
    body = {
        "schemaVersion": "agent-workflow-economics-comparison-validation.v1",
        "status": "NO_COMPARABLE_BASELINE" if blockers else "PASS",
        "comparisonPairId": pair_id if isinstance(pair_id, str) else None,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _valid_token_usage(value: Any) -> bool:
    return value == "UNAVAILABLE" or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


MAX_SESSION_COUNTER = 10**9
SESSION_USAGE_SCHEMA = "agent-provider-session-usage.v1"
SESSION_COUNTERS = (
    "inputTokens",
    "cachedInputTokens",
    "nonCachedInputTokens",
    "outputTokens",
    "totalTokens",
    "invocations",
    "wallSeconds",
)
SESSION_BINDINGS = (
    "sessionDigest",
    "sourceRevision",
    "subjectDigest",
    "assignmentDigest",
)


def validate_cumulative_session_usage(
    receipt: Any,
    *,
    binding: dict[str, Any],
    qualification: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check qualified provider counters, never prompt size or legacy defaults.

    The integration must obtain qualification from its existing independently
    checked adapter/profile source. A reviewer output cannot supply that proof.
    This pure join does not attest a host or validate provider credentials.
    """
    blockers: list[dict[str, str]] = []
    if not _session_shape(receipt):
        return {"status": "FAIL", "blockers": [{"code": "session-usage-invalid"}]}
    if any(receipt[key] != binding.get(key) for key in SESSION_BINDINGS):
        blockers.append({"code": "session-usage-binding-mismatch"})
    proof = qualification if isinstance(qualification, dict) else {}
    if not (
        proof.get("status") == "PASS"
        and proof.get("provenanceValidated") is True
        and proof.get("sourceArtifactDigest") == receipt["sourceArtifactDigest"]
        and proof.get("receiptDigest") == receipt["receiptDigest"]
        and all(proof.get(key) == binding.get(key) for key in SESSION_BINDINGS)
    ):
        blockers.append({"code": "session-usage-provenance-unavailable"})
    if previous is not None:
        if not _session_shape(previous) or any(previous[key] != receipt[key] for key in SESSION_BINDINGS):
            blockers.append({"code": "session-usage-previous-binding-invalid"})
        elif receipt["sequence"] <= previous["sequence"] or any(
            receipt["usage"][key] < previous["usage"][key] for key in SESSION_COUNTERS
        ):
            blockers.append({"code": "session-usage-reset-or-decrease"})
    if limits is not None:
        if (
            not isinstance(limits, dict)
            or not limits
            or set(limits) - set(SESSION_COUNTERS)
            or any(type(value) is not int or not 0 <= value <= MAX_SESSION_COUNTER for value in limits.values())
        ):
            blockers.append({"code": "session-usage-limit-invalid"})
        elif any(receipt["usage"][key] > limit for key, limit in limits.items()):
            blockers.append({"code": "session-usage-budget-exceeded"})
    return {
        "status": "FAIL" if blockers else "PASS",
        "blockers": blockers,
        "receiptDigest": receipt["receiptDigest"],
        "usage": dict(receipt["usage"]),
        "basis": "CUMULATIVE_PROVIDER_SESSION",
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }


def _session_shape(value: Any) -> bool:
    fields = {
        "schemaVersion",
        *SESSION_BINDINGS,
        "sequence",
        "sourceArtifactDigest",
        "usage",
        "receiptDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return False
    usage = value["usage"]
    if (
        value["schemaVersion"] != SESSION_USAGE_SCHEMA
        or not all(
            _session_digest(value[key])
            for key in (
                "sessionDigest",
                "subjectDigest",
                "assignmentDigest",
                "sourceArtifactDigest",
                "receiptDigest",
            )
        )
        or not isinstance(value["sourceRevision"], str)
        or len(value["sourceRevision"]) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in value["sourceRevision"])
        or type(value["sequence"]) is not int
        or not 0 <= value["sequence"] <= MAX_SESSION_COUNTER
        or not isinstance(usage, dict)
        or set(usage) != set(SESSION_COUNTERS)
        or any(type(item) is not int or not 0 <= item <= MAX_SESSION_COUNTER for item in usage.values())
    ):
        return False
    return (
        usage["cachedInputTokens"] + usage["nonCachedInputTokens"] == usage["inputTokens"]
        and usage["inputTokens"] + usage["outputTokens"] == usage["totalTokens"]
        and value["receiptDigest"]
        == canonical_digest({key: item for key, item in value.items() if key != "receiptDigest"})
    )


def check_job_observation(
    value: dict[str, Any],
    request: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    *,
    max_attempts: int,
) -> None:
    if "observation" not in value:
        return
    observation = value["observation"]
    fields = {
        "subjectDigest",
        "assignmentDigest",
        "requestDigest",
        "attempt",
        "deliveryAttempt",
        "semanticRound",
        "remoteState",
        "localState",
        "semanticStatus",
        "responseDigest",
        "sessionUsage",
    }
    if not isinstance(observation, dict) or set(observation) != fields:
        blockers.append({"code": "external-job-observation-invalid"})
        return
    valid = (
        all(_session_digest(observation[key]) for key in ("subjectDigest", "assignmentDigest", "requestDigest"))
        and all(
            type(observation[key]) is int and 1 <= observation[key] <= max_attempts
            for key in (
                "attempt",
                "deliveryAttempt",
                "semanticRound",
            )
        )
        and observation["remoteState"] in ("UNKNOWN", "RUNNING", "TERMINAL")
        and observation["localState"] in ("PENDING", "LOST", "RECOVERED", "COMPLETE", "FAILED")
        and observation["semanticStatus"] in ("UNAVAILABLE", "PASS", "FAIL", "INCOMPLETE")
        and (observation["responseDigest"] is None or _session_digest(observation["responseDigest"]))
        and observation["attempt"] == value.get("attempt")
        and observation["requestDigest"] == value.get("requestDigest")
    )
    if observation["localState"] in ("COMPLETE", "RECOVERED"):
        valid = valid and observation["responseDigest"] is not None and observation["remoteState"] == "TERMINAL"
    session = observation["sessionUsage"]
    if session is not None:
        valid = valid and _session_shape(session)
        if isinstance(session, dict):
            valid = valid and all(session.get(key) == observation[key] for key in ("subjectDigest", "assignmentDigest"))
            if request is not None:
                valid = valid and session.get("sourceRevision") == request.get("sourceRevision")
    if value.get("schemaVersion") == "agent-external-job-result.v1" and observation["responseDigest"] is not None:
        valid = valid and observation["responseDigest"] == value.get("outputDigest")
    if value.get("schemaVersion") == "agent-external-job-result.v1":
        verdict = value.get("verdict")
        if verdict in ("PASS", "FAIL"):
            valid = valid and observation["semanticStatus"] == verdict
            if value.get("complete") is True:
                valid = (
                    valid
                    and observation["remoteState"] == "TERMINAL"
                    and observation["localState"]
                    in (
                        "COMPLETE",
                        "RECOVERED",
                    )
                    and observation["responseDigest"] is not None
                )
        if value.get("blockingEligible") is True:
            valid = valid and value.get("complete") is True and observation["semanticStatus"] == verdict
    if not valid:
        blockers.append({"code": "external-job-observation-binding-invalid"})


def _session_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


WORKFLOW_ECONOMICS_SCHEMAS[SESSION_USAGE_SCHEMA] = open_object_schema(
    SESSION_USAGE_SCHEMA,
    required=["schemaVersion", *SESSION_BINDINGS, "sequence", "sourceArtifactDigest", "usage", "receiptDigest"],
    properties={
        "usage": {
            "type": "object",
            "required": list(SESSION_COUNTERS),
            "properties": {
                key: {"type": "integer", "minimum": 0, "maximum": MAX_SESSION_COUNTER} for key in SESSION_COUNTERS
            },
            "additionalProperties": False,
        },
        "receiptDigest": _DIGEST,
    },
)

__all__ = [
    "WORKFLOW_ECONOMICS_SCHEMAS",
    "build_comparable_workload_identity",
    "build_workflow_economics_comparison_pair",
    "validate_workflow_economics_comparison",
]
