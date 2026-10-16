"""Owned codex prompt preparation helpers."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.input_fit import assess_local_input_fit
from agent_lifecycle.adapter_sessions.attempt_authority import (
    _invocation_namespace,
    capture_attempt_authority,
    reserve_attempt_result,
    verify_attempt_reservation,
)
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import (
    _exact_keyword_values,
    _exact_prepared_result,
    _ExactAttempt,
    _ExactAuthority,
    _ExactFit,
    _ExactHost,
    _ExactPrelaunch,
    _ExactProcess,
    _ExactPrompt,
    _ExactRaw,
    _observed_bundled_catalog,
    _observed_prompt_diagnostic,
    _recheck_active_workflow_state,
    _recheck_alk_fit_sources,
    _require_current_manifest,
    _require_fresh_catalog,
    _selected_binary_path,
)
from agent_lifecycle.adapter_sessions.input_lifecycle import (
    _assert_no_cleanup_blockers,
    _part,
    _remove_snapshot_no_start,
    _seal_request,
    _sha,
    _snapshot_digest,
    _snapshot_raw_sources,
    cleanup_no_start,
    reconcile_prelaunch_intents,
)
from agent_lifecycle.adapter_sessions.private_input import (
    _read_private,
    _require,
    _verify_private_ancestors,
    _write_exclusive,
)
from agent_lifecycle.context import render_context
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash

ROUTE_ID = "codex-exact-prompt-v1"

CLAIM = "ALK_CONTROLLED_OUTBOUND_INPUT_FIT"

_EXACT_EVIDENCE_RELATIVE = "work/release-2-16/evidence/codex-exact-prompt"
_EXACT_PRIVATE_RELATIVE = "work/release-2-16/private-details/codex-exact-prompt"
_RUNTIME_REL = "work/release-2-16/runtime-private/codex-exact-prompt"


def _exact_wire_identity(
    run_id: str, task_id: str, attempt_id: str, role: str | None, final_sha: str
) -> dict[str, str | None]:
    return {
        "routeId": ROUTE_ID,
        "requestedClaim": CLAIM,
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "role": role,
        "finalPromptSha256": final_sha,
    }


def _selected_host_evidence(
    root: Path,
    request: dict[str, Any],
    identity: dict[str, Any],
    final_sha: str,
    run_id: str,
    task_id: str,
    attempt_id: str,
    executable: str,
    process_env: dict[str, str],
    role: str,
    *,
    operation_id: str | None = None,
) -> tuple[str, str, str, dict[str, Any], dict[str, Any], str]:
    """Create ALK prelaunch sources without claiming child internal equivalence."""
    base = root / _EXACT_EVIDENCE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    private = root / _EXACT_PRIVATE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    selected = request.get("selectedHost")
    _require(isinstance(selected, dict), "codex-exact-host-proof-missing", "selected host proof is missing")
    selected = _validated_cast(dict[str, Any], selected)
    model = selected.get("model")
    _require(
        isinstance(model, str) and bool(model) and len(model) <= 128,
        "codex-exact-model-invalid",
        "selected model is invalid",
    )
    model = _validated_cast(str, model)
    _require(
        selected.get("binarySha256") == identity.get("executableContentSha256"),
        "codex-exact-binary-mismatch",
        "selected binary changed",
    )
    catalog = _observed_bundled_catalog(root, executable, identity, model, process_env)
    if "catalogWindowTokens" in selected:
        _require(
            selected["catalogWindowTokens"] == catalog["catalogWindowTokens"],
            "codex-exact-window-mismatch",
            "caller catalog hint differs from selected binary",
        )
    _require(
        not any(key in selected for key in ("configManifestSha256", "transportWitnessSha256", "diagnosticSha256")),
        "codex-exact-legacy-witness-refused",
        "caller-authored host PASS witnesses are not accepted",
    )
    snapshot = root / _RUNTIME_REL / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "codex-home"
    _verify_private_ancestors(snapshot, root=root)
    info = snapshot.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
        "codex-exact-config-unsafe",
        "private CODEX_HOME is not protected",
    )
    snapshot_digest = _snapshot_digest(snapshot, root=root)
    effective_config = private / "effective-config.json"
    source = {
        "schemaVersion": "alk-codex-alk-config-source.v1",
        **_exact_wire_identity(run_id, task_id, attempt_id, role, final_sha),
        "model": model,
        "binarySha256": identity["executableContentSha256"],
        "selectedBinaryVersion": catalog["version"],
        "catalogSha256": catalog["catalogSha256"],
        "cwdPathSha256": _sha(os.fsencode(str(root))),
        "codexHomePathSha256": _sha(os.fsencode(str(snapshot))),
        "codexHomeContentDigest": snapshot_digest,
        "childInternalEffectiveConfig": "UNPROVEN",
    }
    _write_exclusive(effective_config, canonical_bytes(source), root=root)
    diagnostic = _observed_prompt_diagnostic(
        root,
        executable,
        identity,
        snapshot=snapshot,
        model=model,
        role=role,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        final_sha=final_sha,
        process_env=process_env,
        operation_id=operation_id,
    )
    config_source = _raw_source_record(root, effective_config, "alk-config-source")
    manifest = {
        "schemaVersion": "alk-codex-config-source-manifest.v1",
        "status": "OBSERVED_ALK_SOURCE",
        **_exact_wire_identity(run_id, task_id, attempt_id, role, final_sha),
        "model": model,
        "binarySha256": identity["executableContentSha256"],
        "selectedBinaryVersion": catalog["version"],
        "catalogObservation": catalog,
        "configSource": config_source,
        "diagnosticRawSha256": diagnostic["rawSha256"],
        "diagnosticItemCount": diagnostic["itemCount"],
        "childInternalEffectiveConfig": "UNPROVEN",
    }
    config_manifest = base / "config-snapshot-manifest.json"
    manifest_raw = canonical_bytes(manifest)
    _write_exclusive(config_manifest, manifest_raw, root=root)
    return model, str(snapshot), snapshot_digest, catalog, diagnostic, _sha(manifest_raw)


def _raw_source_record(root: Path, path: Path, kind: str) -> dict[str, Any]:
    raw = _read_private(path, root=root)
    info = path.lstat()
    _require(
        stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == len(raw),
        "codex-exact-raw-inventory-invalid",
        "raw source changed during inventory",
    )
    return {
        "kind": kind,
        "path": str(path.relative_to(root)),
        "pathSha256": _sha(os.fsencode(str(path))),
        "fileIdentity": {"device": info.st_dev, "inode": info.st_ino},
        "sha256": _sha(raw),
        "bytes": len(raw),
    }


def _record_transport_witness(
    root: Path,
    evidence: Path,
    *,
    run_id: str,
    task_id: str,
    attempt_id: str,
    role: str,
    final_sha: str,
    operation_id: str | None = None,
    config_manifest_sha: str,
    diagnostic: dict[str, Any],
    event: dict[str, Any],
) -> None:
    """Join actual start and OS-pipe receipts without asserting consumption."""
    try:
        start_raw = _read_private(evidence / "process-start.json", root=root)
        input_raw = _read_private(evidence / "process-input.json", root=root)
    except OSError as exc:
        raise LifecycleError("codex-exact-process-join-invalid", "observed process receipt is missing") from exc
    try:
        start = json.loads(start_raw)
        observed_input = json.loads(input_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-process-join-invalid", "observed process receipt is malformed") from exc
    _require(
        start.get("schemaVersion") == "alk-codex-process-start.v1"
        and start.get("hostLaunchStarted") is True
        and start.get("stdinStatus") == "PENDING"
        and observed_input.get("schemaVersion") == "alk-codex-process-input.v1"
        and all(
            start.get(key) == value and observed_input.get(key) == value
            for key, value in (("runId", run_id), ("taskId", task_id), ("attemptId", attempt_id), ("role", role))
        )
        and (operation_id is None or start.get("operationId") == observed_input.get("operationId") == operation_id)
        and start.get("finalPromptSha256") == final_sha
        and observed_input.get("finalPromptSha256") == final_sha
        and all(observed_input.get(key) == value for key, value in event.items()),
        "codex-exact-process-join-invalid",
        "start/input receipt subject differs",
    )
    transport = {
        "schemaVersion": "alk-codex-os-pipe-transport.v1",
        "status": "OS_PIPE_ACCEPTED" if event["status"] == "COMPLETE" else "STARTED_INPUT_FAILURE",
        **_exact_wire_identity(run_id, task_id, attempt_id, role, final_sha),
        "configManifestSha256": config_manifest_sha,
        "diagnosticRawSha256": diagnostic["rawSha256"],
        "diagnosticItemDigests": diagnostic["items"],
        "processStartSha256": _sha(start_raw),
        "processInputSha256": _sha(input_raw),
        "observedPipe": event,
        "childConsumption": "UNPROVEN",
        "execStdinDiagnosticEquivalence": "UNPROVEN",
    }
    if operation_id is not None:
        transport["operationId"] = operation_id
    _write_exclusive(evidence / "transport-equivalence.json", canonical_bytes(transport), root=root)


def _workflow_journal_identity(root: Path, state: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Pin the PRE workflow event-log file identity, not a financial Journal grant."""
    event_log = state.get("eventLog")
    _require(
        state.get("runId") == run_id
        and isinstance(event_log, str)
        and bool(event_log)
        and not Path(event_log).is_absolute()
        and ".." not in Path(event_log).parts
        and bool(Path(event_log).parts),
        "codex-exact-journal-unavailable",
        "workflow event-log binding is missing",
    )
    event_log = _validated_cast(str, event_log)
    try:
        root_info = root.lstat()
        _require(stat.S_ISDIR(root_info.st_mode), "codex-exact-journal-unavailable", "workflow root is not a directory")
        relative = Path(event_log)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            _require(
                stat.S_ISDIR(current.lstat().st_mode),
                "codex-exact-journal-unavailable",
                "workflow event-log parent is unsafe",
            )
        journal_info = (root / relative).lstat()
        _require(
            stat.S_ISREG(journal_info.st_mode),
            "codex-exact-journal-unavailable",
            "workflow event log is not a regular file",
        )
    except OSError as exc:
        raise LifecycleError("codex-exact-journal-unavailable", "workflow event log cannot be inspected") from exc
    subject = {
        "kind": "WORKFLOW_EVENT_LOG_PRE_WS01",
        "runId": run_id,
        "rootPathSha256": _sha(os.fsencode(str(root))),
        "rootFileIdentity": {"device": root_info.st_dev, "inode": root_info.st_ino},
        "eventLog": relative.as_posix(),
        "eventLogFileIdentity": {"device": journal_info.st_dev, "inode": journal_info.st_ino},
    }
    return {**subject, "journalIdentity": canonical_digest(subject)}


