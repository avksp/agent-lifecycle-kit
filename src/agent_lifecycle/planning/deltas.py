"""Deterministic, read-only comparison of plan revisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.domain_language import build_domain_language_delta
from agent_lifecycle.contracts.plan_delta_schemas import (
    PLAN_DELTA_SCHEMA,
    PLAN_DELTA_VALIDATION_SCHEMA,
)

_AUTHORITY_CATEGORIES = ("requirements", "writes", "acceptance", "evidence", "budgets", "risks", "gates", "terms")
_CATEGORIES = (*_AUTHORITY_CATEGORIES, "workstreams", "documentation")


def build_plan_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    before_snapshot: dict[str, Any] | None = None,
    after_snapshot: dict[str, Any] | None = None,
    before_lock: dict[str, Any] | None = None,
    after_lock: dict[str, Any] | None = None,
    principles: dict[str, Any] | None = None,
    language_before: dict[str, Any] | None = None,
    language_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two plans without writing or applying either artifact."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(before, dict) or not isinstance(after, dict):
        blockers.append({"code": "plan-delta-input-invalid"})
        before = before if isinstance(before, dict) else {}
        after = after if isinstance(after, dict) else {}

    before_id = _package_id(before)
    after_id = _package_id(after)
    if before_id is None or after_id is None:
        blockers.append({"code": "plan-delta-package-id-required"})
    elif before_id != after_id:
        blockers.append({"code": "plan-delta-package-mismatch", "before": before_id, "after": after_id})

    before_revision = before.get("planRevision")
    after_revision = after.get("planRevision")
    if (
        not isinstance(before_revision, int)
        or isinstance(before_revision, bool)
        or not isinstance(after_revision, int)
        or isinstance(after_revision, bool)
        or after_revision <= before_revision
    ):
        blockers.append({"code": "plan-delta-revision-not-increasing"})

    before_digest = canonical_digest(before)
    after_digest = canonical_digest(after)
    _check_snapshot(before_snapshot, before_digest, "before", blockers)
    _check_snapshot(after_snapshot, after_digest, "after", blockers)
    _check_lock(before_lock, before_digest, "before", blockers)
    _check_lock(after_lock, after_digest, "after", blockers)
    if principles is not None and not isinstance(principles, dict):
        blockers.append({"code": "plan-delta-principles-invalid"})
    if (language_before is None) != (language_after is None):
        blockers.append({"code": "plan-delta-language-pair-required"})
    term_changes = None
    if isinstance(language_before, dict) and isinstance(language_after, dict):
        term_changes = build_domain_language_delta(language_before, language_after)
        if term_changes.get("status") != "PASS":
            blockers.append({"code": "plan-delta-language-invalid", "details": term_changes.get("blockers", [])})

    projections = _projections(before, after, language_before=language_before, language_after=language_after)
    changes = {
        category: _compare(before_value, after_value) for category, (before_value, after_value) in projections.items()
    }
    changed_categories = [category for category in _CATEGORIES if _has_changes(changes[category])]
    authority_categories = [category for category in _AUTHORITY_CATEGORIES if _has_changes(changes[category])]
    authority_impact = {
        "changed": bool(authority_categories),
        "categories": authority_categories,
        "requiresReview": bool(authority_categories),
        "requiresNewLock": bool(authority_categories),
    }
    lineage: dict[str, Any] = {
        "packageId": after_id,
        "revisionIncreased": isinstance(before_revision, int)
        and isinstance(after_revision, int)
        and after_revision > before_revision,
        "beforeSnapshotDigest": before_snapshot.get("snapshotDigest") if isinstance(before_snapshot, dict) else None,
        "afterSnapshotDigest": after_snapshot.get("snapshotDigest") if isinstance(after_snapshot, dict) else None,
        "beforeLockDigest": canonical_digest(before_lock) if isinstance(before_lock, dict) else None,
        "afterLockDigest": canonical_digest(after_lock) if isinstance(after_lock, dict) else None,
        "principlesDigest": principles.get("principlesDigest") if isinstance(principles, dict) else None,
        "domainLanguageBeforeDigest": term_changes.get("beforeDigest") if isinstance(term_changes, dict) else None,
        "domainLanguageAfterDigest": term_changes.get("afterDigest") if isinstance(term_changes, dict) else None,
    }
    body = {
        "schemaVersion": PLAN_DELTA_SCHEMA,
        "status": "PASS" if not blockers else "BLOCKED",
        "before": _identity(before, before_digest),
        "after": _identity(after, after_digest),
        "lineage": lineage,
        "changes": changes,
        "authorityImpact": authority_impact,
        "reviewRequired": bool(authority_categories),
        "newLockRequired": bool(authority_categories),
        "readOnly": True,
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    if term_changes is not None:
        body["termChanges"] = term_changes
    # Keep the report useful without exposing plan prose: categories and
    # digests are sufficient for a reviewer to locate the changed authority.
    lineage["changedCategories"] = changed_categories
    return {**body, "deltaDigest": canonical_digest(body)}


def validate_plan_delta(delta: dict[str, Any]) -> dict[str, Any]:
    """Validate a delta report and its self-digest."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(delta, dict):
        blockers.append({"code": "plan-delta-report-invalid"})
        delta = {}
    if delta.get("schemaVersion") != PLAN_DELTA_SCHEMA:
        blockers.append({"code": "plan-delta-schema-invalid"})
    if delta.get("readOnly") is not True:
        blockers.append({"code": "plan-delta-not-read-only"})
    if delta.get("modelCallsStarted") is not False or delta.get("hostLaunchStarted") is not False:
        blockers.append({"code": "plan-delta-execution-boundary"})
    if delta.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "plan-delta-production-claim"})
    expected = canonical_digest({key: value for key, value in delta.items() if key != "deltaDigest"})
    if delta.get("deltaDigest") != expected:
        blockers.append({"code": "plan-delta-digest-mismatch", "expected": expected})
    if delta.get("status") == "PASS" and delta.get("blockers"):
        blockers.append({"code": "plan-delta-status-blocker-mismatch"})
    if delta.get("status") not in {"PASS", "BLOCKED"}:
        blockers.append({"code": "plan-delta-status-invalid"})
    term_changes = delta.get("termChanges")
    if term_changes is not None:
        if not isinstance(term_changes, dict) or term_changes.get("readOnly") is not True:
            blockers.append({"code": "plan-delta-language-boundary"})
        if isinstance(term_changes, dict):
            if term_changes.get("status") != "PASS":
                blockers.append({"code": "plan-delta-language-status-invalid"})
            if term_changes.get("productionPromotionClaimed") is not False:
                blockers.append({"code": "plan-delta-language-production-claim"})
            expected_term_digest = canonical_digest(
                {key: value for key, value in term_changes.items() if key != "deltaDigest"}
            )
            if term_changes.get("deltaDigest") != expected_term_digest:
                blockers.append({"code": "plan-delta-language-digest-mismatch"})
    report = {
        "schemaVersion": PLAN_DELTA_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "deltaStatus": delta.get("status"),
        "reviewRequired": delta.get("reviewRequired") is True,
        "newLockRequired": delta.get("newLockRequired") is True,
        "blockers": blockers,
        "deltaDigest": delta.get("deltaDigest"),
        "productionPromotionClaimed": False,
    }
    return {**report, "validationDigest": canonical_digest(report)}


