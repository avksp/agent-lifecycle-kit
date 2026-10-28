"""Create and explicitly migrate durable workflow state."""

from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.git import changed_files, resolve_revision
from agent_lifecycle.compiler.task_packets import compile_task_packets, packet_publication_lock
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, read_json_object
from agent_lifecycle.contracts.authority_io import (
    create_authority_bytes,
    read_authority_bytes,
    resolve_authority_anchor,
)
from agent_lifecycle.contracts.authority_text import require_manifest_text
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, load_json_object, prepare_json_object
from agent_lifecycle.contracts.execution_target import (
    discard_created_output,
    inspect_execution_target,
    require_execution_target_digest,
)
from agent_lifecycle.contracts.ownership_paths import (
    compiler_output_paths,
    repository_authority_name,
    require_manifest_authority_paths,
    require_output_footprint,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.persistence import create_private_json
from agent_lifecycle.contracts.workflow_state_authority import workflow_package_root
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_MIGRATION_RECEIPT,
    WORKFLOW_STATE_V3,
    WORKFLOW_STATE_V4,
    WORKFLOW_STATE_V5,
    validate_workflow_state,
)
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
from agent_lifecycle.planning.prerequisites import validate_prerequisite_acceptance
from agent_lifecycle.planning.validation import validate_plan_manifest
from agent_lifecycle.workflow.checkpoint_gate import normalize_context_checkpoint_policy
from agent_lifecycle.workflow.operation_kernel import (
    commit_state,
    load_for_update,
    observe_workflow_writes,
    record_prepared_workflow_writes,
)
from agent_lifecycle.workflow.plan_adoption import adopt_plan
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import now_iso, storage_root_for_state
from agent_lifecycle.workflow.transactions import workflow_transaction, workflow_transaction_context


def initialize_workflow_state(
    state_path: Path,
    *,
    run_id: str,
    package_id: str,
    package_root: str = ".",
    event_log: str = "events.jsonl",
) -> dict[str, Any]:
    """Create one unbound v4 state without replacing an existing state file."""

    if not run_id or not package_id:
        raise LifecycleError("invalid-workflow-state", "runId and packageId are required")
    state = {
        "schemaVersion": WORKFLOW_STATE_V4,
        "runId": run_id,
        "packageId": package_id,
        "planRevision": 0,
        "planDigest": "",
        "sourceRevision": "",
        "stateRevision": 1,
        "phase": "AWAITING_AUTHORIZATION",
        "runStartedAt": now_iso(),
        "packageRoot": package_root,
        "eventLog": event_log,
        "operationLedger": {},
        "tasks": [],
        "budgets": {},
        "authorization": {"required": True, "granted": False},
        "blocker": None,
        "priorSnapshots": [],
    }
    validate_workflow_state(state, allow_legacy=False)
    prepared = prepare_json_object(state, label="initial workflow state")
    with workflow_transaction_context(state_path, creation_root=workflow_package_root(state_path, state)):
        record_prepared_workflow_writes(state_path, prepared)
        create_private_json(state_path, state)
        return status(state_path)


@workflow_transaction
def migrate_workflow_state(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    target_schema: str = WORKFLOW_STATE_V4,
) -> dict[str, Any]:
    """Explicitly migrate storage without renewing execution authority or clocks."""

    state = load_for_update(
        state_path, operation_id=operation_id, expected_revision=expected_revision, authorization_required=False
    )
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    if target_schema == WORKFLOW_STATE_V5:
        return _migrate_storage_v5(state_path, state, operation_id)
    if target_schema != WORKFLOW_STATE_V4:
        raise LifecycleError("unsupported-workflow-state", "Unsupported migration target")
    if state.get("schemaVersion") != WORKFLOW_STATE_V3:
        raise LifecycleError("workflow-state-migration-not-required", "state migration requires v3 input")
    migrated = _migrate_copy(state)
    source_state_revision = int(state["stateRevision"])
    receipt_body = {
        "schemaVersion": WORKFLOW_STATE_MIGRATION_RECEIPT,
        "status": "PASS",
        "runId": migrated["runId"],
        "packageId": migrated["packageId"],
        "fromSchemaVersion": WORKFLOW_STATE_V3,
        "toSchemaVersion": WORKFLOW_STATE_V4,
        "sourceStateRevision": source_state_revision,
        "targetStateRevision": source_state_revision + 1,
        "operationId": operation_id,
    }
    migration_receipt = {**receipt_body, "receiptDigest": canonical_digest(receipt_body)}
    migrated["migration"] = migration_receipt
    validate_workflow_state(migrated, allow_legacy=False)
    state.clear()
    state.update(migrated)
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="workflow-state-migrated",
        payload={"migrationReceipt": migration_receipt},
    )
    return {**status(state_path), "migrationReceipt": migration_receipt}