def create_prestart_raw_inventory(
    project_root: Path,
    *,
    run_id: str,
    task_id: str,
    attempt_id: str,
    sealed_request: Path,
    state: dict[str, Any],
    plan_digest: str,
    operation_id: str | None = None,
) -> tuple[Path, Path, str]:
    """Seal all known raw and the whole child snapshot cleanup obligation before Popen."""
    root = Path(project_root).absolute()
    run_id, task_id, attempt_id = (_part(value, "rawInventoryIdentity") for value in (run_id, task_id, attempt_id))
    journal = _workflow_journal_identity(root, state, run_id)
    private = root / _EXACT_PRIVATE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    expected_request = private / "input-request.json"
    _require(
        Path(sealed_request).absolute() == expected_request,
        "codex-exact-raw-inventory-invalid",
        "sealed request identity differs",
    )
    sources = [
        _raw_source_record(root, expected_request, "sealed-request"),
        _raw_source_record(root, private / "prompt-input.json", "diagnostic"),
        _raw_source_record(root, private / "effective-config.json", "effective-config"),
        *_snapshot_raw_sources(
            root,
            (root / _RUNTIME_REL / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "codex-home"),
        ),
    ]
    inventory = {
        "schemaVersion": "alk-r68b-raw-inventory.v1",
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "planDigest": plan_digest,
        "journalAuthorityKind": journal["kind"],
        "journalIdentity": journal["journalIdentity"],
        "eventLog": journal["eventLog"],
        "eventLogFileIdentity": journal["eventLogFileIdentity"],
        "rootPathSha256": journal["rootPathSha256"],
        "rootFileIdentity": journal["rootFileIdentity"],
        "workflowStateDigest": canonical_digest(state),
        "sources": sources,
    }
    if operation_id is not None:
        inventory["operationId"] = operation_id
    inventory_path = private / "raw-inventory.json"
    pending_path = (
        root
        / _EXACT_EVIDENCE_RELATIVE
        / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
        / "raw-cleanup-pending.json"
    )
    _reserve(pending_path, root=root)
    _write_exclusive(inventory_path, canonical_bytes(inventory), root=root)
    inventory_sha = _sha(inventory_path.read_bytes())
    pending = {
        "schemaVersion": "alk-r68b-raw-cleanup-pending.v1",
        "status": "PENDING",
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "journalIdentity": journal["journalIdentity"],
        "journalAuthorityKind": journal["kind"],
        "rootPathSha256": inventory["rootPathSha256"],
        "inventorySha256": inventory_sha,
    }
    if operation_id is not None:
        pending["operationId"] = operation_id
    _replace_reserved(pending_path, pending, root=root)
    return inventory_path, pending_path, inventory_sha


