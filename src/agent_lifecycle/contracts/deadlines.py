"""Pure D-DEADLINE comparisons; current producer and authority remain external."""

from __future__ import annotations

from datetime import timedelta
from copy import deepcopy
import re
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.closing_window_schemas import validate_window_request
from agent_lifecycle.contracts.deadline_schemas import (
    utc_microseconds,
    validate_duration_rule,
    validate_freshness_rule,
    validate_permission_rule,
    validate_clock_observation,
)


def evaluate_original_permission(rule: dict[str, Any], now: str) -> dict[str, Any]:
    selected = validate_permission_rule(rule)
    observed = utc_microseconds(now)
    within = utc_microseconds(selected["validFrom"]) <= observed < utc_microseconds(selected["expiresAt"])
    candidate = within and selected["replacement"] == "RETAIN_ORIGINAL"
    return {
        "disposition": "DATA_CANDIDATE" if candidate else "REFUSED_OR_NATIVE_INTERSECTION_REQUIRED",
        "originalPermissionWithinTime": within,
        "nativeAuthorityGranted": False,
        "replacementEvaluated": False,
    }


def evaluate_original_duration(rule: dict[str, Any], now: str) -> dict[str, Any]:
    selected = validate_duration_rule(rule)
    observed = utc_microseconds(now)
    deadline = utc_microseconds(selected["originalDeadlineAt"])
    within = observed < deadline if selected["comparison"] == "LT" else observed <= deadline
    return {"disposition": "DATA_CANDIDATE" if within else "REFUSED", "originalDeadlineAt": selected["originalDeadlineAt"],
            "nativePermissionGranted": False}


def evaluate_original_freshness(rule: dict[str, Any], generated_at: str, now: str) -> dict[str, Any]:
    selected = validate_freshness_rule(rule)
    created = utc_microseconds(generated_at)
    observed = utc_microseconds(now)
    age = observed - created
    age_microseconds = (age.days * 86_400 + age.seconds) * 1_000_000 + age.microseconds
    within = age >= timedelta(0) and (
        selected["maxAgeSeconds"] is None or age_microseconds <= selected["maxAgeSeconds"] * 1_000_000
    )
    return {"disposition": "DATA_CANDIDATE" if within else "REFUSED", "nativeEvidenceBindingVerified": False,
            "nativePermissionGranted": False}


_ACTIVATION_SELECTION = {"inventoryDigest", "deadlineInputDigest", "bindingId", "closingWindowId", "operationId",
                         "phase", "taskId", "expectedWorkflowRevision", "expectedAuthorityEpoch",
                         "originalAuthorizationDigest", "closingGrantDigest", "originalDeadlineDigest",
                         "originalValidFrom", "originalExpiresAt", "grantValidFrom", "grantExpiresAt",
                         "sourceRevision", "planDigest", "adoptionConfigurationDigest", "compiledControllerGatesDigest",
                         "runtimeRegistryDigest", "journalIdentity", "clockObservationDigest", "clockQualificationDigest",
                         "clockProcessIdentity", "clockOriginId", "expectedCoveredRoutes", "expectedApplicableConsumerIds"}
_DEADLINE_ROUTES = {"ACTIVATE", "RESERVE", "CLAIM", "APPLY_FINAL_OUTCOME", "FINALIZE", "PRODUCE_PROOF", "CONTINUE",
                    "TASK_START", "TASK_REWORK", "RECORD_FACT", "RECONCILE", "PUBLISH_PROJECTION", "PUBLISH_AUTHORITY_STATUS"}


def _binding_require(condition: bool, detail: str) -> None:
    if not condition:
        raise LifecycleError("deadline-binding-invalid", detail)


def _local_record(value: Any, fields: set[str], label: str) -> dict:
    _binding_require(type(value) is dict and set(value) == fields, f"{label}: closed local fields required")
    try:
        _binding_require(len(canonical_bytes(value)) <= 1_048_576, f"{label}: document too large")
    except (TypeError, ValueError) as exc:
        raise LifecycleError("deadline-binding-invalid", f"{label}: invalid data") from exc
    return value


def _local_uint(value: Any, label: str) -> None:
    _binding_require(type(value) is int and 0 <= value <= (1 << 53) - 1, f"{label}: bounded integer required")