def _migrate_storage_v5(state_path: Path, state: dict[str, Any], operation_id: str) -> dict[str, Any]:
    if state.get("schemaVersion") != WORKFLOW_STATE_V4:
        raise LifecycleError("workflow-state-migration-not-required", "V5 migration requires v4 input")
    operation = StorageOperation.current()
    assert operation is not None
    operation.check()
    root = workflow_package_root(state_path, state)
    raw = read_authority_bytes(state_path, root=root, max_bytes=MAX_JSON_INPUT_BYTES)
    operation.check()
    if load_json_object(raw) != state:
        raise LifecycleError("authority-input-changed", "Migration source changed after loading")
    raw_sha = hashlib.sha256(raw).hexdigest()
    backup_path = state_path.with_name(f"{state_path.name}.v4-backup-{raw_sha}.json")
    root_name = storage_root_for_state(state_path, state)
    migrated = deepcopy(state)
    migrated["schemaVersion"] = WORKFLOW_STATE_V5
    migrated["storage"] = {"schemaVersion": "agent-workflow-storage.v1", "root": root_name}
    body = {
        "schemaVersion": "agent-workflow-storage-migration-receipt.v1",
        "status": "PASS",
        "runId": state["runId"],
        "packageId": state["packageId"],
        "fromSchemaVersion": WORKFLOW_STATE_V4,
        "toSchemaVersion": WORKFLOW_STATE_V5,
        "sourceStateSha256": raw_sha,
        "sourceStateBytes": len(raw),
        "sourceStateRevision": state["stateRevision"],
        "targetStateRevision": state["stateRevision"] + 1,
        "operationId": operation_id,
        "storageRoot": root_name,
        "backupPath": backup_path.absolute().relative_to(root).as_posix(),
    }
    receipt = {**body, "receiptDigest": canonical_digest(body)}
    migrated["storageMigration"] = receipt

    def persist_backup() -> None:
        try:
            create_authority_bytes(backup_path, raw, root=root, private=True)
        except FileExistsError:
            if read_authority_bytes(backup_path, root=root, max_bytes=MAX_JSON_INPUT_BYTES) != raw:
                raise LifecycleError("workflow-storage-invalid", "Migration backup collision") from None
        operation._published(backup_path, raw, "IMMUTABLE_BACKUP")

    commit_state(
        state_path,
        migrated,
        operation_id=operation_id,
        event_type="workflow-state-migrated",
        payload={"migrationReceipt": receipt},
        persist_artifacts=(persist_backup,),
        prepared_writes={backup_path: raw},
    )
    return {**status(state_path), "migrationReceipt": receipt}


