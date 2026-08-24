"""Pure lifecycle-control gates for host actions and workflow completion.

The gate never launches a host process and never mutates workflow state.  It
only binds a proposed action to the frozen plan, lock, state and ownership
rules, then returns a bounded decision that an adapter-owned host may enforce.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.lifecycle_action_catalog import action_types_for_operation
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    CONTROL_LEVELS,
    CONTROL_OPERATIONS,
    build_default_lifecycle_control_policy,
    build_lifecycle_control_decision,
    build_lifecycle_control_request,
    lifecycle_control_limits,
    resolve_lifecycle_control,
    validate_lifecycle_control_event,
    validate_lifecycle_control_policy,
)
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.freeze import verify_plan_lock_envelope

LIFECYCLE_GATE_SCHEMA = "agent-lifecycle-control-gate.v1"
_SELECTED_LEVELS = {"OBSERVED", "ENFORCED"}
_ENFORCED_LEVEL = "ENFORCED"


def evaluate_pre_action_gate(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    operation: str,
    action_digest: str,
    paths: list[str],
    requested_level: str = _ENFORCED_LEVEL,
    policy: dict[str, Any] | None = None,
    next_action: dict[str, Any] | None = None,
    task_id: str | None = None,
    expected_state_revision: int | None = None,
    package_integrity: dict[str, Any] | None = None,
    nonce: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate a host action without starting it or writing state."""

    selected_policy = policy if policy is not None else build_default_lifecycle_control_policy()
    resolved = resolve_lifecycle_control(selected_policy, operation, requested_level=requested_level)
    effective_level = str(resolved.get("effectiveLevel", "GUIDANCE_ONLY"))
    configured_level, _, _ = lifecycle_control_selection(state)
    selection_invalid = requested_level not in CONTROL_LEVELS or configured_level not in CONTROL_LEVELS
    selected = (
        selection_invalid
        or requested_level in _SELECTED_LEVELS
        or effective_level in _SELECTED_LEVELS
        or configured_level in _SELECTED_LEVELS
    )
    enforcement_active = (
        effective_level == _ENFORCED_LEVEL and resolved.get("status") == "PASS"
    ) or configured_level == _ENFORCED_LEVEL
    blockers: list[dict[str, Any]] = []
    if requested_level not in CONTROL_LEVELS:
        blockers.append({"code": "control-requested-level-invalid", "requestedLevel": requested_level})
    blockers.extend(
        lifecycle_control_selection_blockers(
            state,
            manifest=manifest,
            requested_level=requested_level,
        )
    )
    policy_validation = validate_lifecycle_control_policy(selected_policy)
    if policy_validation["status"] != "PASS":
        blockers.extend(policy_validation["blockers"])
    if selected:
        blockers.extend(
            _pre_action_invariants(
                manifest=manifest,
                lock=lock,
                state=state,
                operation=operation,
                action_digest=action_digest,
                paths=paths,
                next_action=next_action,
                task_id=task_id,
                expected_state_revision=expected_state_revision,
                package_integrity=package_integrity,
            )
        )
    if requested_level in _SELECTED_LEVELS and effective_level not in _SELECTED_LEVELS:
        blockers.append(
            {
                "code": "control-level-unavailable",
                "requestedLevel": requested_level,
                "effectiveLevel": effective_level,
            }
        )
    request = _build_request(
        state=state,
        operation=operation,
        action_digest=action_digest,
        paths=paths,
        requested_level=requested_level,
        lock=lock,
        manifest=manifest,
        task_id=task_id,
        nonce=nonce,
        created_at=created_at,
    )
    if resolved.get("status") != "PASS" and selected:
        blockers.extend(resolved.get("blockers", []))
    status = "PASS"
    pre_action_blocking = bool(
        blockers and (enforcement_active or requested_level == _ENFORCED_LEVEL or selection_invalid)
    )
    if pre_action_blocking:
        status = "BLOCKED"
    elif (blockers and selected) or (resolved.get("status") != "PASS" and selected):
        status = "REVIEW_REQUIRED"
    decision = build_lifecycle_control_decision(
        request,
        status=status,
        effective_level=effective_level if effective_level in CONTROL_LEVELS else "GUIDANCE_ONLY",
        host_action_allowed=bool(enforcement_active and not blockers),
        blockers=blockers,
    )
    body = {
        "schemaVersion": LIFECYCLE_GATE_SCHEMA,
        "gateType": "pre-action",
        "status": status,
        "blocking": pre_action_blocking,
        "selected": selected,
        "enforcementActive": enforcement_active,
        "operation": operation,
        "request": request,
        "decision": decision,
        "ownership": _ownership_summary(manifest, paths),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "gateDigest": canonical_digest(body)}