def _local_text(value: Any, label: str) -> None:
    _binding_require(type(value) is str and 1 <= len(value) <= 256, f"{label}: bounded identity required")


def _local_digest(value: Any, label: str) -> None:
    _binding_require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                     f"{label}: canonical digest required")


def _local_ref(value: Any) -> None:
    ref = _local_record(value, {"path", "sha256", "bytes"}, "receiptRef")
    _binding_require(type(ref["path"]) is str and 1 <= len(ref["path"]) <= 4096, "receiptRef path invalid")
    _local_digest(ref["sha256"], "receiptRef sha256")
    _local_uint(ref["bytes"], "receiptRef bytes")
    _binding_require(ref["bytes"] > 0, "receiptRef is empty")


def _identity_list(value: Any, label: str, maximum: int) -> list:
    _binding_require(type(value) is list and len(value) <= maximum, f"{label}: bounded list required")
    for item in value:
        _local_text(item, label)
    _binding_require(len(set(value)) == len(value), f"{label}: duplicate identity")
    return value


def _activation_selection(selected: dict) -> None:
    _local_record(selected, _ACTIVATION_SELECTION, "independent activation selection")
    for key, value in selected.items():
        if key.startswith("expected") and key.endswith("Revision") or key == "expectedAuthorityEpoch":
            _local_uint(value, key)
        elif key.endswith("Digest"):
            _local_digest(value, key)
        elif key.endswith("From") or key.endswith("At"):
            utc_microseconds(value)
        elif key == "taskId" and value is None:
            continue
        elif key in ("expectedCoveredRoutes", "expectedApplicableConsumerIds"):
            _identity_list(value, key, 4096)
            _binding_require(value == sorted(value), "Selected identity list must be sorted")
        else:
            _local_text(value, key)


def _activation_inventory(request: dict, inventory: dict, selected: dict) -> None:
    fields = {"schemaVersion", "bindingId", "runId", "journalIdentity", "planDigest", "sourceRevision",
              "adoptionConfigurationDigest", "compiledControllerGatesDigest", "runtimeRegistryDigest", "clockPolicy",
              "clockQualificationRef", "inventoryQualificationRef", "bindings", "coveredRoutes"}
    _local_record(inventory, fields, "inventory header")
    _binding_require(inventory["schemaVersion"] == "agent-closing-deadline-inventory.v1"
                     and inventory["clockPolicy"] == "QUALIFIED_HOST_UTC_NONDECREASING", "Inventory version/clock policy differs")
    for key in ("bindingId", "runId", "journalIdentity"):
        _local_text(inventory[key], key)
        _binding_require(inventory[key] == request["scope"][key], "Inventory/request scope differs")
    for key in ("sourceRevision", "planDigest", "adoptionConfigurationDigest", "compiledControllerGatesDigest",
                "runtimeRegistryDigest", "journalIdentity"):
        (_local_digest if key.endswith("Digest") else _local_text)(inventory[key], key)
        _binding_require(inventory[key] == selected[key], "Independent inventory identity differs")
    _binding_require(inventory["planDigest"] == request["scope"]["effectivePlanDigest"]
                     and inventory["sourceRevision"] == request["scope"]["sourceRevision"], "Selected plan/source differs")
    for key in ("clockQualificationRef", "inventoryQualificationRef"):
        _local_ref(inventory[key])
    routes = _identity_list(inventory["coveredRoutes"], "coveredRoutes", 16)
    _binding_require(set(routes) <= _DEADLINE_ROUTES and "ACTIVATE" in routes
                     and sorted(routes) == selected["expectedCoveredRoutes"], "Explicit route coverage differs")


