"""Closed, bounded remedy data contracts. No execution or workflow authority."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path

POLICY_VERSION = "agent-review-remedy-policy.v1"
AUTHORITY_VERSION = "agent-review-remedy-authority.v1"
DECISIONS_VERSION = "agent-review-remedy-decisions.v1"
EVIDENCE_VERSION = "agent-review-remedy-evidence.v1"
RECHECK_VERSION = "agent-review-remedy-recheck.v1"
PARTICIPATION_VERSION = "agent-review-remedy-participation.v1"
PHASES = {"freeze", "implementation-audit", "final-audit"}
ARTIFACT_KINDS = {
    "assignment",
    "result",
    "decision",
    "participation",
    "disposition",
    "recheck",
    "delta",
    "dependency",
    "validation-selection",
    "finding-binding",
    "finding-evidence",
    "manifest",
    "lock",
    "state",
}
FINDING_REF_FIELDS = {"findingId", "findingDigest", "assignmentDigest", "resultDigest", "reviewEvidenceDigest"}
PROPOSAL_REF_FIELDS = {"resultDigest", "findingId", "proposalId", "proposalDigest"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def remedy_error(message: str) -> LifecycleError:
    return LifecycleError("review-remedy-invalid", message)


def closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise remedy_error(f"{label} has missing or unknown fields")
    return value


def text(value: Any, label: str, maximum: int = 2048) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise remedy_error(f"{label} must be nonempty bounded text")
    return value


def identity(value: Any, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise remedy_error(f"{label} is not a stable ASCII identity")
    return value


def digest(value: Any, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise remedy_error(f"{label} is not a digest")
    return value


def revision(value: Any) -> str:
    if type(value) is not str or _REVISION.fullmatch(value) is None:
        raise remedy_error("source revision is invalid")
    return value


def bounded_list(value: Any, maximum: int, label: str, *, nonempty: bool = False) -> list[Any]:
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        raise remedy_error(f"{label} must be a bounded list")
    return value


def stable_set(value: Any, maximum: int, label: str, *, paths: bool = False, nonempty: bool = False) -> list[str]:
    items = bounded_list(value, maximum, label, nonempty=nonempty)
    for item in items:
        if paths:
            if type(item) is not str or len(item.encode("utf-8")) > 1024 or normalize_repo_path(item) != item:
                raise remedy_error(f"{label} contains an invalid path")
        else:
            identity(item, label)
    if items != sorted(set(items)):
        raise remedy_error(f"{label} must have unique sorted identities")
    return items


def require_bound_digest(value: dict[str, Any], field: str, maximum: int) -> dict[str, Any]:
    if len(canonical_bytes(value)) > maximum:
        raise remedy_error("serialized remedy contract exceeds its byte cap")
    digest(value.get(field), field)
    if value[field] != canonical_digest({key: item for key, item in value.items() if key != field}):
        raise remedy_error(f"{field} differs from content")
    return value


def require_remedy_policy(value: Any) -> dict[str, Any]:
    value = closed(
        value, {"schemaVersion", "mode", "phases", "maxProposalsPerFinding", "roleScopes", "policyDigest"}, "policy"
    )
    if (
        value["schemaVersion"] != POLICY_VERSION
        or not isinstance(value["mode"], str)
        or value["mode"] not in {"advisory", "required"}
    ):
        raise remedy_error("unsupported remedy policy")
    phases = stable_set(value["phases"], 3, "phases", nonempty=True)
    if set(phases) - PHASES:
        raise remedy_error("unsupported remedy phase")
    cap = value["maxProposalsPerFinding"]
    if type(cap) is not int or not 1 <= cap <= 3:
        raise remedy_error("proposal cap must be 1..3")
    roles = []
    for scope in bounded_list(value["roleScopes"], 32, "role scopes", nonempty=True):
        scope = closed(scope, {"role", "modules", "paths", "checkIds"}, "role scope")
        roles.append(identity(scope["role"], "role"))
        stable_set(scope["modules"], 32, "modules")
        stable_set(scope["paths"], 64, "paths", paths=True)
        stable_set(scope["checkIds"], 64, "check IDs")
    if roles != sorted(set(roles)):
        raise remedy_error("role scopes must have unique sorted roles")
    return require_bound_digest(value, "policyDigest", 65536)


def remedy_policy(config: Any, *, phase: str | None = None) -> dict[str, Any] | None:
    if not isinstance(config, dict) or "remedyProfile" not in config:
        return None
    policy = require_remedy_policy(config["remedyProfile"])
    if policy["mode"] == "required":
        gate_phases = config.get("phases", [])
        if config.get("required") is not True or (gate_phases and not set(policy["phases"]).issubset(gate_phases)):
            raise remedy_error("required remedy phases require the containing Review Mesh gate")
    native_phase = "freeze" if phase == "plan-review" else phase
    quorum = config.get("quorumPolicy", {})
    if not isinstance(quorum, dict):
        raise remedy_error("frozen quorum policy must be an object")
    declared_roles = quorum.get("requiredRoles", config.get("requiredRoles", []))
    if not isinstance(declared_roles, list) or not {scope["role"] for scope in policy["roleScopes"]}.issubset(
        declared_roles
    ):
        raise remedy_error("role scopes must map existing frozen required roles")
    return policy if phase is None or native_phase in policy["phases"] else None


def require_remedy_authority(container: dict[str, Any], *, state: bool = False) -> dict[str, Any] | None:
    policy = remedy_policy(container.get("reviewMesh"))
    required = policy is not None and policy["mode"] == "required"
    marker = container.get("reviewRemedyAuthority")
    if policy is not None and policy["mode"] == "required":
        expected = {
            "schemaVersion": AUTHORITY_VERSION,
            "requiredPolicyDigest": policy["policyDigest"],
            "stateSchemaVersion": "agent-workflow-state.v6",
        }
        if marker != expected:
            raise remedy_error("required remedy policy needs its exact authority marker")
    elif marker is not None:
        raise remedy_error("off/advisory authority must omit the remedy marker")
    if state:
        tasks = container.get("tasks", [])
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            task_policy = remedy_policy(task.get("reviewMesh"))
            if task_policy is not None and task_policy["mode"] == "required" and task_policy != policy:
                raise remedy_error("task remedy cannot introduce or replace run authority")
            if required and task_policy != policy:
                raise remedy_error("task cannot erase the inherited required remedy policy")
            if required:
                task_config = task.get("reviewMesh")
                if not isinstance(task_config, dict):
                    raise remedy_error("task cannot erase the inherited required remedy policy")
                _require_inherited_gate(container["reviewMesh"], task_config)
    if state and (container.get("schemaVersion") == "agent-workflow-state.v6") is not required:
        raise remedy_error("required remedy authority and native v6 must occur together")
    return policy if required else None


def require_proposal(value: Any) -> dict[str, Any]:
    value = closed(value, {"proposalId", "action", "paths", "rationale", "risks", "checks"}, "proposal")
    identity(value["proposalId"], "proposal ID")
    text(value["action"], "action")
    stable_set(value["paths"], 64, "proposal paths", paths=True)
    text(value["rationale"], "rationale")
    for risk in bounded_list(value["risks"], 8, "risks"):
        text(risk, "risk", 512)
    checks = bounded_list(value["checks"], 64, "checks", nonempty=True)
    ids = []
    for check in checks:
        check = closed(check, {"checkId", "expectation"}, "check")
        ids.append(identity(check["checkId"], "check ID"))
        text(check["expectation"], "expectation", 1024)
    if ids != sorted(set(ids)) or len(canonical_bytes(value)) > 16384:
        raise remedy_error("proposal checks or serialized size is invalid")
    return value


def require_finding_remedies(findings: Any, policy: dict[str, Any]) -> None:
    ids = []
    for finding in bounded_list(findings, 256, "findings"):
        if type(finding) is not dict:
            raise remedy_error("finding must be an object")
        ids.append(identity(finding.get("id"), "finding ID"))
        remedy = finding.get("remedy")
        if not isinstance(remedy, dict):
            raise remedy_error("every opted-in finding requires remedy data")
        availability = remedy.get("availability")
        extra = "proposals" if availability == "AVAILABLE" else "reason"
        closed(remedy, {"schemaVersion", "availability", extra}, "finding remedy")
        if remedy["schemaVersion"] != "agent-finding-remedy.v1":
            raise remedy_error("unsupported finding remedy")
        if availability == "AVAILABLE":
            proposals = bounded_list(remedy["proposals"], policy["maxProposalsPerFinding"], "proposals", nonempty=True)
            names = [require_proposal(proposal)["proposalId"] for proposal in proposals]
            if names != sorted(set(names)):
                raise remedy_error("proposal IDs must be unique and sorted")
        elif availability == "UNAVAILABLE":
            text(remedy["reason"], "unavailable reason")
        else:
            raise remedy_error("unsupported remedy availability")
    if len(ids) != len(set(ids)) or len(canonical_bytes(findings)) > 262144:
        raise remedy_error("finding identities or extension size is invalid")


def require_finding_ref(value: Any) -> dict[str, Any]:
    value = closed(value, FINDING_REF_FIELDS, "finding reference")
    identity(value["findingId"], "finding ID")
    for field in FINDING_REF_FIELDS - {"findingId"}:
        digest(value[field], field)
    return value


def require_proposal_ref(value: Any) -> dict[str, Any]:
    value = closed(value, PROPOSAL_REF_FIELDS, "proposal reference")
    if value["resultDigest"] is not None:
        digest(value["resultDigest"], "result digest")
    identity(value["findingId"], "finding ID")
    identity(value["proposalId"], "proposal ID")
    digest(value["proposalDigest"], "proposal digest")
    return value


def require_decisions(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "policyDigest",
        "profileDigest",
        "responseContractDigest",
        "subjectDigest",
        "sourceRevision",
        "sourceLineageDigest",
        "inputResultDigests",
        "coordinatorId",
        "decisions",
        "authorityClaimed",
        "productionPromotionClaimed",
        "decisionsDigest",
    }
    value = closed(value, fields, "decisions")
    if value["schemaVersion"] != DECISIONS_VERSION:
        raise remedy_error("unsupported decisions contract")
    for field in ("policyDigest", "profileDigest", "responseContractDigest", "subjectDigest", "sourceLineageDigest"):
        digest(value[field], field)
    revision(value["sourceRevision"])
    identity(value["coordinatorId"], "coordinator ID")
    results = bounded_list(value["inputResultDigests"], 32, "input results", nonempty=True)
    for item in results:
        digest(item, "result digest")
    if results != sorted(set(results)):
        raise remedy_error("input results must have unique sorted identities")
    for decision in bounded_list(value["decisions"], 256, "decisions"):
        _require_decision(decision)
    _no_authority(value)
    return require_bound_digest(value, "decisionsDigest", 262144)


def _require_decision(value: Any) -> None:
    value = closed(
        value,
        {
            "findingRefs",
            "coordinatorProposals",
            "selected",
            "rationale",
            "comparisons",
            "executionPaths",
            "dispositionDigest",
        },
        "decision",
    )
    refs = bounded_list(value["findingRefs"], 32, "finding origins", nonempty=True)
    _unique_objects([require_finding_ref(item) for item in refs], "finding origins")
    for item in bounded_list(value["coordinatorProposals"], 3, "coordinator proposals"):
        closed(item, {"proposal", "findingRefs"}, "coordinator proposal")
        require_proposal(item["proposal"])
        origins = bounded_list(item["findingRefs"], 32, "coordinator origins", nonempty=True)
        for origin in origins:
            require_finding_ref(origin)
        if origins != refs:
            raise remedy_error("coordinator proposal must bind the complete decision origin set")
    if value["selected"] is not None:
        require_proposal_ref(value["selected"])
    text(value["rationale"], "decision rationale")
    for comparison in bounded_list(value["comparisons"], 95, "comparisons"):
        closed(comparison, {"proposalRef", "reason"}, "comparison")
        require_proposal_ref(comparison["proposalRef"])
        text(comparison["reason"], "comparison reason")
    stable_set(value["executionPaths"], 64, "execution paths", paths=True)
    if value["dispositionDigest"] is not None:
        digest(value["dispositionDigest"], "disposition digest")
    if value["selected"] is None and value["dispositionDigest"] is None:
        raise remedy_error("null selection requires an existing disposition")


def require_evidence_index(value: Any) -> dict[str, Any]:
    value = closed(value, {"schemaVersion", "artifacts", "bundleDigest"}, "evidence index")
    if value["schemaVersion"] != EVIDENCE_VERSION:
        raise remedy_error("unsupported evidence index")
    identities, paths = [], []
    for artifact in bounded_list(value["artifacts"], 512, "artifact references"):
        closed(artifact, {"kind", "path", "sha256", "digest"}, "artifact reference")
        if not isinstance(artifact["kind"], str) or artifact["kind"] not in ARTIFACT_KINDS:
            raise remedy_error("unsupported evidence kind")
        if normalize_repo_path(artifact["path"]) != artifact["path"]:
            raise remedy_error("evidence path must be portable")
        digest(artifact["sha256"], "artifact sha256")
        digest(artifact["digest"], "artifact digest")
        identities.append((artifact["kind"], artifact["digest"]))
        paths.append(artifact["path"])
    if identities != sorted(set(identities)) or len(paths) != len(set(paths)):
        raise remedy_error("evidence identities must be unique and sorted")
    return require_bound_digest(value, "bundleDigest", 65536)


def require_recheck(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "policyDigest",
        "decisionsDigest",
        "findingRefs",
        "runId",
        "taskId",
        "previousAttempt",
        "currentAttempt",
        "currentSubjectDigest",
        "currentSourceRevision",
        "currentSourceLineageDigest",
        "deltaReceiptDigest",
        "disposition",
        "requiredRoles",
        "selectedCheckIds",
        "reviewEvidenceDigests",
        "substitutions",
        "reasons",
        "authorityClaimed",
        "productionPromotionClaimed",
        "recheckDigest",
    }
    value = closed(value, fields, "recheck")
    if value["schemaVersion"] != RECHECK_VERSION:
        raise remedy_error("unsupported recheck")
    for field in ("policyDigest", "decisionsDigest", "currentSubjectDigest", "currentSourceLineageDigest"):
        digest(value[field], field)
    revision(value["currentSourceRevision"])
    identity(value["runId"], "run ID")
    identity(value["taskId"], "task ID")
    if (
        type(value["previousAttempt"]) is not int
        or value["previousAttempt"] < 1
        or type(value["currentAttempt"]) is not int
        or value["currentAttempt"] != value["previousAttempt"] + 1
    ):
        raise remedy_error("recheck requires actual adjacent positive attempts")
    refs = bounded_list(value["findingRefs"], 256, "recheck origins", nonempty=True)
    _unique_objects([require_finding_ref(item) for item in refs], "recheck origins")
    if not isinstance(value["disposition"], str) or value["disposition"] not in {
        "DELTA_REVIEW_AVAILABLE",
        "FULL_AUDIT_REQUIRED",
    }:
        raise remedy_error("unsupported recheck disposition")
    if value["deltaReceiptDigest"] is not None:
        digest(value["deltaReceiptDigest"], "delta digest")
    elif value["disposition"] != "FULL_AUDIT_REQUIRED":
        raise remedy_error("missing delta requires full audit")
    stable_set(value["requiredRoles"], 32, "required roles", nonempty=True)
    stable_set(value["selectedCheckIds"], 64, "selected check IDs")
    reviews = bounded_list(value["reviewEvidenceDigests"], 32, "review evidence")
    for item in reviews:
        digest(item, "review evidence digest")
    if reviews != sorted(set(reviews)):
        raise remedy_error("review evidence digests must be unique and sorted")
    for item in bounded_list(value["substitutions"], 32, "substitutions"):
        closed(item, {"originalReviewerId", "replacementReviewerId", "role", "reason"}, "substitution")
        for field in ("originalReviewerId", "replacementReviewerId", "role"):
            identity(item[field], field)
        text(item["reason"], "substitution reason")
    reasons = bounded_list(value["reasons"], 32, "recheck reasons")
    for reason in reasons:
        text(reason, "recheck reason")
    if value["disposition"] == "FULL_AUDIT_REQUIRED" and not reasons:
        raise remedy_error("full fallback requires a reason")
    _no_authority(value)
    return require_bound_digest(value, "recheckDigest", 65536)


def _unique_objects(values: list[dict[str, Any]], label: str) -> None:
    identities = [canonical_digest(item) for item in values]
    if identities != sorted(set(identities)):
        raise remedy_error(f"{label} must have unique sorted identities")


def _no_authority(value: dict[str, Any]) -> None:
    if value["authorityClaimed"] is not False or value["productionPromotionClaimed"] is not False:
        raise remedy_error("remedy data grants no execution or promotion authority")


def remedy_schema(schema_id: str, fields: list[str]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", *fields],
        "properties": {"schemaVersion": {"const": schema_id}, **{field: {} for field in fields}},
    }


REMEDY_SCHEMAS = {
    AUTHORITY_VERSION: remedy_schema(AUTHORITY_VERSION, ["requiredPolicyDigest", "stateSchemaVersion"]),
    POLICY_VERSION: remedy_schema(
        POLICY_VERSION, ["mode", "phases", "maxProposalsPerFinding", "roleScopes", "policyDigest"]
    ),
    EVIDENCE_VERSION: remedy_schema(EVIDENCE_VERSION, ["artifacts", "bundleDigest"]),
}
REMEDY_SCHEMAS[AUTHORITY_VERSION]["properties"].update(
    requiredPolicyDigest={"type": "string", "pattern": "^[0-9a-f]{64}$"},
    stateSchemaVersion={"const": "agent-workflow-state.v6"},
)


REMEDY_SCHEMAS.update(
    {
        DECISIONS_VERSION: remedy_schema(
            DECISIONS_VERSION,
            [
                "policyDigest",
                "profileDigest",
                "responseContractDigest",
                "subjectDigest",
                "sourceRevision",
                "sourceLineageDigest",
                "inputResultDigests",
                "coordinatorId",
                "decisions",
                "authorityClaimed",
                "productionPromotionClaimed",
                "decisionsDigest",
            ],
        ),
        RECHECK_VERSION: remedy_schema(
            RECHECK_VERSION,
            [
                "policyDigest",
                "decisionsDigest",
                "findingRefs",
                "runId",
                "taskId",
                "previousAttempt",
                "currentAttempt",
                "currentSubjectDigest",
                "currentSourceRevision",
                "currentSourceLineageDigest",
                "deltaReceiptDigest",
                "disposition",
                "requiredRoles",
                "selectedCheckIds",
                "reviewEvidenceDigests",
                "substitutions",
                "reasons",
                "authorityClaimed",
                "productionPromotionClaimed",
                "recheckDigest",
            ],
        ),
        PARTICIPATION_VERSION: remedy_schema(
            PARTICIPATION_VERSION,
            [
                "assignmentDigest",
                "rawOutputDigest",
                "participation",
                "independentEvidence",
                "sessionUsageContext",
                "qualificationDigest",
            ],
        ),
    }
)
for _schema in REMEDY_SCHEMAS.values():
    for _field in _schema["properties"]:
        if _field.endswith("Digest"):
            _schema["properties"][_field] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        elif _field in {"authorityClaimed", "productionPromotionClaimed"}:
            _schema["properties"][_field] = {"const": False}
REMEDY_SCHEMAS[RECHECK_VERSION]["properties"]["deltaReceiptDigest"] = {
    "type": ["string", "null"],
    "pattern": "^[0-9a-f]{64}$",
}


def _require_inherited_gate(run_config: dict[str, Any], task_config: dict[str, Any]) -> None:
    for field in ("required", "phases", "remedyProfile", "profileDigest", "quorumPolicy", "independenceRequirement"):
        if field in run_config and task_config.get(field) != run_config[field]:
            raise remedy_error("task cannot weaken inherited frozen review gate bindings")
    effective = []
    for config in (run_config, task_config):
        quorum = config.get("quorumPolicy", {})
        if not isinstance(quorum, dict):
            raise remedy_error("inherited quorum policy must be an object")
        roles = quorum.get("requiredRoles", config.get("requiredRoles", []))
        minimum = quorum.get("minReviewers", len(run_config["remedyProfile"]["roleScopes"]))
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles) or type(minimum) is not int:
            raise remedy_error("inherited quorum requirements are invalid")
        effective.append((set(roles), minimum))
    if not effective[0][0].issubset(effective[1][0]) or effective[1][1] < effective[0][1]:
        raise remedy_error("task cannot weaken inherited effective quorum requirements")


def _shape(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def _array(items: dict[str, Any], maximum: int, minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": items, "maxItems": maximum, "minItems": minimum, "uniqueItems": True}


_ID_SCHEMA = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
_DIGEST_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TEXT_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 2048}
_PATH_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 1024,
    "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))[^\\\\]+$",
}
_FINDING_REF_SCHEMA = _shape(
    {"findingId": _ID_SCHEMA, **{field: _DIGEST_SCHEMA for field in FINDING_REF_FIELDS - {"findingId"}}}
)
_PROPOSAL_REF_SCHEMA = _shape(
    {
        "resultDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
        "findingId": _ID_SCHEMA,
        "proposalId": _ID_SCHEMA,
        "proposalDigest": _DIGEST_SCHEMA,
    }
)
_PROPOSAL_SCHEMA = _shape(
    {
        "proposalId": _ID_SCHEMA,
        "action": _TEXT_SCHEMA,
        "paths": _array(_PATH_SCHEMA, 64),
        "rationale": _TEXT_SCHEMA,
        "risks": _array({"type": "string", "minLength": 1, "maxLength": 512}, 8),
        "checks": _array(
            _shape({"checkId": _ID_SCHEMA, "expectation": {"type": "string", "minLength": 1, "maxLength": 1024}}), 64, 1
        ),
    }
)
REMEDY_SCHEMAS[POLICY_VERSION]["properties"].update(
    mode={"enum": ["advisory", "required"]},
    phases=_array({"enum": sorted(PHASES)}, 3, 1),
    maxProposalsPerFinding={"type": "integer", "minimum": 1, "maximum": 3},
    roleScopes=_array(
        _shape(
            {
                "role": _ID_SCHEMA,
                "modules": _array(_ID_SCHEMA, 32),
                "paths": _array(_PATH_SCHEMA, 64),
                "checkIds": _array(_ID_SCHEMA, 64),
            }
        ),
        32,
        1,
    ),
)
REMEDY_SCHEMAS[EVIDENCE_VERSION]["properties"]["artifacts"] = _array(
    _shape(
        {
            "kind": {"enum": sorted(ARTIFACT_KINDS)},
            "path": _PATH_SCHEMA,
            "sha256": _DIGEST_SCHEMA,
            "digest": _DIGEST_SCHEMA,
        }
    ),
    512,
)
REMEDY_SCHEMAS[DECISIONS_VERSION]["properties"].update(
    sourceRevision={"type": "string", "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"},
    coordinatorId=_ID_SCHEMA,
    inputResultDigests=_array(_DIGEST_SCHEMA, 32, 1),
    decisions=_array(
        _shape(
            {
                "findingRefs": _array(_FINDING_REF_SCHEMA, 32, 1),
                "coordinatorProposals": _array(
                    _shape({"proposal": _PROPOSAL_SCHEMA, "findingRefs": _array(_FINDING_REF_SCHEMA, 32, 1)}), 3
                ),
                "selected": {"anyOf": [{"type": "null"}, _PROPOSAL_REF_SCHEMA]},
                "rationale": _TEXT_SCHEMA,
                "comparisons": _array(_shape({"proposalRef": _PROPOSAL_REF_SCHEMA, "reason": _TEXT_SCHEMA}), 3),
                "executionPaths": _array(_PATH_SCHEMA, 64),
                "dispositionDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            }
        ),
        256,
    ),
)
REMEDY_SCHEMAS[RECHECK_VERSION]["properties"].update(
    runId=_ID_SCHEMA,
    taskId=_ID_SCHEMA,
    previousAttempt={"type": "integer", "minimum": 1},
    currentAttempt={"type": "integer", "minimum": 2},
    findingRefs=_array(_FINDING_REF_SCHEMA, 256, 1),
    currentSourceRevision={"type": "string", "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"},
    disposition={"enum": ["DELTA_REVIEW_AVAILABLE", "FULL_AUDIT_REQUIRED"]},
    requiredRoles=_array(_ID_SCHEMA, 32, 1),
    selectedCheckIds=_array(_ID_SCHEMA, 64),
    reviewEvidenceDigests=_array(_DIGEST_SCHEMA, 32),
    reasons=_array(_TEXT_SCHEMA, 32),
    substitutions=_array(
        _shape(
            {
                "originalReviewerId": _ID_SCHEMA,
                "replacementReviewerId": _ID_SCHEMA,
                "role": _ID_SCHEMA,
                "reason": _TEXT_SCHEMA,
            }
        ),
        32,
    ),
)
