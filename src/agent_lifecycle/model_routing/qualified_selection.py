"""Bounded, advisory consumption of previously accepted benchmark evidence.

Digest membership is caller-owned integrity evidence, never authentication or
proof that the producer collected every invocation. This module performs no I/O.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

from agent_lifecycle.benchmarks import (
    compare_qualified_routes,
    qualify_benchmark_runs,
    validate_benchmark_run_receipt,
)
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.model_routing.resolver import resolve_model_route

REQUEST_SCHEMA = "agent-qualified-route-ranking-request.v1"
MAX_INPUT_BYTES = 1_048_576
MAX_REPORT_BYTES = 65_536
MAX_INTEGER = 2**53 - 1
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z")
_ROLES = {"coordinator", "worker", "review", "audit", "retry", "correction"}
_BASE_KEYS = {"schemaVersion", "enabled"}
_ENABLED_KEYS = {
    "modelRequest",
    "routingProfile",
    "hostIdentityDigest",
    "productSourceDigest",
    "environmentDigest",
    "scorerDigest",
    "metric",
    "maxAgeSeconds",
    "trustedReceiptDigests",
    "candidates",
}
_TASK_FIELDS = ("taskId", "taskVersion", "taskDigest", "family", "tier", "shape")
_REQUEST_KEYS = {
    "schemaVersion",
    "operationId",
    "phase",
    "sddTier",
    "riskFlags",
    "capabilityRequirements",
    "targetContextWindow",
    "routingPolicy",
    "budgetClass",
    "userPolicy",
    "maxBillableTokens",
    "lifecycleMode",
    "qualityFloor",
    "failureSignals",
}
_PROFILE_KEYS = {
    "schemaVersion",
    "profileId",
    "classes",
    "phaseRules",
    "tokenBudgets",
    "criticalReviewPhases",
    "policyPresets",
    "progressiveEscalation",
}
_HOST_KEYS = {
    "schemaVersion",
    "profileId",
    "host",
    "bindings",
    "budgetModeDefault",
    "fallbackPolicies",
    "redactionPolicy",
}
_BINDING_KEYS = {
    "providerModel",
    "contextWindow",
    "capabilities",
    "jsonReliability",
    "toolUse",
    "usageAccounting",
    "dataPolicy",
    "calibrationStatus",
    "allowedForTiers",
    "allowedForPhases",
    "disallowedForRisks",
    "reviewStrategy",
}
_RECEIPT_KEYS = {
    "schemaVersion",
    "receiptId",
    *_TASK_FIELDS,
    "route",
    "environment",
    "scorer",
    "source",
    "completed",
    "quality",
    "measurements",
    "modelCallsStarted",
    "hostLaunchStarted",
    "productionPromotionClaimed",
    "receiptDigest",
}
_TOTAL_KEYS = {
    "scope",
    "accepted",
    "complete",
    "observedAt",
    "hostIdentityDigest",
    "productSourceDigest",
    "contributions",
}
_CONTRIBUTION_KEYS = {
    "id",
    "role",
    "tokens",
    "elapsedMilliseconds",
    "evidenceDigest",
}


def rank_qualified_routes(
    request: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Recommend only within the entire supplied allowlist, without execution."""
    _validate_request_shape(request)
    if not request.get("enabled", False):
        return _report(request, "MANUAL_DEFAULT")
    try:
        initial = resolve_model_route(request["modelRequest"], request["routingProfile"])
    except LifecycleError as exc:
        if exc.code != "host-model-profile-required":
            raise
    else:
        if initial["modelClass"] == "no-model":
            return _report(request, "NO_MODEL_REQUIRED")
    current = datetime.now(UTC) if now is None else now
    if not isinstance(current, datetime) or current.utcoffset() is None:
        _invalid()
    candidates = request["candidates"]
    if not candidates:
        return _report(request, "NO_ELIGIBLE_CANDIDATE")
    reasons = _candidate_policy_reasons(request)
    if reasons:
        return _report(request, *reasons)
    reasons = _evidence_reasons(request, current)
    if reasons:
        return _report(request, *reasons)
    return _rank_pools(request)