def _activation_consumers(request: dict, inventory: dict, deadline_input: dict, selected: dict) -> None:
    bindings = inventory["bindings"]
    _binding_require(type(bindings) is list and 1 <= len(bindings) <= 4096, "Registered consumer set missing")
    registered, applicable = [], []
    for row in bindings:
        _local_record(row, {"bindingKey", "source", "taskId", "phases", "operations", "rule", "validityEvidenceMode"}, "consumer")
        _local_text(row["bindingKey"], "bindingKey")
        if row["taskId"] is not None:
            _local_text(row["taskId"], "consumer taskId")
        phases = _identity_list(row["phases"], "consumer phases", 16)
        routes = _identity_list(row["operations"], "consumer operations", 16)
        _binding_require(bool(phases) and bool(routes) and set(routes) <= set(inventory["coveredRoutes"]), "Consumer route membership invalid")
        _binding_require(type(row["source"]) is dict and type(row["rule"]) is dict
                         and type(row["validityEvidenceMode"]) is str and row["validityEvidenceMode"] in
                         {"CURRENT_SQL_STATE", "QUALIFIED_IMMUTABLE_INTERVAL", "NATIVE_CONSUMER_RECEIPT"}, "Consumer projection malformed")
        registered.append(row["bindingKey"])
        if "ACTIVATE" in routes and deadline_input["phase"] in phases and row["taskId"] in (None, deadline_input["taskId"]):
            applicable.append(row["bindingKey"])
    _binding_require(len(set(registered)) == len(registered) and request["deadlineConsumerIds"] == sorted(registered),
                     "Request must retain the complete sorted registered consumer set")
    _binding_require(bool(applicable) and sorted(applicable) == selected["expectedApplicableConsumerIds"],
                     "Independent phase/task applicability differs; registration may not shrink")


def _activation_input(request: dict, inventory: dict, deadline_input: dict, selected: dict) -> None:
    fields = {"schemaVersion", "bindingId", "inventoryDigest", "operationId", "operationKind", "taskId", "phase",
              "expectedWorkflowRevision", "expectedAuthorityEpoch", "closingWindowId", "originalAuthorizationDigest",
              "closingGrantDigest", "applicabilityAssessmentRefs", "currentReceiptObservations"}
    _local_record(deadline_input, fields, "ACTIVATE input header")
    _binding_require(deadline_input["schemaVersion"] == "agent-closing-deadline-input.v1"
                     and deadline_input["operationKind"] == "ACTIVATE", "ACTIVATE input required")
    _binding_require(request["deadlineInventoryDigest"] == canonical_digest(inventory) == deadline_input["inventoryDigest"]
                     == selected["inventoryDigest"] and canonical_digest(deadline_input) == selected["deadlineInputDigest"],
                     "Independent complete inventory/input digest differs")
    for key in ("bindingId", "closingWindowId", "operationId", "phase", "taskId", "expectedWorkflowRevision",
                "expectedAuthorityEpoch", "originalAuthorizationDigest", "closingGrantDigest"):
        value = deadline_input[key]
        if key in ("expectedWorkflowRevision", "expectedAuthorityEpoch"):
            _local_uint(value, key)
        _binding_require(value == selected[key], "ACTIVATE identity differs")
    for key in ("closingWindowId", "expectedWorkflowRevision", "originalAuthorizationDigest", "originalDeadlineDigest"):
        _binding_require(request[key] == selected[key], "Request/selected deadline identity differs")
    _binding_require(request["scope"]["bindingId"] == selected["bindingId"]
                     and request["ownerPermissionRef"] == "sha256:" + selected["closingGrantDigest"], "Selected grant/binding differs")
    for key in ("applicabilityAssessmentRefs", "currentReceiptObservations"):
        _binding_require(type(deadline_input[key]) is list and len(deadline_input[key]) <= 4096, "Bounded downstream data required")


def evaluate_activation_deadline_binding(request: dict, inventory: dict, deadline_input: dict,
                                         clock_observation: dict, selected: dict) -> dict:
    """Verify a bounded local ACTIVATE join; nested wire/signature/clock qualification remains external."""
    validate_window_request(request)
    _activation_selection(selected)
    _activation_inventory(request, inventory, selected)
    _activation_input(request, inventory, deadline_input, selected)
    _activation_consumers(request, inventory, deadline_input, selected)
    validate_clock_observation(clock_observation)
    _binding_require(canonical_digest(clock_observation) == selected["clockObservationDigest"], "Original complete clock digest differs")
    for key, expected in (("journalIdentity", "journalIdentity"), ("processIdentity", "clockProcessIdentity"),
                          ("monotonicOriginId", "clockOriginId"), ("clockQualificationDigest", "clockQualificationDigest")):
        _binding_require(clock_observation[key] == selected[expected], "Independently selected clock identity differs")
    _binding_require(request["validFrom"] == selected["originalValidFrom"] and request["expiresAt"] == selected["originalExpiresAt"],
                     "Original request interval differs")
    observed = utc_microseconds(clock_observation["observedAt"])
    for start, end in ((request["validFrom"], request["expiresAt"]), (selected["grantValidFrom"], selected["grantExpiresAt"])):
        _binding_require(utc_microseconds(start) <= observed < utc_microseconds(end), "Original/grant interval excludes observation")
    return {"disposition": "DATA_CANDIDATE", "dataBindingMatched": True, "fullNestedWireValidated": False,
            "nativeClockQualified": False, "nativePermissionGranted": False, "nativeActivationGranted": False,
            "dispatchAuthorized": False, "financialAdmission": False, "nonceConsumed": False}