def verify_prestart_raw_inventory(
    project_root: Path,
    *,
    inventory_path: Path,
    pending_path: Path,
    state: dict[str, Any],
    plan_digest: str,
    started: bool = False,
) -> str:
    """Recheck sealed sources; a started host owns additions to its runtime tree."""
    _require(type(started) is bool, "codex-exact-raw-inventory-stale", "invalid process-start boundary")
    root = Path(project_root).absolute()
    raw = _read_private(Path(inventory_path).absolute(), root=root)
    try:
        inventory = json.loads(raw)
        pending = json.loads(_read_private(Path(pending_path).absolute(), root=root))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-raw-inventory-stale", "raw inventory is unreadable") from exc
    _require(
        isinstance(inventory, dict)
        and isinstance(pending, dict)
        and inventory.get("schemaVersion") == "alk-r68b-raw-inventory.v1"
        and pending.get("schemaVersion") == "alk-r68b-raw-cleanup-pending.v1"
        and pending.get("status") == "PENDING"
        and inventory.get("planDigest") == plan_digest
        and inventory.get("workflowStateDigest") == canonical_digest(state),
        "codex-exact-raw-inventory-stale",
        "raw inventory subject changed",
    )
    inventory = _validated_cast(dict[str, Any], inventory)
    pending = _validated_cast(dict[str, Any], pending)
    run_id = _part(inventory.get("runId"), "rawInventoryRunId")
    task_id = _part(inventory.get("taskId"), "rawInventoryTaskId")
    attempt_id = _part(inventory.get("attemptId"), "rawInventoryAttemptId")
    operation_id = inventory.get("operationId")
    _require(
        "operationId" not in inventory or (isinstance(operation_id, str) and bool(operation_id)),
        "codex-exact-raw-inventory-stale",
        "raw operation identity is invalid",
    )
    private = root / _EXACT_PRIVATE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    evidence = root / _EXACT_EVIDENCE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    _require(
        Path(inventory_path).absolute() == private / "raw-inventory.json"
        and Path(pending_path).absolute() == evidence / "raw-cleanup-pending.json",
        "codex-exact-raw-inventory-stale",
        "raw inventory paths changed",
    )
    journal = _workflow_journal_identity(root, state, run_id)
    _require(
        inventory.get("journalAuthorityKind") == journal["kind"]
        and inventory.get("journalIdentity") == journal["journalIdentity"]
        and inventory.get("eventLogFileIdentity") == journal["eventLogFileIdentity"]
        and inventory.get("rootFileIdentity") == journal["rootFileIdentity"]
        and inventory.get("rootPathSha256") == journal["rootPathSha256"],
        "codex-exact-raw-inventory-stale",
        "workflow journal/root identity changed",
    )
    expected = [
        _raw_source_record(root, private / "input-request.json", "sealed-request"),
        _raw_source_record(root, private / "prompt-input.json", "diagnostic"),
        _raw_source_record(root, private / "effective-config.json", "effective-config"),
    ]
    snapshot = root / _RUNTIME_REL / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "codex-home"
    if started:
        # The cleanup obligation covers the whole tree, including additions.
        # Its prestart digest is not a post-spawn whole-tree observation.
        _verify_private_ancestors(snapshot, root=root)
        info = snapshot.lstat()
        _require(
            stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
            "codex-exact-config-unsafe",
            "private CODEX_HOME is not protected",
        )
        pinned = inventory.get("sources", [])[3:]
        _require(
            pinned
            and pinned[0].get("kind") == "codex-home-snapshot-tree"
            and pinned[0].get("path") == str(snapshot.relative_to(root))
            and pinned[0].get("pathSha256") == _sha(os.fsencode(str(snapshot)))
            and pinned[0].get("fileIdentity") == {"device": info.st_dev, "inode": info.st_ino}
            and pinned[0].get("cleanupScope") == "WHOLE_TREE_INCLUDING_POST_START_ADDITIONS",
            "codex-exact-raw-inventory-stale",
            "snapshot root binding changed",
        )
        expected.append(pinned[0])
        for row in pinned[1:]:
            path = root / str(row.get("path", ""))
            _require(
                row.get("kind") == "codex-home-snapshot-file"
                and path.is_relative_to(snapshot)
                and ".." not in path.parts,
                "codex-exact-raw-inventory-stale",
                "snapshot source path changed",
            )
            raw_source = _read_private(path, root=root, allowed_modes=(0o400, 0o600), max_bytes=8_388_608)
            file_info = path.lstat()
            expected.append(
                {
                    "kind": "codex-home-snapshot-file",
                    "path": str(path.relative_to(root)),
                    "pathSha256": _sha(os.fsencode(str(path))),
                    "fileIdentity": {"device": file_info.st_dev, "inode": file_info.st_ino},
                    "sha256": _sha(raw_source),
                    "bytes": len(raw_source),
                    "mode": stat.S_IMODE(file_info.st_mode),
                }
            )
    else:
        expected.extend(_snapshot_raw_sources(root, snapshot))
    _require(
        inventory.get("sources") == expected
        and pending.get("inventorySha256") == _sha(raw)
        and pending.get("journalIdentity") == journal["journalIdentity"]
        and all(
            pending.get(key) == inventory.get(key)
            for key in ("runId", "taskId", "attemptId", "operationId", "rootPathSha256")
        ),
        "codex-exact-raw-inventory-stale",
        "raw source bytes or pending obligation changed",
    )
    return _sha(raw)


