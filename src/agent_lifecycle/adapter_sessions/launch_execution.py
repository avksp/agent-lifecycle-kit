"""Descriptor-driven managed adapter launcher implementation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.contracts import digest
from agent_lifecycle.accounting.host_bridge import (
    CAPABILITY_UNAVAILABLE,
    TASK_BYTES,
    accounting_request_blocker,
    read_source_lifecycle_qualification,
    read_source_lifecycle_qualifications,
)
from agent_lifecycle.accounting.support_profiles import match_requested_claims
from agent_lifecycle.adapter_sessions.contracts import (
    build_launch_receipt,
    build_local_launch_profile_receipt,
)
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.immutable_input import (
    planning_invocation_context,
    require_no_strong_protection,
    validate_current_invocation,
)
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    build_executable_identity,
    load_local_launch_profile,
    local_profile_summary,
    render_planning_launch_argv,
)
from agent_lifecycle.adapter_sessions.ordinary_audit import verify_area_report
from agent_lifecycle.adapter_sessions.planning_launch import run_planning_launch
from agent_lifecycle.adapter_sessions.qualification import (
    shipped_profile_digest,
)
from agent_lifecycle.adapter_sessions.worktree_identity import capture_git_worktree_identity
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.host_protocol.validation import validate_managed_launch_profile


def _read_reviewed_final_profile_snapshot(
    *, project_root: Path, profiles_root: Path, adapter_ids: list[str], byte_limit: int,
) -> dict:
    """Read one bounded snapshot and its actual origins; not a final verdict.

    Callers must still compare a fresh, fully re-enumerated snapshot before
    using these contents. Keeping this stage private prevents a supplied PASS
    from replacing the final consumer's own validation.
    """
    first = read_source_lifecycle_qualifications(project_root, profiles_root, adapter_ids, final=True, byte_limit=byte_limit)
    reports = {}
    prefix = profiles_root.absolute().relative_to(project_root.absolute()).as_posix()
    for adapter, item in first["profiles"].items():
        for report, ref, subject, obligations, traces in (
            (item["review"], item["reviewRef"], item["subjectRef"], ["accounting.profile." + adapter], []),
            (item["resolverReceipt"], item["resolver"]["receiptRef"], item["resolverSubjectRef"],
             ["accounting.profile." + adapter, "accounting.profile.requested-guarantee-denial"],
             [row["rawTraceRef"] for row in item["resolver"]["observations"]]),
        ):
            review_id = report["reviewId"]
            if review_id not in reports:
                reports[review_id] = verify_area_report(project_root, review_id=review_id)
            verified = reports[review_id]
            if (verified["assurance"] != "PROCEDURAL_SAME_ACCOUNT" or verified["nativeAllowed"] is not False
                    or verified["report"] != report or verified["reportSha256"] != ref["sha256"]
                    or report["planDigest"] != item["joins"]["planDigest"]
                    or report["lockSha256"] != item["authorityRefs"]["plan.lock.json"]["sha256"]
                    or verified["assignment"]["scopeId"] != "HOST_AND_TRANSPORT"
                    or any(obligation not in report["coveredObligations"] for obligation in obligations)
                    or subject not in report["coveredFiles"]
                    or any({**trace, "path": prefix + "/" + trace["path"]} not in report["coveredFiles"] for trace in traces)):
                raise LifecycleError(CAPABILITY_UNAVAILABLE, "Final accounting evidence origin differs")
    return first


def _require_matching_final_profile_snapshots(first: dict, second: dict) -> None:
    if (second["snapshotRefs"] != first["snapshotRefs"]
            or set(second["profiles"]) != set(first["profiles"])
            or any(second["profiles"][adapter]["contentDigest"] != item["contentDigest"]
                   for adapter, item in first["profiles"].items())):
        raise LifecycleError(CAPABILITY_UNAVAILABLE, "Final accounting evidence changed during verification")


def verify_final_source_accounting_profiles(
    *, project_root: Path, profiles_root: Path, adapter_ids: list[str], byte_limit: int = TASK_BYTES,
) -> dict:
    """Verify contents and actual AREA origins with two shared snapshots.

    The offline validator also checks every exact resolver mutation and retained
    core witness. This supplies data, not a dispatch or release permit.
    """
    if type(byte_limit) is not int or not 0 < byte_limit <= TASK_BYTES:
        raise LifecycleError(CAPABILITY_UNAVAILABLE, "Final accounting read budget is invalid")
    first = _read_reviewed_final_profile_snapshot(
        project_root=project_root, profiles_root=profiles_root, adapter_ids=adapter_ids, byte_limit=byte_limit,
    )
    second = read_source_lifecycle_qualifications(
        project_root, profiles_root, adapter_ids, final=True, byte_limit=byte_limit - first["readBytes"],
    )
    _require_matching_final_profile_snapshots(first, second)
    return {**first, "readBytes": first["readBytes"] + second["readBytes"],
            "assurance": "PROCEDURAL_SAME_ACCOUNT", "dispatchEntitlement": False}


def resolve_qualified_accounting_capability(
    *, project_root: Path, profiles_root: Path, adapter_id: str, request: dict,
) -> dict:
    """Check staged source-only qualification, without accepting a final profile.

    An observed ordinary AREA review must cover the exact content projection.
    Neither a supplied PASS nor this capability result authorizes host dispatch.
    Positive native/financial qualification and final resolver evidence remain
    separate obligations; this route supports only LIFECYCLE_ONLY with no claims.
    """
    marker = digest({"invalidInput": True})
    result = {"schemaVersion": "alk-accounting-capability-result.v1",
              "requestDigest": marker, "profileDigest": marker, "expectationDigest": marker,
              "outcome": "DENY", "reason": CAPABILITY_UNAVAILABLE,
              "detail": "UNQUALIFIED_EVIDENCE", "matchedClaimIds": [], "dispatchEntitlement": False}
    try:
        result["requestDigest"] = digest(request)
        first = read_source_lifecycle_qualification(project_root, profiles_root, adapter_id)
        joins = first["joins"]
        result.update(profileDigest=joins["profileDigest"], expectationDigest=joins["expectationDigest"])
        matched = match_requested_claims(first["payload"], request,
                                         expectation_digest=joins["expectationDigest"],
                                         plan_digest=joins["planDigest"], candidate_digest=joins["alkCandidateDigest"])
        if matched["status"] != "MATCH_PENDING_EVIDENCE":
            result["detail"] = matched["detail"]
            return result
        verified = verify_area_report(project_root, review_id=first["review"]["reviewId"])
        report = verified["report"]
        if (verified["assurance"] != "PROCEDURAL_SAME_ACCOUNT" or verified["nativeAllowed"] is not False
                or report != first["review"] or verified["reportSha256"] != first["reviewRef"]["sha256"]
                or report["planDigest"] != joins["planDigest"]
                or report["lockSha256"] != first["authorityRefs"]["plan.lock.json"]["sha256"]
                or verified["assignment"]["scopeId"] != "HOST_AND_TRANSPORT"
                or "accounting.profile." + adapter_id not in report["coveredObligations"]
                or first["subjectRef"] not in report["coveredFiles"]):
            raise ValueError("Qualification review origin or exact subject differs")
        # Reopen after provenance checks; a changed source, expectation, profile
        # or evidence graph invalidates the same decision rather than a new read.
        second = read_source_lifecycle_qualification(
            project_root, profiles_root, adapter_id, byte_limit=TASK_BYTES - first["readBytes"],
        )
        if (second["contentDigest"] != first["contentDigest"]
                or second["subjectRef"] not in report["coveredFiles"]):
            raise ValueError("Qualification changed during review verification")
        result.update(outcome="ALLOW_CAPABILITY", reason="CAPABILITY_MATCH", detail="MATCH")
    except (LifecycleError, OSError, ValueError, TypeError, KeyError, RecursionError):
        # Missing publication/observed raw origin, unresolved evidence, drift or
        # unsupported safe I/O always leaves the staged qualification unavailable.
        pass
    return result


def load_adapter_descriptor(adapter_id: str, descriptor_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = descriptor_path or Path("adapters") / adapter_id / "adapter.descriptor.json"
    descriptor = read_json_object(path, label="adapter descriptor")
    if descriptor.get("adapterId") != adapter_id:
        raise LifecycleError("adapter-descriptor-id-mismatch", "descriptor adapterId does not match requested adapter")
    return path, descriptor


def managed_launch_profile(descriptor: dict[str, Any]) -> dict[str, Any]:
    profile = descriptor.get("managedLaunch")
    if not isinstance(profile, dict):
        raise LifecycleError("adapter-managed-launch-missing", "adapter descriptor must declare managedLaunch")
    return profile


def launch_from_descriptor(
    *,
    descriptor: dict[str, Any],
    session_id: str,
    launch_mode: str,
    task_id: str | None = None,
    state_path: Path | None = None,
    policy_path: Path | None = None,
    process_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Block generic descriptor-driven launch until the qualified local route exists."""

    del task_id, state_path, policy_path, process_env
    raw_profile = descriptor.get("managedLaunch")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    validation = validate_managed_launch_profile(profile)
    raw_adapter_id = descriptor.get("adapterId")
    adapter_id = raw_adapter_id if isinstance(raw_adapter_id, str) else "unknown"
    timeout_seconds = _timeout_seconds(profile)
    blockers: list[dict[str, Any]] = []
    if validation["status"] != "PASS":
        blockers.append(
            {
                "code": "adapter-generic-launch-invalid-descriptor",
                "validationBlockers": validation["blockers"],
            }
        )
    blockers.append(
        {
            "code": "adapter-generic-launch-disabled",
            "profileStatus": profile.get("status"),
            "reason": "generic descriptor-driven launch is disabled until a qualified local-profile route exists",
        }
    )
    return build_launch_receipt(
        status="BLOCKED",
        adapter_id=adapter_id,
        session_id=session_id,
        launch_mode=launch_mode,
        argv=[],
        timeout_seconds=timeout_seconds,
        env={"includedNames": [], "valuesRedacted": True, "secretValuesStored": False},
        exit_code=None,
        timed_out=False,
        blockers=blockers,
    )