_RECEIPT_IDENTITIES = {"requiredEvidenceBindingDigest", "sourceBindingDigest", "producerOperationId",
                       "consumerOperationId", "producerGenerationDigest", "bindingKey",
                       "expectedWorkflowRevision", "receiptRef"}


def _receipt_identities(values: dict) -> None:
    for key in _RECEIPT_IDENTITIES:
        value = values[key]
        if key.endswith("Digest"):
            _local_digest(value, key)
        elif key == "expectedWorkflowRevision":
            _local_uint(value, key)
        elif key == "receiptRef":
            _local_ref(value)
        else:
            _local_text(value, key)


def evaluate_original_freshness_binding(rule: dict, observation: dict, now: str, expected: dict) -> dict:
    """Compare independently pinned original rule/observation before evaluating their original age."""
    selected_rule = validate_freshness_rule(rule)
    _local_record(observation, _RECEIPT_IDENTITIES | {"generatedAt"}, "original observation")
    _local_record(expected, _RECEIPT_IDENTITIES | {"originalObservationDigest", "originalRuleDigest"}, "expected")
    _receipt_identities(observation)
    _receipt_identities(expected)
    for key in ("originalObservationDigest", "originalRuleDigest"):
        _local_digest(expected[key], key)
    _binding_require(expected["originalObservationDigest"] == canonical_digest(observation)
                     and expected["originalRuleDigest"] == canonical_digest(selected_rule),
                     "Original observation/time or rule/TTL/selector was substituted")
    _binding_require(all(observation[key] == expected[key] for key in _RECEIPT_IDENTITIES),
                     "Original receipt identity differs from independently selected expectation")
    result = evaluate_original_freshness(selected_rule, observation["generatedAt"], now)
    return {**result, "dataBindingMatched": True, "nativeClockQualified": False,
            "nativeActivationGranted": False, "dispatchAuthorized": False}


_LATE_IDENTITIES = {"subjectDigest", "sourceDigest", "configurationDigest", "oracleDigest", "producerDigest",
                    "producerOperationId", "consumerOperationId", "producerGenerationDigest",
                    "controllerGateDigest", "clockDigest", "workflowGenerationDigest", "accountingGenerationDigest"}
_LATE_FACTS = {"technicalValidity", "controllerGateMatched", "clockBindingMatched",
               "workflowGenerationMatched", "accountingGenerationMatched"}
_LATE_DETERMINATIONS = _LATE_FACTS | {"capConformance"}


def _late_records(original: dict, selected: dict) -> None:
    _local_record(original, {"evidenceRef", "body", "verdict", "completedAt", "deadlineAt", "generatedAt",
                             "maxAgeSeconds", "identities", "facts", "expenses"}, "original evidence")
    _local_record(selected, {"identities", "requireFullCost", "requireCapConformance"}, "selected evidence")
    _local_ref(original["evidenceRef"])
    _binding_require(original["verdict"] in ("PASS", "FAIL", "UNAVAILABLE"), "Evidence verdict invalid")
    for key in ("completedAt", "deadlineAt", "generatedAt"):
        utc_microseconds(original[key])
    if original["maxAgeSeconds"] is not None:
        _local_uint(original["maxAgeSeconds"], "original maxAgeSeconds")
    for side in (original, selected):
        _local_record(side["identities"], _LATE_IDENTITIES, "required original/current identities")
        for key, value in side["identities"].items():
            if value is not None:
                (_local_digest if key.endswith("Digest") else _local_text)(value, key)
    _local_record(original["facts"], _LATE_FACTS, "required determination facts")
    _binding_require(all(type(v) is bool or v is None for v in original["facts"].values()), "Fact value invalid")
    _binding_require(all(type(selected[k]) is bool for k in ("requireFullCost", "requireCapConformance")),
                     "Requested determination must be explicit")
    expenses = _local_record(original["expenses"], {"actualTokens", "reportedTokens", "unknownTokens", "capConformance"}, "expenses")
    for key in ("actualTokens", "reportedTokens", "unknownTokens"):
        if expenses[key] is not None:
            _local_uint(expenses[key], key)
    _binding_require(type(expenses["capConformance"]) is bool or expenses["capConformance"] is None,
                     "Cap determination invalid")