def require_plan_delta_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("plan-delta-validation-failed", "plan delta failed validation", {"validation": validation})
    return validation


def finding_check_plan_lineage(delta: dict[str, Any]) -> dict[str, Any]:
    """Project an accepted plan delta into the lineage a check may bind to."""

    validation = validate_plan_delta(delta)
    if validation.get("status") != "PASS" or delta.get("status") != "PASS":
        raise LifecycleError(
            "finding-check-plan-delta-invalid", "a passing plan delta is required for finding adoption"
        )
    after = _object(delta.get("after"))
    base = _object(after.get("baseRevision"))
    package_id = after.get("packageId")
    plan_revision = after.get("planRevision")
    plan_digest = after.get("planDigest")
    source_revision = base.get("sha")
    if (
        not isinstance(package_id, str)
        or not isinstance(plan_revision, int)
        or isinstance(plan_revision, bool)
        or not isinstance(plan_digest, str)
        or not isinstance(source_revision, str)
        or not package_id
        or not source_revision
    ):
        raise LifecycleError("finding-check-plan-lineage-invalid", "plan delta does not contain complete after-lineage")
    return {
        "packageId": package_id,
        "planRevision": plan_revision,
        "planDigest": plan_digest,
        "sourceRevision": source_revision,
    }


def _projections(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    language_before: dict[str, Any] | None = None,
    language_after: dict[str, Any] | None = None,
) -> dict[str, tuple[Any, Any]]:
    return {
        "requirements": (
            _indexed(_object(before.get("specification")).get("requirements"), "id"),
            _indexed(_object(after.get("specification")).get("requirements"), "id"),
        ),
        "writes": (_writes(before), _writes(after)),
        "acceptance": (
            _indexed(before.get("acceptance", {}).get("criteria"), "id"),
            _indexed(after.get("acceptance", {}).get("criteria"), "id"),
        ),
        "evidence": (_evidence(before), _evidence(after)),
        "budgets": (_bounded_object(before.get("budgetPolicy")), _bounded_object(after.get("budgetPolicy"))),
        "risks": (_risk_projection(before), _risk_projection(after)),
        "gates": (_gate_projection(before), _gate_projection(after)),
        "workstreams": (_indexed(before.get("workstreams"), "id"), _indexed(after.get("workstreams"), "id")),
        "documentation": (_documentation_projection(before), _documentation_projection(after)),
        "terms": (_language_projection(language_before), _language_projection(language_after)),
    }


