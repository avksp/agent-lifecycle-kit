"""Team-scale plan continuity helpers.

The helpers in this module are optional: a plan without repository references
keeps the existing single-checkout lifecycle unchanged.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.domain_language import domain_language_digest, validate_domain_language
from agent_lifecycle.contracts.domain_language_schemas import (
    DOMAIN_LANGUAGE_CONTINUITY_SCHEMA,
    DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA,
)
from agent_lifecycle.contracts.paths import normalize_repo_path

REFERENCE_VALIDATION_SCHEMA = "agent-plan-reference-validation.v1"
SNAPSHOT_SCHEMA = "agent-plan-snapshot.v1"
RECONCILIATION_SCHEMA = "agent-plan-reconciliation.v1"
HANDOFF_SCHEMA = "agent-plan-handoff.v1"

DRIFT_MATCH = "MATCH"
DRIFT_REQUIRES_NEW_PLAN = "REQUIRES_NEW_PLAN"
DRIFT_BLOCKED = "BLOCKED"


def validate_repository_references(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate optional cross-repository references in a plan manifest."""

    blockers: list[dict[str, Any]] = []
    references = _repository_references(manifest, blockers)
    seen_ids: set[str] = set()
    for index, reference in enumerate(references):
        ref_id = _required_text(reference, "id", index, blockers)
        repo_id = _required_text(reference, "repoId", index, blockers)
        owner = _required_text(reference, "owner", index, blockers)
        access = reference.get("access")
        if access not in {"read-only", "write-scoped"}:
            blockers.append({"code": "invalid-repository-access", "index": index, "access": access})
        if ref_id:
            if ref_id in seen_ids:
                blockers.append({"code": "duplicate-repository-reference", "id": ref_id})
            seen_ids.add(ref_id)
        if repo_id and _looks_like_local_absolute_path(repo_id):
            blockers.append({"code": "absolute-repository-reference", "index": index, "field": "repoId"})
        paths = reference.get("paths", [])
        if not isinstance(paths, list) or any(not isinstance(item, str) or not item.strip() for item in paths):
            blockers.append({"code": "invalid-repository-reference-paths", "index": index})
            paths = []
        for path in paths:
            try:
                normalize_repo_path(path)
            except LifecycleError as exc:
                blockers.append(
                    {"code": "invalid-repository-reference-path", "index": index, "path": path, "reason": exc.code}
                )
        if access == "write-scoped" and not paths:
            blockers.append({"code": "write-reference-missing-paths", "index": index})
        if owner and _looks_like_local_absolute_path(owner):
            blockers.append({"code": "invalid-repository-owner", "index": index})
    status = "PASS" if not blockers else "FAIL"
    repository_ids: set[str] = {item["repoId"] for item in references if isinstance(item.get("repoId"), str)}
    body = {
        "schemaVersion": REFERENCE_VALIDATION_SCHEMA,
        "status": status,
        "packageId": _package_id(manifest),
        "referenceCount": len(references),
        "repositoryIds": sorted(repository_ids),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_repository_references_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "plan-references-validation-failed", "repository references failed validation", {"validation": validation}
        )
    return validation


def build_plan_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build an immutable content-addressed snapshot for a frozen plan."""

    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-snapshot-requires-frozen-manifest", "plan snapshot requires a frozen manifest")
    references_validation = require_repository_references_pass(validate_repository_references(manifest))
    source_digest = canonical_digest(manifest)
    specification = manifest.get("specification") if isinstance(manifest.get("specification"), dict) else {}
    acceptance = manifest.get("acceptance") if isinstance(manifest.get("acceptance"), dict) else {}
    references = _repository_references(manifest, [])
    body = {
        "schemaVersion": SNAPSHOT_SCHEMA,
        "status": "PASS",
        "packageId": _package_id(manifest),
        "planRevision": manifest.get("planRevision"),
        "sourceDigest": source_digest,
        "baseRevision": manifest.get("baseRevision") if isinstance(manifest.get("baseRevision"), dict) else {},
        "specificationDigest": canonical_digest(specification),
        "acceptanceDigest": canonical_digest(acceptance),
        "repositoryReferencesDigest": canonical_digest(references),
        "referenceValidationDigest": references_validation["validationDigest"],
        "immutable": True,
    }
    return {**body, "snapshotDigest": canonical_digest(body)}


def build_domain_language_continuity(
    language: dict[str, Any],
    *,
    plan_digest: str | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Bind an optional vocabulary to its own revision and plan lineage."""

    validation = validate_domain_language(language)
    body = {
        "schemaVersion": DOMAIN_LANGUAGE_CONTINUITY_SCHEMA,
        "status": "PASS" if validation["status"] == "PASS" else "FAIL",
        "languageId": language.get("languageId") if isinstance(language, dict) else None,
        "revision": language.get("revision") if isinstance(language, dict) else None,
        "languageDigest": domain_language_digest(language) if isinstance(language, dict) else None,
        "planDigest": plan_digest,
        "sourceRevision": source_revision,
        "blockers": validation.get("blockers", []),
        "productionPromotionClaimed": False,
    }
    return {**body, "continuityDigest": canonical_digest(body)}


