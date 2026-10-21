"""Pure compact-to-canonical DRAFT translation using existing ALK validators."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_text import require_manifest_text
from agent_lifecycle.contracts.compact_plan_schemas import MAX_COMPACT_OUTPUT_BYTES, require_compact_plan_input
from agent_lifecycle.contracts.ownership_paths import authority_paths_overlap, require_manifest_authority_paths
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path
from agent_lifecycle.planning.completeness import build_plan_completeness_profile
from agent_lifecycle.planning.tiering import resolve_sdd_tier
from agent_lifecycle.planning.traceability import validate_plan_traceability
from agent_lifecycle.planning.validation import validate_plan_manifest

_RESERVED_ROOTS = (".git", ".alk", ".claude")


def compile_compact_plan(source: dict[str, Any], *, source_path: str, manifest_path: str) -> dict[str, Any]:
    """Return a detached canonical draft; never write, review, freeze or execute."""
    source = deepcopy(require_compact_plan_input(source))
    paths = _source_paths(source, source_path, manifest_path)
    tier_request = _tier_request(source)
    resolution = resolve_sdd_tier(tier_request)
    if resolution["tier"] == "S2":
        raise LifecycleError("compact-plan-full-s2-required", "Resolved risks require the full S2 route")
    _require_scope(source)
    requirements, criteria, evidence, workstreams, commands = _change_projection(source)
    package = {**source["package"], "root": ".", "workspaceRoot": "."}
    runtime = package["artifactRoot"]
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "DRAFT",
        "planRevision": 1,
        "package": package,
        "planFiles": sorted(paths.values()),
        "packageIntegrity": {
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "inventorySource": "planFiles",
            "undeclaredTopLevelFiles": "reject",
            "allowedUnlistedFiles": ["plan.lock.json"],
        },
        "author": source["author"],
        "baseRevision": source["baseRevision"],
        "specification": {
            "tier": source["tier"],
            "intent": "to-be",
            "status": "DRAFT",
            "source": paths["source"],
            "requirements": requirements,
            "tierResolutionRequest": tier_request,
        },
        "workstreams": workstreams,
        "acceptance": {"criteria": criteria, "evidence": evidence},
        "validation": {"commands": commands, "extraEvidence": [item["id"] for item in evidence]},
        "readOnly": source["readOnly"],
        "forbiddenWrites": source["forbiddenWrites"],
        "leadOwned": [
            {"path": package["planArtifactRoot"], "reason": "explicit plan authority"},
            {"path": runtime, "reason": "explicit runtime evidence authority"},
        ],
        "releaseImpact": source["releaseImpact"],
        "securityGates": source["securityGates"],
        "contextLimits": source["contextLimits"],
        "orchestration": {
            **source["orchestration"],
            "stateFile": runtime + "/run.state.json",
            "eventLog": runtime + "/workflow-events.jsonl",
        },
        "planReview": {
            "required": True,
            "report": paths["review"],
            "reviewedRevision": 1,
            "verdict": "READY_TO_FREEZE",
        },
        "implementationAudit": {"required": True, "finalRequired": True},
        "budgetPolicy": {
            "liveHostCallsAllowedByDefault": False,
            "modelTokenBudgetForPlanValidation": 0,
            "moneyFieldsCanonical": False,
            "budgetUnits": "reported-tokens",
        },
        "finalAuditGates": [f"[AC-{item['id']}|EV-{item['id']}] {item['acceptance']}" for item in source["changes"]],
    }
    require_manifest_text(manifest)
    validate_plan_manifest(manifest, require_completeness=True)
    require_manifest_authority_paths(manifest)
    trace = validate_plan_traceability(manifest)
    if trace["status"] != "PASS":
        raise LifecycleError("compact-plan-traceability-invalid", "Generated canonical graph is incomplete", trace)
    if len(canonical_bytes(manifest)) + 1 > MAX_COMPACT_OUTPUT_BYTES:
        raise LifecycleError("compact-plan-output-too-large", "Canonical draft exceeds 262144 bytes")
    return manifest


def build_plan_package_profiles() -> dict[str, Any]:
    """Describe authoring eligibility without weakening existing authority gates."""
    existing = build_plan_completeness_profile()
    profiles = []
    for tier, meaning in (
        ("S0", "One explicit mechanical change and executable owner, no elevated risk"),
        ("S1", "Standard serial changes with one executable owner, no elevated risk"),
        ("S2", "Full reviewed package for elevated, external or uncertain risk"),
    ):
        profiles.append(
            {
                "tier": tier,
                "compactSupported": tier != "S2",
                "eligibility": meaning,
                "requiredChecks": existing["profiles"][tier]["requiredChecks"],
                "requiredArtifacts": [
                    "compact source and canonical manifest" if tier != "S2" else "complete full-tier plan package",
                    "independent accepting plan review",
                    "reviewed inventory lock",
                    "task and final audit evidence",
                ],
                "reviewLevel": {"S0": "independent-bounded", "S1": "independent-standard", "S2": "full-independent-s2"}[
                    tier
                ],
                "integrity": "Existing canonical planFiles inventory and reviewed-lock checks; no bypass",
                "independentReviewRequired": True,
                "reviewedLockRequired": True,
                "separateAuthorizationRequired": True,
                "taskAndFinalAuditRequired": True,
            }
        )
    body = {
        "schemaVersion": "agent-plan-package-profiles.v1",
        "status": "READ_ONLY",
        "profiles": profiles,
        "missingTierDefaultsToLowerTier": False,
        "authorityClaimed": False,
        "modelCallsStarted": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def explain_compact_plan(source: dict[str, Any], *, source_path: str, manifest_path: str) -> dict[str, Any]:
    """Explain the same translation read-only, including actionable refusals."""
    requested = source.get("tier") if isinstance(source, dict) else None
    requested = requested if requested in ("S0", "S1", "S2") else None
    try:
        manifest = compile_compact_plan(source, source_path=source_path, manifest_path=manifest_path)
    except LifecycleError as exc:
        return {
            "schemaVersion": "agent-compact-plan-explanation.v1",
            "status": "FAIL",
            "requestedTier": requested,
            "resolvedTier": "S2" if exc.code == "compact-plan-full-s2-required" else None,
            "nextCommands": ["Complete explicit facts; use full S2 planning if scope or risk remains uncertain"],
            "blockers": [{"code": exc.code, "message": exc.message}],
            "filesWritten": False,
            "authorityClaimed": False,
            "modelCallsStarted": False,
        }
    return {
        "schemaVersion": "agent-compact-plan-explanation.v1",
        "status": "PASS",
        "requestedTier": requested,
        "resolvedTier": manifest["specification"]["tier"],
        "manifestDigest": canonical_digest(manifest),
        "canonicalOutputBytes": len(canonical_bytes(manifest)) + 1,
        "mapping": [
            {
                "sourceChangeId": item["id"],
                "requirementId": "R-" + item["id"],
                "acceptanceId": "AC-" + item["id"],
                "evidenceId": "EV-" + item["id"],
                "taskId": "WS-" + item["id"],
            }
            for item in source["changes"]
        ],
        "nextCommands": [
            "plan freeze-prepare",
            "independent plan review",
            "plan lock-create",
            "task compile",
            "workflow init",
            "workflow adopt-plan --start-mode approval-required",
            "workflow authorize",
        ],
        "pendingReviewIsNotAcceptingEvidence": True,
        "filesWritten": False,
        "authorityClaimed": False,
        "modelCallsStarted": False,
    }


def _source_paths(source: dict[str, Any], source_path: str, manifest_path: str) -> dict[str, str]:
    plan = source["package"]["planArtifactRoot"]
    runtime = source["package"]["artifactRoot"]
    normalized = [normalize_repo_path(item) for item in (source_path, manifest_path)]
    if normalized != [source_path, manifest_path] or any(
        character in path for path in normalized for character in "*?[]"
    ):
        raise LifecycleError("compact-plan-path-invalid", "Source/output paths must be canonical relative paths")
    paths = {"source": source_path, "manifest": manifest_path, "review": plan + "/independent-plan-review.json"}
    if any(len(path) > 1024 for path in paths.values()):
        raise LifecycleError("compact-plan-path-invalid", "Source/output/review paths exceed 1024 characters")
    if (
        not is_under_repo_path(source_path, plan)
        or source_path == plan
        or manifest_path != plan + "/plan.manifest.json"
    ):
        raise LifecycleError(
            "compact-plan-output-path-invalid", "Source and canonical manifest must share declared plan root"
        )
    names = list(paths.values())
    if any(_overlap(left, right) for index, left in enumerate(names) for right in names[index + 1 :]):
        raise LifecycleError("compact-plan-input-output-collision", "Source/output/review paths must not overlap")
    if _overlap(plan, runtime):
        raise LifecycleError("compact-plan-root-overlap", "Plan and runtime roots must not overlap")
    for name in (plan, runtime):
        if any(_overlap(name, reserved) for reserved in _RESERVED_ROOTS):
            raise LifecycleError("compact-plan-protected-path", "Plan/runtime roots cannot overlap reserved authority")
    return paths


def _require_scope(source: dict[str, Any]) -> None:
    plan = source["package"]["planArtifactRoot"]
    runtime = source["package"]["artifactRoot"]
    restrictions = source["readOnly"] + source["forbiddenWrites"]
    for root in (plan, runtime):
        if any(_overlap(root, path) for path in restrictions):
            raise LifecycleError("compact-plan-authority-conflict", "Plan/runtime root overlaps a declared restriction")
    for change in source["changes"]:
        evidence = change["evidencePath"]
        if not is_under_repo_path(evidence, runtime) or evidence == runtime:
            raise LifecycleError("compact-plan-evidence-path-invalid", "Evidence must be contained under runtime root")
        for path in change["writes"]:
            if any(_overlap(path, other) for other in [plan, runtime, *_RESERVED_ROOTS, *restrictions]):
                raise LifecycleError(
                    "compact-plan-authority-conflict", "Worker writes overlap protected authority or inputs"
                )


def _tier_request(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "taskCount": len(source["changes"]),
        "executableOwners": [source["owner"]],
        "capabilityHints": ["bounded-mechanical"] if source["mechanical"] else [],
        "riskFlags": {
            name: source["riskFlags"][name]
            for name in ("architecture", "security", "performance", "browser", "externalEnvironment")
        },
        "externalSpecification": source["riskFlags"]["externalSpecification"],
        "requirementsBytes": sum(len(item["requirement"].encode("utf-8")) for item in source["changes"]),
    }


def _change_projection(source: dict[str, Any]) -> tuple[list[Any], list[Any], list[Any], list[Any], list[str]]:
    requirements: list[Any] = []
    criteria: list[Any] = []
    evidence: list[Any] = []
    workstreams: list[Any] = []
    commands: list[str] = []
    for item in source["changes"]:
        identity = item["id"]
        r_id, ac_id, ev_id, ws_id = (prefix + identity for prefix in ("R-", "AC-", "EV-", "WS-"))
        requirements.append(
            {
                "id": r_id,
                "description": item["requirement"],
                "owner": source["owner"],
                "acceptanceIds": [ac_id],
                "evidenceIds": [ev_id],
            }
        )
        criteria.append(
            {"id": ac_id, "requirementIds": [r_id], "evidenceIds": [ev_id], "statement": item["acceptance"]}
        )
        evidence.append(
            {
                "id": ev_id,
                "description": item["evidenceDescription"],
                "artifactPath": item["evidencePath"],
            }
        )
        workstreams.append(
            {
                "id": ws_id,
                "title": item["title"],
                "owner": source["owner"],
                "dependsOn": [workstreams[-1]["id"]] if workstreams else [],
                "writes": item["writes"],
                "acceptanceIds": [ac_id],
                "evidenceIds": [ev_id],
                "plannedItems": [
                    {
                        "id": ac_id,
                        "title": item["title"],
                        "acceptanceIds": [ac_id],
                        "evidenceIds": [ev_id],
                        "validationCommands": item["validationCommands"],
                    }
                ],
            }
        )
        for command in item["validationCommands"]:
            if command not in commands:
                commands.append(command)
    return requirements, criteria, evidence, workstreams, commands


def _overlap(left: str, right: str) -> bool:
    return authority_paths_overlap(left.casefold(), right.casefold())


__all__ = ["build_plan_package_profiles", "compile_compact_plan", "explain_compact_plan"]