def _compare(before: Any, after: Any) -> dict[str, Any]:
    before_map = before if isinstance(before, dict) else {}
    after_map = after if isinstance(after, dict) else {}
    added = sorted(set(after_map) - set(before_map))
    removed = sorted(set(before_map) - set(after_map))
    changed = [
        {"id": key, "beforeDigest": canonical_digest(before_map[key]), "afterDigest": canonical_digest(after_map[key])}
        for key in sorted(set(before_map) & set(after_map))
        if before_map[key] != after_map[key]
    ]
    return {"added": added, "removed": removed, "changed": changed, "changedCount": len(changed)}


def _indexed(items: Any, key: str) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    result = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get(key), str):
            result[item[key]] = item
    return result


def _writes(manifest: dict[str, Any]) -> dict[str, Any]:
    paths: set[str] = set()
    for workstream in manifest.get("workstreams", []) if isinstance(manifest.get("workstreams"), list) else []:
        if isinstance(workstream, dict) and isinstance(workstream.get("writes"), list):
            paths.update(item for item in workstream["writes"] if isinstance(item, str))
    return {path: {"path": path} for path in sorted(paths)}


def _evidence(manifest: dict[str, Any]) -> dict[str, Any]:
    ids: set[str] = set()
    for workstream in manifest.get("workstreams", []) if isinstance(manifest.get("workstreams"), list) else []:
        if isinstance(workstream, dict):
            ids.update(item for item in workstream.get("evidenceIds", []) if isinstance(item, str))
    validation = manifest.get("validation")
    if isinstance(validation, dict):
        ids.update(item for item in validation.get("extraEvidence", []) if isinstance(item, str))
    return {item: {"id": item} for item in sorted(ids)}


def _risk_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    specification = _object(manifest.get("specification"))
    return {
        "tier": specification.get("tier"),
        "tierResolutionRequest": specification.get("tierResolutionRequest"),
        "securityFlags": manifest.get("securityGates", []),
    }


def _gate_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    validation = _object(manifest.get("validation"))
    return {
        "securityGates": manifest.get("securityGates", []),
        "finalAuditGates": manifest.get("finalAuditGates", []),
        "commands": validation.get("commands", []),
    }


def _documentation_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "planFiles": manifest.get("planFiles", []),
        "developerOverview": manifest.get("developerOverview"),
        "source": _object(manifest.get("specification")).get("source"),
    }


def _language_projection(language: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(language, dict):
        return {}
    return _indexed(language.get("terms"), "termId")


def _bounded_object(value: Any) -> Any:
    return value if isinstance(value, dict) else {}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _identity(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    base = _object(manifest.get("baseRevision"))
    return {
        "packageId": _package_id(manifest),
        "planRevision": manifest.get("planRevision"),
        "status": manifest.get("status"),
        "planDigest": digest,
        "baseRevision": {"ref": base.get("ref"), "sha": base.get("sha")},
    }


def _check_snapshot(snapshot: Any, expected_digest: str, side: str, blockers: list[dict[str, Any]]) -> None:
    if snapshot is None:
        return
    if not isinstance(snapshot, dict) or snapshot.get("sourceDigest") != expected_digest:
        blockers.append({"code": "plan-delta-snapshot-source-mismatch", "side": side})


def _check_lock(lock: Any, expected_digest: str, side: str, blockers: list[dict[str, Any]]) -> None:
    if lock is None:
        return
    if not isinstance(lock, dict) or lock.get("manifestHash") != expected_digest:
        blockers.append({"code": "plan-delta-lock-source-mismatch", "side": side})


def _has_changes(change: dict[str, Any]) -> bool:
    return bool(change.get("added") or change.get("removed") or change.get("changed"))


def _package_id(manifest: dict[str, Any]) -> str | None:
    package = _object(manifest.get("package"))
    value = package.get("id")
    return value if isinstance(value, str) and value else None