def _late_dependencies(dependencies: Any) -> list[dict]:
    _binding_require(type(dependencies) is list and 1 <= len(dependencies) <= 4096, "Dependent proof list invalid")
    seen = set()
    for row in dependencies:
        _local_record(row, {"proofId", "original", "current", "missing", "bindingKeys", "determinationKeys"}, "dependency")
        _local_text(row["proofId"], "proofId")
        _binding_require(row["proofId"] not in seen and type(row["missing"]) is bool, "Duplicate proof or invalid missing fact")
        seen.add(row["proofId"])
        keys = row["bindingKeys"]
        _binding_require(type(keys) is list and all(type(k) is str for k in keys)
                         and len(keys) == len(set(keys)) and set(keys) <= _LATE_IDENTITIES, "Dependency binding map invalid")
        facts = _identity_list(row["determinationKeys"], "dependent determination keys", 6)
        _binding_require(set(facts) <= _LATE_DETERMINATIONS, "Dependent determination map invalid")
        for side in ("original", "current"):
            data = row[side]
            _binding_require(type(data) is dict and 1 <= len(data) <= 256, "Dependency identities incomplete")
            for key, value in data.items():
                _local_text(key, "dependency key")
                if value is not None:
                    _local_digest(value, "dependency identity")
        _binding_require(set(row["original"]) == set(row["current"]), "Dependency membership differs")
    return dependencies


def _late_disposition(original: dict, selected: dict, dependencies: list[dict]) -> tuple[str, list[str]]:
    expenses = original["expenses"]
    cost_unknown = expenses["actualTokens"] is None or expenses["unknownTokens"] != 0
    unresolved = (any(v is None for side in (original, selected) for v in side["identities"].values())
                  or any(v is None for v in original["facts"].values())
                  or any(v is None for row in dependencies if not row["missing"]
                         for side in ("original", "current") for v in row[side].values())
                  or ((selected["requireFullCost"] or selected["requireCapConformance"]) and cost_unknown)
                  or (selected["requireCapConformance"] and expenses["capConformance"] is None))
    changed = {k for k in _LATE_IDENTITIES if original["identities"][k] != selected["identities"][k]}
    mapped = set().union(*(set(row["bindingKeys"]) for row in dependencies))
    failed_facts = {key for key, value in original["facts"].items() if value is False}
    if selected["requireCapConformance"] and expenses["capConformance"] is False:
        failed_facts.add("capConformance")
    mapped_facts = set().union(*(set(row["determinationKeys"]) for row in dependencies))
    if unresolved or not changed <= mapped or not failed_facts <= mapped_facts:
        return "UNAVAILABLE", []
    affected = sorted(row["proofId"] for row in dependencies if row["missing"]
                      or row["original"] != row["current"] or changed.intersection(row["bindingKeys"])
                      or failed_facts.intersection(row["determinationKeys"]))
    return ("RERUN_REQUIRED" if affected else "REUSE"), affected


def evaluate_late_result_applicability(original: dict, selected: dict, dependencies: list) -> dict:
    """Classify original evidence without refreshing it or dispatching any rerun."""
    _late_records(original, selected)
    checked = _late_dependencies(dependencies)
    disposition, affected = _late_disposition(original, selected, checked)
    return {"disposition": disposition, "affectedProofIds": affected, "original": deepcopy(original),
            "nativePermissionGranted": False, "nativeClockQualified": False, "dispatchAuthorized": False,
            "acceptanceGranted": False, "rerunDispatched": False}


__all__ = ["evaluate_original_duration", "evaluate_original_freshness", "evaluate_original_permission",
           "evaluate_original_freshness_binding", "evaluate_late_result_applicability", "evaluate_activation_deadline_binding"]
