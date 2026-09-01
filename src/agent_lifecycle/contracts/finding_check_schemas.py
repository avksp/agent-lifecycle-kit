"""Contracts for binding accepted findings to deterministic checks."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.ownership_paths import normalize_authority_path
from agent_lifecycle.contracts.schema_builders import open_object_schema

FINDING_CHECK_BINDING_SCHEMA = "agent-finding-check-binding.v1"
FINDING_CHECK_BINDING_VALIDATION_SCHEMA = "agent-finding-check-binding-validation.v1"
FINDING_CHECK_PROPOSAL_SCHEMA = "agent-finding-check-proposal.v1"
FINDING_CHECK_PROPOSAL_VALIDATION_SCHEMA = "agent-finding-check-proposal-validation.v1"
FINDING_CHECK_EVIDENCE_SCHEMA = "agent-finding-check-evidence.v1"
FINDING_CHECK_EVIDENCE_VALIDATION_SCHEMA = "agent-finding-check-evidence-validation.v1"
FINDING_CHECK_TRANSITION_SCHEMA = "agent-finding-check-transition.v1"
FINDING_CHECK_TRACEABILITY_SCHEMA = "agent-finding-check-traceability-validation.v1"
FINDING_IMPACT_SCOPE_SCHEMA = "agent-finding-impact-scope.v1"
FINDING_IMPACT_SCOPE_VALIDATION_SCHEMA = "agent-finding-impact-scope-validation.v1"

FINDING_CHECK_STATUSES = ("PROPOSED", "ACCEPTED", "IMPLEMENTED", "VERIFIED", "RETIRED")
FINDING_CHECK_RESULTS = ("PASS", "FAIL", "BLOCKED")
_STATUS_INDEX = {value: index for index, value in enumerate(FINDING_CHECK_STATUSES)}
_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ID = {"type": "string", "minLength": 1, "maxLength": 256}
_TEXT = {"type": "string", "minLength": 1, "maxLength": 2048}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 128}
_CHECK_ROUTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


FINDING_CHECK_SCHEMAS: dict[str, dict[str, Any]] = {
    FINDING_IMPACT_SCOPE_SCHEMA: open_object_schema(
        FINDING_IMPACT_SCOPE_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion status findingId findingDigest planRevision planDigest sourceRevision paths modules "
            "ownershipPaths acceptanceIds gateIds productionPromotionClaimed scopeDigest"
        ).split(),
        properties={
            "status": {"const": "FROZEN"},
            "findingId": _ID,
            "findingDigest": _DIGEST,
            "planRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": _TEXT,
            "paths": {"type": "array", "minItems": 1, "maxItems": 128, "items": _ID},
            "modules": {"type": "array", "minItems": 1, "maxItems": 128, "items": _ID},
            "ownershipPaths": {"type": "array", "maxItems": 128, "items": _ID},
            "acceptanceIds": {"type": "array", "maxItems": 128, "items": _ID},
            "gateIds": {"type": "array", "maxItems": 128, "items": _ID},
            "productionPromotionClaimed": {"const": False},
            "scopeDigest": _DIGEST,
        },
    ),
    FINDING_IMPACT_SCOPE_VALIDATION_SCHEMA: open_object_schema(
        FINDING_IMPACT_SCOPE_VALIDATION_SCHEMA,
        required=["schemaVersion", "status", "findingId", "blockers", "productionPromotionClaimed", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "findingId": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_BINDING_SCHEMA: open_object_schema(
        FINDING_CHECK_BINDING_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion bindingId status findingId findingDigest planDeltaDigest planLineage checkIdentity owner "
            "scope sourceRevision expectedResult transitions productionPromotionClaimed bindingDigest"
        ).split(),
        properties={
            "bindingId": _ID,
            "status": {"enum": list(FINDING_CHECK_STATUSES)},
            "findingId": _ID,
            "findingDigest": _DIGEST,
            "planDeltaDigest": _DIGEST,
            "planLineage": {"type": "object", "maxProperties": 12},
            "checkIdentity": {"type": "object", "maxProperties": 8},
            "owner": _TEXT,
            "scope": {"type": "object", "maxProperties": 16},
            "sourceRevision": _TEXT,
            "expectedResult": {"enum": list(FINDING_CHECK_RESULTS)},
            "transitions": {"type": "array", "maxItems": 5, "items": {"type": "object", "maxProperties": 12}},
            "productionPromotionClaimed": {"const": False},
            "bindingDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_BINDING_VALIDATION_SCHEMA: open_object_schema(
        FINDING_CHECK_BINDING_VALIDATION_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion status bindingStatus bindingId blockers productionPromotionClaimed validationDigest"
        ).split(),
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "bindingStatus": {"type": ["string", "null"]},
            "bindingId": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_PROPOSAL_SCHEMA: open_object_schema(
        FINDING_CHECK_PROPOSAL_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion proposalId status binding approvalRequired applyAllowed authorityClaimed blockers "
            "productionPromotionClaimed proposalDigest"
        ).split(),
        properties={
            "proposalId": _ID,
            "status": {"enum": ["PASS", "FAIL"]},
            "binding": {"type": "object"},
            "reviewerReproduction": {"type": "object", "maxProperties": 4},
            "approvalRequired": {"const": True},
            "applyAllowed": {"const": False},
            "authorityClaimed": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "proposalDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_PROPOSAL_VALIDATION_SCHEMA: open_object_schema(
        FINDING_CHECK_PROPOSAL_VALIDATION_SCHEMA,
        required="schemaVersion status proposalStatus blockers productionPromotionClaimed validationDigest".split(),  # noqa: SIM905
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "proposalStatus": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_EVIDENCE_SCHEMA: open_object_schema(
        FINDING_CHECK_EVIDENCE_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion status bindingId findingId checkIdentity sourceRevision result evidenceIds readOnly "
            "modelCallsStarted hostLaunchStarted productionPromotionClaimed evidenceDigest"
        ).split(),
        properties={
            "status": {"enum": ["PASS", "FAIL", "BLOCKED"]},
            "bindingId": _ID,
            "findingId": _ID,
            "checkIdentity": {"type": "object", "maxProperties": 8},
            "sourceRevision": _TEXT,
            "result": {"enum": list(FINDING_CHECK_RESULTS)},
            "evidenceIds": {"type": "array", "minItems": 1, "maxItems": 128, "items": _ID},
            "readOnly": {"const": True},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "evidenceDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_EVIDENCE_VALIDATION_SCHEMA: open_object_schema(
        FINDING_CHECK_EVIDENCE_VALIDATION_SCHEMA,
        required="schemaVersion status result bindingId blockers productionPromotionClaimed validationDigest".split(),  # noqa: SIM905
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "result": {"type": ["string", "null"]},
            "bindingId": {"type": ["string", "null"]},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_TRANSITION_SCHEMA: open_object_schema(
        FINDING_CHECK_TRANSITION_SCHEMA,
        required=(  # noqa: SIM905
            "schemaVersion status binding targetStatus idempotent blockers productionPromotionClaimed transitionDigest"
        ).split(),
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "binding": {"type": "object"},
            "targetStatus": {"enum": list(FINDING_CHECK_STATUSES)},
            "idempotent": {"type": "boolean"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "transitionDigest": _DIGEST,
        },
    ),
    FINDING_CHECK_TRACEABILITY_SCHEMA: open_object_schema(
        FINDING_CHECK_TRACEABILITY_SCHEMA,
        required="schemaVersion status bindingCount blockers productionPromotionClaimed validationDigest".split(),  # noqa: SIM905
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "bindingCount": {"type": "integer", "minimum": 0, "maximum": 128},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_finding_impact_scope(
    *,
    finding_id: str,
    finding_digest: str,
    plan_revision: int,
    plan_digest: str,
    source_revision: str,
    paths: list[str],
    modules: list[str],
    ownership_paths: list[str] | None = None,
    acceptance_ids: list[str] | None = None,
    gate_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Freeze the machine-readable impact boundary for one accepted finding."""

    _required_id(finding_id, "findingId")
    _digest(finding_digest, "findingDigest")
    if not isinstance(plan_revision, int) or isinstance(plan_revision, bool) or plan_revision < 1:
        raise LifecycleError("finding-impact-scope-revision", "planRevision must be a positive integer")
    _digest(plan_digest, "planDigest")
    _required_text(source_revision, "sourceRevision")
    normalized_modules = _canonical_string_list(sorted(set(modules)), "modules", allow_empty=False)
    if any(not _valid_module_name(module) for module in normalized_modules):
        raise LifecycleError("finding-impact-scope-module-invalid", "modules contains an invalid package module")
    body = {
        "schemaVersion": FINDING_IMPACT_SCOPE_SCHEMA,
        "status": "FROZEN",
        "findingId": finding_id,
        "findingDigest": finding_digest,
        "planRevision": plan_revision,
        "planDigest": plan_digest,
        "sourceRevision": source_revision,
        "paths": _canonical_scope_paths(paths, "paths", allow_empty=False),
        "modules": normalized_modules,
        "ownershipPaths": _canonical_scope_paths(ownership_paths or [], "ownershipPaths", allow_empty=True),
        "acceptanceIds": _canonical_string_list(sorted(set(acceptance_ids or [])), "acceptanceIds", allow_empty=True),
        "gateIds": _canonical_string_list(sorted(set(gate_ids or [])), "gateIds", allow_empty=True),
        "productionPromotionClaimed": False,
    }
    return {**body, "scopeDigest": canonical_digest(body)}