def cleanup_prestart_raw(
    project_root: Path,
    *,
    run_id: str,
    task_id: str,
    attempt_id: str,
    staging_source: Path | None,
    proven_no_start: bool,
    operation_id: str | None = None,
) -> None:
    """Remove attempt raw only after an in-process, proven no-Popen outcome."""
    root = Path(project_root).absolute()
    _require(
        proven_no_start, "codex-exact-start-uncertain", "raw sources cannot be removed after a possible child start"
    )
    run_id, task_id, attempt_id = (_part(value, "rawCleanupIdentity") for value in (run_id, task_id, attempt_id))
    evidence = root / _EXACT_EVIDENCE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    start = evidence / "process-start.json"
    _require(
        not any(
            (evidence / name).exists() or (evidence / name).is_symlink()
            for name in ("attempt-result-terminal.json", "attempt-result-terminal.pending.json")
        ),
        "codex-exact-start-uncertain",
        "terminal or uncertain attempt forbids no-start cleanup",
    )
    _require(
        not start.exists() or start.stat().st_size == 0,
        "codex-exact-start-uncertain",
        "observed child start forbids no-start cleanup",
    )
    private = root / _EXACT_PRIVATE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
    failed: list[str] = []
    for name in ("input-request.json", "prompt-input.json", "effective-config.json", "raw-inventory.json"):
        path = private / name
        try:
            if path.exists() or path.is_symlink():
                _read_private(path, root=root)
            path.unlink(missing_ok=True)
        except (OSError, LifecycleError):
            failed.append(_sha(os.fsencode(str(path))))
    snapshot = root / _RUNTIME_REL / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "codex-home"
    try:
        _remove_snapshot_no_start(snapshot, root=root)
    except (OSError, LifecycleError):
        failed.append(_sha(os.fsencode(str(snapshot))))
    if staging_source is not None:
        try:
            cleanup_no_start(root, None, staging_source)
        except LifecycleError:
            failed.append(_sha(os.fsencode(str(Path(staging_source).absolute()))))
    marker = evidence / "raw-cleanup-pending.json"
    if marker.exists():
        raw = _read_private(marker, root=root)
        try:
            previous = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError) as exc:
            raise LifecycleError("codex-exact-private-cleanup-pending", "raw cleanup marker is corrupt") from exc
    else:
        previous = {}
    _require(
        previous.get("status") in {None, "PENDING", "PRIVATE_CLEANUP_PENDING", "DONE"},
        "codex-exact-private-cleanup-pending",
        "raw cleanup marker state is invalid",
    )
    record = {
        **previous,
        "schemaVersion": "alk-r68b-raw-cleanup-pending.v1",
        "status": "PRIVATE_CLEANUP_PENDING" if failed else "DONE",
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "failedRawPathSha256": sorted(set(failed)),
    }
    if operation_id is not None:
        record["operationId"] = operation_id
    temporary = marker.with_name(marker.name + ".tmp")
    _write_exclusive(temporary, canonical_bytes(record), root=root)
    temporary.replace(marker)
    if failed:
        raise LifecycleError(
            "codex-exact-private-cleanup-pending", "raw cleanup failed; durable privacy blocker retained"
        )