def inspect_local_launch_profile(
    profile_path: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Inspect a local profile without reaching the process boundary."""

    root = (project_root or Path.cwd()).absolute()
    relative, profile, validation = load_local_launch_profile(profile_path, project_root=root)
    identity = build_executable_identity(
        profile,
        profile_digest=str(validation["profileDigest"]),
        shipped_profile_digest=shipped_profile_digest(str(profile["adapterId"]), repository_root=root),
        strict=False,
    )
    return build_local_launch_profile_receipt(
        status="PASS",
        operation="INSPECT",
        profile_path=relative.as_posix(),
        profile_summary=local_profile_summary(profile),
        profile_digest=validation["profileDigest"],
        process_calls=0,
        host_identity=identity,
    )


def run_planning_qualification_candidate(
    *,
    profile_path: Path,
    project_root: Path,
    approval_digest: str,
    max_wall_seconds: float,
    model_token_budget: int,
    process_env: dict[str, str] | None = None,
    capture_identity: Callable[[Path], dict[str, Any]] | None = None,
    planning_runner: Callable[..., dict[str, Any]] | None = None,
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one explicitly approved live candidate without promoting the profile."""

    root = project_root.resolve()
    _relative, profile, validation = load_local_launch_profile(profile_path, project_root=root)
    planning = profile.get("planningOnly")
    if not isinstance(planning, dict) or planning.get("status") != "CANDIDATE":
        return _planning_qualification_report(
            profile=profile,
            profile_digest=str(validation["profileDigest"]),
            approval_digest=approval_digest,
            receipt=None,
            before=None,
            after=None,
            blockers=[{"code": "planning-qualification-candidate-unavailable"}],
            usage_evidence=None,
            approved_model_token_budget=model_token_budget,
            approved_wall_seconds=max_wall_seconds,
        )
    if (
        not isinstance(max_wall_seconds, (int, float))
        or isinstance(max_wall_seconds, bool)
        or max_wall_seconds <= 0
        or not isinstance(model_token_budget, int)
        or isinstance(model_token_budget, bool)
        or model_token_budget <= 0
    ):
        return _planning_qualification_report(
            profile=profile,
            profile_digest=str(validation["profileDigest"]),
            approval_digest=approval_digest,
            receipt=None,
            before=None,
            after=None,
            blockers=[{"code": "planning-qualification-budget-invalid"}],
            usage_evidence=None,
            approved_model_token_budget=model_token_budget,
            approved_wall_seconds=max_wall_seconds,
        )
    fixture = (
        "Inspect this disposable repository and return a minimal review-required plan. "
        "Do not modify files or authorize implementation."
    )
    binding = {"profileDigest": validation["profileDigest"], "approvalDigest": approval_digest,
               "modelTokenBudget": model_token_budget, "maxWallSeconds": max_wall_seconds}
    try:
        request = require_no_strong_protection(immutable_input_request, expected_protection="NONE")
        env, _env_receipt = resolve_launch_env(profile, process_env=process_env)
        argv = render_planning_launch_argv(profile)
        current = planning_invocation_context(
            adapter_id=str(profile["adapterId"]), session_id=f"{profile['adapterId']}-planning-qualification",
            request=request, requested_mode="plan", task_text=fixture, input_source="qualification-fixture",
            argv=argv, env=env, advisory=None,
            timeout_seconds=min(float(profile["timeoutSeconds"]), float(max_wall_seconds), 300),
            process_cwd=root, profile_digest=str(validation["profileDigest"]), qualification_binding=binding,
        )
        validate_current_invocation(immutable_input_context if immutable_input_context is not None else current,
                                    request, current_context=current)
    except LifecycleError as exc:
        return _planning_qualification_report(
            profile=profile, profile_digest=str(validation["profileDigest"]), approval_digest=approval_digest,
            receipt=None, before=None, after=None, blockers=[{"code": exc.code, "message": exc.message}],
            usage_evidence=None, approved_model_token_budget=model_token_budget,
            approved_wall_seconds=max_wall_seconds,
        )
    identity_runner = capture_identity or capture_git_worktree_identity
    launch_runner = planning_runner or run_planning_launch
    before = identity_runner(root)
    receipt = launch_runner(
        adapter_id=str(profile["adapterId"]),
        session_id=f"{profile['adapterId']}-planning-qualification",
        requested_mode="plan",
        task_text=fixture,
        input_source="qualification-fixture",
        argv=argv,
        env=env,
        timeout_seconds=min(float(profile["timeoutSeconds"]), float(max_wall_seconds)),
        process_cwd=root,
        immutable_input_request=request,
        immutable_input_context=current,
        profile_digest=str(validation["profileDigest"]),
        qualification_binding=binding,
    )
    after = identity_runner(root)
    blockers = list(receipt.get("blockers", []))
    raw_usage = receipt.get("usageEvidence")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = usage.get("inputTokens")
    output_tokens = usage.get("outputTokens")
    if usage.get("confidence") != "ATTESTED" or not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        blockers.append({"code": "planning-qualification-usage-unattested"})
    elif input_tokens + output_tokens > model_token_budget:
        blockers.append(
            {
                "code": "planning-qualification-token-budget-exceeded",
                "approvedModelTokenBudget": model_token_budget,
                "observedTokens": input_tokens + output_tokens,
            }
        )
    if before["identityDigest"] != after["identityDigest"]:
        blockers.append({"code": "planning-qualification-worktree-drift"})
    return _planning_qualification_report(
        profile=profile,
        profile_digest=str(validation["profileDigest"]),
        approval_digest=approval_digest,
        receipt=receipt,
        before=before,
        after=after,
        blockers=blockers,
        usage_evidence=usage,
        approved_model_token_budget=model_token_budget,
        approved_wall_seconds=max_wall_seconds,
    )


def _attach_qualification_receipt(payload: dict[str, Any], receipt: dict[str, Any] | None) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "receiptDigest"}
    body["qualificationReceipt"] = receipt
    return {**body, "receiptDigest": canonical_digest(body)}