def _rank_pools(request: dict[str, Any]) -> dict[str, Any]:
    candidates = request["candidates"]
    qualifications = [qualify_benchmark_runs(item["receipts"]) for item in candidates]
    qualification_digests = [item["qualificationDigest"] for item in qualifications]
    if any(item["status"] != "QUALIFIED" for item in qualifications):
        return _report(request, "INSUFFICIENT_QUALIFICATION", qualifications=qualification_digests)
    if not _same_tasks(candidates):
        return _report(request, "TASK_POOL_MISMATCH", qualifications=qualification_digests)
    comparisons = [
        compare_qualified_routes(left["receipts"], right["receipts"]) for left, right in combinations(candidates, 2)
    ]
    comparison_digests = [item["comparisonDigest"] for item in comparisons]
    if any(not _comparison_passes(item) for item in comparisons):
        return _report(
            request,
            "INCOMPARABLE_EVIDENCE",
            qualifications=qualification_digests,
            comparisons=comparison_digests,
        )
    ranking = [
        {
            "candidateId": item["id"],
            "hostBindingDigest": item["hostBindingDigest"],
            "modelClass": item["modelClass"],
            "metricTotal": sum(row["measurements"][request["metric"]] for row in item["receipts"]),
        }
        for item in candidates
    ]
    ranking.sort(key=lambda item: item["metricTotal"])
    return _report(
        request,
        ranking=ranking,
        qualifications=qualification_digests,
        comparisons=comparison_digests,
    )


def _invalid() -> None:
    raise LifecycleError("invalid-qualified-ranking-request", "ranking request is invalid or exceeds its bounds")


def _closed(value: Any, allowed: set[str], required: set[str] | None = None) -> None:
    if not isinstance(value, dict):
        _invalid()
    if set(value) - allowed or (required or set()) - set(value):
        _invalid()


def _bounded_tree(value: Any) -> None:
    pending = [(value, 1)]
    nodes = 0
    primitive_bytes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 12_000 or depth > 16:
            _invalid()
        if isinstance(item, dict):
            _pending_bound(nodes, len(pending), len(item))
            for key in item:
                if not isinstance(key, str):
                    _invalid()
                primitive_bytes += _primitive_size(key)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            _pending_bound(nodes, len(pending), len(item))
            pending.extend((child, depth + 1) for child in item)
        else:
            primitive_bytes += _primitive_size(item)
        if primitive_bytes > MAX_INPUT_BYTES:
            _invalid()
    try:
        encoded_size = len(canonical_bytes(value))
    except LifecycleError as exc:
        if exc.code == "json-output-invalid":
            _invalid()
        raise
    if encoded_size > MAX_INPUT_BYTES:
        _invalid()


def _pending_bound(nodes: int, pending: int, children: int) -> None:
    if nodes + pending + children > 12_000:
        _invalid()


def _primitive_size(value: Any) -> int:
    if type(value) is str:
        if len(value) > MAX_INPUT_BYTES:
            _invalid()
        try:
            return len(value.encode("utf-8")) + 2
        except UnicodeError:
            _invalid()
    elif type(value) is int:
        # More than four bits per admitted byte cannot fit decimal JSON.
        # Retain runtime-supported integers within the input byte boundary.
        if value.bit_length() > MAX_INPUT_BYTES * 4:
            _invalid()
        try:
            return len(str(value))
        except ValueError:
            _invalid()
    elif type(value) in (bool, type(None)):
        return len(str(value))
    else:
        _invalid()
    return 0


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def _validate_request_shape(request: dict[str, Any]) -> None:
    _bounded_tree(request)
    _closed(request, _BASE_KEYS | _ENABLED_KEYS, {"schemaVersion"})
    if request["schemaVersion"] != REQUEST_SCHEMA or type(request.get("enabled", False)) is not bool:
        _invalid()
    if not request.get("enabled", False):
        _closed(request, _BASE_KEYS)
        return
    _closed(request, _BASE_KEYS | _ENABLED_KEYS, _ENABLED_KEYS)
    _closed(request["modelRequest"], _REQUEST_KEYS)
    _closed(request["routingProfile"], _PROFILE_KEYS)
    _request_options_shape(request["modelRequest"])
    _routing_profile_types(request["routingProfile"])
    if request["metric"] not in ("tokens", "elapsedMilliseconds"):
        _invalid()
    if not _integer(request["maxAgeSeconds"]) or not 1 <= request["maxAgeSeconds"] <= 604_800:
        _invalid()
    for field in ("hostIdentityDigest", "productSourceDigest", "environmentDigest", "scorerDigest"):
        if not _digest(request[field]):
            _invalid()
    trusted = request["trustedReceiptDigests"]
    if not isinstance(trusted, list) or len(trusted) > 192:
        _invalid()
    if any(not _digest(item) for item in trusted) or len(set(trusted)) != len(trusted):
        _invalid()
    candidates = request["candidates"]
    if not isinstance(candidates, list) or len(candidates) > 3:
        _invalid()
    for candidate in candidates:
        _candidate_shape(candidate)
    for field in ("id", "hostBindingDigest"):
        if len({item[field] for item in candidates}) != len(candidates):
            _invalid()


