from __future__ import annotations

import argparse
import shlex
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json

from agent_lifecycle.contracts import LifecycleError, normalize_repo_path
from agent_lifecycle.contracts.schemas import get_schema


PLAN_SCHEMA = "agent-live-host-promotion-plan.v1"
EVIDENCE_SCHEMA = "agent-live-host-promotion-plan-validation.v1"

REQUIRED_SHARED_INPUTS = {
    "liveCalibrationProfile",
    "budgetTargets",
    "adapterBaseline",
    "planManifest",
    "planLock",
}
REQUIRED_BLOCKER_CODES = {
    "BLOCKED_USAGE_ATTESTATION",
    "BLOCKED_NON_INTERACTIVE_HOST_SURFACE",
    "BLOCKED_BUDGET_EXHAUSTED",
    "BLOCKED_DIRTY_WORKTREE",
    "BLOCKED_HOST_AUTH",
    "BLOCKED_HOST_CLI_MISSING",
    "BLOCKED_HARNESS_TESTS",
    "BLOCKED_GATEWAY_STARTUP",
}
REQUIRED_ACCEPTANCE_IDS = {f"LHP-AC-{index:02d}" for index in range(1, 9)}
LOCAL_ABSOLUTE_MARKERS = (
    "/Vol" "umes/",
    "/Us" "ers/",
    "/private/" "tmp/",
    "/var/" "folders/",
    "file://",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    plan = load_json(plan_path)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    _validate_registered_schemas(blockers, checks)
    profile = _load_shared_json(plan, "liveCalibrationProfile", blockers)
    baseline = _load_shared_json(plan, "adapterBaseline", blockers)
    _validate_plan(plan, plan_path, profile, baseline, blockers, checks)

    evidence = {
        "schemaVersion": EVIDENCE_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "plan": file_identity(plan_path),
        "planDigest": digest_value(plan),
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _validate_registered_schemas(blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    missing: list[str] = []
    for schema_id in (PLAN_SCHEMA, EVIDENCE_SCHEMA):
        try:
            get_schema(schema_id)
        except LifecycleError:
            missing.append(schema_id)
    _record(
        checks,
        blockers,
        "schema-registry",
        not missing,
        "live-host-promotion-schema-unregistered",
        f"schema registry is missing: {', '.join(missing)}",
    )


def _validate_plan(
    plan: dict[str, Any],
    plan_path: Path,
    profile: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    package_root = plan_path.parent
    _record(
        checks,
        blockers,
        "schema-version",
        plan.get("schemaVersion") == PLAN_SCHEMA,
        "invalid-live-host-promotion-plan-schema",
        f"plan schemaVersion must be {PLAN_SCHEMA}",
    )
    _record(
        checks,
        blockers,
        "sdd-tier",
        plan.get("sddTier") == "S2" and _nested(plan, "tierResolution", "tier") == "S2",
        "invalid-live-host-promotion-tier",
        "live host promotion must remain S2 in the plan and tier resolution",
    )

    host_order = _string_list(plan.get("hostOrder"))
    workstreams = _object_list(plan.get("workstreams"))
    workstreams_by_host = {item.get("host"): item for item in workstreams if isinstance(item.get("host"), str)}
    workstream_ids = [item.get("id") for item in workstreams if isinstance(item.get("id"), str)]
    _record(
        checks,
        blockers,
        "host-order",
        bool(host_order) and len(host_order) == len(set(host_order)) and set(host_order) == set(workstreams_by_host),
        "invalid-live-host-order",
        "hostOrder must be unique and match workstream hosts",
    )
    _record(
        checks,
        blockers,
        "workstream-ids",
        len(workstream_ids) == len(set(workstream_ids)) == len(workstreams),
        "invalid-live-host-workstreams",
        "workstream ids must be unique non-empty strings",
    )
    _record(
        checks,
        blockers,
        "sequencing-policy",
        _nested(plan, "sequencingPolicy", "kind") == "operational-one-host-at-a-time",
        "invalid-live-host-sequencing-policy",
        "sequencingPolicy.kind must be operational-one-host-at-a-time",
    )
    _validate_dependency_graph(host_order, workstreams_by_host, blockers, checks)
    _validate_host_availability(plan, host_order, blockers, checks)
    evidence_root = _evidence_root_for_plan(plan, plan_path)
    _validate_paths(plan, package_root, workstreams, evidence_root, blockers, checks)
    _validate_shared_inputs(plan, blockers, checks)
    _validate_artifact_root_policy(plan, blockers, checks)
    _validate_budget_policy(plan, profile, blockers, checks)
    _validate_operation_requirements(plan, baseline, blockers, checks)
    _validate_blocker_codes(plan, blockers, checks)
    _validate_acceptance(plan, blockers, checks)
    _validate_validation_command(plan, plan_path, evidence_root, blockers, checks)
    _validate_no_local_absolute_paths(plan, blockers, checks)


def _validate_dependency_graph(
    host_order: list[str],
    workstreams_by_host: dict[str, dict[str, Any]],
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    ids_by_host = {
        host: workstream.get("id")
        for host, workstream in workstreams_by_host.items()
        if isinstance(workstream.get("id"), str)
    }
    ids = {item for item in ids_by_host.values() if isinstance(item, str)}
    unknown_deps: list[str] = []
    chain_mismatches: list[str] = []
    graph: dict[str, list[str]] = {}
    for index, host in enumerate(host_order):
        workstream = workstreams_by_host.get(host, {})
        workstream_id = ids_by_host.get(host)
        depends_on = _string_list(workstream.get("dependsOn"))
        if workstream_id:
            graph[workstream_id] = depends_on
        unknown_deps.extend(dep for dep in depends_on if dep not in ids)
        expected = [] if index == 0 else [ids_by_host.get(host_order[index - 1])]
        expected = [item for item in expected if isinstance(item, str)]
        if depends_on != expected:
            chain_mismatches.append(host)
    has_cycle = _has_cycle(graph)
    _record(
        checks,
        blockers,
        "workstream-dependency-graph",
        not unknown_deps and not has_cycle,
        "invalid-live-host-dependencies",
        "workstream dependencies must reference known workstreams and be acyclic",
        {"unknownDependencies": sorted(set(unknown_deps)), "cycle": has_cycle},
    )
    _record(
        checks,
        blockers,
        "operational-sequencing-chain",
        not chain_mismatches,
        "invalid-live-host-sequencing-chain",
        "operational-one-host-at-a-time sequencing must depend on the previous host only",
        {"hosts": chain_mismatches},
    )


def _validate_paths(
    plan: dict[str, Any],
    package_root: Path,
    workstreams: list[dict[str, Any]],
    evidence_root: str,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    invalid: list[str] = []
    missing_host_plans: list[str] = []
    invalid_evidence: list[str] = []
    for value in plan.get("sharedInputs", {}).values() if isinstance(plan.get("sharedInputs"), dict) else []:
        if not isinstance(value, str):
            invalid.append(str(value))
            continue
        if not _repo_path_ok(value):
            invalid.append(value)
        elif not Path(value).is_file():
            invalid.append(value)
    for workstream in workstreams:
        plan_ref = workstream.get("plan")
        if not isinstance(plan_ref, str) or not _repo_path_ok(plan_ref):
            invalid.append(str(plan_ref))
        elif not (package_root / plan_ref).is_file():
            missing_host_plans.append(plan_ref)
        for evidence_path in _string_list(workstream.get("evidence")):
            if not _repo_path_ok(evidence_path) or not evidence_path.startswith(evidence_root):
                invalid_evidence.append(evidence_path)
    _record(
        checks,
        blockers,
        "input-and-plan-paths",
        not invalid and not missing_host_plans,
        "invalid-live-host-promotion-paths",
        "shared inputs and host plan paths must be repository-relative and exist",
        {"invalid": invalid, "missingHostPlans": missing_host_plans},
    )
    _record(
        checks,
        blockers,
        "evidence-paths",
        not invalid_evidence,
        "invalid-live-host-evidence-paths",
        f"host evidence paths must be repository-relative under {evidence_root}",
        {"invalidEvidencePaths": invalid_evidence, "evidenceRoot": evidence_root},
    )


def _validate_host_availability(
    plan: dict[str, Any],
    host_order: list[str],
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    snapshot = plan.get("hostAvailabilitySnapshot")
    keys = set(snapshot) if isinstance(snapshot, dict) else set()
    _record(
        checks,
        blockers,
        "host-availability-snapshot",
        set(host_order) <= keys,
        "invalid-live-host-availability-snapshot",
        "hostAvailabilitySnapshot must include every host in hostOrder",
        {"missing": sorted(set(host_order) - keys)},
    )


def _validate_shared_inputs(plan: dict[str, Any], blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    shared_inputs = plan.get("sharedInputs")
    missing = sorted(REQUIRED_SHARED_INPUTS - set(shared_inputs if isinstance(shared_inputs, dict) else {}))
    _record(
        checks,
        blockers,
        "shared-inputs",
        isinstance(shared_inputs, dict) and not missing,
        "missing-live-host-shared-inputs",
        "live host promotion plan must declare all shared inputs",
        {"missing": missing},
    )


def _validate_artifact_root_policy(plan: dict[str, Any], blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    policy = plan.get("artifactRootPolicy")
    ok = (
        isinstance(policy, dict)
        and policy.get("kind") == "parent-release-live-evidence-carveout"
        and policy.get("requiresParentRefreezeBeforeMove") is True
    )
    _record(
        checks,
        blockers,
        "artifact-root-policy",
        ok,
        "invalid-live-host-artifact-root-policy",
        "artifactRootPolicy must preserve the parent release live-evidence carve-out",
    )


def _validate_budget_policy(
    plan: dict[str, Any],
    profile: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    policy = plan.get("budgetPolicy")
    if not isinstance(policy, dict) or profile is None:
        _record(checks, blockers, "budget-policy", False, "invalid-live-host-budget-policy", "budgetPolicy and calibration profile are required")
        return
    scenarios = _string_list(profile.get("requiredScenarios"))
    cohorts = _string_list(profile.get("requiredCohorts"))
    minimum = int(profile.get("minimumRunsPerScenarioCohort", 0) or 0)
    recommended = int(profile.get("recommendedRunsPerScenarioCohort", 0) or 0)
    expected_minimum = len(scenarios) * len(cohorts) * minimum
    expected_recommended = len(scenarios) * len(cohorts) * recommended
    ok = (
        policy.get("requiresHumanApprovedCapBeforeLiveCalls") is True
        and policy.get("onCapExceeded") == "BLOCKED_BUDGET_EXHAUSTED"
        and policy.get("requiresPerInvocationAccountingReconciliation") is True
        and set(_string_list(policy.get("supportedModes"))) == {"metered", "subscription", "local"}
        and policy.get("meteredModeRequiresUsdCap") is True
        and policy.get("nonMeteredModesRequireResourceCaps") is True
        and set(_string_list(policy.get("resourceCapFields"))) == {"maxInvocations", "maxBillableTokens", "maxWallSeconds"}
        and _string_list(policy.get("costAccountingRequiredModes")) == ["metered"]
        and policy.get("minimumRunsPerHost") == expected_minimum
        and policy.get("recommendedRunsPerHost") == expected_recommended
    )
    _record(
        checks,
        blockers,
        "budget-policy",
        ok,
        "invalid-live-host-budget-policy",
        "budgetPolicy must support metered/subscription/local modes, reconcile per invocation, and fail closed on cap exhaustion",
        {"expectedMinimumRunsPerHost": expected_minimum, "expectedRecommendedRunsPerHost": expected_recommended},
    )


def _validate_operation_requirements(
    plan: dict[str, Any],
    baseline: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    requirements = plan.get("operationEvidenceRequirements")
    required_operations = set(_string_list(baseline.get("requiredOperations") if baseline else None))
    actual_operations = set(requirements) if isinstance(requirements, dict) else set()
    _record(
        checks,
        blockers,
        "operation-evidence-requirements",
        bool(required_operations) and actual_operations == required_operations,
        "invalid-operation-evidence-requirements",
        "operationEvidenceRequirements must cover exactly the adapter baseline requiredOperations",
        {"missing": sorted(required_operations - actual_operations), "extra": sorted(actual_operations - required_operations)},
    )


def _validate_blocker_codes(plan: dict[str, Any], blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    codes = _string_list(plan.get("blockerCodes"))
    ok = bool(codes) and len(codes) == len(set(codes)) and REQUIRED_BLOCKER_CODES <= set(codes) and all(code.startswith("BLOCKED_") for code in codes)
    _record(
        checks,
        blockers,
        "blocker-codes",
        ok,
        "invalid-live-host-blocker-codes",
        "blockerCodes must include the canonical BLOCKED_* live host blockers",
        {"missing": sorted(REQUIRED_BLOCKER_CODES - set(codes))},
    )


def _validate_acceptance(plan: dict[str, Any], blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    criteria = _object_list(plan.get("acceptanceCriteria"))
    ids = [item.get("id") for item in criteria if isinstance(item.get("id"), str)]
    ok = len(ids) == len(set(ids)) and REQUIRED_ACCEPTANCE_IDS <= set(ids)
    _record(
        checks,
        blockers,
        "acceptance-criteria",
        ok,
        "invalid-live-host-acceptance",
        "acceptanceCriteria must include the falsifiable LHP-AC-01..08 set",
        {"missing": sorted(REQUIRED_ACCEPTANCE_IDS - set(ids))},
    )


def _validate_validation_command(
    plan: dict[str, Any],
    plan_path: Path,
    evidence_root: str,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    commands = _object_list(plan.get("validationCommands"))
    command = next((item for item in commands if item.get("id") == "LHP-VAL-PLAN-CHECK"), None)
    artifacts = _object_list(plan.get("evidenceArtifacts"))
    artifact = next((item for item in artifacts if item.get("id") == "LHP-EV-PLAN-CHECK"), None)
    argv = command.get("argv") if isinstance(command, dict) else None
    plan_arg: str | None = None
    evidence_arg: str | None = None
    if isinstance(argv, str):
        parts = shlex.split(argv)
        plan_arg = _argument_value(parts, "--plan")
        evidence_arg = _argument_value(parts, "--evidence")
    artifact_path = artifact.get("path") if isinstance(artifact, dict) else None
    logical_plan_path = _repo_logical_path(plan_path)
    ok = (
        isinstance(argv, str)
        and "tools/release/validate_live_host_promotion_plan.py" in argv
        and isinstance(plan_arg, str)
        and _repo_path_ok(plan_arg)
        and plan_arg.endswith("/host-promotion.plan.json")
        and (logical_plan_path is None or plan_arg == logical_plan_path)
        and isinstance(evidence_arg, str)
        and _repo_path_ok(evidence_arg)
        and isinstance(artifact, dict)
        and artifact.get("schemaVersion") == EVIDENCE_SCHEMA
        and isinstance(artifact_path, str)
        and artifact_path == evidence_arg
        and artifact_path.startswith(evidence_root)
    )
    _record(
        checks,
        blockers,
        "plan-validation-command",
        ok,
        "missing-live-host-plan-validation-command",
        "host promotion package must declare its own mechanical validation command and evidence artifact",
        {"planArg": plan_arg, "evidenceArg": evidence_arg, "artifactPath": artifact_path, "evidenceRoot": evidence_root},
    )


def _validate_no_local_absolute_paths(plan: dict[str, Any], blockers: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    offenders: list[str] = []
    for value in _walk_strings(plan):
        if any(marker in value for marker in LOCAL_ABSOLUTE_MARKERS):
            offenders.append(value)
    _record(
        checks,
        blockers,
        "no-local-absolute-paths",
        not offenders,
        "local-absolute-path-in-live-host-plan",
        "live host promotion plan must not contain machine-local absolute paths",
        {"offenders": offenders[:10]},
    )


def _load_shared_json(plan: dict[str, Any], key: str, blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    shared_inputs = plan.get("sharedInputs")
    value = shared_inputs.get(key) if isinstance(shared_inputs, dict) else None
    if not isinstance(value, str) or not _repo_path_ok(value):
        blockers.append({"code": "invalid-live-host-shared-input", "message": f"{key} must be a repository-relative path"})
        return None
    path = Path(value)
    if not path.is_file():
        blockers.append({"code": "missing-live-host-shared-input", "message": f"{key} does not exist: {value}"})
        return None
    return load_json(path)


def _evidence_root_for_plan(plan: dict[str, Any], plan_path: Path) -> str:
    explicit = plan.get("evidenceRoot")
    if isinstance(explicit, str) and _repo_path_ok(explicit):
        return explicit.rstrip("/") + "/"
    logical_plan_path = _repo_logical_path(plan_path)
    release_root = _release_root_from_repo_path(logical_plan_path)
    if release_root:
        return f"{release_root}/evidence/"
    shared_inputs = plan.get("sharedInputs")
    if isinstance(shared_inputs, dict):
        manifest_root = _release_root_from_repo_path(shared_inputs.get("planManifest"))
        if manifest_root:
            return f"{manifest_root}/evidence/"
    return "work/release-0-3/evidence/"


def _release_root_from_repo_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    for index, part in enumerate(parts[:-1]):
        if part == "tasks" and parts[index + 1].startswith("release-"):
            return f"work/{parts[index + 1]}"
    return None


def _repo_logical_path(path: Path) -> str | None:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return None


def _argument_value(parts: list[str], name: str) -> str | None:
    try:
        index = parts.index(name)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _repo_path_ok(value: str) -> bool:
    try:
        normalize_repo_path(value)
    except LifecycleError:
        return False
    return True


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for dependency in graph.get(node, []):
            if visit(dependency):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _record(
    checks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    name: str,
    ok: bool,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    check = {"name": name, "status": "PASS" if ok else "FAIL"}
    if details:
        check["details"] = details
    checks.append(check)
    if not ok:
        blocker = {"code": code, "message": message}
        if details:
            blocker["details"] = details
        blockers.append(blocker)


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_walk_strings(item))
        return output
    if isinstance(value, dict):
        output = []
        for item in value.values():
            output.extend(_walk_strings(item))
        return output
    return []


if __name__ == "__main__":
    raise SystemExit(main())