def validate_finding_impact_scope(scope: dict[str, Any], *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate exact frozen scope lineage and canonical collections."""

    blockers: list[dict[str, Any]] = []
    expected_keys = set(FINDING_CHECK_SCHEMAS[FINDING_IMPACT_SCOPE_SCHEMA]["required"])
    if not isinstance(scope, dict) or set(scope) != expected_keys:
        blockers.append({"code": "finding-impact-scope-shape"})
    else:
        if scope.get("schemaVersion") != FINDING_IMPACT_SCOPE_SCHEMA or scope.get("status") != "FROZEN":
            blockers.append({"code": "finding-impact-scope-status"})
        for field in ("findingId", "sourceRevision"):
            if not isinstance(scope.get(field), str) or not scope[field]:
                blockers.append({"code": "finding-impact-scope-field", "field": field})
        for field in ("findingDigest", "planDigest"):
            if not _is_digest(scope.get(field)):
                blockers.append({"code": "finding-impact-scope-digest", "field": field})
        if (
            not isinstance(scope.get("planRevision"), int)
            or isinstance(scope.get("planRevision"), bool)
            or scope["planRevision"] < 1
        ):
            blockers.append({"code": "finding-impact-scope-revision"})
        for field, allow_empty in (
            ("paths", False),
            ("modules", False),
            ("ownershipPaths", True),
            ("acceptanceIds", True),
            ("gateIds", True),
        ):
            try:
                normalized = _canonical_string_list(scope.get(field), field, allow_empty=allow_empty)
                if normalized != scope.get(field):
                    blockers.append({"code": "finding-impact-scope-list-not-canonical", "field": field})
            except LifecycleError:
                blockers.append({"code": "finding-impact-scope-list-invalid", "field": field})
        for field in ("paths", "ownershipPaths"):
            try:
                if _canonical_scope_paths(scope.get(field), field, allow_empty=field == "ownershipPaths") != scope.get(
                    field
                ):
                    blockers.append({"code": "finding-impact-scope-path-not-canonical", "field": field})
            except LifecycleError:
                blockers.append({"code": "finding-impact-scope-path-invalid", "field": field})
        if any(not _valid_module_name(item) for item in scope.get("modules", [])):
            blockers.append({"code": "finding-impact-scope-module-invalid"})
        for field, value in (expected or {}).items():
            if scope.get(field) != value:
                blockers.append({"code": "finding-impact-scope-lineage", "field": field})
        body = {key: value for key, value in scope.items() if key != "scopeDigest"}
        if scope.get("scopeDigest") != canonical_digest(body):
            blockers.append({"code": "finding-impact-scope-digest-mismatch"})
        if scope.get("productionPromotionClaimed") is not False:
            blockers.append({"code": "finding-impact-scope-production-claim"})
    return _validation(
        FINDING_IMPACT_SCOPE_VALIDATION_SCHEMA,
        blockers,
        findingId=scope.get("findingId")
        if isinstance(scope, dict) and isinstance(scope.get("findingId"), str)
        else None,
    )


def build_finding_check_binding(
    *,
    finding_id: str,
    finding_digest: str,
    plan_delta_digest: str,
    plan_lineage: dict[str, Any],
    check_identity: dict[str, Any],
    owner: str,
    scope: dict[str, Any],
    source_revision: str,
    expected_result: str = "PASS",
    status: str = "PROPOSED",
) -> dict[str, Any]:
    _required_id(finding_id, "findingId")
    _digest(finding_digest, "findingDigest")
    _digest(plan_delta_digest, "planDeltaDigest")
    lineage = _validate_plan_lineage(plan_lineage)
    check = _normalize_check_identity(check_identity)
    _required_text(owner, "owner")
    if not isinstance(scope, dict) or not scope:
        raise LifecycleError("finding-check-scope-invalid", "finding-check scope must be a non-empty object")
    _required_text(source_revision, "sourceRevision")
    if expected_result not in FINDING_CHECK_RESULTS:
        raise LifecycleError("finding-check-result-invalid", "expectedResult is not supported")
    if status not in FINDING_CHECK_STATUSES:
        raise LifecycleError("finding-check-status-invalid", "binding status is not supported")
    identity = {
        "findingId": finding_id,
        "findingDigest": finding_digest,
        "planDeltaDigest": plan_delta_digest,
        "planLineage": lineage,
        "checkIdentity": check,
        "owner": owner,
        "scope": scope,
        "sourceRevision": source_revision,
        "expectedResult": expected_result,
    }
    binding_id = f"finding-check-{canonical_digest(identity)[:32]}"
    body = {
        "schemaVersion": FINDING_CHECK_BINDING_SCHEMA,
        "bindingId": binding_id,
        "status": status,
        **identity,
        "transitions": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "bindingDigest": canonical_digest(body)}


def validate_finding_check_binding(binding: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(binding, dict):
        raise LifecycleError("finding-check-binding-invalid", "binding must be an object")
    if binding.get("schemaVersion") != FINDING_CHECK_BINDING_SCHEMA:
        blockers.append({"code": "finding-check-binding-schema-invalid"})
    status = binding.get("status")
    if status not in FINDING_CHECK_STATUSES:
        blockers.append({"code": "finding-check-status-invalid"})
    for field in ("findingId", "owner", "sourceRevision"):
        if not isinstance(binding.get(field), str) or not binding[field]:
            blockers.append({"code": "finding-check-field-missing", "field": field})
    for field in ("findingDigest", "planDeltaDigest"):
        if not _is_digest(binding.get(field)):
            blockers.append({"code": "finding-check-digest-invalid", "field": field})
    try:
        _validate_plan_lineage(binding.get("planLineage"))
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    try:
        check = _normalize_check_identity(binding.get("checkIdentity"))
        if check != binding.get("checkIdentity"):
            blockers.append({"code": "finding-check-identity-not-canonical"})
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    if not isinstance(binding.get("scope"), dict) or not binding.get("scope"):
        blockers.append({"code": "finding-check-scope-invalid"})
    if binding.get("expectedResult") not in FINDING_CHECK_RESULTS:
        blockers.append({"code": "finding-check-result-invalid"})
    transitions = binding.get("transitions")
    if not isinstance(transitions, list) or len(transitions) > 5:
        blockers.append({"code": "finding-check-transitions-invalid"})
        transitions = []
    _validate_transitions(transitions, status, blockers)
    identity = {
        "findingId": binding.get("findingId"),
        "findingDigest": binding.get("findingDigest"),
        "planDeltaDigest": binding.get("planDeltaDigest"),
        "planLineage": binding.get("planLineage"),
        "checkIdentity": binding.get("checkIdentity"),
        "owner": binding.get("owner"),
        "scope": binding.get("scope"),
        "sourceRevision": binding.get("sourceRevision"),
        "expectedResult": binding.get("expectedResult"),
    }
    expected_binding_id = f"finding-check-{canonical_digest(identity)[:32]}"
    if binding.get("bindingId") != expected_binding_id:
        blockers.append({"code": "finding-check-binding-id-mismatch"})
    expected = canonical_digest({key: value for key, value in binding.items() if key != "bindingDigest"})
    if binding.get("bindingDigest") != expected:
        blockers.append({"code": "finding-check-binding-digest-mismatch"})
    if binding.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "finding-check-production-claim"})
    return _validation(
        FINDING_CHECK_BINDING_VALIDATION_SCHEMA,
        blockers,
        bindingStatus=status if isinstance(status, str) else None,
        bindingId=binding.get("bindingId") if isinstance(binding.get("bindingId"), str) else None,
    )


def build_finding_check_evidence(
    binding: dict[str, Any],
    *,
    result: str,
    source_revision: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    validation = validate_finding_check_binding(binding)
    if validation["status"] != "PASS":
        raise LifecycleError("finding-check-binding-invalid", "cannot build evidence for an invalid binding")
    if result not in FINDING_CHECK_RESULTS:
        raise LifecycleError("finding-check-result-invalid", "evidence result is not supported")
    _required_text(source_revision, "sourceRevision")
    _string_list(evidence_ids, "evidenceIds")
    body = {
        "schemaVersion": FINDING_CHECK_EVIDENCE_SCHEMA,
        "status": result,
        "bindingId": binding["bindingId"],
        "findingId": binding["findingId"],
        "checkIdentity": dict(binding["checkIdentity"]),
        "sourceRevision": source_revision,
        "result": result,
        "evidenceIds": sorted(set(evidence_ids)),
        "readOnly": True,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "evidenceDigest": canonical_digest(body)}


def validate_finding_check_evidence(evidence: dict[str, Any], binding: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(evidence, dict):
        raise LifecycleError("finding-check-evidence-invalid", "evidence must be an object")
    if evidence.get("schemaVersion") != FINDING_CHECK_EVIDENCE_SCHEMA:
        blockers.append({"code": "finding-check-evidence-schema-invalid"})
    if evidence.get("result") not in FINDING_CHECK_RESULTS:
        blockers.append({"code": "finding-check-evidence-result-invalid"})
    if not isinstance(evidence.get("evidenceIds"), list) or not evidence["evidenceIds"]:
        blockers.append({"code": "finding-check-evidence-ids-invalid"})
    if (
        evidence.get("readOnly") is not True
        or evidence.get("modelCallsStarted") is not False
        or evidence.get("hostLaunchStarted") is not False
    ):
        blockers.append({"code": "finding-check-evidence-execution-boundary"})
    expected = canonical_digest({key: value for key, value in evidence.items() if key != "evidenceDigest"})
    if evidence.get("evidenceDigest") != expected:
        blockers.append({"code": "finding-check-evidence-digest-mismatch"})
    if evidence.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "finding-check-evidence-production-claim"})
    if binding is not None:
        binding_validation = validate_finding_check_binding(binding)
        if binding_validation["status"] != "PASS":
            blockers.append({"code": "finding-check-binding-invalid"})
        elif evidence.get("bindingId") != binding.get("bindingId") or evidence.get("findingId") != binding.get(
            "findingId"
        ):
            blockers.append({"code": "finding-check-evidence-lineage-mismatch"})
        elif evidence.get("checkIdentity") != binding.get("checkIdentity"):
            blockers.append({"code": "finding-check-evidence-identity-mismatch"})
        elif evidence.get("sourceRevision") != binding.get("sourceRevision"):
            blockers.append({"code": "finding-check-evidence-source-mismatch"})
    return _validation(
        FINDING_CHECK_EVIDENCE_VALIDATION_SCHEMA,
        blockers,
        result=evidence.get("result") if isinstance(evidence.get("result"), str) else None,
        bindingId=evidence.get("bindingId") if isinstance(evidence.get("bindingId"), str) else None,
    )


def transition_finding_check_binding(
    binding: dict[str, Any],
    target_status: str,
    *,
    authorization: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_finding_check_binding(binding)
    if validation["status"] != "PASS":
        raise LifecycleError("finding-check-binding-invalid", "cannot transition an invalid binding")
    if target_status not in FINDING_CHECK_STATUSES:
        raise LifecycleError("finding-check-transition-invalid", "target status is not supported")
    _validate_authorization(authorization)
    current = str(binding["status"])
    operation_id = authorization["operationId"]
    transitions = list(binding.get("transitions", []))
    if target_status == current:
        if transitions and transitions[-1].get("operationId") == operation_id:
            return _transition_receipt(binding, target_status, True, [])
        raise LifecycleError(
            "finding-check-transition-not-idempotent", "repeated transition requires the original operationId"
        )
    if current == "RETIRED" or target_status == "PROPOSED" or _STATUS_INDEX[target_status] < _STATUS_INDEX[current]:
        raise LifecycleError("finding-check-transition-order", "binding status cannot move backwards")
    if _STATUS_INDEX[target_status] > _STATUS_INDEX[current] + 1 and target_status != "RETIRED":
        raise LifecycleError("finding-check-transition-order", "binding status transition must be sequential")
    if target_status in {"IMPLEMENTED", "VERIFIED"}:
        if not isinstance(evidence, dict):
            raise LifecycleError("finding-check-evidence-required", "implementation and verification require evidence")
        evidence_validation = validate_finding_check_evidence(evidence, binding)
        if evidence_validation["status"] != "PASS":
            raise LifecycleError(
                "finding-check-evidence-invalid", "transition evidence failed validation", evidence_validation
            )
        if target_status == "VERIFIED" and evidence.get("result") != binding.get("expectedResult"):
            raise LifecycleError("finding-check-result-mismatch", "verification result does not match expected result")
    transition = {
        "fromStatus": current,
        "toStatus": target_status,
        "actor": authorization["actor"],
        "operationId": operation_id,
        "authorizationDigest": canonical_digest(authorization),
        "evidenceDigest": evidence.get("evidenceDigest") if isinstance(evidence, dict) else None,
    }
    updated = {**binding, "status": target_status, "transitions": [*transitions, transition]}
    updated["bindingDigest"] = canonical_digest(
        {key: value for key, value in updated.items() if key != "bindingDigest"}
    )
    return _transition_receipt(updated, target_status, False, [])


def validate_finding_check_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(proposal, dict):
        raise LifecycleError("finding-check-proposal-invalid", "proposal must be an object")
    if proposal.get("schemaVersion") != FINDING_CHECK_PROPOSAL_SCHEMA:
        blockers.append({"code": "finding-check-proposal-schema-invalid"})
    binding = proposal.get("binding")
    binding_valid = False
    if isinstance(binding, dict):
        binding_valid = validate_finding_check_binding(binding)["status"] == "PASS"
    if not binding_valid:
        blockers.append({"code": "finding-check-proposal-binding-invalid"})
    if proposal.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "finding-check-proposal-status-invalid"})
    reproduction = proposal.get("reviewerReproduction")
    if reproduction is not None and (
        not isinstance(reproduction, dict)
        or not isinstance(reproduction.get("text"), str)
        or not reproduction["text"]
        or reproduction.get("parsedAsCommand") is not False
        or reproduction.get("executionAuthorityGranted") is not False
    ):
        blockers.append({"code": "finding-check-proposal-reproduction-invalid"})
    if (
        proposal.get("approvalRequired") is not True
        or proposal.get("applyAllowed") is not False
        or proposal.get("authorityClaimed") is not False
    ):
        blockers.append({"code": "finding-check-proposal-authority-boundary"})
    expected = canonical_digest({key: value for key, value in proposal.items() if key != "proposalDigest"})
    if proposal.get("proposalDigest") != expected:
        blockers.append({"code": "finding-check-proposal-digest-mismatch"})
    if proposal.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "finding-check-proposal-production-claim"})
    return _validation(
        FINDING_CHECK_PROPOSAL_VALIDATION_SCHEMA,
        blockers,
        proposalStatus=proposal.get("status") if isinstance(proposal.get("status"), str) else None,
    )


def build_finding_check_proposal(binding: dict[str, Any], *, reproduction: str) -> dict[str, Any]:
    """Preserve reviewer reproduction text as advisory data only."""

    validation = validate_finding_check_binding(binding)
    if validation["status"] != "PASS":
        raise LifecycleError("finding-check-proposal-binding-invalid", "proposal binding failed validation")
    _required_text(reproduction, "reproduction")
    proposal_seed = canonical_digest({"binding": binding["bindingDigest"], "text": reproduction})
    body = {
        "schemaVersion": FINDING_CHECK_PROPOSAL_SCHEMA,
        "proposalId": f"finding-check-proposal-{proposal_seed[:32]}",
        "status": "PASS",
        "binding": dict(binding),
        "reviewerReproduction": {
            "text": reproduction,
            "parsedAsCommand": False,
            "executionAuthorityGranted": False,
        },
        "approvalRequired": True,
        "applyAllowed": False,
        "authorityClaimed": False,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "proposalDigest": canonical_digest(body)}


def _transition_receipt(
    binding: dict[str, Any], target_status: str, idempotent: bool, blockers: list[dict[str, Any]]
) -> dict[str, Any]:
    body = {
        "schemaVersion": FINDING_CHECK_TRANSITION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "binding": binding,
        "targetStatus": target_status,
        "idempotent": idempotent,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "transitionDigest": canonical_digest(body)}


def _validate_plan_lineage(lineage: Any) -> dict[str, Any]:
    if not isinstance(lineage, dict):
        raise LifecycleError("finding-check-plan-lineage-invalid", "planLineage must be an object")
    required = ("packageId", "planRevision", "planDigest", "sourceRevision")
    if any(
        not isinstance(lineage.get(key), str) or not lineage[key]
        for key in ("packageId", "planDigest", "sourceRevision")
    ):
        raise LifecycleError("finding-check-plan-lineage-invalid", "planLineage has missing identity fields")
    if (
        not isinstance(lineage.get("planRevision"), int)
        or isinstance(lineage["planRevision"], bool)
        or lineage["planRevision"] < 1
    ):
        raise LifecycleError("finding-check-plan-lineage-invalid", "planLineage revision is invalid")
    if not _is_digest(lineage["planDigest"]):
        raise LifecycleError("finding-check-plan-lineage-invalid", "planLineage digest is invalid")
    return {key: lineage[key] for key in required}


def _normalize_check_identity(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise LifecycleError("finding-check-identity-invalid", "checkIdentity must be an object")
    if any(key in identity for key in ("argv", "command", "exec", "script", "shell")):
        raise LifecycleError("finding-check-identity-authority", "checkIdentity cannot contain executable command text")
    check_id = identity.get("id")
    route = identity.get("route")
    if not isinstance(check_id, str) or not check_id or not isinstance(route, str) or not route:
        raise LifecycleError("finding-check-identity-invalid", "checkIdentity requires id and route")
    route_parts = route.split("/")
    if (
        _CHECK_ROUTE.fullmatch(route) is None
        or route.startswith("/")
        or "//" in route
        or any(part in {".", ".."} for part in route_parts)
    ):
        raise LifecycleError("finding-check-identity-authority", "check route contains unsafe command text")
    normalized = {"id": check_id, "route": route}
    expected = canonical_digest(normalized)
    supplied = identity.get("digest")
    if supplied is not None and supplied != expected:
        raise LifecycleError("finding-check-identity-digest", "check identity digest does not match id and route")
    return {**normalized, "digest": expected}


def _validate_transitions(transitions: list[Any], status: Any, blockers: list[dict[str, Any]]) -> None:
    previous = "PROPOSED"
    for item in transitions:
        if (
            not isinstance(item, dict)
            or item.get("fromStatus") != previous
            or item.get("toStatus") not in FINDING_CHECK_STATUSES
        ):
            blockers.append({"code": "finding-check-transition-history-invalid"})
            return
        if _STATUS_INDEX[item["toStatus"]] < _STATUS_INDEX[previous] and item["toStatus"] != "RETIRED":
            blockers.append({"code": "finding-check-transition-history-invalid"})
            return
        for field in ("actor", "operationId", "authorizationDigest"):
            if not isinstance(item.get(field), str) or not item[field]:
                blockers.append({"code": "finding-check-transition-history-invalid", "field": field})
        previous = item["toStatus"]
    if transitions and status != transitions[-1].get("toStatus"):
        blockers.append({"code": "finding-check-transition-status-mismatch"})
    if not transitions and status != "PROPOSED":
        blockers.append({"code": "finding-check-transition-history-missing"})


def _validate_authorization(authorization: Any) -> None:
    if not isinstance(authorization, dict) or authorization.get("status") != "APPROVED":
        raise LifecycleError("finding-check-authorization-required", "an approved authorization is required")
    for field in ("actor", "operationId"):
        _required_text(authorization.get(field), f"authorization.{field}")
    if authorization.get("authorityClaimed") is True:
        raise LifecycleError("finding-check-authority-boundary", "finding-check evidence cannot claim authority")


def _validation(schema: str, blockers: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    body = {
        "schemaVersion": schema,
        "status": "PASS" if not blockers else "FAIL",
        **fields,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _required_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise LifecycleError("finding-check-field-invalid", f"{field} must be a non-empty bounded string")


def _required_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise LifecycleError("finding-check-field-invalid", f"{field} must be a non-empty bounded string")


def _digest(value: Any, field: str) -> None:
    if not _is_digest(value):
        raise LifecycleError("finding-check-digest-invalid", f"{field} must be a lowercase SHA-256 digest")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _string_list(values: Any, field: str) -> None:
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value or len(value) > 256 for value in values)
    ):
        raise LifecycleError("finding-check-list-invalid", f"{field} must be a non-empty list of bounded strings")


def _canonical_string_list(values: Any, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value or len(value) > 256 for value in values
    ):
        raise LifecycleError("finding-check-list-invalid", f"{field} must be an array of bounded strings")
    normalized = sorted(set(values))
    if normalized != values or (not allow_empty and not normalized) or len(normalized) > 128:
        raise LifecycleError("finding-check-list-invalid", f"{field} must be canonical and within limits")
    return normalized


def _canonical_scope_paths(values: Any, field: str, *, allow_empty: bool) -> list[str]:
    normalized = _canonical_string_list(
        sorted(set(values)) if isinstance(values, list) else values, field, allow_empty=allow_empty
    )
    try:
        paths = sorted(normalize_authority_path(value, label=field) for value in normalized)
    except LifecycleError as exc:
        raise LifecycleError("finding-check-list-invalid", f"{field} contains an invalid repository path") from exc
    return paths


def _valid_module_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and all(part.isidentifier() for part in value.split("."))
        and value.startswith("agent_lifecycle")
    )


__all__ = [
    "FINDING_CHECK_BINDING_SCHEMA",
    "FINDING_CHECK_BINDING_VALIDATION_SCHEMA",
    "FINDING_CHECK_EVIDENCE_SCHEMA",
    "FINDING_CHECK_EVIDENCE_VALIDATION_SCHEMA",
    "FINDING_CHECK_PROPOSAL_SCHEMA",
    "FINDING_CHECK_PROPOSAL_VALIDATION_SCHEMA",
    "FINDING_CHECK_RESULTS",
    "FINDING_CHECK_SCHEMAS",
    "FINDING_CHECK_STATUSES",
    "FINDING_CHECK_TRACEABILITY_SCHEMA",
    "FINDING_CHECK_TRANSITION_SCHEMA",
    "FINDING_IMPACT_SCOPE_SCHEMA",
    "FINDING_IMPACT_SCOPE_VALIDATION_SCHEMA",
    "build_finding_check_binding",
    "build_finding_check_evidence",
    "build_finding_check_proposal",
    "build_finding_impact_scope",
    "transition_finding_check_binding",
    "validate_finding_check_binding",
    "validate_finding_check_evidence",
    "validate_finding_check_proposal",
    "validate_finding_impact_scope",
]