def evaluate_post_action_gate(
    *,
    pre_action: dict[str, Any],
    manifest: dict[str, Any],
    actual_changed_paths: list[str],
    outcome: dict[str, Any] | None = None,
    actual_status: str = "PASS",
    event: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind observed command results to the previously authorized action."""

    blockers: list[dict[str, Any]] = []
    request = pre_action.get("request") if isinstance(pre_action, dict) else None
    if not isinstance(request, dict):
        blockers.append({"code": "pre-action-request-missing"})
        request = {}
    elif pre_action.get("status") != "PASS":
        blockers.append({"code": "pre-action-not-passed"})
    elif not _gate_digest_valid(pre_action):
        blockers.append({"code": "pre-action-evidence-invalid"})
    expected_paths = _normalize_paths(request.get("paths"), blockers, "expected-action-paths")
    actual_paths = _normalize_paths(actual_changed_paths, blockers, "actual-changed-paths")
    if set(expected_paths) != set(actual_paths):
        blockers.append(
            {
                "code": "post-action-path-drift",
                "expected": expected_paths,
                "actual": actual_paths,
            }
        )
    if actual_status != "PASS":
        blockers.append({"code": "post-action-outcome-failed", "status": actual_status})
    if policy is not None:
        policy_validation = validate_lifecycle_control_policy(policy)
        if policy_validation["status"] != "PASS":
            blockers.extend(policy_validation["blockers"])
    if isinstance(event, dict):
        validation = validate_lifecycle_control_event(event, policy_limits=_policy_limits(policy))
        if validation["status"] != "PASS":
            blockers.append({"code": "post-action-event-invalid", "details": validation["blockers"]})
        else:
            _bind_event(event, request, blockers, expected_type="post-action")
    elif bool(pre_action.get("enforcementActive")) or bool(pre_action.get("selected")):
        blockers.append({"code": "post-action-event-missing"})
    ownership = _ownership_summary(manifest, actual_paths)
    blockers.extend(_ownership_blockers(ownership))
    selected = bool(pre_action.get("selected"))
    enforcement_active = bool(pre_action.get("enforcementActive"))
    status = "PASS" if not blockers else ("BLOCKED" if enforcement_active or selected else "REVIEW_REQUIRED")
    body = {
        "schemaVersion": LIFECYCLE_GATE_SCHEMA,
        "gateType": "post-action",
        "status": status,
        "blocking": bool(blockers and (enforcement_active or selected)),
        "selected": selected,
        "enforcementActive": enforcement_active,
        "operation": request.get("operation"),
        "requestDigest": request.get("requestDigest"),
        "actionDigest": request.get("actionDigest"),
        "actualChangedPaths": actual_paths,
        "outcome": _outcome_summary(outcome),
        "event": event,
        "ownership": ownership,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "gateDigest": canonical_digest(body)}


def evaluate_stop_gate(
    *,
    state: dict[str, Any],
    final_audit: dict[str, Any] | None = None,
    final_proof: dict[str, Any] | None = None,
    pre_action: dict[str, Any] | None = None,
    post_action: dict[str, Any] | None = None,
    requested_level: str = _ENFORCED_LEVEL,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require accepted workflow evidence before an enforced stop succeeds."""

    selected_policy = policy if policy is not None else build_default_lifecycle_control_policy()
    resolved = resolve_lifecycle_control(selected_policy, "run-finalize", requested_level=requested_level)
    effective_level = str(resolved.get("effectiveLevel", "GUIDANCE_ONLY"))
    configured_level, _, _ = lifecycle_control_selection(state)
    selection_invalid = requested_level not in CONTROL_LEVELS or configured_level not in CONTROL_LEVELS
    selected = (
        selection_invalid
        or requested_level in _SELECTED_LEVELS
        or effective_level in _SELECTED_LEVELS
        or configured_level in _SELECTED_LEVELS
    )
    enforcement_active = (
        effective_level == _ENFORCED_LEVEL and resolved.get("status") == "PASS"
    ) or configured_level == _ENFORCED_LEVEL
    blockers: list[dict[str, Any]] = []
    if requested_level not in CONTROL_LEVELS:
        blockers.append({"code": "control-requested-level-invalid", "requestedLevel": requested_level})
    blockers.extend(lifecycle_control_selection_blockers(state, requested_level=requested_level))
    policy_validation = validate_lifecycle_control_policy(selected_policy)
    if policy_validation["status"] != "PASS" and (selected or requested_level != "OFF"):
        blockers.extend(policy_validation["blockers"])
    if selected:
        if resolved.get("status") != "PASS":
            blockers.extend(resolved.get("blockers", []))
        blockers.extend(_stop_invariants(state, final_audit=final_audit, final_proof=final_proof))
        if not isinstance(pre_action, dict):
            blockers.append({"code": "pre-action-evidence-missing"})
        elif pre_action.get("status") != "PASS" or not _gate_digest_valid(pre_action):
            blockers.append({"code": "pre-action-evidence-invalid"})
        if not isinstance(post_action, dict):
            blockers.append({"code": "post-action-evidence-missing"})
        elif not _gate_digest_valid(post_action) or post_action.get("status") != "PASS":
            blockers.append({"code": "post-action-evidence-invalid"})
    status = "PASS"
    if blockers and enforcement_active:
        status = "BLOCKED"
    elif blockers and selected:
        status = "REVIEW_REQUIRED"
    body = {
        "schemaVersion": LIFECYCLE_GATE_SCHEMA,
        "gateType": "stop",
        "status": status,
        "blocking": bool(blockers and selected),
        "selected": selected,
        "enforcementActive": enforcement_active,
        "operation": "run-finalize",
        "effectiveLevel": effective_level,
        "preActionDigest": pre_action.get("gateDigest") if isinstance(pre_action, dict) else None,
        "postActionDigest": post_action.get("gateDigest") if isinstance(post_action, dict) else None,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "gateDigest": canonical_digest(body)}


def require_lifecycle_gate_pass(gate: dict[str, Any], *, gate_type: str) -> dict[str, Any]:
    """Raise a stable error when a selected control gate blocks progress."""

    if not isinstance(gate, dict) or gate.get("schemaVersion") != LIFECYCLE_GATE_SCHEMA:
        raise LifecycleError("lifecycle-gate-invalid", f"{gate_type} lifecycle gate is invalid")
    if gate.get("blocking") is True and gate.get("status") != "PASS":
        raise LifecycleError(
            "lifecycle-gate-blocked",
            f"{gate_type} lifecycle gate blocked the operation",
            {"gateType": gate_type, "blockers": gate.get("blockers", [])},
        )
    return gate


def lifecycle_control_selection(state: dict[str, Any]) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """Read explicit workflow control selection; absent selection means off."""

    config = state.get("lifecycleControl")
    if not isinstance(config, dict):
        return "OFF", None, {}
    level = config.get("level", config.get("requestedLevel", "OFF"))
    if not isinstance(level, str):
        level = "__INVALID__"
    raw_policy = config.get("policy")
    policy: dict[str, Any] | None = (
        {str(key): value for key, value in raw_policy.items()} if isinstance(raw_policy, dict) else None
    )
    raw_evidence = config.get("evidence")
    evidence: dict[str, Any] = (
        {str(key): value for key, value in raw_evidence.items()} if isinstance(raw_evidence, dict) else {}
    )
    return level, policy, evidence


def lifecycle_control_selection_blockers(
    state: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
    requested_level: str | None = None,
) -> list[dict[str, Any]]:
    """Require a selected control level to be bound to the frozen plan."""

    config = state.get("lifecycleControl")
    configured_level = "OFF"
    if isinstance(config, dict):
        raw_level = config.get("level", config.get("requestedLevel", "OFF"))
        configured_level = raw_level if isinstance(raw_level, str) else "__INVALID__"
    selected_level = requested_level if requested_level is not None else configured_level
    blockers: list[dict[str, Any]] = []
    if configured_level not in CONTROL_LEVELS:
        blockers.append({"code": "control-selection-level-invalid", "level": configured_level})
    if selected_level not in CONTROL_LEVELS:
        return blockers
    if configured_level != "OFF" and selected_level != configured_level:
        blockers.append(
            {
                "code": "control-selection-bypass",
                "configuredLevel": configured_level,
                "requestedLevel": selected_level,
            }
        )
    if selected_level == "OFF":
        return blockers
    if not isinstance(config, dict):
        blockers.append({"code": "control-selection-missing"})
        return blockers
    if config.get("source") != "frozen-plan":
        blockers.append({"code": "control-selection-source-unbound"})
    expected_plan_digest = canonical_digest(manifest) if isinstance(manifest, dict) else state.get("planDigest")
    if config.get("planDigest") != expected_plan_digest:
        blockers.append({"code": "control-selection-plan-mismatch"})
    if config.get("planRevision") != state.get("planRevision"):
        blockers.append({"code": "control-selection-revision-mismatch"})
    return blockers


def _pre_action_invariants(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    operation: str,
    action_digest: str,
    paths: list[str],
    next_action: dict[str, Any] | None,
    task_id: str | None,
    expected_state_revision: int | None,
    package_integrity: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(manifest, dict) or manifest.get("status") != "FROZEN":
        blockers.append({"code": "plan-not-frozen"})
    if operation not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-operation-unsupported", "operation": operation})
    try:
        lock_verification = verify_plan_lock_envelope(manifest, lock)
        if package_integrity is not None and package_integrity.get("status") != "PASS":
            blockers.append({"code": "plan-package-integrity-failed"})
        if isinstance(state.get("lockDigest"), str) and state["lockDigest"] != canonical_digest(lock):
            blockers.append({"code": "lock-digest-mismatch"})
        if lock_verification.get("planRevision") != manifest.get("planRevision"):
            blockers.append({"code": "plan-lock-revision-mismatch"})
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message, "details": exc.details})
    manifest_digest = canonical_digest(manifest) if isinstance(manifest, dict) else None
    if state.get("planDigest") != manifest_digest:
        blockers.append({"code": "plan-digest-mismatch"})
    if state.get("planRevision") != manifest.get("planRevision"):
        blockers.append({"code": "plan-revision-mismatch"})
    state_revision = state.get("stateRevision")
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        blockers.append({"code": "state-revision-invalid"})
    if expected_state_revision is not None and state_revision != expected_state_revision:
        blockers.append({"code": "state-revision-mismatch"})
    if not isinstance(action_digest, str) or len(action_digest) != 64:
        blockers.append({"code": "action-digest-invalid"})
    if next_action is None:
        blockers.append({"code": "next-action-missing"})
    else:
        raw_projected = next_action.get("projectedAction")
        projected: dict[str, Any] = raw_projected if isinstance(raw_projected, dict) else next_action
        expected_types = action_types_for_operation(operation)
        if projected.get("type") not in expected_types:
            blockers.append({"code": "next-action-mismatch", "operation": operation, "actual": projected.get("type")})
        if (
            task_id is not None
            and isinstance(projected.get("taskIds"), list)
            and projected.get("taskIds")
            and task_id not in projected["taskIds"]
        ):
            blockers.append({"code": "next-task-mismatch", "taskId": task_id})
    normalized_paths = _normalize_paths(paths, blockers, "action-paths")
    if operation in {"file-edit", "shell-command"} and not normalized_paths:
        blockers.append({"code": "action-paths-missing"})
    ownership = _ownership_summary(manifest, normalized_paths)
    blockers.extend(_ownership_blockers(ownership))
    return blockers


