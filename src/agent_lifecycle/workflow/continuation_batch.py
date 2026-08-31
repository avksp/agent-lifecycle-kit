"""Bounded orchestration over the projection-first continuation service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    sha256_hex,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.persistence import create_private_json, replace_private_json
from agent_lifecycle.contracts.workflow_continuation_batch_schemas import (
    CONTINUATION_BATCH_STOP_REASONS,
    MAX_CONTINUATION_BATCH_STEPS,
    build_continuation_batch_summary,
    build_unpersisted_continuation_batch_summary,
    continuation_batch_blocker,
    continuation_batch_projection_fields,
    continuation_batch_stop_reason,
    is_sha256_digest,
    normalize_continuation_input_reference,
)
from agent_lifecycle.workflow.artifacts import package_root
from agent_lifecycle.workflow.continuation import (
    CONTINUATION_APPLY_ACTION_TYPES,
    CONTINUATION_PATH_INPUTS,
    continue_workflow,
    normalize_continuation_inputs,
)
from agent_lifecycle.workflow.events import event_log_path
from agent_lifecycle.workflow.state import load_state, state_identity
from agent_lifecycle.workflow.transition_contract import ACTION_TYPES

MODEL_CALLS_STARTED = False
HOST_LAUNCH_STARTED = False
MAX_PROSPECTIVE_BLOCKER_BYTES = 16_384
MAX_PROSPECTIVE_RECORD_OVERHEAD = 4_096

STOP_ACTION_REASONS = {
    "none": "TERMINAL",
    "blocked": "BLOCKED",
    "wait-for-task-outcome": "WAITING",
    "run-final-audit": "AUDIT_REQUIRED",
    "request-human-decision": "HUMAN_DECISION_REQUIRED",
    "record-budget-decision": "BUDGET_DECISION_REQUIRED",
    "record-external-action-receipt": "EXTERNAL_ACTION_REQUIRED",
    "adopt-plan": "PLAN_AUTHORITY_REQUIRED",
}


def continue_workflow_batch(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    input_bundle_path: str,
    output_path: str,
    max_transitions: int,
    max_io_bytes: int,
    expected_revision: int,
    source_revision: str,
    reason: str,
    resume_receipt_path: str | None = None,
) -> dict[str, Any]:
    """Apply an explicit transition bundle until a bounded stop is reached."""

    if max_transitions <= 0 or max_io_bytes <= 0:
        return build_unpersisted_continuation_batch_summary(
            stop_reason="BLOCKED",
            blockers=[_simple_blocker("continuation-batch-cap-invalid", "batch caps must be positive")],
        )
    try:
        state = load_state(state_path)
        root = package_root(state_path, state)
        normalized_output = normalize_repo_path(output_path, label="continuation batch output")
        normalized_bundle = normalize_repo_path(input_bundle_path, label="continuation input bundle")
        normalized_resume = (
            normalize_repo_path(resume_receipt_path, label="continuation resume receipt")
            if resume_receipt_path is not None
            else None
        )
        prepared = _prepare_inputs(
            root=root,
            bundle_path=normalized_bundle,
            resume_path=normalized_resume,
            max_io_bytes=max_io_bytes,
        )
        _require_action_classification()
        _require_lineage(
            state,
            prepared["bundle"],
            expected_revision=expected_revision,
            source_revision=source_revision,
        )
        initial_projection = _project(
            state_path=state_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            step=prepared["steps"][0],
            expected_revision=expected_revision,
            source_revision=source_revision,
            reason=reason,
        )
        prefix = _validate_retry_prefix(state_path, state, prepared, source_revision)
        if initial_projection["status"] == "BLOCKED":
            initial_action_type = _projected_action_type(initial_projection)
            initial_stop_reason = (
                STOP_ACTION_REASONS.get(initial_action_type, "BLOCKED") if initial_action_type else "BLOCKED"
            )
            return _persist_initial_stop(
                root=root,
                output_path=normalized_output,
                prepared=prepared,
                state_path=state_path,
                state=state,
                limits=(max_transitions, max_io_bytes),
                stop_reason=initial_stop_reason,
                projection=initial_projection,
                prefix=prefix,
            )
        context = _BatchContext(
            root=root,
            state_path=state_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            output_path=normalized_output,
            source_revision=source_revision,
            reason=reason,
            max_transitions=max_transitions,
            max_io_bytes=max_io_bytes,
            prepared=prepared,
            prefix=prefix,
        )
        _reserve_output(context, state)
        try:
            return _run_batch(context)
        except LifecycleError as exc:
            projection = {"requiredInputs": [], "blockers": [continuation_batch_blocker(exc)]}
            return _finalize(
                context,
                stop_reason=continuation_batch_stop_reason(exc),
                projection=projection,
            )
    except FileExistsError:
        return build_unpersisted_continuation_batch_summary(
            stop_reason="BLOCKED",
            blockers=[_simple_blocker("continuation-output-exists", "batch output path already exists")],
        )
    except LifecycleError as exc:
        reason_code = continuation_batch_stop_reason(exc)
        return build_unpersisted_continuation_batch_summary(
            stop_reason=reason_code,
            blockers=[continuation_batch_blocker(exc)],
        )


class _BatchContext:
    def __init__(
        self,
        *,
        root: Path,
        state_path: Path,
        manifest_path: Path,
        lock_path: Path,
        output_path: str,
        source_revision: str,
        reason: str,
        max_transitions: int,
        max_io_bytes: int,
        prepared: dict[str, Any],
        prefix: list[dict[str, Any]],
    ) -> None:
        self.root = root
        self.state_path = state_path
        self.manifest_path = manifest_path
        self.lock_path = lock_path
        self.output_path = output_path
        self.source_revision = source_revision
        self.reason = reason
        self.max_transitions = max_transitions
        self.max_io_bytes = max_io_bytes
        self.prepared = prepared
        self.records = list(prefix)
        self.already_applied = len(prefix)
        self.applied = 0


def _prepare_inputs(
    *,
    root: Path,
    bundle_path: str,
    resume_path: str | None,
    max_io_bytes: int,
) -> dict[str, Any]:
    bundle_bytes = read_stable_repository_file(
        root,
        bundle_path,
        max_bytes=max_io_bytes,
        label="continuation input bundle",
    )
    bundle = load_json_object(bundle_bytes, label="continuation input bundle")
    _validate_bundle_shape(bundle)
    total_bytes = len(bundle_bytes)
    snapshots: list[tuple[str, bytes]] = [(bundle_path, bundle_bytes)]
    prepared_steps: list[dict[str, Any]] = []
    for sequence, step in enumerate(bundle["steps"], start=1):
        normalized_inputs: dict[str, Any] = {}
        for name, value in step["inputs"].items():
            if name not in CONTINUATION_PATH_INPUTS:
                normalized_inputs[name] = value
                continue
            reference = normalize_continuation_input_reference(value, name)
            remaining = max_io_bytes - total_bytes
            if remaining <= 0:
                raise LifecycleError("continuation-input-cap-exceeded", "batch inputs exceed the I/O cap")
            data = read_stable_repository_file(root, reference["path"], max_bytes=remaining, label=name)
            if sha256_hex(data) != reference["sha256"]:
                raise LifecycleError(
                    "continuation-input-digest-mismatch",
                    "referenced input digest does not match",
                    {"field": name, "path": reference["path"]},
                )
            total_bytes += len(data)
            snapshots.append((reference["path"], data))
            normalized_inputs[name] = reference["path"]
        normalized_inputs = normalize_continuation_inputs(normalized_inputs)
        prepared_steps.append(
            {
                "sequence": sequence,
                "operationId": step["operationId"],
                "expectedActionType": step["expectedActionType"],
                "inputs": normalized_inputs,
                "inputStepDigest": canonical_digest(step),
            }
        )
    resume: dict[str, Any] | None = None
    if resume_path is not None:
        remaining = max_io_bytes - total_bytes
        if remaining <= 0:
            raise LifecycleError("continuation-input-cap-exceeded", "batch inputs exceed the I/O cap")
        resume_bytes = read_stable_repository_file(root, resume_path, max_bytes=remaining, label="resume receipt")
        resume = load_json_object(resume_bytes, label="resume receipt")
        total_bytes += len(resume_bytes)
        snapshots.append((resume_path, resume_bytes))
    if total_bytes > max_io_bytes:
        raise LifecycleError("continuation-input-cap-exceeded", "batch inputs exceed the I/O cap")
    return {
        "bundle": bundle,
        "bundleIdentity": {
            "path": bundle_path,
            "sha256": sha256_hex(bundle_bytes),
            "canonicalDigest": canonical_digest(bundle),
            "bytes": len(bundle_bytes),
        },
        "steps": prepared_steps,
        "resume": resume,
        "inputBytes": total_bytes,
        "snapshots": snapshots,
    }


def _validate_bundle_shape(bundle: dict[str, Any]) -> None:
    required = {"schemaVersion", "runId", "packageId", "planDigest", "sourceRevision", "steps"}
    if bundle.get("schemaVersion") != "agent-workflow-continuation-input-bundle.v1" or set(bundle) != required:
        raise LifecycleError("continuation-bundle-invalid", "continuation input bundle is invalid")
    for name in ("runId", "packageId", "sourceRevision"):
        if not isinstance(bundle.get(name), str) or not bundle[name]:
            raise LifecycleError("continuation-bundle-invalid", f"bundle {name} must be a non-empty string")
    if not is_sha256_digest(bundle.get("planDigest")):
        raise LifecycleError("continuation-bundle-invalid", "bundle planDigest must be a SHA-256 digest")
    steps = bundle.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > MAX_CONTINUATION_BATCH_STEPS:
        raise LifecycleError("continuation-bundle-invalid", "bundle steps must be a bounded non-empty list")
    operation_ids: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"operationId", "expectedActionType", "inputs"}:
            raise LifecycleError("continuation-bundle-invalid", "each bundle step must use the closed step shape")
        operation_id = step.get("operationId")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 256:
            raise LifecycleError("continuation-bundle-invalid", "each step requires a bounded operationId")
        if operation_id in operation_ids:
            raise LifecycleError("continuation-bundle-operation-duplicate", "bundle operation IDs must be unique")
        operation_ids.add(operation_id)
        if step.get("expectedActionType") not in CONTINUATION_APPLY_ACTION_TYPES:
            raise LifecycleError("continuation-bundle-action-invalid", "bundle step action must be apply-class")
        if not isinstance(step.get("inputs"), dict):
            raise LifecycleError("continuation-bundle-invalid", "bundle step inputs must be an object")


def _require_action_classification() -> None:
    catalog = set(ACTION_TYPES)
    apply_actions = set(CONTINUATION_APPLY_ACTION_TYPES)
    stop_actions = set(STOP_ACTION_REASONS)
    if apply_actions & stop_actions or catalog != apply_actions | stop_actions:
        raise LifecycleError(
            "continuation-action-classification-invalid",
            "continuation action catalog is not classified exactly once",
            {
                "missing": sorted(catalog - apply_actions - stop_actions),
                "extra": sorted((apply_actions | stop_actions) - catalog),
            },
        )
    if set(STOP_ACTION_REASONS.values()).difference(CONTINUATION_BATCH_STOP_REASONS):
        raise LifecycleError("continuation-stop-reason-invalid", "continuation stop reason is not closed")


def _require_lineage(
    state: dict[str, Any],
    bundle: dict[str, Any],
    *,
    expected_revision: int,
    source_revision: str,
) -> None:
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": source_revision,
    }
    actual = {key: bundle.get(key) for key in expected}
    if actual != expected:
        raise LifecycleError("continuation-bundle-lineage-mismatch", "bundle lineage does not match workflow state")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "workflow source revision does not match")
    if state.get("stateRevision") != expected_revision:
        raise LifecycleError(
            "state-revision-mismatch",
            "workflow state revision mismatch",
            {"expected": expected_revision, "actual": state.get("stateRevision")},
        )


def _project(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    step: dict[str, Any],
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    return continue_workflow(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        operation_id=step["operationId"],
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=reason,
        inputs=step["inputs"],
    )


def _validate_retry_prefix(
    state_path: Path, state: dict[str, Any], prepared: dict[str, Any], source_revision: str
) -> list[dict[str, Any]]:
    ledger = state.get("operationLedger", {})
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    used = [step["operationId"] for step in prepared["steps"] if step["operationId"] in ledger]
    resume = prepared["resume"]
    if used and resume is None:
        raise LifecycleError("continuation-retry-proof-required", "reused bundle operations require a prior receipt")
    if resume is None:
        return []
    _require_receipt_digest(resume)
    lineage = resume.get("lineage")
    expected_lineage = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": source_revision,
    }
    if lineage != expected_lineage or resume.get("bundle") != prepared["bundleIdentity"]:
        raise LifecycleError("continuation-retry-proof-mismatch", "resume receipt lineage or bundle is different")
    records = resume.get("steps")
    if not isinstance(records, list) or len(records) > len(prepared["steps"]):
        raise LifecycleError("continuation-retry-proof-mismatch", "resume receipt step prefix is invalid")
    events = _events_by_operation(state_path, state)
    for index, record in enumerate(records):
        step = prepared["steps"][index]
        if not isinstance(record, dict) or not _record_matches_step(record, step):
            raise LifecycleError("continuation-retry-proof-mismatch", "resume step does not match the bundle prefix")
        operation_id = step["operationId"]
        entry = ledger.get(operation_id)
        event = events.get(operation_id)
        if not isinstance(entry, dict) or event is None or not _record_matches_history(record, entry, event):
            raise LifecycleError("continuation-retry-proof-mismatch", "resume step is not proven by ledger and event")
    prefix_ids = {step["operationId"] for step in prepared["steps"][: len(records)]}
    if any(operation_id not in prefix_ids for operation_id in used):
        raise LifecycleError("continuation-retry-proof-mismatch", "operation ledger is ahead of the resume receipt")
    return [dict(record) for record in records]


def _require_receipt_digest(receipt: dict[str, Any]) -> None:
    if receipt.get("schemaVersion") != "agent-workflow-continuation-batch-receipt.v1":
        raise LifecycleError("continuation-retry-proof-mismatch", "resume receipt schema is invalid")
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    if receipt.get("receiptDigest") != canonical_digest(body):
        raise LifecycleError("continuation-retry-proof-mismatch", "resume receipt digest is invalid")


def _record_matches_step(record: dict[str, Any], step: dict[str, Any]) -> bool:
    return (
        record.get("sequence") == step["sequence"]
        and record.get("operationId") == step["operationId"]
        and record.get("expectedActionType") == step["expectedActionType"]
        and record.get("inputStepDigest") == step["inputStepDigest"]
    )


def _record_matches_history(record: dict[str, Any], ledger: dict[str, Any], event: dict[str, Any]) -> bool:
    identity = record.get("event")
    return (
        isinstance(identity, dict)
        and record.get("stateRevisionAfter") == ledger.get("stateRevision")
        and identity.get("eventType") == ledger.get("eventType") == event.get("eventType")
        and identity.get("stateRevision") == event.get("stateRevision")
        and identity.get("sha256") == canonical_digest(event)
    )


def _events_by_operation(state_path: Path, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = event_log_path(state_path, state)
    if not path.exists():
        return {}
    events: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                operation_id = event.get("operationId") if isinstance(event, dict) else None
                if not isinstance(operation_id, str) or operation_id in events:
                    raise LifecycleError("invalid-workflow-event-log", "event operation identity is invalid")
                events[operation_id] = event
    except json.JSONDecodeError as exc:
        raise LifecycleError("invalid-workflow-event-log", "workflow event log contains malformed JSON") from exc
    except OSError as exc:
        raise LifecycleError("invalid-workflow-event-log", "workflow event log is unavailable") from exc
    return events


def _reserve_output(context: _BatchContext, state: dict[str, Any]) -> None:
    receipt = _build_receipt(
        context,
        status="IN_PROGRESS",
        stop_reason=None,
        state=state,
        projection=None,
    )
    if context.prepared["inputBytes"] + len(canonical_bytes(receipt)) + 1 > context.max_io_bytes:
        raise LifecycleError("continuation-input-cap-exceeded", "batch receipt cannot fit within the I/O cap")
    create_private_json(context.root / context.output_path, receipt)


def _run_batch(context: _BatchContext) -> dict[str, Any]:
    projection: dict[str, Any] | None = None
    stop_reason = "INPUT_REQUIRED"
    while True:
        state = load_state(context.state_path)
        index = len(context.records)
        step = context.prepared["steps"][index] if index < len(context.prepared["steps"]) else None
        projection_step = step or {"operationId": context.prepared["steps"][-1]["operationId"], "inputs": {}}
        projection = _project(
            state_path=context.state_path,
            manifest_path=context.manifest_path,
            lock_path=context.lock_path,
            step=projection_step,
            expected_revision=state["stateRevision"],
            source_revision=context.source_revision,
            reason=context.reason,
        )
        action_type = _projected_action_type(projection)
        if projection.get("status") == "BLOCKED":
            stop_reason = STOP_ACTION_REASONS.get(action_type, "BLOCKED") if action_type else "BLOCKED"
            break
        if action_type in STOP_ACTION_REASONS:
            stop_reason = STOP_ACTION_REASONS[action_type]
            break
        if step is not None and action_type != step["expectedActionType"]:
            stop_reason = "BLOCKED" if index == 0 else "STALE_BUNDLE_ENTRY"
            projection = _with_mismatch_blocker(projection, step, action_type)
            break
        if projection.get("requiredInputs"):
            stop_reason = "INPUT_REQUIRED"
            break
        if step is None:
            projection = _with_required_bundle_step(projection, action_type)
            stop_reason = "INPUT_REQUIRED"
            break
        if context.applied >= context.max_transitions:
            stop_reason = "CAP_TRANSITIONS"
            break
        if not _prospective_output_fits(context, projection, step):
            stop_reason = "CAP_BYTES"
            break
        _revalidate_snapshots(context)
        applied = continue_workflow(
            state_path=context.state_path,
            manifest_path=context.manifest_path,
            lock_path=context.lock_path,
            operation_id=step["operationId"],
            expected_revision=projection["action"]["stateRevision"],
            source_revision=context.source_revision,
            reason=context.reason,
            apply=True,
            projected_state_revision=projection["action"]["stateRevision"],
            projected_action_digest=projection["action"]["actionDigest"],
            inputs=step["inputs"],
        )
        after = load_state(context.state_path)
        ledger = after.get("operationLedger", {})
        if step["operationId"] not in ledger:
            projection = applied
            stop_reason = "BLOCKED"
            break
        record = _step_record(context, step, projection, after)
        context.records.append(record)
        context.applied += 1
        progress = _build_receipt(
            context,
            status="IN_PROGRESS",
            stop_reason=None,
            state=after,
            projection=applied,
        )
        replace_private_json(context.root / context.output_path, progress)
        if applied.get("status") != "APPLIED":
            projection = applied
            stop_reason = "BLOCKED"
            break
    return _finalize(context, stop_reason=stop_reason, projection=projection)


def _projected_action_type(projection: dict[str, Any]) -> str | None:
    action = projection.get("action")
    if isinstance(action, dict) and isinstance(action.get("managedActionType"), str):
        return action["managedActionType"]
    next_action = projection.get("nextAction")
    return next_action.get("type") if isinstance(next_action, dict) else None


def _with_required_bundle_step(projection: dict[str, Any], action_type: str | None) -> dict[str, Any]:
    required = list(projection.get("requiredInputs", []))
    required.append(
        {
            "name": "steps",
            "option": "--input-bundle",
            "reason": f"the bundle has no explicit step for {action_type}",
        }
    )
    return {**projection, "requiredInputs": required}


def _with_mismatch_blocker(
    projection: dict[str, Any],
    step: dict[str, Any],
    action_type: str | None,
) -> dict[str, Any]:
    blocker = {
        "code": "continuation-bundle-action-mismatch",
        "message": "bundle step does not match the freshly projected action",
        "context": {
            "sequence": step["sequence"],
            "expectedActionType": step["expectedActionType"],
            "actualActionType": action_type,
        },
    }
    return {**projection, "blockers": [*projection.get("blockers", []), blocker]}


def _prospective_output_fits(
    context: _BatchContext,
    projection: dict[str, Any],
    step: dict[str, Any],
) -> bool:
    state = load_state(context.state_path)
    projected_record = {
        "sequence": step["sequence"],
        "operationId": step["operationId"],
        "expectedActionType": step["expectedActionType"],
        "actualActionType": _projected_action_type(projection),
        "route": projection.get("action", {}).get("route"),
        "stateRevisionBefore": state["stateRevision"],
        "stateRevisionAfter": state["stateRevision"] + 1,
        "projectedActionDigest": projection.get("action", {}).get("actionDigest"),
        "inputStepDigest": step["inputStepDigest"],
        "event": {"eventType": "x" * 128, "stateRevision": state["stateRevision"] + 1, "sha256": "f" * 64},
        "resultingState": state_identity(context.state_path, state),
    }
    current = _build_receipt(
        context,
        status="IN_PROGRESS",
        stop_reason=None,
        state=state,
        projection=projection,
    )
    reservation = (
        len(canonical_bytes(current))
        + len(canonical_bytes(projected_record))
        + MAX_PROSPECTIVE_BLOCKER_BYTES
        + MAX_PROSPECTIVE_RECORD_OVERHEAD
        + 2
    )
    return context.prepared["inputBytes"] + reservation <= context.max_io_bytes


def _revalidate_snapshots(context: _BatchContext) -> None:
    for path, expected in context.prepared["snapshots"]:
        actual = read_stable_repository_file(
            context.root,
            path,
            max_bytes=len(expected),
            label="continuation stable input",
        )
        if actual != expected:
            raise LifecycleError("continuation-input-changed", "batch input changed after preflight", {"path": path})


def _step_record(
    context: _BatchContext,
    step: dict[str, Any],
    projection: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    events = _events_by_operation(context.state_path, after)
    event = events.get(step["operationId"])
    if event is None:
        raise LifecycleError("continuation-event-proof-missing", "committed transition has no ordinary event")
    return {
        "sequence": step["sequence"],
        "operationId": step["operationId"],
        "expectedActionType": step["expectedActionType"],
        "actualActionType": _projected_action_type(projection),
        "route": projection["action"]["route"],
        "stateRevisionBefore": projection["action"]["stateRevision"],
        "stateRevisionAfter": after["stateRevision"],
        "projectedActionDigest": projection["action"]["actionDigest"],
        "inputStepDigest": step["inputStepDigest"],
        "event": {
            "eventType": event.get("eventType"),
            "stateRevision": event.get("stateRevision"),
            "sha256": canonical_digest(event),
        },
        "resultingState": state_identity(context.state_path, after),
    }


def _build_receipt(
    context: _BatchContext,
    *,
    status: str,
    stop_reason: str | None,
    state: dict[str, Any],
    projection: dict[str, Any] | None,
    output_bytes: int = 0,
) -> dict[str, Any]:
    next_command, required, blockers = continuation_batch_projection_fields(projection)
    body = {
        "schemaVersion": "agent-workflow-continuation-batch-receipt.v1",
        "status": status,
        "stopReason": stop_reason,
        "receiptPath": context.output_path,
        "bundle": context.prepared["bundleIdentity"],
        "lineage": {
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": context.source_revision,
        },
        "limits": {"maxTransitions": context.max_transitions, "maxIoBytes": context.max_io_bytes},
        "inputBytes": context.prepared["inputBytes"],
        "outputBytes": output_bytes,
        "steps": context.records,
        "appliedCount": context.applied,
        "alreadyAppliedCount": context.already_applied,
        "lastAppliedOperationId": context.records[-1]["operationId"] if context.records else None,
        "finalState": state_identity(context.state_path, state),
        "nextCommand": next_command,
        "requiredInputs": required,
        "blockers": blockers,
        "modelCallsStarted": MODEL_CALLS_STARTED,
        "hostLaunchStarted": HOST_LAUNCH_STARTED,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _finalize(
    context: _BatchContext,
    *,
    stop_reason: str,
    projection: dict[str, Any] | None,
) -> dict[str, Any]:
    state = load_state(context.state_path)
    status = "COMPLETE" if stop_reason == "TERMINAL" else "STOPPED"
    receipt, summary, output_bytes = _render_final_artifacts(
        context,
        status=status,
        stop_reason=stop_reason,
        state=state,
        projection=projection,
    )
    total = context.prepared["inputBytes"] + output_bytes
    if total > context.max_io_bytes and context.applied == 0 and stop_reason != "CAP_BYTES":
        receipt, summary, _ = _render_final_artifacts(
            context,
            status="STOPPED",
            stop_reason="CAP_BYTES",
            state=state,
            projection=None,
        )
    replace_private_json(context.root / context.output_path, receipt)
    return summary


def _render_final_artifacts(
    context: _BatchContext,
    *,
    status: str,
    stop_reason: str,
    state: dict[str, Any],
    projection: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Render a receipt and summary whose byte accounting is self-consistent."""

    output_bytes = 0
    receipt: dict[str, Any]
    summary: dict[str, Any]
    for _ in range(16):
        receipt = _build_receipt(
            context,
            status=status,
            stop_reason=stop_reason,
            state=state,
            projection=projection,
            output_bytes=output_bytes,
        )
        summary = build_continuation_batch_summary(receipt)
        measured = len(canonical_bytes(receipt)) + len(canonical_bytes(summary)) + 2
        if measured == output_bytes:
            return receipt, summary, output_bytes
        output_bytes = measured
    raise LifecycleError("continuation-output-accounting-invalid", "batch output byte accounting did not converge")


def _persist_initial_stop(
    *,
    root: Path,
    output_path: str,
    prepared: dict[str, Any],
    state_path: Path,
    state: dict[str, Any],
    limits: tuple[int, int],
    stop_reason: str,
    projection: dict[str, Any],
    prefix: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _BatchContext(
        root=root,
        state_path=state_path,
        manifest_path=Path(),
        lock_path=Path(),
        output_path=output_path,
        source_revision=str(state.get("sourceRevision") or ""),
        reason="",
        max_transitions=limits[0],
        max_io_bytes=limits[1],
        prepared=prepared,
        prefix=prefix,
    )
    receipt = _build_receipt(
        context,
        status="IN_PROGRESS",
        stop_reason=None,
        state=state,
        projection=projection,
    )
    create_private_json(root / output_path, receipt)
    return _finalize(context, stop_reason=stop_reason, projection=projection)


def _simple_blocker(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


__all__ = ["STOP_ACTION_REASONS", "continue_workflow_batch"]