def _reserve(path: Path, *, root: Path) -> None:
    _write_exclusive(path, b"", root=root)


def _replace_reserved(path: Path, record: dict[str, Any], *, root: Path) -> None:
    _require(
        path.exists() and path.stat().st_size == 0, "codex-exact-receipt-reservation-lost", "reserved receipt changed"
    )
    temporary = path.with_name(path.name + ".tmp")
    _write_exclusive(temporary, canonical_bytes(record), root=root)
    temporary.replace(path)


def _verify_exact_inputs_before_start(captured: _ExactPrelaunch) -> None:
    executable = captured.executable.executable
    executable_identity = captured.executable.executable_identity
    intent_path = captured.raw.intent_path
    plan_digest = captured.authority.plan_digest
    request = captured.authority.request
    root = captured.attempt.root
    selected_env = captured.executable.selected_env
    state = captured.authority.state
    task_id = captured.attempt.task_id
    _recheck_active_workflow_state(
        root, captured.authority.state_path, state, captured.attempt.run_id, task_id, captured.attempt.attempt
    )
    _require(
        _selected_binary_path(executable, executable_identity, selected_env) == captured.executable.selected_binary,
        "codex-exact-binary-mismatch",
        "selected binary path changed",
    )
    _require_current_manifest(root, captured.authority.manifest_path, captured.authority.manifest, plan_digest)
    _require(
        _sha(Path(_validated_cast(Path, captured.authority.lock_path)).read_bytes()) == captured.authority.lock_digest,
        "codex-exact-plan-stale",
        "lock changed before start",
    )
    _recheck_alk_fit_sources(
        root,
        request,
        captured.fit.packet_rel,
        request["packetSha256"],
        captured.fit.contract_sha,
        captured.fit.profile_sha,
        plan_digest,
        task_id,
        captured.fit.selection,
        captured.fit.summary,
        captured.fit.binding,
        captured.fit.fit["receiptDigest"],
    )
    _require_fresh_catalog(
        root, executable, executable_identity, captured.host.model, selected_env, captured.host.catalog
    )
    _require(
        _snapshot_digest(Path(captured.host.codex_home), root=root) == captured.host.snapshot_digest,
        "codex-exact-config-mismatch",
        "private CODEX_HOME changed before start",
    )
    _require(
        verify_prestart_raw_inventory(
            root,
            inventory_path=captured.raw.inventory_path,
            pending_path=captured.raw.pending_path,
            state=state,
            plan_digest=plan_digest,
        )
        == captured.raw.inventory_sha,
        "codex-exact-raw-inventory-stale",
        "sealed raw inventory changed",
    )
    _require(
        _read_private(intent_path, root=root) == canonical_bytes(captured.raw.intent)
        and captured.raw.start_path.stat().st_size == 0
        and (captured.raw.input_path.stat().st_size == 0),
        "codex-exact-receipt-reservation-lost",
        "prelaunch intent or receipt reservation changed",
    )
    verify_attempt_reservation(root, intent_path=intent_path)
    _require(
        _sha(_read_private(captured.raw.evidence / "config-snapshot-manifest.json", root=root))
        == captured.host.config_manifest_sha,
        "codex-exact-config-mismatch",
        "ALK config-source manifest changed",
    )


def _record_exact_inputs_started(captured: _ExactPrelaunch, event: dict[str, Any]) -> None:
    codex_home = captured.host.codex_home
    config_manifest_sha = captured.host.config_manifest_sha
    intent = captured.raw.intent
    root = captured.attempt.root
    _require(
        verify_prestart_raw_inventory(
            root,
            inventory_path=captured.raw.inventory_path,
            pending_path=captured.raw.pending_path,
            state=captured.authority.state,
            plan_digest=captured.authority.plan_digest,
            started=True,
        )
        == captured.raw.inventory_sha,
        "codex-exact-raw-inventory-stale",
        "sealed raw inventory changed after spawn",
    )
    _require(
        _read_private(captured.raw.intent_path, root=root) == canonical_bytes(intent)
        and _sha(_read_private(captured.raw.evidence / "config-snapshot-manifest.json", root=root))
        == config_manifest_sha,
        "codex-exact-start-mismatch",
        "sealed intent or config manifest changed",
    )
    _require(
        event["commandIdentityHash"] == intent["commandIdentityHash"]
        and event.get("argv") == captured.executable.argv
        and (event.get("cwd") == str(root))
        and (
            event.get("environmentSha256")
            == canonical_digest({**captured.executable.selected_env, "CODEX_HOME": codex_home})
        )
        and (event["plannedStdinSha256"] == captured.prompt.final_sha)
        and (event["plannedStdinBytes"] == len(captured.prompt.final_raw))
        and (event["codexHome"] == codex_home),
        "codex-exact-start-mismatch",
        "observed child differs from prelaunch intent",
    )
    body = {
        **intent,
        "schemaVersion": "alk-codex-process-start.v1",
        "hostLaunchStarted": True,
        "observedPid": event["pid"],
        "processIdentityHash": event["processIdentityHash"],
        "groupIdentityHash": event["groupIdentityHash"],
        "observedArgv": event["argv"],
        "observedCwd": event["cwd"],
        "observedCodexHome": event["codexHome"],
        "observedEnvironmentSha256": event["environmentSha256"],
        "observedConfigSourceSha256": config_manifest_sha,
        "prelaunchCodexHomeContentDigest": captured.host.snapshot_digest,
        "observedCodexHomeContentDigest": "UNPROVEN",
        "postStartSnapshotScope": "PRESTART_PINNED_FILES_ONLY",
        "childInternalEffectiveConfig": "UNPROVEN",
        "stdinStatus": "PENDING",
    }
    _replace_reserved(captured.raw.start_path, body, root=root)


