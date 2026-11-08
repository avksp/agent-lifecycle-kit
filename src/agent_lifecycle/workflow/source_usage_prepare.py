"""Data producers for the explicitly registered frozen declared-source route."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from agent_lifecycle.accounting.declared_source_route import (
    canonical_source_bytes,
    prepare_project_opening,
    project_binding,
    project_owner,
    project_token_hold,
)
from agent_lifecycle.accounting.generic_source_usage import advance_project_source
from agent_lifecycle.accounting.source_usage_context import load_frozen_source_policy
from agent_lifecycle.accounting.usage_types import UsageContext, source_reference
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.declared_source_schemas import (
    PROJECT_POLICY,
    PROJECT_WINDOW,
    require_declared,
    validate_project_window,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.scoped_usage_schemas import (
    SOURCE_USAGE_METRICS,
    SOURCE_USAGE_MODE,
    validate_source_usage_receipt_shape,
)
from agent_lifecycle.model_routing.stage_bindings import availability_probe_only
from agent_lifecycle.workflow.artifacts import artifact_path, package_root
from agent_lifecycle.workflow.limited_usage import (
    current_source_snapshot,
    emit_registry_artifact,
    require_snapshot_current,
    validate_limited_source_usage,
)
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import load_state, require_current_authorization, require_expected_revision


class _AuthorityArguments(TypedDict):
    state_path: Path
    manifest_path: Path
    lock_path: Path
    task_id: str
    operation_id: str
    expected_revision: int
    source_revision: str
    actor_id: str


def prepare_source_opening(
    repository_root: Path,
    *,
    carry_path: str,
    owner_bindings_path: str,
    opening_out: str,
    source_root: str,
) -> dict[str, Any]:
    return prepare_project_opening(
        repository_root.absolute(),
        carry_path=carry_path,
        owner_bindings_path=owner_bindings_path,
        opening_out=opening_out,
        source_root=source_root,
    )


def _current_authority(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    actor_id: str,
) -> tuple[Path, dict[str, Any], dict[str, Any], UsageContext]:
    state = load_state(state_path)
    require_current_authorization(state)
    require_expected_revision(state, expected_revision)
    root = package_root(state_path, state)
    require_declared(
        state["phase"] == "RUNNING" and state["sourceRevision"] == source_revision, "current run/source differs"
    )
    require_declared(
        manifest_path.absolute() == root / state["manifestPath"]
        and lock_path.absolute() == (root / state["manifestPath"]).with_name("plan.lock.json"),
        "producer cannot select foreign plan inputs",
    )
    task = find_task(state, task_id)
    require_declared(task["status"] == "RUNNING" and task["attempt"] > 0, "producer requires current running attempt")
    for deadline in (state.get("runDeadlineAt"), task.get("attemptDeadlineAt")):
        require_declared(
            isinstance(deadline, str) and datetime.now(UTC) < datetime.fromisoformat(deadline.replace("Z", "+00:00")),
            "original admission window expired",
        )
    selection = load_frozen_source_policy(root, state, task, adapter_id=task.get("adapterId"))
    require_declared(selection is not None, "source opt-in absent")
    assert selection is not None
    require_declared(selection.policy["schemaVersion"] == PROJECT_POLICY, "producer requires registered generic route")
    owner, _ = project_owner(selection.inputs, task_id)
    route = task.get("attemptModelRoute") or {}
    require_declared(
        owner == actor_id
        and route.get("operationId") == operation_id
        and route.get("modelClass") in selection.policy["allowedModelClasses"],
        "actor/operation/model differs from actual attempt",
    )
    if availability_probe_only(selection.inputs["manifest"], task_id):
        require_declared(
            bool(task.get("attemptExecutionStrategy", {}).get("stageBinding")), "probe-only task lacks adopted binding"
        )
    adopted = task.get("attemptRiskExecutionProfile") or task.get("attemptExecutionStrategy") or {}
    require_declared(
        adopted.get("sourceUsagePolicyDigest") == selection.policy_digest
        and adopted.get("usageMode") == SOURCE_USAGE_MODE,
        "source policy was not adopted",
    )
    return root, state, task, selection


def prepare_source_admission(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    actor_id: str,
    expected_head_sha256: str,
    out: str,
) -> dict[str, Any]:
    args = _AuthorityArguments(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        actor_id=actor_id,
    )
    _root, state, task, selection = _current_authority(**args)
    source_root = selection.policy["financialSource"]["sourceRoot"]
    out = normalize_repo_path(out)
    window_id = Path(out).stem
    require_declared(
        out == source_root + "/windows/" + window_id + ".json", "admission output is outside source windows"
    )
    snapshot = current_source_snapshot(selection)
    current = snapshot["current"]
    binding = project_binding(selection.inputs, state, task, window_id)
    existing = [row for row in current["windows"] if row["sourceRef"]["path"] == out]
    if existing:
        original = existing[0]["source"]
        require_declared(
            original["binding"] == binding
            and original["declaredTokenHold"] == project_token_hold(task)
            and original["previousHeadSha256"] == expected_head_sha256,
            "published window identity differs",
        )
        require_snapshot_current(selection, snapshot)
        return {
            "status": "DECLARED_FULL_HOLD",
            "windowRef": existing[0]["sourceRef"],
            "headSha256": current["headSha256"],
            "executionAuthorized": False,
            "actualTokens": None,
            "actualUSD": None,
            "financialClosure": "OPEN_UNAVAILABLE",
        }
    window = {
        "schemaVersion": PROJECT_WINDOW,
        "id": window_id,
        "sequence": current["head"]["sequence"] + 1,
        "openingSha256": selection.policy["openingRef"]["sha256"],
        "previousHeadSha256": expected_head_sha256,
        "binding": binding,
        "declaredTokenHold": project_token_hold(task),
        "sourceContextRefs": [],
        "observations": [],
        "costStatus": "UNAVAILABLE",
        "actualTokens": None,
        "actualUSD": None,
        "financialClosure": "OPEN_UNAVAILABLE",
    }
    validate_project_window(window)

    def recheck() -> None:
        _, now_state, now_task, now_selection = _current_authority(**args)
        require_declared(
            now_state == state and now_task == task and now_selection.policy_digest == selection.policy_digest,
            "current native authority changed before source publication",
        )

    require_snapshot_current(selection, snapshot)
    result = advance_project_source(selection.inputs, window, expected_head_sha256, precommit=recheck)
    return {
        "status": "DECLARED_FULL_HOLD",
        "windowRef": source_reference(out, canonical_source_bytes(window)),
        "headSha256": result["headSha256"],
        "executionAuthorized": False,
        "actualTokens": None,
        "actualUSD": None,
        "financialClosure": "OPEN_UNAVAILABLE",
    }


def prepare_source_receipt(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    actor_id: str,
    window: str,
    out: str,
) -> dict[str, Any]:
    args = _AuthorityArguments(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        actor_id=actor_id,
    )
    root, state, task, selection = _current_authority(**args)
    out = normalize_repo_path(out)
    evidence_dir = Path(artifact_path(task, "result", task["attempt"])).parent
    require_declared(
        Path(out).parent == evidence_dir and out != artifact_path(task, "result", task["attempt"]),
        "usage output must be separate current task evidence",
    )
    snapshot = current_source_snapshot(selection)
    pools = [
        row
        for row in snapshot["projection"]["windowPools"]
        if row["binding"] == project_binding(selection.inputs, state, task, row["windowId"])
    ]
    require_declared(
        len(pools) == 1 and pools[0]["admissionRef"]["path"] == normalize_repo_path(window),
        "receipt window is not the independently selected original attempt",
    )
    route = task["attemptModelRoute"]
    lineage = {key: state[key] for key in ("runId", "packageId", "planDigest", "sourceRevision")}
    lineage.update(taskId=task_id, attempt=task["attempt"], routeDecisionDigest=route["decisionDigest"])
    registry_ref = emit_registry_artifact(root, state, task)
    receipt = {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v2",
        "operationId": operation_id,
        "host": selection.policy["adapterHost"],
        "modelClass": route["modelClass"],
        "providerModelHash": canonical_digest(
            {"routeDecisionDigest": route["decisionDigest"], "identityAssurance": "UNAVAILABLE"}
        ),
        "lineage": lineage,
        "attestation": {"source": "alk-declared", "status": "UNAVAILABLE"},
        "usage": dict.fromkeys(SOURCE_USAGE_METRICS),
        "metricStates": dict.fromkeys(SOURCE_USAGE_METRICS, "UNAVAILABLE"),
        "usageMode": SOURCE_USAGE_MODE,
        "policyDigest": selection.policy_digest,
        "sourceAuthoringRegistryDigest": selection.policy["sourceAuthoringRegistryRef"]["sha256"],
        "ledgerRef": source_reference(selection.source.head_path, snapshot["current"]["headRaw"]),
        "currentAdmissionRef": pools[0]["admissionRef"],
        "actorId": actor_id,
        "sourceContextRefs": [],
        "currentRegistryRef": registry_ref,
    }
    validate_source_usage_receipt_shape(receipt)
    validate_limited_source_usage(root, state, task, receipt)
    _, now_state, _, _ = _current_authority(**args)
    require_declared(now_state == state, "native authority changed during receipt production")
    require_snapshot_current(selection, snapshot)
    raw = canonical_source_bytes(receipt)
    create_authority_bytes(root / out, raw, root=root)
    require_snapshot_current(selection, snapshot)
    return {
        "status": "DECLARED_USAGE_ONLY",
        "usageRef": source_reference(out, raw),
        "executionAuthorized": False,
        "financialClosure": "OPEN_UNAVAILABLE",
        "actualTokens": None,
        "actualUSD": None,
    }
