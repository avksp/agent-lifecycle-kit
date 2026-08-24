"""Criterion-scoped independent evidence checks for Review Mesh."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.independent_evidence_schemas import (
    validate_independence_requirement,
    validate_independent_evidence,
)


def result_independence_blockers(
    *,
    requirement: Any,
    evidence: Any,
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return blockers for one reviewer result without changing authority."""

    if requirement is None:
        return []
    prefix = "review-mesh-result"
    requirement_validation = _requirement_validation(requirement, prefix=prefix)
    if requirement_validation is not None:
        return [requirement_validation]
    if evidence is None:
        return [{"code": f"{prefix}-independent-evidence-required"}] if requirement["required"] is True else []
    validation = validate_independent_evidence(
        evidence,
        requirement=requirement,
        expected_source_revision=subject.get("sourceRevision"),
        expected_source_lineage_digest=subject.get("sourceLineageDigest"),
        primary_producer_class=subject.get("primaryProducerClass"),
        primary_implementation_digest=subject.get("primaryImplementationDigest"),
    )
    if validation["status"] != "PASS" and requirement["required"] is True:
        return [{"code": f"{prefix}-independent-evidence-invalid", "validation": validation}]
    return []


def quorum_independence_blockers(
    *,
    requirement: Any,
    evidence_values: Any,
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return blockers for a quorum's criterion-scoped evidence list."""

    if requirement is None:
        return []
    prefix = "review-mesh-quorum"
    requirement_validation = _requirement_validation(requirement, prefix=prefix)
    if requirement_validation is not None:
        return [requirement_validation]
    if evidence_values is None:
        return [{"code": f"{prefix}-independent-evidence-required"}] if requirement["required"] is True else []
    if not isinstance(evidence_values, list) or not all(isinstance(item, dict) for item in evidence_values):
        return [{"code": f"{prefix}-independent-evidence-invalid"}] if requirement["required"] is True else []
    validations = [
        validate_independent_evidence(
            item,
            requirement=requirement,
            expected_source_revision=subject.get("sourceRevision"),
            expected_source_lineage_digest=subject.get("sourceLineageDigest"),
            primary_producer_class=subject.get("primaryProducerClass"),
            primary_implementation_digest=subject.get("primaryImplementationDigest"),
        )
        for item in evidence_values
    ]
    blockers: list[dict[str, Any]] = []
    if requirement["required"] is True and not any(
        item.get("independenceStatus") == "REQUIRED_PASS" for item in validations
    ):
        blockers.append({"code": f"{prefix}-independent-evidence-required"})
    if requirement["required"] is True:
        blockers.extend(
            {"code": f"{prefix}-independent-evidence-invalid", "validation": item}
            for item in validations
            if item.get("status") != "PASS"
        )
    return blockers


def _requirement_validation(requirement: Any, *, prefix: str) -> dict[str, Any] | None:
    if not isinstance(requirement, dict):
        return {"code": f"{prefix}-independence-requirement-invalid"}
    validation = validate_independence_requirement(requirement)
    if validation["status"] != "PASS":
        return {"code": f"{prefix}-independence-requirement-invalid", "validation": validation}
    return None


__all__ = ["quorum_independence_blockers", "result_independence_blockers"]