def _migrate_copy(state: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(state)
    migrated["schemaVersion"] = WORKFLOW_STATE_V4
    phase = migrated.get("phase")
    if phase in {"STEP_REVIEW", "REMEDIATING"}:
        migrated["phase"] = "RUNNING"
    for task in migrated.get("tasks", []):
        if not isinstance(task, dict):
            raise LifecycleError("invalid-workflow-state", "legacy task entries must be objects")
        if task.get("status") in {"VALIDATING", "ACCEPTANCE_PENDING"}:
            raise LifecycleError(
                "workflow-state-migration-unsupported-status",
                "legacy task status has no v4 producer contract",
                {"taskId": task.get("id"), "status": task.get("status")},
            )
    migrated.setdefault("operationLedger", {})
    migrated.setdefault("priorSnapshots", [])
    migrated.setdefault("blocker", None)
    migrated.setdefault("authorization", {"required": False, "granted": True})
    return migrated


@dataclass(frozen=True)
class _InitializationInputs:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    state_path: Path
    event_log: str
    package_root: str
    output_dir: Path
    source_identity: dict[str, Any]
    source_paths: list[str]
    outputs: dict[str, bytes | None]


def project_workflow_initialization(
    state_path: Path,
    *,
    manifest_path: Path,
    run_id: str,
    package_id: str,
    repository_root: Path | None = None,
    package_root: str | None = None,
    event_log: str | None = None,
    output_dir: Path | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Project the real local destinations without creating state or packets."""
    prepared = _prepare_initialization_inputs(
        state_path,
        manifest_path,
        run_id,
        package_id,
        repository_root,
        package_root,
        event_log,
        output_dir,
        source_revision,
    )
    return _observe_initialization(prepared, run_id=run_id, package_id=package_id)


def initialize_compiled_workflow(
    state_path: Path,
    *,
    manifest_path: Path,
    run_id: str,
    package_id: str,
    projected_target_digest: str,
    operation_id: str,
    repository_root: Path | None = None,
    package_root: str | None = None,
    event_log: str | None = None,
    output_dir: Path | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Compose existing operations; stop at separate execution authorization."""
    if not operation_id:
        raise LifecycleError("invalid-operation-id", "Composition requires an adoption operation ID")
    args = (
        state_path,
        manifest_path,
        run_id,
        package_id,
        repository_root,
        package_root,
        event_log,
        output_dir,
        source_revision,
    )
    prepared = _prepare_initialization_inputs(*args)
    initial = _observe_initialization(prepared, run_id=run_id, package_id=package_id)
    require_execution_target_digest(projected_target_digest, initial)
    if prepared.manifest["status"] != "FROZEN":
        raise LifecycleError("plan-not-frozen", "Composition requires an actually reviewed frozen plan")
    with (
        workflow_transaction_context(prepared.state_path, creation_root=prepared.root),
        packet_publication_lock(prepared.root / prepared.output_dir),
    ):
        current = _prepare_initialization_inputs(*args)
        fresh = _observe_initialization(current, run_id=run_id, package_id=package_id)
        require_execution_target_digest(projected_target_digest, fresh)
        compile_task_packets(
            current.manifest_path,
            repository_root=current.root,
            write=True,
            publication_guard=lambda: _recheck_initialization_progress(current, initial, args, {}, run_id, package_id),
        )
        return _initialize_after_packet_commit(current, initial, args, run_id, package_id, operation_id)


def _initialize_after_packet_commit(
    prepared: _InitializationInputs,
    initial: dict[str, Any],
    args: tuple[Any, ...],
    run_id: str,
    package_id: str,
    operation_id: str,
) -> dict[str, Any]:
    expected: dict[Path, list[bytes]] = {}
    published = {name: data for name, data in prepared.outputs.items() if data is not None}
    creating: Path | None = prepared.state_path

    def observe(values: dict[Path, bytes]) -> None:
        # A second guard may follow our own append. Accept only bytes that
        # were prepared by this invocation, never an arbitrary newer output.
        for path, versions in expected.items():
            try:
                actual = read_authority_bytes(path, root=prepared.root, max_bytes=8_388_608)
            except FileNotFoundError:
                continue
            if actual in versions:
                published[path.relative_to(prepared.root).as_posix()] = actual
        _recheck_initialization_progress(prepared, initial, args, published, run_id, package_id)
        allowed = {prepared.state_path, prepared.root / prepared.event_log}
        for path, data in values.items():
            if path not in allowed:
                raise LifecycleError("execution-target-selector-mismatch", "Unexpected workflow output selector")
            expected.setdefault(path, []).append(data)

    try:
        _recheck_initialization_progress(prepared, initial, args, published, run_id, package_id)
        with observe_workflow_writes(prepared.state_path, observe):
            initialize_workflow_state(
                prepared.state_path,
                run_id=run_id,
                package_id=package_id,
                package_root=prepared.package_root,
                event_log=prepared.event_log,
            )
            state_rel = prepared.state_path.relative_to(prepared.root).as_posix()
            published[state_rel] = read_authority_bytes(prepared.state_path, root=prepared.root, max_bytes=8_388_608)
            creating = prepared.root / prepared.event_log
            _recheck_initialization_progress(prepared, initial, args, published, run_id, package_id)
            expected.setdefault(creating, []).append(b"")
            create_authority_bytes(creating, b"", root=prepared.root, private=True)
            published[prepared.event_log] = b""
            creating = None
            _recheck_initialization_progress(prepared, initial, args, published, run_id, package_id)
            result = adopt_plan(
                prepared.state_path,
                manifest_path=prepared.manifest_path,
                operation_id=operation_id,
                expected_revision=1,
                source_revision=prepared.source_identity["sourceRevision"],
                reset_tasks=False,
                start_mode="approval-required",
            )
        return {
            "schemaVersion": "agent-workflow-initialization-transaction.v1",
            "status": "PASS",
            "state": result,
            "targetBinding": initial,
            "packetSetCommitted": True,
            "executionAuthorized": False,
            "productionPromotionClaimed": False,
            "operations": ["task compile", "workflow init", "workflow adopt-plan"],
        }
    except BaseException as exc:
        if isinstance(exc, FileExistsError) and creating is not None:
            expected.pop(creating, None)
        conflicts = []
        for path, versions in reversed(list(expected.items())):
            try:
                removed = discard_created_output(
                    prepared.root, path.relative_to(prepared.root).as_posix(), versions, allow_partial=True
                )
            except (OSError, LifecycleError):
                removed = False
            if not removed:
                conflicts.append(path.relative_to(prepared.root).as_posix())
        if conflicts:
            raise LifecycleError(
                "workflow-initialization-rollback-conflict",
                "Changed writer data was retained during rollback",
                {"paths": conflicts, "completePacketSetRetained": True},
            ) from exc
        raise


def _prepare_initialization_inputs(
    state_path: Path,
    manifest_path: Path,
    run_id: str,
    package_id: str,
    repository_root: Path | None,
    package_root: str | None,
    event_log: str | None,
    output_dir: Path | None,
    source_revision: str | None,
) -> _InitializationInputs:
    root = (repository_root or Path.cwd()).resolve(strict=True)
    manifest_rel = repository_authority_name(root / manifest_path, root)
    manifest_path = root / manifest_rel
    manifest = read_json_object(manifest_path, label="initialization manifest")
    require_manifest_text(manifest)
    require_manifest_authority_paths(manifest, operation_root=root)
    validate_plan_manifest(manifest, require_completeness=True)
    package = manifest["package"]
    if not run_id or package_id != package["id"]:
        raise LifecycleError("execution-target-selector-mismatch", "Run/package selectors do not match the plan")
    if manifest_rel != package["planArtifactRoot"] + "/plan.manifest.json":
        raise LifecycleError("execution-target-selector-mismatch", "Manifest selector does not match its authority")
    state_rel = repository_authority_name(root / state_path, root)
    state_path = root / state_rel
    selected_root = package_root if package_root is not None else os.path.relpath(root, state_path.parent)
    if (state_path.parent / selected_root).resolve() != root:
        raise LifecycleError("execution-target-selector-mismatch", "State package root names a different checkout")
    if resolve_authority_anchor(state_path, selected_root) != root:
        raise LifecycleError("execution-target-selector-mismatch", "Run from the selected repository root")
    orchestration = manifest.get("orchestration", {})
    selected_event = normalize_repo_path(event_log or orchestration.get("eventLog", "events.jsonl"))
    for key, selected in [("stateFile", state_rel), ("eventLog", selected_event)]:
        if orchestration.get(key) is not None and orchestration[key] != selected:
            raise LifecycleError("execution-target-selector-mismatch", "Runtime selectors disagree with the plan")
    artifact_root = package.get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    default_output = Path(artifact_root) / "workflow/task-packets"
    selected_output = repository_authority_name(root / (output_dir or default_output), root)
    if selected_output != default_output.as_posix():
        raise LifecycleError("execution-target-selector-mismatch", "Packet output disagrees with adoption's selector")
    if normalize_context_checkpoint_policy(manifest.get("contextCheckpointPolicy"))["enabled"]:
        raise LifecycleError(
            "composition-policy-unsupported", "Use explicit operations for checkpoint-enabled adoption"
        )
    source = source_revision or manifest.get("baseRevision", {}).get("sha")
    if not isinstance(source, str) or not source or source != manifest.get("baseRevision", {}).get("sha"):
        raise LifecycleError("execution-target-selector-mismatch", "Source selector disagrees with the frozen base")
    outputs = _project_packet_outputs(root, manifest_path, manifest, default_output)
    if state_rel == selected_event or state_rel in outputs or selected_event in outputs:
        raise LifecycleError("execution-target-alias", "Initialization outputs must have distinct selectors")
    outputs.update({state_rel: None, selected_event: None})
    require_output_footprint(manifest, list(outputs), repository_root=root, manifest_path=manifest_path)
    source_id: dict[str, Any] = {
        "sourceRevision": resolve_revision(root, source, label="initialization source"),
        "headRevision": resolve_revision(root, "HEAD"),
    }
    changed = [name for name in changed_files(root, base=source_id["sourceRevision"]) if name not in outputs]
    source_id["changedPaths"] = changed
    inputs = sorted(set(changed + manifest.get("planFiles", [])))
    if manifest["status"] == "FROZEN":
        inputs.append(package["planArtifactRoot"] + "/plan.lock.json")
    return _InitializationInputs(
        root,
        manifest_path,
        manifest,
        state_path,
        selected_event,
        selected_root,
        default_output,
        source_id,
        inputs,
        outputs,
    )


def _project_packet_outputs(
    root: Path, manifest_path: Path, manifest: dict[str, Any], output_dir: Path
) -> dict[str, bytes | None]:
    if manifest["status"] != "FROZEN":
        return {name: None for name in compiler_output_paths(manifest, output_dir=output_dir)}
    review = manifest.get("planReview", {})
    review_path = review.get("report") if isinstance(review, dict) else None
    if not isinstance(review_path, str):
        raise LifecycleError("plan-review-required", "Composition requires the existing reviewed freeze contract")
    report_bytes = read_authority_bytes(root / review_path, root=root, max_bytes=8_388_608)
    report = read_json_object(root / review_path, label="initialization plan review")
    build_reviewed_plan_lock_v2(
        manifest,
        report,
        review_path=review_path,
        review_sha256=hashlib.sha256(report_bytes).hexdigest(),
        repository_root=root,
    )
    validate_prerequisite_acceptance(manifest, repository_root=root)
    compiled = compile_task_packets(manifest_path, repository_root=root, write=False)
    outputs: dict[str, bytes | None] = {
        (output_dir / f"{packet['task']['id']}.task-packet.json").as_posix(): canonical_bytes(packet) + b"\n"
        for packet in compiled["packets"]
    }
    outputs[(output_dir / "index.json").as_posix()] = canonical_bytes(compiled["index"]) + b"\n"
    return outputs


def _observe_initialization(
    prepared: _InitializationInputs,
    *,
    run_id: str,
    package_id: str,
    published: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    published = published or {}
    outputs = []
    for name, original in prepared.outputs.items():
        data = published.get(name, original)
        outputs.append(
            {
                "path": name,
                "role": "INITIALIZATION_OUTPUT",
                "expectedSha256": hashlib.sha256(data).hexdigest() if data is not None else None,
                "expectedBytes": len(data) if data is not None else None,
                "allowExisting": data is not None,
            }
        )
    manifest = prepared.manifest
    return inspect_execution_target(
        prepared.root,
        source_identity=prepared.source_identity,
        plan_identity={
            "packageId": package_id,
            "runId": run_id,
            "planRevision": manifest["planRevision"],
            "planDigest": canonical_digest(manifest),
            "package": manifest["package"],
            "statePackageRoot": prepared.package_root,
        },
        source_paths=prepared.source_paths,
        outputs=outputs,
        state_path=prepared.state_path.relative_to(prepared.root).as_posix(),
        event_log=prepared.event_log,
        stage="FROZEN" if manifest["status"] == "FROZEN" else "PLANNING",
    )


def _recheck_initialization_progress(
    _prepared: _InitializationInputs,
    initial: dict[str, Any],
    args: tuple[Any, ...],
    published: dict[str, bytes],
    run_id: str,
    package_id: str,
) -> None:
    current = _prepare_initialization_inputs(*args)
    observed = _observe_initialization(current, run_id=run_id, package_id=package_id, published=published)
    fixed = ["targetId", "sourceIdentity", "planIdentity", "sourceInventory", "statePath", "eventLog", "stage"]
    if any(observed[key] != initial[key] for key in fixed):
        raise LifecycleError("execution-target-changed", "Source, checkout, authority or selectors changed before use")
    for output in observed["outputs"]:
        if output["path"] in published and output["disposition"] != "EXACT_MATCH":
            raise LifecycleError("execution-target-changed", "An already published output changed before use")


__all__ = [
    "initialize_compiled_workflow",
    "initialize_workflow_state",
    "migrate_workflow_state",
    "project_workflow_initialization",
]
