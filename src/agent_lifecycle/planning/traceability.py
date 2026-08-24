"""Deterministic graph checks for canonical plan authority."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.finding_check_schemas import (
    FINDING_CHECK_TRACEABILITY_SCHEMA,
    validate_finding_check_binding,
    validate_finding_check_evidence,
)

TRACEABILITY_SCHEMA = "agent-plan-traceability-validation.v1"
_GATE_LINK_RE = re.compile(r"\[([^|\]]+)\|([^\]]+)\]")


def validate_plan_traceability(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the requirement-to-final-gate graph and workstream ownership."""

    blockers: list[dict[str, Any]] = []
    requirements = _requirements(manifest)
    criteria = _criteria(manifest)
    workstreams = _workstreams(manifest)

    requirement_ids = _unique_ids(requirements, "requirements", blockers)
    criterion_ids = _unique_ids(criteria, "acceptance", blockers)
    workstream_ids = _unique_ids(workstreams, "workstreams", blockers)
    evidence_ids = _evidence_ids(criteria)
    _check_requirement_links(requirements, criteria, requirement_ids, blockers)
    _check_criterion_links(criteria, requirement_ids, evidence_ids, blockers)
    _check_workstream_links(workstreams, criterion_ids, evidence_ids, workstream_ids, blockers)
    _check_final_gates(manifest.get("finalAuditGates"), criterion_ids, evidence_ids, blockers)

    body = {
        "schemaVersion": TRACEABILITY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageId": _package_id(manifest),
        "requirements": sorted(requirement_ids),
        "acceptance": sorted(criterion_ids),
        "evidence": sorted(evidence_ids),
        "workstreams": sorted(workstream_ids),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_finding_check_traceability(
    *,
    findings: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    plan_deltas: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
    active_binding_ids: list[str] | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Validate finding/check lineage without executing any referenced check."""

    blockers: list[dict[str, Any]] = []
    finding_map = {str(item.get("findingId") or item.get("id")): item for item in findings if isinstance(item, dict)}
    delta_map = {str(item.get("deltaDigest")): item for item in plan_deltas if isinstance(item, dict)}
    evidence_values = evidence if isinstance(evidence, list) else []
    active = set(active_binding_ids or [])
    for binding in bindings if isinstance(bindings, list) else []:
        if not isinstance(binding, dict):
            blockers.append(_blocker("finding-check-binding-invalid", "binding must be an object"))
            continue
        validation = validate_finding_check_binding(binding)
        if validation.get("status") != "PASS":
            blockers.append(
                _blocker(
                    "finding-check-binding-invalid",
                    "binding failed contract validation",
                    {"bindingId": binding.get("bindingId")},
                )
            )
            continue
        binding_id = binding["bindingId"]
        finding = finding_map.get(binding["findingId"])
        if not isinstance(finding, dict) or finding.get("findingDigest") not in {None, binding["findingDigest"]}:
            blockers.append(
                _blocker(
                    "finding-check-finding-orphan",
                    "binding does not resolve to the accepted finding",
                    {"bindingId": binding_id},
                )
            )
        delta = delta_map.get(binding["planDeltaDigest"])
        if not isinstance(delta, dict) or delta.get("status") != "PASS":
            blockers.append(
                _blocker(
                    "finding-check-plan-delta-unapproved",
                    "binding does not resolve to a passing plan delta",
                    {"bindingId": binding_id},
                )
            )
        lineage = _object(binding.get("planLineage"))
        delta_after = _object(delta.get("after")) if isinstance(delta, dict) else {}
        if delta and (
            delta_after.get("planDigest") != lineage.get("planDigest")
            or delta_after.get("planRevision") != lineage.get("planRevision")
        ):
            blockers.append(
                _blocker(
                    "finding-check-plan-lineage-mismatch",
                    "binding plan lineage differs from the delta",
                    {"bindingId": binding_id},
                )
            )
        if source_revision is not None and binding.get("sourceRevision") != source_revision:
            blockers.append(
                _blocker("finding-check-source-stale", "binding source revision is stale", {"bindingId": binding_id})
            )
        matching_evidence = [
            item for item in evidence_values if isinstance(item, dict) and item.get("bindingId") == binding_id
        ]
        if binding["status"] in {"IMPLEMENTED", "VERIFIED"} and not matching_evidence:
            blockers.append(
                _blocker("finding-check-evidence-missing", "active binding has no evidence", {"bindingId": binding_id})
            )
        for item in matching_evidence:
            evidence_validation = validate_finding_check_evidence(item, binding)
            if evidence_validation.get("status") != "PASS":
                blockers.append(
                    _blocker(
                        "finding-check-evidence-invalid",
                        "evidence failed contract validation",
                        {"bindingId": binding_id},
                    )
                )
            if item.get("checkIdentity") != binding.get("checkIdentity"):
                blockers.append(
                    _blocker(
                        "finding-check-identity-changed",
                        "evidence check identity differs from binding",
                        {"bindingId": binding_id},
                    )
                )
            if item.get("sourceRevision") != binding.get("sourceRevision"):
                blockers.append(
                    _blocker(
                        "finding-check-source-stale",
                        "evidence source revision differs from binding",
                        {"bindingId": binding_id},
                    )
                )
        if binding["status"] == "RETIRED" and binding_id in active:
            blockers.append(
                _blocker(
                    "finding-check-retired-active",
                    "a retired binding is still claimed as active",
                    {"bindingId": binding_id},
                )
            )
    body = {
        "schemaVersion": FINDING_CHECK_TRACEABILITY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "bindingCount": len(bindings) if isinstance(bindings, list) else 0,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _requirements(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    specification = manifest.get("specification")
    values = specification.get("requirements") if isinstance(specification, dict) else None
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _criteria(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    acceptance = manifest.get("acceptance")
    values = acceptance.get("criteria") if isinstance(acceptance, dict) else manifest.get("acceptanceCriteria")
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _workstreams(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    values = manifest.get("workstreams")
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _unique_ids(values: list[dict[str, Any]], label: str, blockers: list[dict[str, Any]]) -> set[str]:
    ids: list[str] = []
    for index, value in enumerate(values):
        identifier = value.get("id")
        if not isinstance(identifier, str) or not identifier:
            blockers.append(
                _blocker(
                    "traceability-id-missing",
                    f"{label}[{index}] requires a non-empty id",
                    {"label": label, "index": index},
                )
            )
            continue
        ids.append(identifier)
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        blockers.append(
            _blocker("traceability-id-duplicate", f"{label} ids must be unique", {"label": label, "ids": duplicates})
        )
    return set(ids)


def _evidence_ids(criteria: list[dict[str, Any]]) -> set[str]:
    return {identifier for criterion in criteria for identifier in _strings(criterion.get("evidenceIds"))}


def _check_requirement_links(
    _requirements: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    requirement_ids: set[str],
    blockers: list[dict[str, Any]],
) -> None:
    referenced = {identifier for criterion in criteria for identifier in _strings(criterion.get("requirementIds"))}
    for identifier in sorted(requirement_ids.difference(referenced)):
        blockers.append(
            _blocker(
                "traceability-requirement-orphan",
                "requirement is not linked to an acceptance criterion",
                {"requirementId": identifier},
            )
        )
    for criterion in criteria:
        criterion_id = criterion.get("id")
        links = _strings(criterion.get("requirementIds"))
        if not links:
            blockers.append(
                _blocker(
                    "traceability-requirement-link-missing",
                    "acceptance criterion must link a requirement",
                    {"acceptanceId": criterion_id},
                )
            )
        unknown = sorted(set(links).difference(requirement_ids))
        if unknown:
            blockers.append(
                _blocker(
                    "traceability-reference-unknown",
                    "acceptance criterion links an unknown requirement",
                    {"acceptanceId": criterion_id, "unknown": unknown},
                )
            )


def _check_criterion_links(
    criteria: list[dict[str, Any]],
    requirement_ids: set[str],
    evidence_ids: set[str],
    blockers: list[dict[str, Any]],
) -> None:
    for criterion in criteria:
        criterion_id = criterion.get("id")
        links = _strings(criterion.get("evidenceIds"))
        if not links:
            blockers.append(
                _blocker(
                    "traceability-evidence-link-missing",
                    "acceptance criterion must link evidence",
                    {"acceptanceId": criterion_id},
                )
            )
        if len(links) != len(set(links)):
            blockers.append(
                _blocker(
                    "traceability-evidence-duplicate",
                    "acceptance criterion evidence links must be unique",
                    {"acceptanceId": criterion_id},
                )
            )
        unknown = sorted(set(links).difference(evidence_ids))
        if unknown:
            blockers.append(
                _blocker(
                    "traceability-reference-unknown",
                    "acceptance criterion links unknown evidence",
                    {"acceptanceId": criterion_id, "unknown": unknown},
                )
            )
    if not requirement_ids and criteria:
        blockers.append(
            _blocker("traceability-requirements-missing", "acceptance criteria require at least one requirement")
        )


def _check_workstream_links(
    workstreams: list[dict[str, Any]],
    criterion_ids: set[str],
    evidence_ids: set[str],
    workstream_ids: set[str],
    blockers: list[dict[str, Any]],
) -> None:
    acceptance_owners: dict[str, list[str]] = {}
    evidence_owners: dict[str, list[str]] = {}
    for workstream in workstreams:
        workstream_id = workstream.get("id")
        if not isinstance(workstream_id, str) or not workstream_id:
            continue
        for field, known, owners in (
            ("acceptanceIds", criterion_ids, acceptance_owners),
            ("evidenceIds", evidence_ids, evidence_owners),
        ):
            values = _strings(workstream.get(field))
            unknown = sorted(set(values).difference(known))
            if unknown:
                blockers.append(
                    _blocker(
                        "traceability-reference-unknown",
                        f"workstream {field} contains unknown ids",
                        {"workstreamId": workstream_id, "field": field, "unknown": unknown},
                    )
                )
            for identifier in values:
                owners.setdefault(identifier, []).append(workstream_id)
    for label, known, owners in (
        ("acceptance", criterion_ids, acceptance_owners),
        ("evidence", evidence_ids, evidence_owners),
    ):
        for identifier in sorted(known):
            assigned = owners.get(identifier, [])
            if len(assigned) != 1:
                blockers.append(
                    _blocker(
                        "traceability-owner-count",
                        f"{label} id must have exactly one workstream owner",
                        {"id": identifier, "owners": sorted(assigned)},
                    )
                )
    if not workstream_ids:
        blockers.append(_blocker("traceability-workstreams-missing", "traceability requires at least one workstream"))


def _check_final_gates(
    value: Any, criterion_ids: set[str], evidence_ids: set[str], blockers: list[dict[str, Any]]
) -> None:
    if not isinstance(value, list) or not value:
        blockers.append(_blocker("traceability-final-gates-missing", "finalAuditGates must contain linked gates"))
        return
    covered: set[str] = set()
    for index, gate in enumerate(value):
        text = gate if isinstance(gate, str) else gate.get("statement") if isinstance(gate, dict) else None
        if not isinstance(text, str):
            blockers.append(
                _blocker(
                    "traceability-final-gate-invalid",
                    "final audit gate must be text or a statement object",
                    {"index": index},
                )
            )
            continue
        matches = list(_GATE_LINK_RE.finditer(text.lstrip()))
        if not matches or matches[0].start() != 0:
            blockers.append(
                _blocker(
                    "traceability-final-gate-link-missing",
                    "final audit gate must begin with AC|EV links",
                    {"index": index},
                )
            )
            continue
        linked = False
        for match in matches:
            acceptance_id, evidence_id = match.groups()
            if acceptance_id not in criterion_ids or evidence_id not in evidence_ids:
                blockers.append(
                    _blocker(
                        "traceability-final-gate-link-unknown",
                        "final audit gate links an unknown AC or EV",
                        {"index": index, "acceptanceId": acceptance_id, "evidenceId": evidence_id},
                    )
                )
                continue
            linked = True
            covered.add(acceptance_id)
        if not linked:
            blockers.append(
                _blocker(
                    "traceability-final-gate-link-invalid", "final audit gate has no known AC|EV link", {"index": index}
                )
            )
    for identifier in sorted(criterion_ids.difference(covered)):
        blockers.append(
            _blocker(
                "traceability-acceptance-not-final-gated",
                "acceptance criterion is absent from final audit gates",
                {"acceptanceId": identifier},
            )
        )


def _package_id(manifest: dict[str, Any]) -> str | None:
    package = manifest.get("package")
    return package.get("id") if isinstance(package, dict) and isinstance(package.get("id"), str) else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _blocker(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "context": context or {}}


__all__ = ["TRACEABILITY_SCHEMA", "validate_finding_check_traceability", "validate_plan_traceability"]