def _record_exact_inputs_delivered(captured: _ExactPrelaunch, event: dict[str, Any]) -> None:
    attempt_id = captured.attempt.attempt_id
    final_sha = captured.prompt.final_sha
    operation_id = captured.attempt.operation_id
    request = captured.authority.request
    root = captured.attempt.root
    run_id = captured.attempt.run_id
    task_id = captured.attempt.task_id
    body = {
        "schemaVersion": "alk-codex-process-input.v1",
        **_exact_wire_identity(run_id, task_id, attempt_id, request.get("role"), final_sha),
        "operationId": operation_id,
        "planDigest": captured.authority.plan_digest,
        "packetSha256": request["packetSha256"],
        **event,
    }
    _replace_reserved(captured.raw.input_path, body, root=root)
    _record_transport_witness(
        root,
        captured.raw.evidence,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        role=str(request.get("role")),
        final_sha=final_sha,
        config_manifest_sha=captured.host.config_manifest_sha,
        diagnostic=captured.host.diagnostic,
        event=event,
        operation_id=operation_id,
    )
    _require(
        event["status"] == "COMPLETE"
        and event["acceptedBytes"] == len(captured.prompt.final_raw)
        and (event["acceptedSha256"] == final_sha)
        and (event["closeSucceeded"] is True),
        "codex-exact-input-incomplete",
        "OS pipe did not accept complete final prompt",
    )


def _finish_exact_prelaunch(
    *,
    root,
    run_id,
    task_id,
    attempt_id,
    operation_id,
    source_revision,
    request,
    manifest,
    manifest_path,
    lock_path,
    plan_digest,
    lock_digest,
    final_raw,
    final_sha,
    executable,
    executable_identity,
    selected_binary,
    selected_env,
    model,
    codex_home,
    snapshot_digest,
    catalog,
    diagnostic,
    config_manifest_sha,
    contract_sha,
    profile_sha,
    fit,
    packet_rel,
    selection,
    summary,
    binding,
    state,
    state_path,
    attempt,
    evidence,
    start_path,
    input_path,
    inventory_path,
    pending_path,
    inventory_sha,
    reserved,
    sealed,
    argv,
):
    intent = {
        "schemaVersion": "alk-codex-prelaunch-intent.v1",
        "runId": run_id,
        "taskId": task_id,
        "attemptId": attempt_id,
        "role": request.get("role"),
        "operationId": operation_id,
        "lockDigest": lock_digest,
        "sourceRevision": source_revision,
        "requestSha256": _sha(canonical_bytes(request)),
        **capture_attempt_authority(root, lock_path=Path(lock_path), manifest_path=manifest_path),
        "routeId": ROUTE_ID,
        "requestedClaim": CLAIM,
        "planDigest": plan_digest,
        "packetSha256": request["packetSha256"],
        "finalPromptSha256": final_sha,
        "plannedStdinBytes": len(final_raw),
        "commandIdentityHash": command_identity_hash(argv),
        "binarySha256": executable_identity["executableContentSha256"],
        "catalogObservation": catalog,
        "diagnosticObservation": diagnostic,
        "configManifestSha256": config_manifest_sha,
        "codexHomePathSha256": _sha(os.fsencode(codex_home)),
        "codexHomeContentDigest": snapshot_digest,
        "rawInventorySha256": inventory_sha,
        "rawCleanupPendingPath": str(pending_path.relative_to(root)),
        "startReceiptPath": str(start_path.relative_to(root)),
        "inputReceiptPath": str(input_path.relative_to(root)),
        "hostLaunchStarted": False,
    }
    intent_path = evidence / "prelaunch-intent.json"
    _write_exclusive(intent_path, canonical_bytes(intent), root=root)
    reserved.append(intent_path)
    reserve_attempt_result(root, intent_path=intent_path)
    reserved.append(evidence / "attempt-result-reservation.json")

    captured = _ExactPrelaunch(
        _ExactAttempt(root, run_id, task_id, attempt_id, operation_id, attempt),
        _ExactAuthority(manifest, manifest_path, lock_path, plan_digest, lock_digest, state, state_path, request),
        _ExactFit(packet_rel, contract_sha, profile_sha, selection, summary, binding, fit),
        _ExactPrompt(final_raw, final_sha),
        _ExactProcess(executable, executable_identity, selected_binary, selected_env, argv),
        _ExactHost(model, codex_home, snapshot_digest, catalog, diagnostic, config_manifest_sha),
        _ExactRaw(evidence, start_path, input_path, inventory_path, pending_path, inventory_sha, intent_path, intent),
    )

    def verify_before_start() -> None:
        _verify_exact_inputs_before_start(captured)

    def on_started(event: dict[str, Any]) -> None:
        _record_exact_inputs_started(captured, event)

    def on_input(event: dict[str, Any]) -> None:
        _record_exact_inputs_delivered(captured, event)

    return _exact_prepared_result(
        captured,
        sealed,
        final_raw.decode("utf-8"),
        _sha(canonical_bytes(request)),
        on_started,
        on_input,
        verify_before_start,
    )


