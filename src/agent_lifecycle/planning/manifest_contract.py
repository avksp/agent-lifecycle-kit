"""Runtime validation for the closed canonical plan manifest contract."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.plan_manifest_schemas import (
    MANIFEST_SCHEMA,
    MANIFEST_VALIDATION_SCHEMA,
)

_TOP_LEVEL = {
    "schemaVersion",
    "status",
    "planRevision",
    "package",
    "planFiles",
    "packageIntegrity",
    "author",
    "baseRevision",
    "importState",
    "externalImport",
    "specification",
    "readOnly",
    "forbiddenWrites",
    "leadOwned",
    "workstreams",
    "acceptance",
    "acceptanceCriteria",
    "validation",
    "orchestration",
    "developerOverview",
    "releaseTarget",
    "releaseImpact",
    "nonGoals",
    "finalAuditGates",
    "securityGates",
    "sandbox",
    "runtimePolicy",
    "budgetPolicy",
    "budgets",
    "contextLimits",
    "dependsOn",
    "reviewMesh",
    "contextCheckpointPolicy",
    "controllerGates",
    "planReview",
    "repositoryReferences",
    "tierResolution",
    "taskTemplates",
    "compatibility",
    "extensions",
}

_PACKAGE = {"id", "title", "workspaceRoot", "artifactRoot", "root", "planArtifactRoot"}
_AUTHOR = {"id", "surface", "runId"}
_BASE_REVISION = {"ref", "sha"}
_PACKAGE_INTEGRITY = {
    "required",
    "lockSchemaVersion",
    "inventorySource",
    "undeclaredTopLevelFiles",
    "allowedUnlistedFiles",
}
_SPECIFICATION = {
    "tier",
    "intent",
    "status",
    "source",
    "requirements",
    "tierResolutionRequest",
    "revision",
    "artifact",
    "completionCheck",
    "goal",
    "constraints",
    "nonGoals",
    "scope",
}
_REQUIREMENT = {"id", "description", "title", "priority", "source", "acceptanceIds", "evidenceIds", "owner"}
_WORKSTREAM = {
    "id",
    "title",
    "owner",
    "reviewer",
    "dependsOn",
    "writes",
    "readOnly",
    "forbiddenWrites",
    "leadOwned",
    "launchGate",
    "capabilityHints",
    "requiredTools",
    "contextRefs",
    "acceptanceIds",
    "evidenceIds",
    "executionPolicy",
    "artifactPaths",
    "required",
    "plannedItems",
    "modelRoute",
    "reviewMesh",
    "controllerGates",
    "taskShape",
    "qualityFloor",
}
_ACCEPTANCE = {"criteria", "evidence", "releaseGate", "qualityFloor"}
_CRITERION = {"id", "requirementIds", "evidenceIds", "statement", "description", "source", "priority"}
_EVIDENCE = {"id", "description", "source", "validation", "artifactPath", "required"}
_VALIDATION = {"commands", "extraEvidence"}
_ORCHESTRATION = {
    "startMode",
    "remediationMode",
    "maxPlanReviewRounds",
    "maxTaskAttempts",
    "maxParallelTasks",
    "maxValidationRunsPerTask",
    "maxToolCallsPerIteration",
    "maxUsageIterationsPerAttempt",
    "maxToolCallsPerTask",
    "maxToolCallsPerRun",
    "maxReportedTokensPerTask",
    "maxReportedTokensPerRun",
    "maxEvidenceArtifactBytes",
    "maxEvidenceBytesPerTask",
    "maxEvidenceBytesPerRun",
    "maxTaskWallSeconds",
    "maxRunWallSeconds",
    "maxContextBytes",
    "maxRenderedPacketBytes",
    "stateFile",
    "eventLog",
    "stepReviewRequired",
    "finalAuditRequired",
}
_AUTHORITY_MARKERS = {
    "writes",
    "readOnly",
    "forbiddenWrites",
    "leadOwned",
    "dependsOn",
    "acceptanceIds",
    "evidenceIds",
    "requirementIds",
    "commands",
    "integrationSeams",
    "forbiddenWriteExceptions",
    "ordering",
    "exceptions",
    "budget",
    "budgets",
    "maxAttempts",
    "maxInvocations",
    "maxWallSeconds",
    "execution",
    "authority",
}


def validate_plan_manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the manifest envelope without executing any plan command."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(manifest, dict):
        blockers.append(_blocker("plan-manifest-object-required", "plan manifest must be an object"))
        return _result(manifest, blockers)
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        blockers.append(_blocker("plan-manifest-schema-unsupported", "plan manifest schemaVersion is unsupported"))
    _unknown_keys(manifest, _TOP_LEVEL, "manifest", blockers)
    if manifest.get("status") not in {"DRAFT", "REOPENED", "FROZEN"}:
        blockers.append(_blocker("plan-manifest-status-invalid", "plan manifest status is invalid"))
    revision = manifest.get("planRevision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        blockers.append(_blocker("plan-manifest-revision-invalid", "planRevision must be a positive integer"))
    package = manifest.get("package")
    if not isinstance(package, dict):
        blockers.append(_blocker("plan-manifest-package-invalid", "package must be an object"))
    else:
        _unknown_keys(package, _PACKAGE, "package", blockers)
        if not isinstance(package.get("id"), str) or not package["id"].strip():
            blockers.append(_blocker("plan-manifest-package-id-missing", "package.id is required"))
    _validate_nested(manifest, blockers)
    _validate_extensions(manifest.get("extensions"), blockers)
    return _result(manifest, blockers)


def require_plan_manifest_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Raise a stable lifecycle error when the canonical contract fails."""

    from agent_lifecycle.contracts import LifecycleError

    result = validate_plan_manifest_contract(manifest)
    if result["status"] != "PASS":
        raise LifecycleError(
            "plan-manifest-contract-failed", "canonical plan manifest contract failed", {"validation": result}
        )
    return result