def _timeout_seconds(profile: dict[str, Any]) -> float:
    timeout = profile.get("timeoutSeconds")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
        return float(timeout)
    return 30.0


def _managed_launch_blockers(
    *,
    explicit_launch: bool,
    state_path: Path | None,
    manifest_path: Path | None,
    lock_path: Path | None,
    task_id: str | None,
    operation_id: str | None,
    source_revision: str | None,
    risk_profile: dict[str, Any] | None,
    adapter_id: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(risk_profile, dict) and "accountingCapabilityRequest" in risk_profile:
        blockers.append(accounting_request_blocker())
    if not explicit_launch:
        blockers.append({"code": "local-launch-explicit-flag-required"})
    missing = [
        field
        for field, value in {
            "state": state_path,
            "manifest": manifest_path,
            "lock": lock_path,
            "task": task_id,
            "operationId": operation_id,
            "sourceRevision": source_revision,
            "riskProfile": risk_profile,
        }.items()
        if value is None or value == ""
    ]
    if missing:
        blockers.append({"code": "local-launch-frozen-binding-missing", "fields": missing})
    if isinstance(risk_profile, dict) and risk_profile.get("adapterId") != adapter_id:
        blockers.append({"code": "local-launch-risk-profile-adapter-mismatch"})
    return blockers


def _blocked_local_launch(
    *,
    adapter_id: str,
    session_id: str,
    timeout_seconds: float,
    env_receipt: dict[str, Any],
    blockers: list[dict[str, Any]],
    profile_digest: str,
    risk_profile: dict[str, Any] | None,
    host_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk_digest = risk_profile.get("profileDigest") if isinstance(risk_profile, dict) else None
    return build_launch_receipt(
        status="BLOCKED",
        adapter_id=adapter_id,
        session_id=session_id,
        launch_mode="managedTask",
        argv=[],
        timeout_seconds=timeout_seconds,
        env=env_receipt,
        exit_code=None,
        timed_out=False,
        host_launch_started=False,
        blockers=blockers,
        profile_digest=profile_digest,
        risk_profile_digest=risk_digest if isinstance(risk_digest, str) else None,
        host_identity=host_identity,
    )


def _state_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise LifecycleError("local-launch-state-tasks-missing", "workflow state tasks are missing")
    for task in tasks:
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise LifecycleError("local-launch-task-missing", "task is not present in workflow state", {"taskId": task_id})


def _blocked_planning_launch(
    *,
    adapter_id: str,
    session_id: str,
    requested_mode: str | None,
    task_text: str | None,
    input_source: str,
    blockers: list[dict[str, Any]],
    profile_digest: str,
    host_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_value = task_text if isinstance(task_text, str) else ""
    body = {
        "schemaVersion": "agent-planning-launch-receipt.v1",
        "status": "BLOCKED",
        "action": "PLANNING_LAUNCH",
        "adapterId": adapter_id,
        "sessionId": session_id,
        "requestedMode": requested_mode if requested_mode in {"auto", "research", "plan", "review"} else "auto",
        "input": {
            "source": input_source,
            "sha256": canonical_digest({"text": task_value}),
            "byteCount": len(task_value.encode("utf-8")),
            "rawTaskTextStored": False,
        },
        "process": {
            "status": "NOT_STARTED",
            "exitCode": None,
            "timedOut": False,
            "inputBytes": 0,
            "outputBytes": 0,
            "outputLimitExceeded": False,
            "redactionApplied": False,
            "rawOutputStored": False,
        },
        "result": None,
        "usageEvidence": {
            "confidence": "MISSING",
            "inputTokens": None,
            "outputTokens": None,
            "moneyFieldsCanonical": False,
        },
        "processCalls": 0,
        "implementationAuthorized": False,
        "requiresReview": True,
        "rawTaskTextStored": False,
        "hostLaunchStarted": False,
        "modelCallsStarted": False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers,
        "profileDigest": profile_digest,
        "hostIdentity": host_identity,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _planning_qualification_report(
    *,
    profile: dict[str, Any],
    profile_digest: str,
    approval_digest: str,
    receipt: dict[str, Any] | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    usage_evidence: dict[str, Any] | None,
    approved_model_token_budget: int,
    approved_wall_seconds: float,
) -> dict[str, Any]:
    passed = (
        receipt is not None
        and receipt.get("status") == "REVIEW_REQUIRED"
        and before is not None
        and after is not None
        and before.get("identityDigest") == after.get("identityDigest")
        and not blockers
    )
    raw_policy = profile.get("qualification")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    body = {
        "schemaVersion": "agent-planning-launch-qualification-evidence.v1",
        "status": "PASS" if passed else "FAIL",
        "adapterId": profile.get("adapterId"),
        "expectedHostVersion": policy.get("expectedVersion"),
        "profileDigest": profile_digest,
        "approvalDigest": approval_digest,
        "approvedLimits": {
            "maxWallSeconds": approved_wall_seconds,
            "modelTokenBudget": approved_model_token_budget,
        },
        "usageEvidence": usage_evidence
        or {
            "confidence": "MISSING",
            "inputTokens": None,
            "outputTokens": None,
            "moneyFieldsCanonical": False,
        },
        "planningSupportStatus": "PLANNING_ONLY_QUALIFIED" if passed else "PLANNING_ONLY_UNSUPPORTED",
        "processCalls": 1 if receipt and receipt.get("hostLaunchStarted") else 0,
        "modelCallsStarted": bool(receipt and receipt.get("modelCallsStarted")),
        "worktreeUnchanged": bool(before and after and before.get("identityDigest") == after.get("identityDigest")),
        "planningReceiptDigest": receipt.get("receiptDigest") if receipt else None,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "evidenceDigest": canonical_digest(body)}