def _prepare_exact_fit_inputs(
    root: Path, request: dict[str, Any], plan_digest: str, task_id: str
) -> tuple[_ExactFit, _ExactPrompt]:
    packet_rel = request.get("packetPath")
    _require(
        isinstance(packet_rel, str)
        and packet_rel.startswith("work/release-2-16/")
        and (".." not in Path(packet_rel).parts),
        "codex-exact-packet-path-invalid",
        "packet path is outside release work",
    )
    packet_rel = _validated_cast(str, packet_rel)
    packet_raw = read_authority_bytes(root / packet_rel, root=root, max_bytes=65536)
    _require(_sha(packet_raw) == request.get("packetSha256"), "codex-exact-packet-stale", "packet bytes changed")
    packet = json.loads(packet_raw)
    _require(
        packet.get("plan", {}).get("planDigest") == plan_digest and packet.get("task", {}).get("id") == task_id,
        "codex-exact-packet-binding-mismatch",
        "packet lineage differs",
    )
    selection = request.get("selection")
    summary = request.get("summary")
    _require(
        isinstance(selection, dict) and isinstance(summary, dict),
        "codex-exact-fit-input-missing",
        "source selection or summary is missing",
    )
    selection = _validated_cast(dict[str, Any], selection)
    summary = _validated_cast(dict[str, Any], summary)
    contract_raw = read_authority_bytes(
        root / "tasks/release-2-16/alk-input-fit-contract.json", root=root, max_bytes=1048576
    )
    profile_raw = read_authority_bytes(root / "profiles/small-context-profile.v1.json", root=root, max_bytes=65536)
    contract = json.loads(contract_raw)
    profile = json.loads(profile_raw)
    _require(
        contract.get("commonEnvelope", {}).get("reservedOutputEstimatedTokens") == 3072,
        "codex-exact-output-reserve-mismatch",
        "planned output reserve is not 3072 tokens",
    )
    contract_sha, profile_sha = (_sha(contract_raw), _sha(profile_raw))
    binding = {
        key: selection.get(key)
        for key in ("runId", "taskId", "attemptId", "planDigest", "manifestSha256", "candidateDigest", "estimatorId")
    }
    fit = assess_local_input_fit(
        root,
        contract,
        profile,
        packet,
        summary,
        selection,
        role=str(request.get("role")),
        host_adapter_id="codex",
        host_version=str(request.get("hostVersion", "")),
        host_mode=str(request.get("hostMode", "")),
        estimator_id=str(request.get("estimatorId", "")),
        instruction=request.get("instruction"),
        schema=request.get("schema"),
        current_binding=binding,
        latest_user=str(request.get("latestUser", "")),
        window="16k",
    )
    _require(
        fit["status"] == "PASS_ALK_COMPONENTS_ONLY" and all(check["status"] == "PASS" for check in fit["checks"]),
        "codex-exact-fit-refused",
        "ALK-controlled input exceeds a limit",
    )
    rendered = render_context(profile, packet, summary, latest_user=str(request.get("latestUser", "")), window="16k")
    model_input = {
        "renderedEnvelope": rendered["envelope"],
        "selectedSource": selection["selected"],
        "instruction": request["instruction"],
        "schema": request["schema"],
    }
    final_raw = canonical_bytes(model_input)
    final_sha = _sha(final_raw)
    _require(
        request.get("selectedSource") == selection["selected"]
        and fit["inputComponentDigests"]["fullAlkModelInput"] == final_sha,
        "codex-exact-final-prompt-mismatch",
        "final prompt differs from fit receipt",
    )
    return _ExactFit(packet_rel, contract_sha, profile_sha, selection, summary, binding, fit), _ExactPrompt(
        final_raw, final_sha
    )


def _complete_exact_prompt_preparation(
    *,
    attempt_inputs: _ExactAttempt,
    request: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path | None,
    lock_path: Path,
    plan_digest: str,
    lock_digest: str,
    source_revision: str,
    executable: str,
    executable_identity: dict[str, Any],
    process_env: dict[str, str] | None,
    state: dict[str, Any],
    state_path: Path | None,
    sealed: Path,
    reserved: list[Path],
    fit_inputs: _ExactFit,
    prompt_inputs: _ExactPrompt,
) -> dict[str, Any]:
    _require(
        Path(executable).name == "codex" and executable_identity.get("status") == "PASS",
        "codex-exact-binary-unavailable",
        "selected Codex binary is unavailable",
    )
    selected_env = dict(os.environ) if process_env is None else process_env
    model, codex_home, snapshot_digest, catalog, diagnostic, config_manifest_sha = _selected_host_evidence(
        attempt_inputs.root,
        request,
        executable_identity,
        prompt_inputs.final_sha,
        attempt_inputs.run_id,
        attempt_inputs.task_id,
        attempt_inputs.attempt_id,
        executable,
        selected_env,
        str(request.get("role", "")),
        operation_id=attempt_inputs.operation_id,
    )
    inventory_path, pending_path, inventory_sha = create_prestart_raw_inventory(
        attempt_inputs.root,
        run_id=attempt_inputs.run_id,
        task_id=attempt_inputs.task_id,
        attempt_id=attempt_inputs.attempt_id,
        sealed_request=sealed,
        state=state,
        plan_digest=plan_digest,
        operation_id=attempt_inputs.operation_id,
    )
    selected_binary = _selected_binary_path(executable, executable_identity, selected_env)
    argv = [str(selected_binary), "exec", "--json", "--ephemeral", "-m", model, "-C", str(attempt_inputs.root), "-"]
    evidence = (
        attempt_inputs.root
        / _EXACT_EVIDENCE_RELATIVE
        / _invocation_namespace(
            attempt_inputs.run_id, attempt_inputs.task_id, attempt_inputs.attempt_id, attempt_inputs.operation_id
        )
    )
    start_path = evidence / "process-start.json"
    input_path = evidence / "process-input.json"
    _reserve(start_path, root=attempt_inputs.root)
    reserved.append(start_path)
    _reserve(input_path, root=attempt_inputs.root)
    reserved.append(input_path)
    authority = _ExactAuthority(
        manifest, manifest_path, lock_path, plan_digest, lock_digest, state, state_path, request
    )
    process_inputs = _ExactProcess(executable, executable_identity, selected_binary, selected_env, argv)
    host_inputs = _ExactHost(model, codex_home, snapshot_digest, catalog, diagnostic, config_manifest_sha)
    return _finish_exact_prelaunch(
        **_exact_keyword_values(attempt_inputs),
        **_exact_keyword_values(authority),
        **_exact_keyword_values(fit_inputs),
        **_exact_keyword_values(prompt_inputs),
        **_exact_keyword_values(process_inputs),
        **_exact_keyword_values(host_inputs),
        source_revision=source_revision,
        evidence=evidence,
        start_path=start_path,
        input_path=input_path,
        inventory_path=inventory_path,
        pending_path=pending_path,
        inventory_sha=inventory_sha,
        reserved=reserved,
        sealed=sealed,
    )


