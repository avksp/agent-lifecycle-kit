"""Review Mesh assignment and reviewer packet builders."""

from __future__ import annotations

from typing import Any, cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.independent_evidence_schemas import (
    build_independence_requirement,
    validate_independence_requirement,
)
from agent_lifecycle.contracts.thread_bridge_schemas import validate_thread_context_import
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_assignment,
    build_review_mesh_profile,
    require_review_mesh_assignment_pass,
    validate_review_mesh_assignment,
)

DEFAULT_REVIEWER_MODEL_CLASS = "strong-reasoning"


def build_review_mesh_assignment_packet(
    *,
    source: dict[str, Any],
    mode: str,
    phase: str,
    assignment_id: str,
    reviewer_id: str,
    reviewer_role: str,
    reviewer_model_class: str = DEFAULT_REVIEWER_MODEL_CLASS,
    reviewer_host_identity_hash: str | None = None,
    reviewer_model_identity_hash: str | None = None,
    blocking: bool = False,
    profile: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
    independence_requirement: dict[str, Any] | None = None,
    reviewer_producer_class: str = "independent-reviewer",
) -> dict[str, Any]:
    """Build one host-owned reviewer packet without launching a reviewer."""

    selected_profile = profile or build_review_mesh_profile(default_mode=mode, independence_required=False)
    if independence_requirement is not None:
        requirement_validation = validate_independence_requirement(independence_requirement)
        if requirement_validation["status"] != "PASS":
            raise LifecycleError(
                "review-mesh-assignment-independence-invalid",
                "independence requirement is invalid",
                {"validation": requirement_validation},
            )
    subject = _subject_from_source(source, blocking=blocking)
    if independence_requirement is not None:
        subject["independenceRequired"] = independence_requirement.get("required") is True
        subject["independenceRequirementDigest"] = independence_requirement.get("requirementDigest")
    reviewer = _reviewer(
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        reviewer_model_class=reviewer_model_class,
        host_identity_hash=reviewer_host_identity_hash,
        model_identity_hash=reviewer_model_identity_hash,
        producer_class=reviewer_producer_class,
    )
    assignment = build_review_mesh_assignment(
        profile=selected_profile,
        assignment_id=assignment_id,
        subject=subject,
        reviewer=reviewer,
        mode=mode,
        phase=phase,
        blocking=blocking,
        evidence_ids=evidence_ids or [],
        independence_requirement=independence_requirement,
    )
    require_review_mesh_assignment_pass(validate_review_mesh_assignment(assignment, profile=selected_profile))
    packet_body = {
        "schemaVersion": "agent-review-mesh-reviewer-packet.v1",
        "assignment": assignment,
        "reviewerTask": {
            "phase": phase,
            "mode": mode,
            "subject": subject,
            "expectedResultSchema": "agent-review-mesh-result.v1",
            "hostOwnedExecution": True,
            "alkCoreLaunchAllowed": False,
            "promptAuthorityGranted": False,
        },
        "budgetCap": assignment["budgetCap"],
        "providerNeutralModelClassHint": reviewer["modelClass"],
        "productionPromotionClaimed": False,
    }
    return {**packet_body, "packetDigest": canonical_digest(packet_body)}


