"""Operator-facing Review Mesh templates and local packet preparation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.review_mesh.assignments import build_review_mesh_assignment_packet
from agent_lifecycle.review_mesh.contracts import build_review_mesh_profile

REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA = "agent-review-mesh-operator-template.v1"
REVIEW_MESH_OPERATOR_TEMPLATE_LIBRARY_SCHEMA = "agent-review-mesh-operator-template-library.v1"
REVIEW_MESH_PREPARE_RECEIPT_SCHEMA = "agent-review-mesh-prepare-receipt.v1"

REVIEW_MESH_OPERATOR_TEMPLATE_IDS = (
    "leader-draft-review",
    "parallel-research-synthesis",
    "implementation-audit-panel",
)

_DEFAULT_BUDGET = {
    "maxInvocations": 2,
    "maxInputTokens": 12000,
    "maxOutputTokens": 4000,
    "maxWallSeconds": 900,
}

_TEMPLATES: dict[str, dict[str, Any]] = {
    "leader-draft-review": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "leader-draft-review",
        "mode": "leader-draft-multi-review",
        "phase": "plan-review",
        "description": "One lead draft is checked by independent reviewers before freeze.",
        "requiredReviewers": 2,
        "defaultReviewers": [
            {"id": "reviewer-a", "role": "plan-reviewer", "modelClass": "strong-reasoning"},
            {"id": "reviewer-b", "role": "risk-reviewer", "modelClass": "strong-reasoning"},
        ],
        "budgetCap": _DEFAULT_BUDGET,
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
    "parallel-research-synthesis": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "parallel-research-synthesis",
        "mode": "parallel-research-synthesis",
        "phase": "research",
        "description": "Independent research packets are prepared before synthesis.",
        "requiredReviewers": 3,
        "defaultReviewers": [
            {"id": "researcher-a", "role": "architecture-researcher", "modelClass": "strong-reasoning"},
            {"id": "researcher-b", "role": "risk-researcher", "modelClass": "strong-reasoning"},
            {"id": "researcher-c", "role": "local-reviewer", "modelClass": "local-strong-review"},
        ],
        "budgetCap": {
            "maxInvocations": 3,
            "maxInputTokens": 16000,
            "maxOutputTokens": 6000,
            "maxWallSeconds": 1200,
        },
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
    "implementation-audit-panel": {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA,
        "templateId": "implementation-audit-panel",
        "mode": "implementation-audit-panel",
        "phase": "implementation-audit",
        "description": "Multiple auditors check implementation evidence after task completion.",
        "requiredReviewers": 2,
        "defaultReviewers": [
            {"id": "auditor-a", "role": "implementation-auditor", "modelClass": "strong-reasoning"},
            {"id": "auditor-b", "role": "release-auditor", "modelClass": "strong-reasoning"},
        ],
        "budgetCap": _DEFAULT_BUDGET,
        "independenceRequired": True,
        "independenceDimensions": ["host", "model"],
        "blockingDefault": False,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    },
}


def list_review_mesh_operator_templates() -> dict[str, Any]:
    """Return the built-in operator templates without host execution."""

    templates = [get_review_mesh_operator_template(template_id) for template_id in REVIEW_MESH_OPERATOR_TEMPLATE_IDS]
    body = {
        "schemaVersion": REVIEW_MESH_OPERATOR_TEMPLATE_LIBRARY_SCHEMA,
        "templateIds": list(REVIEW_MESH_OPERATOR_TEMPLATE_IDS),
        "templates": templates,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "libraryDigest": canonical_digest(body)}


def get_review_mesh_operator_template(template_id: str) -> dict[str, Any]:
    """Return one built-in operator template by id."""

    if template_id not in _TEMPLATES:
        raise LifecycleError("review-mesh-template-unknown", "unknown Review Mesh operator template", {"templateId": template_id})
    body = deepcopy(_TEMPLATES[template_id])
    return {**body, "templateDigest": canonical_digest(body)}


def validate_review_mesh_operator_template(template: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(template, dict):
        raise LifecycleError("review-mesh-template-invalid", "Review Mesh operator template must be an object")
    if template.get("schemaVersion") != REVIEW_MESH_OPERATOR_TEMPLATE_SCHEMA:
        blockers.append({"code": "review-mesh-template-schema-invalid"})
    template_id = template.get("templateId")
    if template_id not in REVIEW_MESH_OPERATOR_TEMPLATE_IDS:
        blockers.append({"code": "review-mesh-template-id-invalid"})
    if not isinstance(template.get("mode"), str) or not template["mode"]:
        blockers.append({"code": "review-mesh-template-mode-invalid"})
    if not isinstance(template.get("phase"), str) or not template["phase"]:
        blockers.append({"code": "review-mesh-template-phase-invalid"})
    reviewers = template.get("defaultReviewers")
    if not isinstance(reviewers, list) or not reviewers:
        blockers.append({"code": "review-mesh-template-reviewers-invalid"})
    else:
        for reviewer in reviewers:
            try:
                _reviewer_from_mapping(reviewer)
            except LifecycleError as error:
                blockers.append({"code": "review-mesh-template-reviewer-invalid", "error": error.code})
    if not isinstance(template.get("requiredReviewers"), int) or isinstance(template.get("requiredReviewers"), bool) or template["requiredReviewers"] < 1:
        blockers.append({"code": "review-mesh-template-required-reviewers-invalid"})
    if not isinstance(template.get("budgetCap"), dict):
        blockers.append({"code": "review-mesh-template-budget-invalid"})
    for field in ("hostExecutionStarted", "modelCallsStarted", "providerBrokerStarted", "productionPromotionClaimed"):
        if template.get(field) is not False:
            blockers.append({"code": "review-mesh-template-boundary-invalid", "field": field})
    expected_digest = canonical_digest({key: value for key, value in template.items() if key != "templateDigest"})
    if template.get("templateDigest") != expected_digest:
        blockers.append({"code": "review-mesh-template-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-operator-template-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "templateId": template_id if isinstance(template_id, str) else None,
        "blockers": blockers,
        "templateDigest": template.get("templateDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_review_mesh_operator_template_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("review-mesh-template-validation-failed", "Review Mesh operator template validation failed", {"validation": validation})
    return validation


def parse_reviewer_spec(spec: str) -> dict[str, str]:
    """Parse id[:role[:model-class]] into a provider-neutral reviewer descriptor."""

    parts = spec.split(":")
    if len(parts) > 3:
        raise LifecycleError("review-mesh-reviewer-spec-invalid", "reviewer spec must be id[:role[:model-class]]")
    reviewer_id = parts[0].strip() if parts else ""
    role = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "reviewer"
    model_class = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "strong-reasoning"
    return _reviewer_from_mapping({"id": reviewer_id, "role": role, "modelClass": model_class})


def prepare_review_mesh_operator_packets(
    *,
    source: dict[str, Any],
    template_id: str,
    reviewers: list[dict[str, str]] | None = None,
    profile_id: str | None = None,
    phase: str | None = None,
    blocking: bool = False,
    evidence_ids: list[str] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Prepare local Review Mesh packets and an auditable receipt."""

    template = get_review_mesh_operator_template(template_id)
    require_review_mesh_operator_template_pass(validate_review_mesh_operator_template(template))
    selected_reviewers = reviewers or [_reviewer_from_mapping(item) for item in template["defaultReviewers"]]
    if len(selected_reviewers) < template["requiredReviewers"]:
        raise LifecycleError(
            "review-mesh-prepare-reviewer-count-insufficient",
            "template requires more reviewers",
            {"requiredReviewers": template["requiredReviewers"], "actualReviewers": len(selected_reviewers)},
        )
    if blocking and not _source_has_blocking_opt_in(source):
        raise LifecycleError("review-mesh-prepare-blocking-without-plan-opt-in", "blocking Review Mesh requires a frozen plan opt-in")
    selected_phase = phase or template["phase"]
    profile = build_review_mesh_profile(
        profile_id=profile_id or f"{template_id}-profile",
        modes=[template["mode"]],
        default_mode=template["mode"],
        budget_cap=dict(template["budgetCap"]),
        live_calls_allowed=False,
        independence_required=bool(template["independenceRequired"]),
        independence_dimensions=list(template["independenceDimensions"]),
        reviewer_model_classes=_unique_model_classes(selected_reviewers),
    )
    packets = [
        build_review_mesh_assignment_packet(
            source=source,
            mode=template["mode"],
            phase=selected_phase,
            assignment_id=f"{template_id}-{index}",
            reviewer_id=reviewer["id"],
            reviewer_role=reviewer["role"],
            reviewer_model_class=reviewer["modelClass"],
            blocking=blocking,
            profile=profile,
            evidence_ids=evidence_ids or [],
        )
        for index, reviewer in enumerate(selected_reviewers, start=1)
    ]
    artifacts = _write_prepare_artifacts(out_dir=out_dir, profile=profile, packets=packets) if out_dir else []
    body = {
        "schemaVersion": REVIEW_MESH_PREPARE_RECEIPT_SCHEMA,
        "status": "PASS",
        "template": _template_summary(template),
        "source": _source_summary(source),
        "profile": profile,
        "assignmentPackets": packets,
        "artifacts": artifacts,
        "reviewerCount": len(packets),
        "requiredReviewers": template["requiredReviewers"],
        "mode": template["mode"],
        "phase": selected_phase,
        "blocking": bool(blocking),
        "blockingRequiresPlanOptIn": True,
        "hostExecutionStarted": False,
        "modelCallsStarted": False,
        "providerBrokerStarted": False,
        "promptAuthorityGranted": False,
        "portableContractStoresConcreteProviderModel": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _write_prepare_artifacts(*, out_dir: Path, profile: dict[str, Any], packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    profile_path = out_dir / "profile.json"
    write_json_create(profile_path, profile)
    artifacts.append({"role": "profile", "path": "profile.json", "digest": profile["profileDigest"]})
    assignments_dir = out_dir / "assignments"
    assignments_dir.mkdir(parents=True, exist_ok=True)
    for packet in packets:
        assignment_id = packet["assignment"]["assignmentId"]
        relative_path = f"assignments/{assignment_id}.json"
        write_json_create(assignments_dir / f"{assignment_id}.json", packet)
        artifacts.append({"role": "assignment-packet", "path": relative_path, "digest": packet["packetDigest"]})
    return artifacts


def _reviewer_from_mapping(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise LifecycleError("review-mesh-reviewer-invalid", "reviewer must be an object")
    reviewer_id = _required_string(value.get("id"), "review-mesh-reviewer-id-invalid")
    role = _required_string(value.get("role"), "review-mesh-reviewer-role-invalid")
    model_class = _required_string(value.get("modelClass"), "review-mesh-reviewer-model-class-invalid")
    if model_class not in ALLOWED_MODEL_CLASSES or model_class == "no-model":
        raise LifecycleError("review-mesh-reviewer-model-class-invalid", "reviewer model class is not allowed", {"modelClass": model_class})
    return {"id": reviewer_id, "role": role, "modelClass": model_class}


def _unique_model_classes(reviewers: list[dict[str, str]]) -> list[str]:
    return sorted({reviewer["modelClass"] for reviewer in reviewers})


def _source_has_blocking_opt_in(source: dict[str, Any]) -> bool:
    review_mesh = source.get("reviewMesh")
    return isinstance(review_mesh, dict) and review_mesh.get("required") is True


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    digest = source.get("digest")
    return {
        "kind": source.get("kind"),
        "label": source.get("label"),
        "digest": digest if isinstance(digest, str) else canonical_digest(source),
        "status": source.get("status"),
        "reviewMeshRequired": _source_has_blocking_opt_in(source),
    }


def _template_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateId": template["templateId"],
        "mode": template["mode"],
        "phase": template["phase"],
        "templateDigest": template["templateDigest"],
    }


def _required_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, "required string is missing")
    return value