def prepare_exact_prompt(
    *,
    project_root: Path,
    input_request: Path | None,
    route_id: str | None,
    requested_claim: str | None,
    state: dict[str, Any],
    task: dict[str, Any],
    manifest: dict[str, Any],
    lock_path: Path,
    source_revision: str,
    operation_id: str,
    executable_identity: dict[str, Any],
    executable: str,
    process_env: dict[str, str] | None = None,
    state_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Seal and check one task-bound ALK request before any child is started."""
    root = Path(project_root).absolute()
    _require(
        route_id == ROUTE_ID and requested_claim == CLAIM and (input_request is not None),
        "codex-exact-route-required",
        "explicit supported route, claim and private request are required",
    )
    run_id = _part(state.get("runId"), "runId")
    task_id = _part(task.get("id"), "taskId")
    attempt = task.get("attempt")
    _require(
        type(attempt) is int and attempt > 0 and (task.get("status") == "RUNNING"),
        "codex-exact-attempt-unverified",
        "active task attempt is not verified",
    )
    attempt = _validated_cast(int, attempt)
    attempt_id = _part(str(attempt), "attemptId")
    _require(
        state.get("sourceRevision") == source_revision,
        "codex-exact-source-revision-mismatch",
        "source revision changed",
    )
    sealed: Path | None = None
    reserved: list[Path] = []
    try:
        _require(
            isinstance(operation_id, str) and bool(operation_id),
            "codex-exact-request-binding-mismatch",
            "operation identity is missing",
        )
        operation_id = _validated_cast(str, operation_id)
        reconcile_prelaunch_intents(root, active_staging_request=Path(_validated_cast(Path, input_request)))
        _assert_no_cleanup_blockers(root)
        legacy = (
            root
            / _EXACT_EVIDENCE_RELATIVE
            / _invocation_namespace(run_id, task_id, attempt_id)
            / "prelaunch-intent.json"
        )
        if legacy.exists() or legacy.is_symlink():
            previous = json.loads(_read_private(legacy, root=root))
            _require(
                previous.get("operationId") != operation_id,
                "codex-exact-attempt-reused",
                "legacy operation cannot be rekeyed into the new namespace",
            )
        attempt_evidence = (
            root / _EXACT_EVIDENCE_RELATIVE / _invocation_namespace(run_id, task_id, attempt_id, operation_id)
        )
        _require(
            not (attempt_evidence / "prelaunch-intent.json").exists(),
            "codex-exact-attempt-reused",
            "this model operation already has a prelaunch intent",
        )
        sealed, request = _seal_request(
            root, Path(_validated_cast(Path, input_request)), run_id, task_id, attempt_id, operation_id=operation_id
        )
        plan_digest = canonical_digest(manifest)
        lock_digest = _sha(Path(_validated_cast(Path, lock_path)).read_bytes())
        for key, expected in (
            ("routeId", ROUTE_ID),
            ("requestedClaim", CLAIM),
            ("runId", run_id),
            ("taskId", task_id),
            ("attemptId", attempt_id),
            ("planDigest", plan_digest),
            ("lockDigest", lock_digest),
            ("sourceRevision", source_revision),
            ("operationId", operation_id),
        ):
            _require(
                request.get(key) == expected,
                "codex-exact-request-binding-mismatch",
                f"{key} differs from the active attempt",
            )
        fit_inputs, prompt_inputs = _prepare_exact_fit_inputs(root, request, plan_digest, task_id)
        authority_inputs = _ExactAuthority(
            manifest, manifest_path, lock_path, plan_digest, lock_digest, state, state_path, request
        )
        return _complete_exact_prompt_preparation(
            **_exact_keyword_values(authority_inputs),
            attempt_inputs=_ExactAttempt(root, run_id, task_id, attempt_id, operation_id, attempt),
            source_revision=source_revision,
            executable=executable,
            executable_identity=executable_identity,
            process_env=process_env,
            sealed=sealed,
            reserved=reserved,
            fit_inputs=fit_inputs,
            prompt_inputs=prompt_inputs,
        )
    except Exception:
        if sealed is None:
            cleanup_no_start(root, None, Path(_validated_cast(Path, input_request)))
        else:
            for path in reserved:
                path.unlink(missing_ok=True)
            cleanup_prestart_raw(
                root,
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                staging_source=Path(_validated_cast(Path, input_request)),
                proven_no_start=True,
                operation_id=operation_id,
            )
        raise
