"""Closed shapes for explicitly selected, unmetered source authoring.

Shape validity supplies no dispatch, financial settlement or host assurance.
The workflow consumer must independently select the frozen policy and frontier.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.model_classes import ALLOWED_MODEL_CLASSES
from agent_lifecycle.contracts.paths import normalize_repo_path

SOURCE_USAGE_POLICY = "alk-source-usage-completion-policy.v1"
SOURCE_USAGE_RECEIPT = "agent-lifecycle-model-usage-receipt.v2"
SOURCE_RISK_PROFILE = "agent-risk-execution-profile.v2"
SOURCE_WINDOW_BINDING = "alk-source-usage-window-binding.v1"
SOURCE_REGISTRY_PREFIX = "alk-source-usage-registry-prefix.v1"
SOURCE_CURRENT_REGISTRY = "alk-source-usage-current-registry.v1"
SOURCE_USAGE_MODE = "SOURCE_AUTHORING_LIMITED"
SOURCE_USAGE_METRICS = (
    "inputTokens",
    "outputTokens",
    "billableTokens",
    "cumulativeContextBytes",
    "toolCalls",
    "wallSeconds",
    "invocations",
)
SOURCE_USAGE_ROLES = (
    "coordinator",
    "worker",
    "check",
    "auditor",
    "retry",
    "compaction",
    "closeout",
)
MAX_SOURCE_USAGE_BYTES = 65_536
MAX_CURRENT_SOURCE_REGISTRY_BYTES = 1_048_576
MAX_SOURCE_USAGE_BINDINGS = 128
MAX_SAFE_INTEGER = 2**53 - 1

_POLICY_KEYS = {
    "schemaVersion",
    "mode",
    "adapterId",
    "adapterHost",
    "taskIds",
    "allowedModelClasses",
    "accountingKind",
    "openingRef",
    "sourceAuthoringRegistryRef",
    "actualCapConformance",
    "financialClosureAllowed",
}
_LINEAGE_KEYS = {
    "runId",
    "packageId",
    "taskId",
    "attempt",
    "planDigest",
    "sourceRevision",
    "routeDecisionDigest",
}
_RECEIPT_KEYS = {
    "schemaVersion",
    "operationId",
    "host",
    "modelClass",
    "providerModelHash",
    "lineage",
    "attestation",
    "usage",
    "metricStates",
    "usageMode",
    "policyDigest",
    "sourceAuthoringRegistryDigest",
    "ledgerRef",
    "currentAdmissionRef",
    "actorId",
    "sourceContextRefs",
    "currentRegistryRef",
}
_BINDING_KEYS = {
    "schemaVersion",
    "bindingKind",
    "semanticOperationId",
    "runId",
    "packageId",
    "taskId",
    "attempt",
    "planDigest",
    "sourceRevision",
    "routeDecisionDigest",
    "sourceUsagePolicyDigest",
    "actorId",
    "role",
    "originalWindowId",
    "originalCostScope",
    "sourceInputSubjectDigest",
}
_RISK_KEYS = {
    "schemaVersion",
    "status",
    "requestedRisk",
    "planRiskTier",
    "resolvedRiskTier",
    "adapterId",
    "operationId",
    "runId",
    "packageId",
    "planRevision",
    "planDigest",
    "taskId",
    "sourceRevision",
    "qualityFloorDecision",
    "modelRoute",
    "resourceCaps",
    "usageEvidence",
    "policyDigest",
    "hostProfileDigest",
    "blockers",
    "modelCallsStarted",
    "hostLaunchStarted",
    "productionPromotionClaimed",
    "profileDigest",
    "usageMode",
    "sourceUsagePolicyDigest",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LifecycleError("scoped-usage-shape-invalid", message)


def _closed(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, f"{label} has invalid fields")
    value = _validated_cast(dict[str, Any], value)
    return value


def _bounded(value: Any) -> None:
    count = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        _require(depth <= 32 and count <= 4096, "scoped usage tree exceeds its bound")
        if isinstance(item, dict):
            _require(all(isinstance(key, str) for key in item), "JSON keys must be strings")
            for nested in item.values():
                visit(nested, depth + 1)
        elif isinstance(item, list):
            for nested in item:
                visit(nested, depth + 1)
        elif type(item) is int:
            _require(abs(item) <= MAX_SAFE_INTEGER, "integer exceeds the safe bound")
        elif type(item) is float:
            _require(math.isfinite(item), "nonfinite JSON value is forbidden")
        else:
            _require(item is None or type(item) in (str, bool), "unsupported JSON value")

    visit(value, 0)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise LifecycleError("scoped-usage-shape-invalid", "invalid JSON encoding") from exc
    _require(len(raw) <= MAX_SOURCE_USAGE_BYTES, "scoped usage exceeds its byte bound")


def _id(value: Any, label: str) -> None:
    try:
        valid = isinstance(value, str) and bool(value) and len(value.encode("utf-8")) <= 256
    except UnicodeError:
        valid = False
    _require(valid, f"{label} must be a bounded nonempty ID")


def _digest(value: Any, label: str) -> None:
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"{label} must be a lowercase SHA256",
    )
    value = _validated_cast(str, value)


def _counter(value: Any, label: str, *, minimum: int = 0) -> None:
    _require(type(value) is int and minimum <= value <= MAX_SAFE_INTEGER, f"{label} must be a safe integer")
    value = _validated_cast(int, value)


def validate_source_ref_shape(value: Any) -> dict[str, Any]:
    ref = _closed(value, {"path", "sha256", "bytes"}, "source reference")
    _require(
        isinstance(ref["path"], str) and len(ref["path"].encode("utf-8")) <= 4096,
        "source reference path exceeds its bound",
    )
    _require(normalize_repo_path(ref["path"]) == ref["path"], "source path is not canonical")
    _digest(ref["sha256"], "source SHA256")
    _counter(ref["bytes"], "source bytes", minimum=1)
    return ref


def validate_source_usage_policy_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    policy = _closed(value, _POLICY_KEYS, "source usage policy")
    _require(
        policy["schemaVersion"] == SOURCE_USAGE_POLICY and policy["mode"] == SOURCE_USAGE_MODE,
        "unsupported source usage policy",
    )
    for key in ("adapterId", "adapterHost"):
        _id(policy[key], key)

    for key in ("taskIds", "allowedModelClasses"):
        rows = policy[key]
        _require(
            isinstance(rows, list) and 0 < len(rows) <= MAX_SOURCE_USAGE_BINDINGS,
            f"{key} must be a bounded nonempty list",
        )
        rows = _validated_cast(list[Any], rows)
        for row in rows:
            _id(row, key)
        _require(len(rows) == len(set(rows)), f"{key} contains duplicates")
    _require(
        set(policy["allowedModelClasses"]) <= ALLOWED_MODEL_CLASSES - {"no-model"},
        "source usage model classes are unsupported",
    )
    _require(
        policy["accountingKind"] == "EXISTING_DECLARED_COORDINATOR_LEDGER"
        and policy["actualCapConformance"] == "UNAVAILABLE"
        and policy["financialClosureAllowed"] is False,
        "limited policy cannot claim measured or closed finances",
    )
    for key in ("openingRef", "sourceAuthoringRegistryRef"):
        ref = validate_source_ref_shape(policy[key])
        _require(ref["bytes"] <= MAX_SOURCE_USAGE_BYTES, "frozen source exceeds its bound")
    return policy


def validate_source_usage_receipt_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    receipt = _closed(value, _RECEIPT_KEYS, "source usage receipt")
    _require(
        receipt["schemaVersion"] == SOURCE_USAGE_RECEIPT and receipt["usageMode"] == SOURCE_USAGE_MODE,
        "unsupported scoped receipt",
    )
    for key in ("operationId", "host", "modelClass", "providerModelHash", "actorId"):
        _id(receipt[key], key)

    _require(
        receipt["modelClass"] in ALLOWED_MODEL_CLASSES - {"no-model"}, "source usage receipt requires a model class"
    )
    lineage = _closed(receipt["lineage"], _LINEAGE_KEYS, "source usage lineage")
    for key in ("runId", "packageId", "taskId", "sourceRevision"):
        _id(lineage[key], key)
    _counter(lineage["attempt"], "attempt", minimum=1)
    for key in ("planDigest", "routeDecisionDigest"):
        _digest(lineage[key], key)
    for key in ("policyDigest", "sourceAuthoringRegistryDigest"):
        _digest(receipt[key], key)
    _require(
        receipt["attestation"] == {"source": "alk-declared", "status": "UNAVAILABLE"},
        "source usage cannot carry a host attestation",
    )
    usage = _closed(receipt["usage"], set(SOURCE_USAGE_METRICS), "source usage metrics")
    states = _closed(receipt["metricStates"], set(SOURCE_USAGE_METRICS), "metric states")
    _require(
        all(usage[key] is None and states[key] == "UNAVAILABLE" for key in SOURCE_USAGE_METRICS),
        "unknown usage must remain null/UNAVAILABLE",
    )
    for key in ("ledgerRef", "currentAdmissionRef", "currentRegistryRef"):
        validate_source_ref_shape(receipt[key])
    _require(
        receipt["currentRegistryRef"]["bytes"] <= MAX_CURRENT_SOURCE_REGISTRY_BYTES,
        "current registry exceeds its bound",
    )
    refs = receipt["sourceContextRefs"]
    _require(
        isinstance(refs, list) and len(refs) <= MAX_SOURCE_USAGE_BINDINGS,
        "source context references exceed their bound",
    )
    refs = _validated_cast(list[Any], refs)
    for ref in refs:
        validate_source_ref_shape(ref)
    _require(len({ref["path"] for ref in refs}) == len(refs), "duplicate source context path")
    return receipt


def validate_source_window_binding(value: Any) -> dict[str, Any]:
    _bounded(value)
    binding = _closed(value, _BINDING_KEYS, "source window binding")
    _require(
        binding["schemaVersion"] == SOURCE_WINDOW_BINDING
        and binding["bindingKind"] == "DECLARED_COORDINATOR_WORK_WINDOW"
        and binding["role"] == "coordinator"
        and binding["originalCostScope"] == "COORDINATOR_FINITE_SOURCE_AUTHORING_WINDOW",
        "unsupported original source window identity",
    )
    for key in ("semanticOperationId", "runId", "packageId", "taskId", "sourceRevision", "actorId", "originalWindowId"):
        _id(binding[key], key)
    _counter(binding["attempt"], "attempt", minimum=1)
    for key in ("planDigest", "routeDecisionDigest", "sourceUsagePolicyDigest", "sourceInputSubjectDigest"):
        _digest(binding[key], key)
    return binding


def validate_source_registry_prefix_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    prefix = _closed(
        value,
        {
            "schemaVersion",
            "openingHeadSha256",
            "requiredRoles",
            "ownerBindings",
            "historicalSourceRefs",
            "unknownIntervals",
        },
        "source registry prefix",
    )
    _require(prefix["schemaVersion"] == SOURCE_REGISTRY_PREFIX, "unsupported registry prefix")
    _digest(prefix["openingHeadSha256"], "opening head SHA256")
    _require(prefix["requiredRoles"] == list(SOURCE_USAGE_ROLES), "registry roles must be explicit")
    owners = prefix["ownerBindings"]
    _require(
        isinstance(owners, list) and 0 < len(owners) <= MAX_SOURCE_USAGE_BINDINGS,
        "registry owner bindings are missing or excessive",
    )
    owners = _validated_cast(list[Any], owners)
    identities = set()
    for owner in owners:
        _require(
            isinstance(owner, dict) and {"actorId", "role"} <= set(owner) <= {"actorId", "role", "meaning"},
            "invalid registry owner binding",
        )
        owner = _validated_cast(dict[str, Any], owner)
        _id(owner["actorId"], "actorId")
        _require(owner["role"] in SOURCE_USAGE_ROLES, "invalid registry role")
        identities.add((owner["actorId"], owner["role"]))
    _require(len(identities) == len(owners), "duplicate owner/role binding")
    for key in ("historicalSourceRefs", "unknownIntervals"):
        _require(
            isinstance(prefix[key], list) and len(prefix[key]) <= MAX_SOURCE_USAGE_BINDINGS, f"{key} exceeds its bound"
        )
    for ref in prefix["historicalSourceRefs"]:
        validate_source_ref_shape(ref)
    _require(
        all(isinstance(row, dict) for row in prefix["unknownIntervals"]),
        "unknown intervals must preserve original descriptors",
    )
    return prefix


def validate_limited_risk_profile_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    profile = _closed(value, _RISK_KEYS, "limited risk profile")
    _require(
        profile["schemaVersion"] == SOURCE_RISK_PROFILE and profile["usageMode"] == SOURCE_USAGE_MODE,
        "unsupported limited risk profile",
    )
    _digest(profile["sourceUsagePolicyDigest"], "source usage policy digest")
    _require(profile["usageEvidence"] == limited_usage_evidence(), "invalid limited risk evidence")
    _require(
        profile["profileDigest"]
        == canonical_digest({key: item for key, item in profile.items() if key != "profileDigest"}),
        "limited risk profile digest mismatch",
    )
    return profile


def limited_usage_evidence() -> dict[str, Any]:
    return {
        "required": True,
        "hostAttestationRequired": False,
        "requiredMetrics": ["billableTokens", "invocations", "wallSeconds"],
        "estimatesAccepted": False,
        "actualCapConformance": "UNAVAILABLE",
        "usageMode": SOURCE_USAGE_MODE,
    }


def _schema(schema_id: str, keys: set[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(keys),
        "properties": {**{key: {} for key in keys}, "schemaVersion": {"const": schema_id}, **properties},
    }


_ID_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 256}
_DIGEST_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_REF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "sha256", "bytes"],
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
        "sha256": _DIGEST_SCHEMA,
        "bytes": {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER},
    },
}
_LIST_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_SOURCE_USAGE_BINDINGS,
    "uniqueItems": True,
    "items": _ID_SCHEMA,
}
SCOPED_USAGE_SCHEMAS = {
    SOURCE_USAGE_POLICY: _schema(
        SOURCE_USAGE_POLICY,
        _POLICY_KEYS,
        {
            "mode": {"const": SOURCE_USAGE_MODE},
            "adapterId": _ID_SCHEMA,
            "adapterHost": _ID_SCHEMA,
            "taskIds": _LIST_SCHEMA,
            "allowedModelClasses": {**_LIST_SCHEMA, "items": {**_ID_SCHEMA, "not": {"const": "no-model"}}},
            "accountingKind": {"const": "EXISTING_DECLARED_COORDINATOR_LEDGER"},
            "openingRef": _REF_SCHEMA,
            "sourceAuthoringRegistryRef": _REF_SCHEMA,
            "actualCapConformance": {"const": "UNAVAILABLE"},
            "financialClosureAllowed": {"const": False},
        },
    ),
    SOURCE_USAGE_RECEIPT: _schema(
        SOURCE_USAGE_RECEIPT,
        _RECEIPT_KEYS,
        {
            **{key: _ID_SCHEMA for key in ("operationId", "host", "modelClass", "providerModelHash", "actorId")},
            "modelClass": {**_ID_SCHEMA, "not": {"const": "no-model"}},
            "usageMode": {"const": SOURCE_USAGE_MODE},
            "policyDigest": _DIGEST_SCHEMA,
            "sourceAuthoringRegistryDigest": _DIGEST_SCHEMA,
            "lineage": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_LINEAGE_KEYS),
                "properties": {
                    **{key: _ID_SCHEMA for key in ("runId", "packageId", "taskId", "sourceRevision")},
                    "attempt": {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER},
                    "planDigest": _DIGEST_SCHEMA,
                    "routeDecisionDigest": _DIGEST_SCHEMA,
                },
            },
            "attestation": {"const": {"source": "alk-declared", "status": "UNAVAILABLE"}},
            "usage": {
                "type": "object",
                "additionalProperties": False,
                "required": list(SOURCE_USAGE_METRICS),
                "properties": {key: {"type": "null"} for key in SOURCE_USAGE_METRICS},
            },
            "metricStates": {
                "type": "object",
                "additionalProperties": False,
                "required": list(SOURCE_USAGE_METRICS),
                "properties": {key: {"const": "UNAVAILABLE"} for key in SOURCE_USAGE_METRICS},
            },
            **{key: _REF_SCHEMA for key in ("ledgerRef", "currentAdmissionRef", "currentRegistryRef")},
            "sourceContextRefs": {"type": "array", "maxItems": MAX_SOURCE_USAGE_BINDINGS, "items": _REF_SCHEMA},
        },
    ),
    SOURCE_RISK_PROFILE: _schema(
        SOURCE_RISK_PROFILE,
        _RISK_KEYS,
        {
            "usageMode": {"const": SOURCE_USAGE_MODE},
            "sourceUsagePolicyDigest": _DIGEST_SCHEMA,
            "usageEvidence": {"const": limited_usage_evidence()},
            "profileDigest": _DIGEST_SCHEMA,
        },
    ),
}


def populate_scoped_usage_schema_fields(legacy_risk_schema: dict[str, Any]) -> None:
    """Add constraints from immutable v1 objects without modifying them."""

    from copy import deepcopy

    from agent_lifecycle.contracts.context_model_schemas import CONTEXT_MODEL_SCHEMAS

    classes = sorted(ALLOWED_MODEL_CLASSES - {"no-model"})
    policy = SCOPED_USAGE_SCHEMAS[SOURCE_USAGE_POLICY]["properties"]
    receipt = SCOPED_USAGE_SCHEMAS[SOURCE_USAGE_RECEIPT]["properties"]
    policy["allowedModelClasses"]["items"] = {"enum": classes}
    receipt["modelClass"] = {"enum": classes}
    for key in ("openingRef", "sourceAuthoringRegistryRef"):
        policy[key] = deepcopy(_REF_SCHEMA)
        policy[key]["properties"]["bytes"]["maximum"] = MAX_SOURCE_USAGE_BYTES
    for key in ("ledgerRef", "currentAdmissionRef", "currentRegistryRef"):
        receipt[key] = deepcopy(_REF_SCHEMA)
        receipt[key]["properties"]["bytes"]["maximum"] = (
            MAX_CURRENT_SOURCE_REGISTRY_BYTES if key == "currentRegistryRef" else 131_072
        )
    receipt["sourceContextRefs"]["uniqueItems"] = True
    risk = SCOPED_USAGE_SCHEMAS[SOURCE_RISK_PROFILE]
    risk["properties"] = {
        **deepcopy(legacy_risk_schema["properties"]),
        **{key: value for key, value in risk["properties"].items() if value},
    }
    for key in ("adapterId", "operationId", "runId", "packageId", "taskId", "sourceRevision"):
        risk["properties"][key] = deepcopy(_ID_SCHEMA)
    for key in ("planDigest", "policyDigest", "profileDigest"):
        risk["properties"][key] = deepcopy(_DIGEST_SCHEMA)
    risk["properties"]["hostProfileDigest"] = {"anyOf": [_DIGEST_SCHEMA, {"type": "null"}]}
    route = deepcopy(CONTEXT_MODEL_SCHEMAS["agent-lifecycle-model-route-decision.v1"])
    route["properties"]["modelClass"] = {"enum": classes}
    route["properties"]["decisionDigest"] = deepcopy(_DIGEST_SCHEMA)
    risk["properties"]["modelRoute"] = route
    risk["properties"]["resourceCaps"] = {
        "type": "object",
        "required": ["maxBillableTokens", "maxInvocations", "maxWallSeconds"],
        "properties": {
            key: {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER}
            for key in ("maxBillableTokens", "maxInvocations", "maxWallSeconds")
        },
    }


SOURCE_RECOVERY_POLICY = "alk-source-usage-conflict-recovery-policy.v1"
SOURCE_RECOVERY_POLICY_V2 = "alk-source-usage-conflict-recovery-policy.v2"
SOURCE_RECOVERY_POLICY_V3 = "alk-source-usage-conflict-recovery-policy.v3"
SOURCE_CONFLICT_DISPOSITION = "alk-source-window-conflict-disposition.v1"
SOURCE_CONFLICT_DISPOSITION_V2 = "alk-source-window-conflict-disposition.v2"
SOURCE_CONFLICT_GRANT = "alk-source-conflict-controller-repair-grant.v1"
SOURCE_RECOVERY_REGISTRY = "alk-source-usage-current-registry.v2"
SOURCE_INVALID_ANNOTATION_REGISTRY = "alk-source-usage-current-registry.v3"


def validate_source_recovery_policy_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    version = value.get("schemaVersion") if isinstance(value, dict) else None
    _require(
        version in (SOURCE_RECOVERY_POLICY, SOURCE_RECOVERY_POLICY_V2, SOURCE_RECOVERY_POLICY_V3),
        "unsupported recovery policy",
    )
    refs_key = "dispositionRef" if version == SOURCE_RECOVERY_POLICY else "dispositionRefs"
    keys = {"schemaVersion", "originalOpeningRef", refs_key}
    if version == SOURCE_RECOVERY_POLICY_V3:
        keys.add("invalidAnnotationDispositionRef")
    result = _closed(value, keys, "recovery policy")
    opening = validate_source_ref_shape(result["originalOpeningRef"])
    _require(opening["bytes"] <= MAX_SOURCE_USAGE_BYTES, "recovery input exceeds bound")
    refs = [result[refs_key]] if version == SOURCE_RECOVERY_POLICY else result[refs_key]
    _require(isinstance(refs, list) and 1 <= len(refs) <= 16, "recovery requires 1..16 dispositions")
    refs = _validated_cast(list[Any], refs)
    for reference in refs:
        ref = validate_source_ref_shape(reference)
        _require(ref["bytes"] <= MAX_SOURCE_USAGE_BYTES, "recovery input exceeds bound")
    names = [ref["path"] for ref in refs]
    _require(names == sorted(set(names)), "recovery dispositions must be distinct and sorted")
    if version == SOURCE_RECOVERY_POLICY_V3:
        reference = validate_source_ref_shape(result["invalidAnnotationDispositionRef"])
        _require(reference["bytes"] <= MAX_SOURCE_USAGE_BYTES, "invalid annotation disposition exceeds bound")
    return result


def _validate_invalid_annotation_windows(windows: Any) -> None:
    _require(
        isinstance(windows, list) and 1 <= len(windows) <= 3, "invalid annotation disposition requires 1..3 exact pairs"
    )
    windows = _validated_cast(list[Any], windows)
    for row in windows:
        _closed(row, {"windowId", "admissionRef", "costRef", "originalBindingSha256"}, "invalid annotation window")
        _id(row["windowId"], "original window ID")
        _digest(row["originalBindingSha256"], "original binding digest")
        for key, name in (("admissionRef", "admission.json"), ("costRef", "cost.json")):
            reference = validate_source_ref_shape(row[key])
            _require(
                reference["path"] == row["windowId"] + "/" + name and reference["bytes"] <= 131_072,
                "invalid annotation pair changes original identity or bound",
            )
    names = [row["windowId"] for row in windows]
    _require(names == sorted(set(names)), "invalid annotation windows must be distinct and sorted")


def validate_source_invalid_annotation_disposition_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    refs = {
        "originalOpeningRef",
        "authorizingFinancialHeadRef",
        "scopeDecisionRef",
        "specificationRef",
        "specificationSubjectRef",
        "specificationReviewRef",
    }
    result = _closed(
        value,
        refs | {"schemaVersion", "dispositionId", "classification", "originalWindows"},
        "invalid annotation disposition",
    )
    _require(
        result["schemaVersion"] == "alk-source-invalid-annotation-disposition.v1"
        and result["classification"] == "FINANCIAL_HISTORY_ONLY_INVALID_SOURCE_ANNOTATION",
        "unsupported invalid annotation disposition",
    )
    _id(result["dispositionId"], "invalid annotation disposition ID")
    for key in refs:
        reference = validate_source_ref_shape(result[key])
        _require(reference["bytes"] <= MAX_SOURCE_USAGE_BYTES, "invalid annotation authority exceeds bound")
    _validate_invalid_annotation_windows(result["originalWindows"])
    return result


def validate_source_invalid_annotation_subject_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    refs = {"contractRef", "scopeDecisionRef", "originalOpeningRef", "prospectiveAdmissionProcedureRef"}
    result = _closed(
        value,
        refs | {"schemaVersion", "originalWindows", "historicalSourceRefs", "sourceRevision"},
        "invalid annotation specification subject",
    )
    _require(
        result["schemaVersion"] == "alk-source-invalid-annotation-specification-subject.v1",
        "unsupported invalid annotation specification subject",
    )
    for key in refs:
        reference = validate_source_ref_shape(result[key])
        _require(reference["bytes"] <= MAX_SOURCE_USAGE_BYTES, "invalid annotation subject authority exceeds bound")
    _id(result["sourceRevision"], "historical source revision")
    _validate_invalid_annotation_windows(result["originalWindows"])
    historical = result["historicalSourceRefs"]
    _require(isinstance(historical, list) and len(historical) == 3, "three historical source locators required")
    historical = _validated_cast(list[Any], historical)
    paths = set()
    for row in historical:
        _closed(row, {"path", "bytes", "sha256"}, "historical source locator")
        _require(isinstance(row["path"], str) and 0 < len(row["path"]) <= 4096, "invalid historical source locator")
        _counter(row["bytes"], "historical source bytes", minimum=1)
        _digest(row["sha256"], "historical source digest")
        paths.add(row["path"])
    _require(len(paths) == len(historical), "repeated historical source locator")
    return result


def validate_source_invalid_annotation_review_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    result = _closed(
        value,
        {
            "schemaVersion",
            "subjectDigest",
            "reviewerId",
            "independent",
            "verdict",
            "fullReview",
            "findings",
            "coverage",
            "reviewText",
            "unverifiedEvidence",
            "toolCalls",
            "productImplementationApproved",
            "nativeApproved",
            "taskAccepted",
            "releaseReady",
        },
        "invalid annotation contract review",
    )
    _require(
        result["schemaVersion"] == "alk-source-recovery-contract-review.v1"
        and result["verdict"] == "READY_TO_DRAFT"
        and result["fullReview"] is True
        and result["independent"] is True
        and result["reviewerId"] != "/root"
        and type(result["toolCalls"]) is int
        and result["toolCalls"] == 0
        and all(
            result[key] is False
            for key in ("productImplementationApproved", "nativeApproved", "taskAccepted", "releaseReady")
        ),
        "invalid annotation contract has no complete independent review",
    )
    _id(result["reviewerId"], "independent annotation reviewer")
    _digest(result["subjectDigest"], "annotation review subject")
    _require(isinstance(result["reviewText"], str) and bool(result["reviewText"]), "annotation review text is missing")
    for key in ("coverage", "unverifiedEvidence"):
        _require(
            isinstance(result[key], list)
            and len(result[key]) <= 32
            and all(isinstance(text, str) for text in result[key]),
            "invalid annotation review evidence list",
        )
    findings = result["findings"]
    _require(isinstance(findings, list) and len(findings) <= 16, "invalid annotation review findings")
    findings = _validated_cast(list[Any], findings)
    for finding in findings:
        _closed(finding, {"id", "severity", "target", "impact", "requiredEdit"}, "annotation review finding")
        _require(
            finding["severity"] == "LOW" and all(isinstance(text, str) for text in finding.values()),
            "invalid annotation contract has unresolved applicable findings",
        )
    return result


def validate_source_conflict_disposition_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    keys = {
        "schemaVersion",
        "dispositionId",
        "identityTuple",
        "originalWindows",
        "basisReviewRef",
        "authorizingReviewRef",
        "authorizingGrantRef",
        "originalOpeningRef",
        "authorizingFinancialHeadRef",
        "classification",
    }
    result = _closed(value, keys, "conflict disposition")
    _require(
        result["schemaVersion"] in (SOURCE_CONFLICT_DISPOSITION, SOURCE_CONFLICT_DISPOSITION_V2)
        and result["classification"] == "HISTORICAL_INELIGIBLE",
        "unsupported conflict disposition",
    )
    _id(result["dispositionId"], "disposition ID")
    if result["schemaVersion"] == SOURCE_CONFLICT_DISPOSITION:
        _require(result["dispositionId"] == "r605-r606-source-window-conflict", "unsupported legacy disposition")
    identity = _closed(
        result["identityTuple"], {"runId", "packageId", "taskId", "attempt", "semanticOperationId"}, "conflict identity"
    )
    for key in ("runId", "packageId", "taskId", "semanticOperationId"):
        _id(identity[key], key)
    _counter(identity["attempt"], "attempt", minimum=1)
    windows = result["originalWindows"]
    _require(isinstance(windows, list) and len(windows) == 2, "exact two conflict windows required")
    windows = _validated_cast(list[Any], windows)
    for row in windows:
        _closed(row, {"windowId", "admissionRef", "costRef"}, "conflict window")
        _id(row["windowId"], "window ID")
        for key, name in (("admissionRef", "admission.json"), ("costRef", "cost.json")):
            ref = validate_source_ref_shape(row[key])
            _require(
                ref["path"] == row["windowId"] + "/" + name and ref["bytes"] <= 131_072,
                "conflict stage changes original identity or bound",
            )
    ids = [row["windowId"] for row in windows]
    _require(ids == sorted(set(ids)), "conflict windows must be distinct and sorted")
    for key in (
        "basisReviewRef",
        "authorizingReviewRef",
        "authorizingGrantRef",
        "originalOpeningRef",
        "authorizingFinancialHeadRef",
    ):
        ref = validate_source_ref_shape(result[key])
        _require(ref["bytes"] <= MAX_SOURCE_USAGE_BYTES, "conflict authority exceeds bound")
    return result


def validate_source_conflict_grant_shape(value: Any) -> dict[str, Any]:
    _bounded(value)
    keys = {
        "schemaVersion",
        "grantId",
        "actorId",
        "independentReviewerId",
        "repairPackageId",
        "repairOperationId",
        "specificationRef",
        "specificationReviewRef",
        "planRef",
        "inventoryRef",
        "lockRef",
        "planReviewRef",
        "sourceRevision",
        "sourceBeforeRefs",
        "oldRunStateRef",
        "onlyWritePaths",
        "workArtifactRoot",
        "permittedWorkArtifacts",
        "admissionRef",
        "authorizingFinancialHeadRef",
        "inputSubjectDigest",
        "tokenCap",
        "protectedCloseoutTokens",
        "absoluteDeadlineUtc",
        "maxAffectedValidationCommands",
        "maxIndependentSourceReviews",
        "maxNativeInvocations",
        "requiresNonrunningWorkspace",
        "sourceAssurance",
        "taskAccepted",
        "releaseReady",
    }
    result = _closed(value, keys, "controller conflict grant")
    _require(
        result["schemaVersion"] == SOURCE_CONFLICT_GRANT
        and result["actorId"] == "/root"
        and result["independentReviewerId"] != "/root"
        and result["sourceAssurance"] == "CONTROLLER_REPAIR_SOURCE_ONLY_UNAVAILABLE"
        and result["requiresNonrunningWorkspace"] is True
        and result["taskAccepted"] is False
        and result["releaseReady"] is False,
        "grant cannot claim Source/native/task/release authority",
    )
    for key in (
        "grantId",
        "actorId",
        "independentReviewerId",
        "repairPackageId",
        "repairOperationId",
        "sourceRevision",
        "workArtifactRoot",
    ):
        _id(result[key], key)
    _digest(result["inputSubjectDigest"], "input subject")
    for key in (
        "specificationRef",
        "specificationReviewRef",
        "planRef",
        "inventoryRef",
        "lockRef",
        "planReviewRef",
        "oldRunStateRef",
        "admissionRef",
        "authorizingFinancialHeadRef",
    ):
        validate_source_ref_shape(result[key])
    before = result["sourceBeforeRefs"]
    _require(isinstance(before, list) and len(before) == 4, "four original source inputs required")
    before = _validated_cast(list[Any], before)
    for ref in before:
        validate_source_ref_shape(ref)
    for key in ("onlyWritePaths", "permittedWorkArtifacts"):
        rows = result[key]
        _require(
            isinstance(rows, list)
            and 0 < len(rows) <= 128
            and all(isinstance(path, str) for path in rows)
            and len(set(rows)) == len(rows),
            "grant paths missing or repeated",
        )
        rows = _validated_cast(list[Any], rows)
        for path in rows:
            _require(isinstance(path, str) and normalize_repo_path(path) == path, "invalid grant path")
            path = _validated_cast(str, path)
    _require(
        len(result["onlyWritePaths"]) == 4 and {r["path"] for r in before} == set(result["onlyWritePaths"]),
        "grant source/path mismatch",
    )
    for key in (
        "tokenCap",
        "protectedCloseoutTokens",
        "maxAffectedValidationCommands",
        "maxIndependentSourceReviews",
        "maxNativeInvocations",
    ):
        _counter(result[key], key)
    _require(
        0 < result["protectedCloseoutTokens"] < result["tokenCap"] <= 200_000
        and result["maxAffectedValidationCommands"] == 3
        and result["maxIndependentSourceReviews"] == 1
        and result["maxNativeInvocations"] == 0,
        "grant exceeds reviewed finite scope",
    )
    from datetime import datetime, timezone

    _ = (timezone,)

    try:
        deadline = datetime.fromisoformat(result["absoluteDeadlineUtc"])
        _require(deadline.utcoffset() == UTC.utcoffset(deadline), "grant UTC deadline required")
    except (ValueError, TypeError) as exc:
        raise LifecycleError("scoped-usage-shape-invalid", "invalid grant deadline") from exc
    return result