def _stop_invariants(
    state: dict[str, Any],
    *,
    final_audit: dict[str, Any] | None,
    final_proof: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    missing = [
        str(task.get("id"))
        for task in state.get("tasks", [])
        if task.get("required", True) and task.get("status") != "ACCEPTED"
    ]
    if missing:
        blockers.append({"code": "required-tasks-unaccepted", "tasks": missing})
    if not isinstance(final_audit, dict) or final_audit.get("status") != "PASS":
        blockers.append({"code": "final-audit-not-ready"})
    elif final_audit.get("planDigest") != state.get("planDigest"):
        blockers.append({"code": "final-audit-plan-digest-mismatch"})
    if not isinstance(final_proof, dict) or final_proof.get("schemaVersion") != "agent-run-final-proof.v1":
        blockers.append({"code": "final-proof-missing"})
    elif final_proof.get("planDigest") != state.get("planDigest") or final_proof.get("runId") != state.get("runId"):
        blockers.append({"code": "final-proof-lineage-mismatch"})
    return blockers


def _build_request(
    *,
    state: dict[str, Any],
    operation: str,
    action_digest: str,
    paths: list[str],
    requested_level: str,
    lock: dict[str, Any],
    manifest: dict[str, Any],
    task_id: str | None,
    nonce: str | None,
    created_at: str | None,
) -> dict[str, Any]:
    safe_level = requested_level if requested_level in CONTROL_LEVELS else "GUIDANCE_ONLY"
    safe_operation = operation if operation in CONTROL_OPERATIONS else "file-edit"
    safe_paths: list[str] = []
    for raw_path in paths if isinstance(paths, list) else []:
        try:
            safe_paths.append(normalize_authority_path(raw_path, label="action path"))
        except LifecycleError:
            continue
    package = manifest.get("package") if isinstance(manifest, dict) else {}
    package = package if isinstance(package, dict) else {}
    raw_plan_revision = state.get("planRevision", manifest.get("planRevision", 1)) if isinstance(state, dict) else 1
    plan_revision = raw_plan_revision if isinstance(raw_plan_revision, int) and raw_plan_revision > 0 else 1
    raw_state_revision = state.get("stateRevision", 1) if isinstance(state, dict) else 1
    state_revision = raw_state_revision if isinstance(raw_state_revision, int) and raw_state_revision > 0 else 1
    stable_nonce = (
        nonce
        or canonical_digest(
            {
                "runId": state.get("runId"),
                "taskId": task_id or state.get("currentTaskId") or "run",
                "operation": safe_operation,
                "planDigest": canonical_digest(manifest),
                "lockDigest": canonical_digest(lock),
                "stateRevision": state_revision,
                "actionDigest": action_digest,
                "paths": safe_paths,
            }
        )[:32]
    )
    stable_created_at = created_at or state.get("updatedAt") or state.get("runStartedAt")
    if not isinstance(stable_created_at, str) or not stable_created_at:
        stable_created_at = _minute_now_iso()
    return build_lifecycle_control_request(
        request_id=f"{state.get('runId', 'run')}-{safe_operation}",
        adapter_id="provider-neutral",
        host="host-owned",
        host_version="unknown",
        operation=safe_operation,
        run_id=str(state.get("runId", "run")),
        task_id=str(task_id or state.get("currentTaskId") or "run"),
        package_id=str(state.get("packageId", package.get("id", "package"))),
        plan_revision=plan_revision,
        plan_digest=canonical_digest(manifest),
        lock_digest=canonical_digest(lock),
        state_revision=state_revision,
        action_digest=action_digest if isinstance(action_digest, str) and len(action_digest) == 64 else "0" * 64,
        paths=safe_paths,
        requested_level=safe_level,
        producer_id="alk-host-protocol",
        nonce=stable_nonce,
        created_at=stable_created_at,
    )


def _ownership_summary(manifest: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    try:
        raw_package = manifest.get("package")
        package: dict[str, Any] = (
            {str(key): value for key, value in raw_package.items()} if isinstance(raw_package, dict) else {}
        )
        plan_root = _literal_root(package.get("planArtifactRoot"))
        lead_roots = _literal_roots(manifest.get("leadOwned"), objects=True)
        read_only_roots = _literal_roots(manifest.get("readOnly"))
        forbidden_roots = _literal_roots(manifest.get("forbiddenWrites"))
        raw_workstreams = manifest.get("workstreams")
        workstreams: list[Any] = raw_workstreams if isinstance(raw_workstreams, list) else []
        workstream_roots = {
            str(workstream.get("id")): [
                _literal_root(path) for path in workstream.get("writes", []) if isinstance(path, str)
            ]
            for workstream in workstreams
            if isinstance(workstream, dict) and isinstance(workstream.get("id"), str)
        }
        entries = []
        for path in sorted(set(paths)):
            normalized = normalize_authority_path(path, label="ownership path")
            if plan_root and is_under_authority_path(normalized, plan_root):
                entries.append({"path": normalized, "category": "plan-authority", "owners": ["controller"]})
                continue
            matched_lead = [root for root in lead_roots if root and is_under_authority_path(normalized, root)]
            if matched_lead:
                entries.append(
                    {"path": normalized, "category": "lead-owned", "owners": ["controller"], "matched": matched_lead}
                )
                continue
            matched_forbidden = [root for root in forbidden_roots if root and is_under_authority_path(normalized, root)]
            if matched_forbidden:
                entries.append(
                    {"path": normalized, "category": "forbidden", "owners": [], "matched": matched_forbidden}
                )
                continue
            matched_read_only = [root for root in read_only_roots if root and is_under_authority_path(normalized, root)]
            if matched_read_only:
                entries.append(
                    {"path": normalized, "category": "read-only", "owners": [], "matched": matched_read_only}
                )
                continue
            matched_owners = [
                owner
                for owner, roots in workstream_roots.items()
                if any(root and is_under_authority_path(normalized, root) for root in roots)
            ]
            entries.append(
                {
                    "path": normalized,
                    "category": "workstream-owned" if matched_owners else "unowned",
                    "owners": matched_owners,
                }
            )
        counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        for entry in entries:
            category = str(entry["category"])
            counts[category] = counts.get(category, 0) + 1
            for owner in entry.get("owners", []):
                owner_counts[owner] = owner_counts.get(owner, 0) + 1
        return {
            "schemaVersion": "agent-ownership-report.v1",
            "summary": {
                "total": len(entries),
                "byCategory": dict(sorted(counts.items())),
                "byOwner": dict(sorted(owner_counts.items())),
            },
            "entries": entries,
        }
    except LifecycleError as exc:
        return {
            "schemaVersion": "agent-ownership-report.v1",
            "status": "FAIL",
            "blockers": [{"code": exc.code, "message": exc.message}],
            "entries": [],
            "summary": {"total": 0, "byCategory": {}, "byOwner": {}},
        }


def _literal_roots(value: Any, *, objects: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []
    roots: list[str] = []
    for item in value:
        raw = item.get("path") if objects and isinstance(item, dict) else item
        if isinstance(raw, str):
            normalized = _literal_root(raw)
            if normalized is not None:
                roots.append(normalized)
    return roots


def _literal_root(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LifecycleError("invalid-authority-path", "ownership root must be a repository-relative string")
    try:
        return normalize_authority_path(value, label="ownership root")
    except LifecycleError:
        raise


def _ownership_blockers(report: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    if blockers:
        return list(blockers)
    return [
        {"code": "ownership-unsafe-path", "path": entry.get("path"), "category": entry.get("category")}
        for entry in report.get("entries", [])
        if isinstance(entry, dict) and entry.get("category") != "workstream-owned"
    ]


def _normalize_paths(value: Any, blockers: list[dict[str, Any]], code: str) -> list[str]:
    if not isinstance(value, list):
        blockers.append({"code": f"{code}-shape"})
        return []
    paths: list[str] = []
    for raw in value:
        try:
            paths.append(normalize_authority_path(raw, label=code))
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "message": exc.message})
    return sorted(set(paths))


def _bind_event(
    event: dict[str, Any], request: dict[str, Any], blockers: list[dict[str, Any]], *, expected_type: str
) -> None:
    expected = {
        "requestDigest": request.get("requestDigest"),
        "operation": request.get("operation"),
        "nonce": request.get("nonce"),
        "eventType": expected_type,
    }
    for key, value in expected.items():
        if event.get(key) != value:
            blockers.append({"code": "control-event-lineage-mismatch", "field": key})


def _policy_limits(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(policy, dict):
        return None
    try:
        return lifecycle_control_limits(policy)
    except LifecycleError:
        return None


def _gate_digest_valid(gate: dict[str, Any]) -> bool:
    digest = gate.get("gateDigest")
    if not isinstance(digest, str):
        return False
    body = {key: value for key, value in gate.items() if key != "gateDigest"}
    return digest == canonical_digest(body)


def _minute_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _outcome_summary(outcome: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(outcome, dict):
        return {}
    return {"status": outcome.get("status"), "exitCode": outcome.get("exitCode"), "changed": outcome.get("changed")}


__all__ = [
    "LIFECYCLE_GATE_SCHEMA",
    "evaluate_post_action_gate",
    "evaluate_pre_action_gate",
    "evaluate_stop_gate",
    "lifecycle_control_selection",
    "lifecycle_control_selection_blockers",
    "require_lifecycle_gate_pass",
]