def _request_options_shape(request: dict[str, Any]) -> None:
    shapes = {
        "riskFlags": {
            "architecture",
            "security",
            "performance",
            "browser",
            "externalEnvironment",
            "external-environment",
        },
        "userPolicy": {"localModelsAllowed", "cloudModelsAllowed"},
        "failureSignals": {
            "failureClass",
            "confidence",
            "retryCount",
            "remediationLoops",
            "validationStatus",
            "flakeStatus",
            "previousModelClass",
            "classificationDigest",
            "evidenceIds",
        },
    }
    for field, keys in shapes.items():
        if field in request:
            _closed(request[field], keys)
    for field in ("riskFlags", "userPolicy"):
        if any(type(value) is not bool for value in request.get(field, {}).values()):
            _invalid()
    _model_request_types(request)


def _typed_fields(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    expected: type,
    *,
    nullable: bool = False,
) -> None:
    """Check JSON types only; delegated owners retain enum and policy rules."""
    for field in fields:
        if field not in payload:
            continue
        value = payload[field]
        if nullable and value is None:
            continue
        if type(value) is not expected:
            _invalid()


def _string_list_types(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    _typed_fields(payload, fields, list)
    for field in fields:
        if field in payload and any(type(item) is not str for item in payload[field]):
            _invalid()


def _mapping_value_types(payload: dict[str, Any], expected: type) -> None:
    if any(type(value) is not expected for value in payload.values()):
        _invalid()


def _model_request_types(request: dict[str, Any]) -> None:
    _typed_fields(
        request,
        (
            "schemaVersion",
            "operationId",
            "phase",
            "sddTier",
            "targetContextWindow",
            "routingPolicy",
            "budgetClass",
        ),
        str,
    )
    _typed_fields(request, ("lifecycleMode", "qualityFloor"), str, nullable=True)
    _typed_fields(request, ("maxBillableTokens",), int, nullable=True)
    _string_list_types(request, ("capabilityRequirements",))
    signals = request.get("failureSignals", {})
    _typed_fields(
        signals,
        (
            "failureClass",
            "confidence",
            "validationStatus",
            "flakeStatus",
            "previousModelClass",
            "classificationDigest",
        ),
        str,
        nullable=True,
    )
    _typed_fields(signals, ("retryCount", "remediationLoops"), int)
    _string_list_types(signals, ("evidenceIds",))


def _routing_profile_types(profile: dict[str, Any]) -> None:
    _typed_fields(profile, ("schemaVersion", "profileId"), str)
    _string_list_types(profile, ("classes", "criticalReviewPhases"))
    _typed_fields(profile, ("phaseRules", "tokenBudgets", "policyPresets"), dict)
    _mapping_value_types(profile.get("phaseRules", {}), str)
    _mapping_value_types(profile.get("policyPresets", {}), dict)
    budgets = profile.get("tokenBudgets", {})
    _mapping_value_types(budgets, dict)
    for values in budgets.values():
        _mapping_value_types(values, int)
    _typed_fields(profile, ("progressiveEscalation",), dict, nullable=True)
    progressive = profile.get("progressiveEscalation")
    if progressive is not None:
        _typed_fields(progressive, ("enabled",), bool)
        _string_list_types(progressive, ("ladder", "failureClasses", "evidenceTriggers"))


def _host_profile_types(profile: dict[str, Any]) -> None:
    _typed_fields(profile, ("schemaVersion", "profileId", "host", "budgetModeDefault"), str)
    _typed_fields(profile, ("fallbackPolicies", "redactionPolicy"), dict)
    fallbacks = profile.get("fallbackPolicies", {})
    _string_list_types(fallbacks, tuple(fallbacks))
    _typed_fields(profile.get("redactionPolicy", {}), ("providerModel",), str)


def _binding_types(binding: dict[str, Any]) -> None:
    _typed_fields(
        binding,
        (
            "providerModel",
            "contextWindow",
            "jsonReliability",
            "toolUse",
            "usageAccounting",
            "dataPolicy",
            "calibrationStatus",
        ),
        str,
    )
    _typed_fields(binding, ("reviewStrategy",), str, nullable=True)
    _string_list_types(
        binding,
        (
            "capabilities",
            "allowedForTiers",
            "allowedForPhases",
            "disallowedForRisks",
        ),
    )


def _candidate_shape(candidate: Any) -> None:
    fields = {"id", "hostProfile", "modelClass", "hostBindingDigest", "receipts"}
    _closed(candidate, fields, fields)
    if not isinstance(candidate["id"], str) or not _IDENTIFIER.fullmatch(candidate["id"]):
        _invalid()
    if not isinstance(candidate["modelClass"], str) or candidate["modelClass"] not in ALLOWED_MODEL_CLASSES - {
        "no-model"
    }:
        _invalid()
    if not _digest(candidate["hostBindingDigest"]):
        _invalid()
    _closed(candidate["hostProfile"], _HOST_KEYS)
    _host_profile_types(candidate["hostProfile"])
    bindings = candidate["hostProfile"].get("bindings", {})
    _closed(bindings, ALLOWED_MODEL_CLASSES - {"no-model"})
    for binding in bindings.values():
        _closed(binding, _BINDING_KEYS)
        _binding_types(binding)
    receipts = candidate["receipts"]
    if not isinstance(receipts, list) or len(receipts) > 64:
        _invalid()
    for receipt in receipts:
        _receipt_shape(receipt)


def _receipt_shape(receipt: Any) -> None:
    _closed(receipt, _RECEIPT_KEYS)
    for field in ("receiptId", *_TASK_FIELDS):
        if field in receipt and not isinstance(receipt[field], str):
            _invalid()
    for field in ("taskDigest", "receiptDigest"):
        if field in receipt and not _digest(receipt[field]):
            _invalid()
    _boolean_fields(receipt, ("completed", "productionPromotionClaimed", "modelCallsStarted", "hostLaunchStarted"))
    for field in ("route", "environment", "scorer", "source"):
        keys = {f"{field}Class", f"{field}Digest"}
        if field == "route":
            keys.add("adapterClass")
        if field in receipt:
            _closed(receipt[field], keys)
            digest = receipt[field].get(f"{field}Digest")
            if digest is not None and not _digest(digest):
                _invalid()
    if "quality" in receipt:
        _quality_shape(receipt["quality"])
    if "measurements" not in receipt:
        return
    measurements = receipt["measurements"]
    _closed(
        measurements,
        {
            "usageConfidence",
            "tokens",
            "elapsedMilliseconds",
            "retries",
            "remediations",
            "structuredResult",
            "acceptedTaskTotal",
        },
    )
    for metric in ("tokens", "elapsedMilliseconds", "retries", "remediations"):
        if metric in measurements and not _integer(measurements[metric]):
            _invalid()
    if "acceptedTaskTotal" in measurements:
        _total_shape(measurements["acceptedTaskTotal"])
    if "structuredResult" in measurements:
        _structured_shape(measurements["structuredResult"])


def _structured_shape(value: Any) -> None:
    _closed(
        value,
        {
            "schemaVersion",
            "operationId",
            "mode",
            "valid",
            "repairAttempts",
            "maxRepairAttempts",
            "selectionDigest",
            "requiredSchemaDigest",
            "validationDigest",
            "fixtureResults",
            "evidenceComplete",
            "productionPromotionClaimed",
            "measurementDigest",
        },
    )
    _typed_fields(
        value,
        (
            "schemaVersion",
            "operationId",
            "mode",
            "selectionDigest",
            "requiredSchemaDigest",
            "validationDigest",
            "measurementDigest",
        ),
        str,
    )
    _typed_fields(value, ("valid", "evidenceComplete"), bool)
    if value.get("productionPromotionClaimed", False) is not False:
        _invalid()
    _typed_fields(value, ("repairAttempts", "maxRepairAttempts"), int)
    if "fixtureResults" in value:
        _closed(value["fixtureResults"], {"positive", "boundary", "malformed"})


def _total_shape(total: Any) -> None:
    _closed(total, _TOTAL_KEYS)
    _boolean_fields(total, ("accepted", "complete"))
    contributions = total.get("contributions", [])
    if not isinstance(contributions, list):
        _invalid()
    for contribution in contributions:
        _closed(contribution, _CONTRIBUTION_KEYS)
        for metric in ("tokens", "elapsedMilliseconds"):
            if metric in contribution and not _integer(contribution[metric]):
                _invalid()


def _boolean_fields(value: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in value and type(value[field]) is not bool:
            _invalid()


def _quality_shape(quality: Any) -> None:
    _closed(quality, {"criteriaTotal", "criteriaPassed", "falseAcceptance", "measurementGap"})
    _boolean_fields(quality, ("falseAcceptance",))
    for field in ("criteriaTotal", "criteriaPassed"):
        if field in quality and not _integer(quality[field]):
            _invalid()
    gaps = quality.get("measurementGap", [])
    if not isinstance(gaps, list) or any(not isinstance(item, str) for item in gaps):
        _invalid()


def _candidate_policy_reasons(request: dict[str, Any]) -> list[str]:
    reasons: set[str] = set()
    hosts: set[str] = set()
    for candidate in request["candidates"]:
        try:
            decision = resolve_model_route(
                request["modelRequest"],
                request["routingProfile"],
                host_profile=candidate["hostProfile"],
            )
        except LifecycleError as exc:
            if exc.code != "model-route-unsupported":
                raise
            reasons.add("ROUTE_FLOOR_NOT_MET")
            continue
        hosts.add(decision["host"])
        if (decision["modelClass"], decision.get("hostBindingDigest")) != (
            candidate["modelClass"],
            candidate["hostBindingDigest"],
        ):
            reasons.add("BINDING_MISMATCH")
        binding = candidate["hostProfile"]["bindings"].get(candidate["modelClass"], {})
        if binding.get("calibrationStatus") != "PASSED":
            reasons.add("CALIBRATION_NOT_PASSED")
    if len(hosts) > 1:
        reasons.add("HOST_MISMATCH")
    return sorted(reasons)


def _evidence_reasons(request: dict[str, Any], now: datetime) -> list[str]:
    reasons: set[str] = set()
    seen_ids: set[str] = set()
    seen_digests: set[str] = set()
    trusted = set(request["trustedReceiptDigests"])
    for candidate in request["candidates"]:
        for receipt in candidate["receipts"]:
            if not _receipt_passes(receipt):
                reasons.add("INVALID_RECEIPT")
                continue
            identity, digest = receipt["receiptId"], receipt["receiptDigest"]
            if identity in seen_ids or digest in seen_digests:
                reasons.add("REPLAYED_RECEIPT")
            seen_ids.add(identity)
            seen_digests.add(digest)
            if digest not in trusted:
                reasons.add("UNTRUSTED_RECEIPT")
            reasons.update(_receipt_reasons(receipt, candidate, request, now))
    return sorted(reasons)


def _receipt_passes(receipt: dict[str, Any]) -> bool:
    if any(not isinstance(receipt.get(field), str) for field in _TASK_FIELDS):
        return False
    return validate_benchmark_run_receipt(receipt)["status"] == "PASS"


def _receipt_reasons(
    receipt: dict[str, Any],
    candidate: dict[str, Any],
    request: dict[str, Any],
    now: datetime,
) -> set[str]:
    reasons: set[str] = set()
    quality = receipt["quality"]
    if not (
        receipt["completed"] is True
        and quality["criteriaTotal"] > 0
        and quality["criteriaPassed"] == quality["criteriaTotal"]
        and quality["falseAcceptance"] is False
        and quality["measurementGap"] == []
    ):
        reasons.add("QUALITY_NOT_PASSED")
    if receipt["route"].get("routeDigest") != candidate["hostBindingDigest"]:
        reasons.add("RECEIPT_BINDING_MISMATCH")
    for field in ("environment", "scorer"):
        if receipt[field].get(f"{field}Digest") != request[f"{field}Digest"]:
            reasons.add("EVIDENCE_JOIN_MISMATCH")
    measurements = receipt["measurements"]
    if measurements.get("usageConfidence") != "ATTESTED":
        reasons.add("USAGE_NOT_ATTESTED")
    if not _complete_total(measurements, request):
        reasons.add("INCOMPLETE_ACCEPTED_TASK_TOTAL")
    else:
        observed = _observed_at(measurements["acceptedTaskTotal"].get("observedAt"))
        if observed is None:
            reasons.add("INVALID_OBSERVATION_TIME")
        elif not 0 <= (now - observed).total_seconds() <= request["maxAgeSeconds"]:
            reasons.add("STALE_OR_FUTURE_EVIDENCE")
    return reasons


def _complete_total(measurements: dict[str, Any], request: dict[str, Any]) -> bool:
    total = measurements.get("acceptedTaskTotal")
    if not isinstance(total, dict) or set(total) != _TOTAL_KEYS:
        return False
    if (total["scope"], total["accepted"], total["complete"]) != ("ACCEPTED_TASK_TOTAL", True, True):
        return False
    if total["accepted"] is not True or total["complete"] is not True:
        return False
    for field in ("hostIdentityDigest", "productSourceDigest"):
        if total[field] != request[field]:
            return False
    contributions = total["contributions"]
    if not all(_complete_contribution(item) for item in contributions):
        return False
    if {item["role"] for item in contributions} != _ROLES:
        return False
    if len({item["id"] for item in contributions}) != len(contributions):
        return False
    return all(
        _integer(measurements.get(metric)) and sum(item[metric] for item in contributions) == measurements[metric]
        for metric in ("tokens", "elapsedMilliseconds")
    )


def _complete_contribution(item: dict[str, Any]) -> bool:
    if set(item) != _CONTRIBUTION_KEYS:
        return False
    if not isinstance(item["id"], str) or not _IDENTIFIER.fullmatch(item["id"]):
        return False
    return (
        isinstance(item["role"], str)
        and item["role"] in _ROLES
        and _integer(item["tokens"])
        and _integer(item["elapsedMilliseconds"])
        and _digest(item["evidenceDigest"])
    )


def _observed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _same_tasks(candidates: list[dict[str, Any]]) -> bool:
    pools = [
        Counter(tuple(row.get(field) for field in _TASK_FIELDS) for row in item["receipts"]) for item in candidates
    ]
    return all(pool == pools[0] for pool in pools)


def _comparison_passes(comparison: dict[str, Any]) -> bool:
    attestation = comparison["resources"]["attestation"]
    return comparison["status"] == "PASS" and attestation == {"baseline": "ATTESTED", "candidate": "ATTESTED"}


def _report(
    request: dict[str, Any],
    *reasons: str,
    ranking: list[dict[str, Any]] | None = None,
    qualifications: list[str] | None = None,
    comparisons: list[str] | None = None,
) -> dict[str, Any]:
    rows = ranking or []
    body = {
        "schemaVersion": "agent-qualified-route-ranking.v1",
        "status": "RECOMMENDED" if rows else "NO_RECOMMENDATION",
        "reasonCodes": list(reasons),
        "selectedCandidateId": rows[0]["candidateId"] if rows else None,
        "ranking": rows,
        "metric": request.get("metric"),
        "requestDigest": canonical_digest(request),
        "qualificationDigests": qualifications or [],
        "comparisonDigests": comparisons or [],
        "advisoryOnly": True,
        "automaticRouteAdoptionEligible": False,
        "productionPromotionClaimed": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "profileMutation": False,
        "liveEconomicQualification": "UNQUALIFIED",
        "savingsClaimed": False,
    }
    report = {**body, "reportDigest": canonical_digest(body)}
    if len(canonical_bytes(report)) + 1 > MAX_REPORT_BYTES:
        raise LifecycleError("qualified-ranking-output-too-large", "ranking report exceeds its byte limit")
    return report