def _validate_nested(manifest: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    _object_keys(manifest.get("author"), _AUTHOR, "author", blockers)
    _object_keys(manifest.get("baseRevision"), _BASE_REVISION, "baseRevision", blockers)
    _object_keys(manifest.get("specification"), _SPECIFICATION, "specification", blockers)
    specification = manifest.get("specification")
    if isinstance(specification, dict):
        requirements = specification.get("requirements")
        if isinstance(requirements, list):
            for index, requirement in enumerate(requirements):
                _object_keys(requirement, _REQUIREMENT, f"specification.requirements[{index}]", blockers)
    _object_keys(manifest.get("acceptance"), _ACCEPTANCE, "acceptance", blockers)
    acceptance = manifest.get("acceptance")
    if isinstance(acceptance, dict):
        for key, allowed_keys in (("criteria", _CRITERION), ("evidence", _EVIDENCE)):
            values = acceptance.get(key)
            if isinstance(values, list):
                for index, value in enumerate(values):
                    _object_keys(value, allowed_keys, f"acceptance.{key}[{index}]", blockers)
    criteria = manifest.get("acceptanceCriteria")
    if isinstance(criteria, list):
        for index, criterion in enumerate(criteria):
            _object_keys(criterion, _CRITERION, f"acceptanceCriteria[{index}]", blockers)
    _object_keys(manifest.get("validation"), _VALIDATION, "validation", blockers)
    _object_keys(manifest.get("orchestration"), _ORCHESTRATION, "orchestration", blockers)
    integrity = manifest.get("packageIntegrity")
    if integrity is not None:
        if not isinstance(integrity, dict):
            blockers.append(_blocker("plan-manifest-package-integrity-invalid", "packageIntegrity must be an object"))
        else:
            _unknown_keys(integrity, _PACKAGE_INTEGRITY, "packageIntegrity", blockers)
            if integrity.get("lockSchemaVersion") not in {"agent-plan-lock.v1", "agent-plan-lock.v2"}:
                blockers.append(
                    _blocker("plan-manifest-lock-schema-invalid", "packageIntegrity lock schema is unsupported")
                )
            if integrity.get("inventorySource") not in {None, "planFiles"}:
                blockers.append(
                    _blocker("plan-manifest-inventory-source-invalid", "package integrity inventory must use planFiles")
                )
            if integrity.get("undeclaredTopLevelFiles") not in {None, "reject"}:
                blockers.append(
                    _blocker("plan-manifest-undeclared-policy-invalid", "undeclared top-level files must be rejected")
                )
            allowed_files = integrity.get("allowedUnlistedFiles")
            if allowed_files is not None and (
                not isinstance(allowed_files, list)
                or any(not isinstance(item, str) or not item for item in allowed_files)
            ):
                blockers.append(
                    _blocker(
                        "plan-manifest-allowed-files-invalid", "allowedUnlistedFiles must be a non-empty string list"
                    )
                )
    workstreams = manifest.get("workstreams")
    if isinstance(workstreams, list):
        for index, workstream in enumerate(workstreams):
            _object_keys(workstream, _WORKSTREAM, f"workstreams[{index}]", blockers)


def _object_keys(value: Any, allowed: set[str], path: str, blockers: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if path == "author" and isinstance(value, str):
        return
    if not isinstance(value, dict):
        blockers.append(_blocker("plan-manifest-nested-object-invalid", f"{path} must be an object", {"path": path}))
        return
    _unknown_keys(value, allowed, path, blockers)


def _unknown_keys(value: dict[str, Any], allowed: set[str], path: str, blockers: list[dict[str, Any]]) -> None:
    for key in sorted(set(value).difference(allowed)):
        code = "plan-manifest-authority-field-unknown" if key in _AUTHORITY_MARKERS else "plan-manifest-field-unknown"
        blockers.append(_blocker(code, f"unknown field at {path}: {key}", {"path": path, "field": key}))


def _validate_extensions(value: Any, blockers: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        blockers.append(_blocker("plan-manifest-extensions-invalid", "extensions must be an object"))
        return
    for namespace, payload in value.items():
        if not isinstance(namespace, str) or not namespace.strip() or namespace in _AUTHORITY_MARKERS:
            blockers.append(
                _blocker("plan-manifest-extension-namespace-invalid", "extensions keys must be advisory namespaces")
            )
            continue
        _reject_extension_authority(payload, f"extensions.{namespace}", blockers)


def _reject_extension_authority(value: Any, path: str, blockers: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _AUTHORITY_MARKERS:
                blockers.append(
                    _blocker("plan-manifest-extension-authority", f"extensions cannot add authority: {path}.{key}")
                )
            _reject_extension_authority(child, f"{path}.{key}", blockers)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_extension_authority(child, f"{path}[{index}]", blockers)


def _blocker(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "context": context or {}}


def _result(manifest: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    package_value = manifest.get("package") if isinstance(manifest, dict) else None
    package = package_value if isinstance(package_value, dict) else {}
    body = {
        "schemaVersion": MANIFEST_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision") if isinstance(manifest, dict) else None,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


__all__ = ["require_plan_manifest_contract", "validate_plan_manifest_contract"]
