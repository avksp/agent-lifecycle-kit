"""Structural completeness checks for SDD plan tiers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.independent_evidence_schemas import validate_independence_requirement
from agent_lifecycle.contracts.ownership_paths import authority_paths_overlap, normalize_authority_path
from agent_lifecycle.contracts.statistical_evidence_schemas import validate_statistical_evidence_requirement
from agent_lifecycle.planning.traceability import validate_plan_traceability

PROFILE_SCHEMA = "agent-plan-completeness-profile.v1"
VALIDATION_SCHEMA = "agent-plan-completeness-validation.v1"
SUPPORTED_TIERS = {"S0", "S1", "S2"}

DEFAULT_PROFILE: dict[str, Any] = {
    "schemaVersion": PROFILE_SCHEMA,
    "profileId": "alk-default-plan-completeness",
    "profiles": {
        "S0": {
            "description": "Bounded mechanical work with exact write scope and one validation route.",
            "requiredChecks": [
                "single-workstream",
                "write-ownership",
                "validation-command",
            ],
        },
        "S1": {
            "description": "Standard single-owner work with requirements, acceptance, evidence and validation.",
            "requiredChecks": [
                "requirements",
                "acceptance",
                "evidence-route",
                "write-ownership",
                "validation-command",
                "release-impact",
            ],
        },
        "S2": {
            "description": "Large or risky work with complete authority, evidence, budgets and final gates.",
            "requiredChecks": [
                "requirements",
                "acceptance",
                "evidence-route",
                "write-ownership",
                "dag",
                "budget-policy",
                "context-limits",
                "security-release-gates",
                "final-audit-gates",
            ],
        },
    },
}


def build_plan_completeness_profile() -> dict[str, Any]:
    body = deepcopy(DEFAULT_PROFILE)
    return {**body, "profileDigest": canonical_digest(body)}


def load_plan_completeness_profile(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return build_plan_completeness_profile()
    profile = read_json_object(path, label="plan completeness profile")
    validation = validate_plan_completeness_profile(profile)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "plan-completeness-profile-invalid",
            "plan completeness profile validation failed",
            {"validation": validation},
        )
    return profile


def validate_plan_completeness_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if profile.get("schemaVersion") != PROFILE_SCHEMA:
        blockers.append(_blocker("invalid-profile-schema", "profile schemaVersion is unsupported"))
    profiles = profile.get("profiles")
    if not isinstance(profiles, dict):
        blockers.append(_blocker("missing-tier-profiles", "profiles must contain S0, S1 and S2"))
    else:
        missing = sorted(SUPPORTED_TIERS.difference(profiles))
        if missing:
            blockers.append(
                _blocker("missing-tier-profiles", "profiles must contain S0, S1 and S2", {"missing": missing})
            )
        for tier in sorted(SUPPORTED_TIERS.intersection(profiles)):
            required = profiles[tier].get("requiredChecks") if isinstance(profiles[tier], dict) else None
            if not isinstance(required, list) or not all(isinstance(item, str) and item for item in required):
                blockers.append(
                    _blocker(
                        "invalid-required-checks", "tier profile requiredChecks must be a string list", {"tier": tier}
                    )
                )
    expected_digest = profile.get("profileDigest")
    if expected_digest is not None:
        body = {key: value for key, value in profile.items() if key != "profileDigest"}
        if expected_digest != canonical_digest(body):
            blockers.append(_blocker("profile-digest-mismatch", "profileDigest does not match profile body"))
    body = {
        "schemaVersion": "agent-plan-completeness-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "profileId": profile.get("profileId"),
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_plan_completeness(
    manifest: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_profile = profile or build_plan_completeness_profile()
    profile_validation = validate_plan_completeness_profile(active_profile)
    blockers = list(profile_validation["blockers"])
    tier = _tier(manifest)
    if tier not in SUPPORTED_TIERS:
        blockers.append(_blocker("invalid-plan-tier", "plan tier must be S0, S1 or S2", {"tier": tier}))
        tier = "S2"
    required_checks = _required_checks(active_profile, tier)
    for check in required_checks:
        _CHECKS[check](manifest, tier, blockers)
    if tier == "S2" and _canonical_authority_enabled(manifest):
        # Plans carrying packageIntegrity use the closed graph and path rules.
        # Older frozen plans remain readable under their historical profile.
        _check_traceability(manifest, tier, blockers)
        _check_path_authority(manifest, tier, blockers)
        required_checks = [*required_checks, "traceability", "path-authority"]
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageId": _package_id(manifest),
        "tier": tier,
        "requiredChecks": required_checks,
        "blockers": blockers,
        "profileDigest": active_profile.get("profileDigest") or canonical_digest(active_profile),
        "planDigest": canonical_digest(manifest),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_plan_completeness_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "plan-completeness-failed",
            "plan completeness check failed",
            {"validation": validation},
        )
    return validation


def _tier(manifest: dict[str, Any]) -> str:
    specification = manifest.get("specification")
    if isinstance(specification, dict) and isinstance(specification.get("tier"), str):
        return specification["tier"]
    raw = manifest.get("tier")
    return raw if isinstance(raw, str) else "S1"


def _package_id(manifest: dict[str, Any]) -> str | None:
    package = manifest.get("package")
    return package.get("id") if isinstance(package, dict) and isinstance(package.get("id"), str) else None


def _required_checks(profile: dict[str, Any], tier: str) -> list[str]:
    profiles = profile.get("profiles") if isinstance(profile.get("profiles"), dict) else {}
    tier_profile = profiles.get(tier) if isinstance(profiles, dict) else None
    required = tier_profile.get("requiredChecks") if isinstance(tier_profile, dict) else []
    return _strings(required)


def _check_single_workstream(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    workstreams = _workstreams(manifest)
    if len(workstreams) != 1:
        blockers.append(
            _blocker("s0-single-workstream-missing", "S0 plans must contain exactly one workstream", {"tier": tier})
        )


def _check_requirements(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    specification = manifest.get("specification")
    requirements = specification.get("requirements") if isinstance(specification, dict) else None
    if not isinstance(requirements, list) or not requirements:
        blockers.append(
            _blocker("missing-requirements", "plan specification must contain requirements", {"tier": tier})
        )


def _check_acceptance(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    criteria = _acceptance_criteria(manifest)
    if not criteria:
        blockers.append(_blocker("missing-acceptance", "plan must contain acceptance criteria", {"tier": tier}))
        return
    for criterion in criteria:
        if not isinstance(criterion.get("id"), str) or not criterion["id"]:
            blockers.append(_blocker("missing-acceptance-id", "acceptance criterion id is required", {"tier": tier}))
        independence = criterion.get("independence")
        if independence is not None:
            validation = validate_independence_requirement(independence)
            if validation["status"] != "PASS":
                blockers.append(
                    _blocker(
                        "invalid-independence-requirement",
                        "criterion independence requirement is invalid",
                        {"criterionId": criterion.get("id"), "validation": validation},
                    )
                )
            elif independence.get("required") is True and not _strings(criterion.get("independentEvidenceIds")):
                blockers.append(
                    _blocker(
                        "missing-independent-evidence-route",
                        "a criterion requiring independence must route independent evidence ids",
                        {"criterionId": criterion.get("id")},
                    )
                )
        statistical = criterion.get("statisticalEvidence")
        if statistical is None:
            continue
        statistical_validation = validate_statistical_evidence_requirement(statistical)
        if statistical_validation["status"] != "PASS":
            blockers.append(
                _blocker(
                    "invalid-statistical-evidence-requirement",
                    "criterion statistical evidence requirement is invalid",
                    {"criterionId": criterion.get("id"), "validation": statistical_validation},
                )
            )
            continue
        if statistical.get("required") is True and not _strings(criterion.get("statisticalEvidenceIds")):
            blockers.append(
                _blocker(
                    "missing-statistical-evidence-route",
                    "a criterion requiring statistical evidence must route statistical evidence ids",
                    {"criterionId": criterion.get("id")},
                )
            )


def _check_evidence_route(manifest: dict[str, Any], _tier: str, blockers: list[dict[str, Any]]) -> None:
    criteria = _acceptance_criteria(manifest)
    evidence_ids = set()
    for criterion in criteria:
        ids = _strings(criterion.get("evidenceIds"))
        if not ids:
            blockers.append(
                _blocker(
                    "missing-evidence-route",
                    "acceptance criterion must reference evidence ids",
                    {"criterionId": criterion.get("id")},
                )
            )
        evidence_ids.update(ids)
        evidence_ids.update(_strings(criterion.get("independentEvidenceIds")))
        evidence_ids.update(_strings(criterion.get("statisticalEvidenceIds")))
    routed = set()
    for workstream in _workstreams(manifest):
        routed.update(_strings(workstream.get("evidenceIds")))
    validation = manifest.get("validation")
    if isinstance(validation, dict):
        routed.update(_strings(validation.get("extraEvidence")))
    missing = sorted(evidence_ids.difference(routed))
    if missing:
        blockers.append(
            _blocker(
                "missing-evidence-route",
                "evidence ids must be routed to workstreams or validation evidence",
                {"missing": missing},
            )
        )


def _check_write_ownership(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    workstreams = _workstreams(manifest)
    if not workstreams:
        blockers.append(_blocker("missing-write-ownership", "plan must contain workstreams", {"tier": tier}))
        return
    for workstream in workstreams:
        writes = _strings(workstream.get("writes"))
        if not isinstance(workstream.get("id"), str) or not workstream["id"]:
            blockers.append(_blocker("missing-workstream-id", "workstream id is required", {"tier": tier}))
        if not writes:
            blockers.append(
                _blocker(
                    "missing-write-ownership", "workstream writes are required", {"workstreamId": workstream.get("id")}
                )
            )


def _canonical_authority_enabled(manifest: dict[str, Any]) -> bool:
    return isinstance(manifest.get("packageIntegrity"), dict)


def _check_traceability(manifest: dict[str, Any], _tier: str, blockers: list[dict[str, Any]]) -> None:
    validation = validate_plan_traceability(manifest)
    blockers.extend(validation.get("blockers", []))


def _check_path_authority(manifest: dict[str, Any], _tier: str, blockers: list[dict[str, Any]]) -> None:
    authorities: list[tuple[str, str, str | None]] = []
    for field in ("readOnly", "forbiddenWrites"):
        value = manifest.get(field)
        if isinstance(value, list):
            authorities.extend((field, path, None) for path in value if isinstance(path, str))
    lead_owned = manifest.get("leadOwned")
    if isinstance(lead_owned, list):
        for index, item in enumerate(lead_owned):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                authorities.append(("leadOwned", item["path"], str(index)))
            else:
                blockers.append(
                    _blocker("authority-path-invalid", "leadOwned entries require a path", {"index": index})
                )
    workstreams = _workstreams(manifest)
    writes: list[tuple[str, str]] = []
    for workstream in workstreams:
        owner = workstream.get("id")
        if not isinstance(owner, str) or not owner:
            continue
        for path in _strings(workstream.get("writes")):
            writes.append((owner, path))
        for field in ("readOnly", "forbiddenWrites"):
            for path in _strings(workstream.get(field)):
                authorities.append((field, path, owner))
        for item in workstream.get("leadOwned", []) if isinstance(workstream.get("leadOwned"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                authorities.append(("leadOwned", item["path"], owner))

    normalized_authorities: list[tuple[str, str, str | None]] = []
    for category, path, owner in authorities:
        try:
            normalized_authorities.append((category, normalize_authority_path(path, label=f"{category} path"), owner))
        except LifecycleError as exc:
            blockers.append(
                _blocker("authority-path-invalid", str(exc), {"category": category, "path": path, "owner": owner})
            )
    normalized_writes: list[tuple[str, str]] = []
    for owner, path in writes:
        try:
            normalized_writes.append((owner, normalize_authority_path(path, label=f"{owner} write path")))
        except LifecycleError as exc:
            blockers.append(
                _blocker("authority-path-invalid", str(exc), {"category": "writes", "path": path, "owner": owner})
            )

    for index, (left_owner, left_path) in enumerate(normalized_writes):
        for right_owner, right_path in normalized_writes[index + 1 :]:
            if left_owner != right_owner and authority_paths_overlap(left_path, right_path):
                blockers.append(
                    _blocker(
                        "authority-write-conflict",
                        "workstream write prefixes overlap",
                        {"leftOwner": left_owner, "left": left_path, "rightOwner": right_owner, "right": right_path},
                    )
                )
    for owner, write_path in normalized_writes:
        for category, protected_path, protected_owner in normalized_authorities:
            if authority_paths_overlap(write_path, protected_path):
                blockers.append(
                    _blocker(
                        "authority-protected-write-conflict",
                        "workstream write intersects protected authority path",
                        {
                            "owner": owner,
                            "write": write_path,
                            "category": category,
                            "protected": protected_path,
                            "protectedOwner": protected_owner,
                        },
                    )
                )


def _check_validation_command(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    validation = manifest.get("validation")
    commands = validation.get("commands") if isinstance(validation, dict) else None
    if not isinstance(commands, list) or not any(isinstance(item, str) and item.strip() for item in commands):
        blockers.append(
            _blocker(
                "missing-validation-command",
                "plan validation.commands must contain at least one command",
                {"tier": tier},
            )
        )


def _check_release_impact(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    if not any(key in manifest for key in ("releaseTarget", "releaseImpact", "nonGoals", "finalAuditGates")):
        blockers.append(
            _blocker(
                "missing-release-impact", "S1 plans must state release impact or non-release boundary", {"tier": tier}
            )
        )


def _check_dag(manifest: dict[str, Any], _tier: str, blockers: list[dict[str, Any]]) -> None:
    workstreams = _workstreams(manifest)
    ids: list[str] = []
    for workstream in workstreams:
        identifier = workstream.get("id")
        if isinstance(identifier, str):
            ids.append(identifier)
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        blockers.append(
            _blocker("duplicate-workstream-id", "workstream ids must be unique", {"duplicates": duplicates})
        )
    id_set = set(ids)
    for workstream in workstreams:
        depends_on = workstream.get("dependsOn")
        if not isinstance(depends_on, list):
            blockers.append(
                _blocker("missing-dag", "S2 workstreams must declare dependsOn", {"workstreamId": workstream.get("id")})
            )
            continue
        unknown = sorted(item for item in _strings(depends_on) if item not in id_set)
        if unknown:
            blockers.append(
                _blocker(
                    "unknown-workstream-dependency",
                    "workstream dependsOn references unknown ids",
                    {"workstreamId": workstream.get("id"), "unknown": unknown},
                )
            )
    if _has_cycle(workstreams):
        blockers.append(_blocker("cyclic-workstream-dag", "workstream DAG must be acyclic"))


def _check_budget_policy(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    validation = manifest.get("validation")
    has_budget = any(
        _has_path(manifest, path)
        for path in (
            ("budgets",),
            ("budgetPolicy",),
            ("budgetTargets",),
            ("resourceBudgets",),
            ("validation", "budgetPolicy"),
            ("validation", "budgetTargets"),
        )
    )
    if isinstance(validation, dict):
        has_budget = has_budget or any("budget" in str(item).lower() for item in _strings(validation.get("commands")))
    if not has_budget:
        blockers.append(
            _blocker(
                "missing-budget-policy",
                "S2 plans must declare token/resource budget policy or validation",
                {"tier": tier},
            )
        )


def _check_context_limits(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    specification = manifest.get("specification")
    tier_request = specification.get("tierResolutionRequest") if isinstance(specification, dict) else None
    has_limits = any(
        _has_path(manifest, path)
        for path in (
            ("contextLimits",),
            ("contextBudget",),
            ("smallContext",),
            ("validation", "contextLimits"),
        )
    )
    if isinstance(tier_request, dict):
        has_limits = has_limits or isinstance(tier_request.get("requirementsBytes"), int)
    if not has_limits:
        blockers.append(
            _blocker(
                "missing-context-limits", "S2 plans must define context limits or tier byte bounds", {"tier": tier}
            )
        )


def _check_security_release_gates(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    has_security = bool(_strings(manifest.get("forbiddenWrites"))) or any(
        key in manifest for key in ("securityGates", "sandbox", "runtimePolicy")
    )
    has_release = (
        "releaseTarget" not in manifest
        or bool(_strings(manifest.get("finalAuditGates")))
        or _has_path(manifest, ("validation", "commands"))
    )
    if not has_security:
        blockers.append(
            _blocker("missing-security-gate", "S2 plans must declare security or containment gates", {"tier": tier})
        )
    if not has_release:
        blockers.append(
            _blocker("missing-release-gate", "release S2 plans must declare release validation gates", {"tier": tier})
        )


def _check_final_audit_gates(manifest: dict[str, Any], tier: str, blockers: list[dict[str, Any]]) -> None:
    if not _strings(manifest.get("finalAuditGates")):
        blockers.append(
            _blocker("s2-final-audit-gate-missing", "S2 plans must declare final audit gates", {"tier": tier})
        )


def _workstreams(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workstreams = manifest.get("workstreams")
    return [item for item in workstreams if isinstance(item, dict)] if isinstance(workstreams, list) else []


def _acceptance_criteria(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    acceptance = manifest.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else manifest.get("acceptanceCriteria")
    return [item for item in criteria if isinstance(item, dict)] if isinstance(criteria, list) else []


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _has_path(payload: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current not in (None, {}, [], "")


def _has_cycle(workstreams: list[dict[str, Any]]) -> bool:
    graph: dict[str, list[str]] = {}
    for workstream in workstreams:
        identifier = workstream.get("id")
        if isinstance(identifier, str):
            graph[identifier] = _strings(workstream.get("dependsOn"))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in graph.get(node, []):
            if child in graph and visit(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _blocker(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "context": context or {}}


_CHECKS = {
    "single-workstream": _check_single_workstream,
    "requirements": _check_requirements,
    "acceptance": _check_acceptance,
    "evidence-route": _check_evidence_route,
    "write-ownership": _check_write_ownership,
    "validation-command": _check_validation_command,
    "release-impact": _check_release_impact,
    "dag": _check_dag,
    "budget-policy": _check_budget_policy,
    "context-limits": _check_context_limits,
    "security-release-gates": _check_security_release_gates,
    "final-audit-gates": _check_final_audit_gates,
}