def reconcile_domain_language_continuity(
    snapshot: dict[str, Any],
    language: dict[str, Any],
    *,
    plan_digest: str | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Check that a vocabulary snapshot still names the same immutable inputs."""

    current = build_domain_language_continuity(
        language,
        plan_digest=plan_digest,
        source_revision=source_revision,
    )
    blockers: list[dict[str, Any]] = []
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != current["schemaVersion"]:
        blockers.append({"code": "domain-language-continuity-schema-invalid"})
    for field in ("languageId", "revision", "languageDigest", "planDigest", "sourceRevision"):
        if isinstance(snapshot, dict) and snapshot.get(field) != current.get(field):
            blockers.append({"code": "domain-language-continuity-drift", "field": field})
    if isinstance(snapshot, dict):
        expected = canonical_digest({key: value for key, value in snapshot.items() if key != "continuityDigest"})
        if snapshot.get("continuityDigest") != expected:
            blockers.append({"code": "domain-language-continuity-digest-mismatch"})
    body = {
        "schemaVersion": DOMAIN_LANGUAGE_CONTINUITY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def reconcile_plan_snapshot(snapshot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Compare a saved plan snapshot with the current manifest."""

    blockers: list[dict[str, Any]] = []
    if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA:
        blockers.append({"code": "invalid-plan-snapshot-schema"})
    if snapshot.get("immutable") is not True:
        blockers.append({"code": "mutable-plan-snapshot"})
    package_id = _package_id(manifest)
    if snapshot.get("packageId") != package_id:
        blockers.append(
            {"code": "plan-snapshot-package-drift", "expected": snapshot.get("packageId"), "actual": package_id}
        )
    source_digest = canonical_digest(manifest)
    classification = DRIFT_MATCH
    if blockers:
        classification = DRIFT_BLOCKED
    elif snapshot.get("sourceDigest") != source_digest:
        classification = DRIFT_REQUIRES_NEW_PLAN
        blockers.append(
            {"code": "plan-snapshot-source-drift", "expected": snapshot.get("sourceDigest"), "actual": source_digest}
        )
    elif snapshot.get("planRevision") != manifest.get("planRevision"):
        classification = DRIFT_REQUIRES_NEW_PLAN
        blockers.append(
            {
                "code": "plan-snapshot-revision-drift",
                "expected": snapshot.get("planRevision"),
                "actual": manifest.get("planRevision"),
            }
        )
    status = "PASS" if classification == DRIFT_MATCH else "FAIL"
    body = {
        "schemaVersion": RECONCILIATION_SCHEMA,
        "status": status,
        "classification": classification,
        "packageId": package_id,
        "snapshotDigest": snapshot.get("snapshotDigest"),
        "currentDigest": source_digest,
        "blockers": blockers,
    }
    return {**body, "reconciliationDigest": canonical_digest(body)}


def require_reconciliation_pass(reconciliation: dict[str, Any]) -> dict[str, Any]:
    if reconciliation.get("status") != "PASS":
        raise LifecycleError(
            "plan-reconciliation-failed",
            "plan reconciliation blocked the current manifest",
            {"reconciliation": reconciliation},
        )
    return reconciliation


def render_plan_handoff(
    manifest: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
    max_workstreams: int = 12,
    target_tokens: int = 4096,
) -> dict[str, Any]:
    """Render a compact reviewer handoff packet for team-scale planning."""

    if max_workstreams <= 0:
        raise LifecycleError("invalid-plan-handoff-limit", "max_workstreams must be positive")
    if target_tokens <= 0:
        raise LifecycleError("invalid-plan-handoff-limit", "target_tokens must be positive")
    references_validation = validate_repository_references(manifest)
    workstreams = [item for item in manifest.get("workstreams", []) if isinstance(item, dict)]
    selected = workstreams[:max_workstreams]
    body = {
        "schemaVersion": HANDOFF_SCHEMA,
        "status": "PASS",
        "packageId": _package_id(manifest),
        "planRevision": manifest.get("planRevision"),
        "planStatus": manifest.get("status"),
        "baseRevision": manifest.get("baseRevision") if isinstance(manifest.get("baseRevision"), dict) else {},
        "snapshotDigest": snapshot.get("snapshotDigest") if isinstance(snapshot, dict) else None,
        "repositoryReferences": _reference_projection(_repository_references(manifest, [])),
        "referenceValidation": {
            "status": references_validation["status"],
            "referenceCount": references_validation["referenceCount"],
            "blockerCount": len(references_validation["blockers"]),
        },
        "workstreams": [_workstream_projection(item) for item in selected],
        "acceptanceIds": _acceptance_ids(manifest),
        "omitted": {
            "workstreamCount": max(0, len(workstreams) - len(selected)),
            "reason": "outside-compact-reviewer-handoff",
        },
        "sourceDigest": canonical_digest(manifest),
    }
    tokens = estimate_tokens(body)
    body["estimatedTokens"] = tokens
    body["targetTokens"] = target_tokens
    if tokens > target_tokens or references_validation["status"] != "PASS":
        body["status"] = "FAIL"
    return {**body, "handoffDigest": canonical_digest(body)}


def _repository_references(manifest: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = manifest.get("repositoryReferences", [])
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        blockers.append({"code": "invalid-repository-references", "message": "repositoryReferences must be an array"})
        return []
    references: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            blockers.append({"code": "invalid-repository-reference", "index": index})
            continue
        references.append(item)
    return references


def _required_text(reference: dict[str, Any], field: str, index: int, blockers: list[dict[str, Any]]) -> str | None:
    value = reference.get(field)
    if not isinstance(value, str) or not value.strip():
        blockers.append({"code": "repository-reference-field-required", "index": index, "field": field})
        return None
    return value


def _looks_like_local_absolute_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\") or (len(value) > 2 and value[1:3] in {":\\", ":/"})


def _package_id(manifest: dict[str, Any]) -> str | None:
    package_value = manifest.get("package")
    package = package_value if isinstance(package_value, dict) else {}
    return package.get("id") if isinstance(package.get("id"), str) else None


def _reference_projection(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for item in references:
        raw_paths = item.get("paths")
        paths = raw_paths if isinstance(raw_paths, list) else []
        projected.append(
            {
                "id": item.get("id"),
                "repoId": item.get("repoId"),
                "owner": item.get("owner"),
                "access": item.get("access"),
                "pathCount": len(paths),
            }
        )
    return projected


def _workstream_projection(workstream: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workstream.get("id"),
        "title": workstream.get("title"),
        "owner": workstream.get("owner"),
        "dependsOn": list(workstream.get("dependsOn", [])) if isinstance(workstream.get("dependsOn"), list) else [],
        "writeCount": len(workstream.get("writes", [])) if isinstance(workstream.get("writes"), list) else 0,
        "acceptanceIds": list(workstream.get("acceptanceIds", []))
        if isinstance(workstream.get("acceptanceIds"), list)
        else [],
        "evidenceIds": list(workstream.get("evidenceIds", []))
        if isinstance(workstream.get("evidenceIds"), list)
        else [],
    }


def _acceptance_ids(manifest: dict[str, Any]) -> list[str]:
    acceptance = manifest.get("acceptance")
    if not isinstance(acceptance, dict):
        return []
    criteria = acceptance.get("criteria")
    if not isinstance(criteria, list):
        return []
    return [item["id"] for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)]