def build_security_verification_assignment_packet(
    *,
    source: dict[str, Any],
    assignment_id: str,
    phase: str = "implementation-verification",
    reviewer_id: str,
    reviewer_role: str = "security-verifier",
    reviewer_model_class: str = DEFAULT_REVIEWER_MODEL_CLASS,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Prepare a blocking security verification packet with explicit independence."""

    requirement = build_independence_requirement(
        required=True,
        required_dimensions=["producer", "implementation", "source"],
        allowed_methods=["deterministic-check", "human-review"],
        prohibited_producer_classes=["implementer", "primary-implementer"],
        source_policy="exact-revision",
    )
    packet = build_review_mesh_assignment_packet(
        source=source,
        mode="implementation-audit-panel",
        phase=phase,
        assignment_id=assignment_id,
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        reviewer_model_class=reviewer_model_class,
        blocking=True,
        evidence_ids=evidence_ids or [],
        independence_requirement=requirement,
        reviewer_producer_class="independent-reviewer",
    )
    body = {
        **packet,
        "securityAnalysis": {
            "profileId": "security-analysis.v1",
            "independentVerificationRequired": True,
            "authorityClaimed": False,
        },
    }
    return {
        **body,
        "packetDigest": canonical_digest({key: value for key, value in body.items() if key != "packetDigest"}),
    }


def source_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schemaVersion") != "agent-plan-manifest.v1":
        raise LifecycleError("review-mesh-source-manifest-invalid", "expected agent-plan-manifest.v1")
    package_value = manifest.get("package")
    package = cast(dict[str, Any], package_value) if isinstance(package_value, dict) else {}
    digest = canonical_digest(manifest)
    source = {
        "kind": "PLAN_MANIFEST",
        "label": package.get("id") if isinstance(package.get("id"), str) else "plan-manifest",
        "digest": digest,
        "status": manifest.get("status"),
        "reviewMesh": dict(manifest.get("reviewMesh", {})) if isinstance(manifest.get("reviewMesh"), dict) else {},
    }
    base_revision = manifest.get("baseRevision")
    if isinstance(base_revision, dict) and isinstance(base_revision.get("sha"), str) and base_revision["sha"]:
        source.update(
            {
                "sourceRevision": base_revision["sha"],
                "sourceLineageDigest": canonical_digest(
                    {"kind": "PLAN_MANIFEST", "planDigest": digest, "baseRevision": base_revision}
                ),
                "primaryProducerClass": "plan-authority",
                "primaryImplementationDigest": canonical_digest(
                    {"kind": "PLAN_IMPLEMENTATION", "baseRevision": base_revision}
                ),
            }
        )
    return source


def source_from_intake(intake_receipt: dict[str, Any]) -> dict[str, Any]:
    if intake_receipt.get("schemaVersion") != "agent-adapter-task-start-receipt.v1":
        raise LifecycleError("review-mesh-source-intake-invalid", "expected agent-adapter-task-start-receipt.v1")
    input_value = intake_receipt.get("input")
    input_summary = cast(dict[str, Any], input_value) if isinstance(input_value, dict) else {}
    return {
        "kind": "ADAPTER_TASK_INTAKE",
        "label": input_summary.get("label") or intake_receipt.get("adapterId") or "adapter-task-intake",
        "digest": intake_receipt.get("receiptDigest") or canonical_digest(intake_receipt),
        "status": intake_receipt.get("status"),
        "reviewMeshRecommendation": intake_receipt.get("reviewMeshRecommendation")
        if isinstance(intake_receipt.get("reviewMeshRecommendation"), dict)
        else None,
    }


def source_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "PLAN_HANDOFF",
        "label": str(handoff.get("packageId") or handoff.get("taskId") or "plan-handoff"),
        "digest": canonical_digest(handoff),
        "status": handoff.get("status"),
    }


def source_from_thread_context(imported_context: dict[str, Any]) -> dict[str, Any]:
    """Declare imported thread context as an optional, non-proof review source."""

    validation = validate_thread_context_import(imported_context)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "review-mesh-source-thread-context-invalid",
            "thread context is not a valid import",
            {"validation": validation},
        )
    source_value = imported_context.get("source")
    source = cast(dict[str, Any], source_value) if isinstance(source_value, dict) else {}
    return {
        "kind": "THREAD_CONTEXT_IMPORT",
        "label": source.get("sourceId") or "thread-context",
        "digest": imported_context["importDigest"],
        "status": imported_context["status"],
        "sourceOfTruth": False,
        "proof": False,
        "reviewMeshRequired": False,
        "contextRole": "optional-thread-context",
    }


def _subject_from_source(source: dict[str, Any], *, blocking: bool) -> dict[str, Any]:
    digest = _digest(source.get("digest"), canonical_digest(source))
    subject = {
        "kind": source.get("kind"),
        "label": source.get("label"),
        "subjectDigest": digest,
        "hostIdentityHash": canonical_digest({"subject": digest, "identity": "host"}),
        "modelIdentityHash": canonical_digest({"subject": digest, "identity": "model"}),
        "reviewMeshBlockingOptIn": bool(blocking or _source_review_mesh_required(source)),
        "reviewMeshRequired": bool(blocking or _source_review_mesh_required(source)),
    }
    for key in ("sourceRevision", "sourceLineageDigest", "primaryProducerClass", "primaryImplementationDigest"):
        if isinstance(source.get(key), str) and source[key]:
            subject[key] = source[key]
    return subject


def _reviewer(
    *,
    reviewer_id: str,
    reviewer_role: str,
    reviewer_model_class: str,
    host_identity_hash: str | None,
    model_identity_hash: str | None,
    producer_class: str,
) -> dict[str, Any]:
    if reviewer_model_class not in ALLOWED_MODEL_CLASSES:
        raise LifecycleError(
            "review-mesh-reviewer-model-class-invalid",
            "reviewer model class is not provider-neutral",
            {"modelClass": reviewer_model_class},
        )
    identity_seed = {"reviewerId": reviewer_id, "role": reviewer_role, "modelClass": reviewer_model_class}
    return {
        "id": _required(reviewer_id, "reviewerId"),
        "role": _required(reviewer_role, "reviewerRole"),
        "modelClass": reviewer_model_class,
        "producerClass": _required(producer_class, "reviewerProducerClass"),
        "hostIdentityHash": _digest(host_identity_hash, canonical_digest({**identity_seed, "identity": "host"})),
        "modelIdentityHash": _digest(model_identity_hash, canonical_digest({**identity_seed, "identity": "model"})),
    }


def _source_review_mesh_required(source: dict[str, Any]) -> bool:
    review_mesh = source.get("reviewMesh")
    return isinstance(review_mesh, dict) and review_mesh.get("required") is True


def _digest(value: Any, fallback: str) -> str:
    if isinstance(value, str) and len(value) == 64:
        return value
    return fallback


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("review-mesh-assignment-input-missing", f"{label} is required")
    return value
