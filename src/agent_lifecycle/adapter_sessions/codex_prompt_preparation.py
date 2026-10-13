"""Owned codex prompt preparation helpers."""
from __future__ import annotations
from typing import Any
from agent_lifecycle.contracts import LifecycleError
from pathlib import Path
from agent_lifecycle.adapter_sessions.input_lifecycle import _assert_no_cleanup_blockers
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _observed_bundled_catalog
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _observed_prompt_diagnostic
from agent_lifecycle.adapter_sessions.input_lifecycle import _part
from agent_lifecycle.adapter_sessions.private_input import _read_private
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _recheck_active_workflow_state
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _recheck_alk_fit_sources
from agent_lifecycle.adapter_sessions.input_lifecycle import _remove_snapshot_no_start
from agent_lifecycle.adapter_sessions.private_input import _require
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _require_current_manifest
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _require_fresh_catalog
from agent_lifecycle.adapter_sessions.input_lifecycle import _seal_request
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _selected_binary_path
from agent_lifecycle.adapter_sessions.input_lifecycle import _sha
from agent_lifecycle.adapter_sessions.input_lifecycle import _snapshot_digest
from agent_lifecycle.adapter_sessions.input_lifecycle import _snapshot_raw_sources
from agent_lifecycle.adapter_sessions.private_input import _verify_private_ancestors
from agent_lifecycle.adapter_sessions.private_input import _write_exclusive
from agent_lifecycle.accounting.input_fit import assess_local_input_fit
from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.adapter_sessions.attempt_authority import capture_attempt_authority
from agent_lifecycle.adapter_sessions.input_lifecycle import cleanup_no_start
from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash
import json
import os
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.adapter_sessions.input_lifecycle import reconcile_prelaunch_intents
from agent_lifecycle.context import render_context
from agent_lifecycle.adapter_sessions.attempt_authority import reserve_attempt_result
import stat
from agent_lifecycle.adapter_sessions.attempt_authority import verify_attempt_reservation


ROUTE_ID = "codex-exact-prompt-v1"

CLAIM = "ALK_CONTROLLED_OUTBOUND_INPUT_FIT"

def _selected_host_evidence(root: Path, request: dict[str, Any], identity: dict[str, Any],
                            final_sha: str, run_id: str, task_id: str, attempt_id: str,
                            executable: str, process_env: dict[str, str],
                            role: str) -> tuple[str, str, str, dict[str, Any], dict[str, Any], str]:
    """Create ALK prelaunch sources without claiming child internal equivalence."""
    base = root / "work/release-2-16/evidence/codex-exact-prompt" / run_id / task_id / attempt_id
    private = root / "work/release-2-16/private-details/codex-exact-prompt" / run_id / task_id / attempt_id
    selected = request.get("selectedHost")
    _require(isinstance(selected, dict), "codex-exact-host-proof-missing", "selected host proof is missing")
    model = selected.get("model")
    _require(isinstance(model, str) and bool(model) and len(model) <= 128,
             "codex-exact-model-invalid", "selected model is invalid")
    _require(selected.get("binarySha256") == identity.get("executableContentSha256"),
             "codex-exact-binary-mismatch", "selected binary changed")
    catalog = _observed_bundled_catalog(root, executable, identity, model, process_env)
    if "catalogWindowTokens" in selected:
        _require(selected["catalogWindowTokens"] == catalog["catalogWindowTokens"],
                 "codex-exact-window-mismatch", "caller catalog hint differs from selected binary")
    _require(not any(key in selected for key in (
                 "configManifestSha256", "transportWitnessSha256", "diagnosticSha256")),
             "codex-exact-legacy-witness-refused", "caller-authored host PASS witnesses are not accepted")
    snapshot = root / "work/release-2-16/runtime-private/codex-exact-prompt" / run_id / task_id / attempt_id / "codex-home"
    _verify_private_ancestors(snapshot, root=root)
    info = snapshot.lstat()
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
             "codex-exact-config-unsafe", "private CODEX_HOME is not protected")
    snapshot_digest = _snapshot_digest(snapshot, root=root)
    effective_config = private / "effective-config.json"
    source = {"schemaVersion": "alk-codex-alk-config-source.v1",
              "routeId": ROUTE_ID, "requestedClaim": CLAIM,
              "runId": run_id, "taskId": task_id, "attemptId": attempt_id,
              "role": role, "model": model, "finalPromptSha256": final_sha,
              "binarySha256": identity["executableContentSha256"],
              "selectedBinaryVersion": catalog["version"],
              "catalogSha256": catalog["catalogSha256"],
              "cwdPathSha256": _sha(os.fsencode(str(root))),
              "codexHomePathSha256": _sha(os.fsencode(str(snapshot))),
              "codexHomeContentDigest": snapshot_digest,
              "childInternalEffectiveConfig": "UNPROVEN"}
    _write_exclusive(effective_config, canonical_bytes(source), root=root)
    diagnostic = _observed_prompt_diagnostic(
        root, executable, identity, snapshot=snapshot, model=model, role=role,
        run_id=run_id, task_id=task_id, attempt_id=attempt_id,
        final_sha=final_sha, process_env=process_env)
    config_source = _raw_source_record(root, effective_config, "alk-config-source")
    manifest = {"schemaVersion": "alk-codex-config-source-manifest.v1",
                "status": "OBSERVED_ALK_SOURCE", "routeId": ROUTE_ID,
                "requestedClaim": CLAIM, "runId": run_id, "taskId": task_id,
                "attemptId": attempt_id, "role": role, "model": model,
                "finalPromptSha256": final_sha,
                "binarySha256": identity["executableContentSha256"],
                "selectedBinaryVersion": catalog["version"],
                "catalogObservation": catalog,
                "configSource": config_source,
                "diagnosticRawSha256": diagnostic["rawSha256"],
                "diagnosticItemCount": diagnostic["itemCount"],
                "childInternalEffectiveConfig": "UNPROVEN"}
    config_manifest = base / "config-snapshot-manifest.json"
    manifest_raw = canonical_bytes(manifest)
    _write_exclusive(config_manifest, manifest_raw, root=root)
    return model, str(snapshot), snapshot_digest, catalog, diagnostic, _sha(manifest_raw)

def _raw_source_record(root: Path, path: Path, kind: str) -> dict[str, Any]:
    raw = _read_private(path, root=root)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
             and info.st_size == len(raw),
             "codex-exact-raw-inventory-invalid", "raw source changed during inventory")
    return {"kind": kind, "path": str(path.relative_to(root)),
            "pathSha256": _sha(os.fsencode(str(path))),
            "fileIdentity": {"device": info.st_dev, "inode": info.st_ino},
            "sha256": _sha(raw), "bytes": len(raw)}

def _record_transport_witness(
    root: Path, evidence: Path, *, run_id: str, task_id: str,
    attempt_id: str, role: str, final_sha: str,
    config_manifest_sha: str, diagnostic: dict[str, Any],
    event: dict[str, Any],
) -> None:
    """Join actual start and OS-pipe receipts without asserting consumption."""
    try:
        start_raw = _read_private(evidence / "process-start.json", root=root)
        input_raw = _read_private(evidence / "process-input.json", root=root)
    except OSError as exc:
        raise LifecycleError("codex-exact-process-join-invalid",
                             "observed process receipt is missing") from exc
    try:
        start = json.loads(start_raw)
        observed_input = json.loads(input_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-process-join-invalid",
                             "observed process receipt is malformed") from exc
    _require(start.get("schemaVersion") == "alk-codex-process-start.v1"
             and start.get("hostLaunchStarted") is True
             and start.get("stdinStatus") == "PENDING"
             and observed_input.get("schemaVersion") == "alk-codex-process-input.v1"
             and all(start.get(key) == value and observed_input.get(key) == value
                     for key, value in (("runId", run_id), ("taskId", task_id),
                                        ("attemptId", attempt_id), ("role", role)))
             and start.get("finalPromptSha256") == final_sha
             and observed_input.get("finalPromptSha256") == final_sha
             and all(observed_input.get(key) == value for key, value in event.items()),
             "codex-exact-process-join-invalid", "start/input receipt subject differs")
    transport = {"schemaVersion": "alk-codex-os-pipe-transport.v1",
                 "status": ("OS_PIPE_ACCEPTED" if event["status"] == "COMPLETE"
                            else "STARTED_INPUT_FAILURE"),
                 "runId": run_id, "taskId": task_id,
                 "attemptId": attempt_id, "role": role,
                 "routeId": ROUTE_ID, "requestedClaim": CLAIM,
                 "finalPromptSha256": final_sha,
                 "configManifestSha256": config_manifest_sha,
                 "diagnosticRawSha256": diagnostic["rawSha256"],
                 "diagnosticItemDigests": diagnostic["items"],
                 "processStartSha256": _sha(start_raw),
                 "processInputSha256": _sha(input_raw),
                 "observedPipe": event,
                 "childConsumption": "UNPROVEN",
                 "execStdinDiagnosticEquivalence": "UNPROVEN"}
    _write_exclusive(evidence / "transport-equivalence.json",
                     canonical_bytes(transport), root=root)

def _workflow_journal_identity(root: Path, state: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Pin the PRE workflow event-log file identity, not a financial Journal grant."""
    event_log = state.get("eventLog")
    _require(state.get("runId") == run_id and isinstance(event_log, str)
             and bool(event_log) and not Path(event_log).is_absolute()
             and ".." not in Path(event_log).parts and bool(Path(event_log).parts),
             "codex-exact-journal-unavailable", "workflow event-log binding is missing")
    try:
        root_info = root.lstat()
        _require(stat.S_ISDIR(root_info.st_mode), "codex-exact-journal-unavailable",
                 "workflow root is not a directory")
        relative = Path(event_log)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            _require(stat.S_ISDIR(current.lstat().st_mode),
                     "codex-exact-journal-unavailable", "workflow event-log parent is unsafe")
        journal_info = (root / relative).lstat()
        _require(stat.S_ISREG(journal_info.st_mode), "codex-exact-journal-unavailable",
                 "workflow event log is not a regular file")
    except OSError as exc:
        raise LifecycleError("codex-exact-journal-unavailable",
                             "workflow event log cannot be inspected") from exc
    subject = {"kind": "WORKFLOW_EVENT_LOG_PRE_WS01", "runId": run_id,
               "rootPathSha256": _sha(os.fsencode(str(root))),
               "rootFileIdentity": {"device": root_info.st_dev, "inode": root_info.st_ino},
               "eventLog": relative.as_posix(),
               "eventLogFileIdentity": {"device": journal_info.st_dev, "inode": journal_info.st_ino}}
    return {**subject, "journalIdentity": canonical_digest(subject)}

def create_prestart_raw_inventory(
    project_root: Path, *, run_id: str, task_id: str, attempt_id: str,
    sealed_request: Path, state: dict[str, Any], plan_digest: str,
) -> tuple[Path, Path, str]:
    """Seal all known raw and the whole child snapshot cleanup obligation before Popen."""
    root = Path(project_root).absolute()
    run_id, task_id, attempt_id = (_part(value, "rawInventoryIdentity")
                                   for value in (run_id, task_id, attempt_id))
    journal = _workflow_journal_identity(root, state, run_id)
    private = root / "work/release-2-16/private-details/codex-exact-prompt" / run_id / task_id / attempt_id
    expected_request = private / "input-request.json"
    _require(Path(sealed_request).absolute() == expected_request,
             "codex-exact-raw-inventory-invalid", "sealed request identity differs")
    sources = [
        _raw_source_record(root, expected_request, "sealed-request"),
        _raw_source_record(root, private / "prompt-input.json", "diagnostic"),
        _raw_source_record(root, private / "effective-config.json", "effective-config"),
        *_snapshot_raw_sources(
            root, (root / "work/release-2-16/runtime-private/codex-exact-prompt"
                   / run_id / task_id / attempt_id / "codex-home")),
    ]
    inventory = {"schemaVersion": "alk-r68b-raw-inventory.v1", "runId": run_id,
                 "taskId": task_id, "attemptId": attempt_id, "planDigest": plan_digest,
                 "journalAuthorityKind": journal["kind"],
                 "journalIdentity": journal["journalIdentity"],
                 "eventLog": journal["eventLog"],
                 "eventLogFileIdentity": journal["eventLogFileIdentity"],
                 "rootPathSha256": journal["rootPathSha256"],
                 "rootFileIdentity": journal["rootFileIdentity"],
                 "workflowStateDigest": canonical_digest(state), "sources": sources}
    inventory_path = private / "raw-inventory.json"
    pending_path = (root / "work/release-2-16/evidence/codex-exact-prompt"
                    / run_id / task_id / attempt_id / "raw-cleanup-pending.json")
    _reserve(pending_path, root=root)
    _write_exclusive(inventory_path, canonical_bytes(inventory), root=root)
    inventory_sha = _sha(inventory_path.read_bytes())
    pending = {"schemaVersion": "alk-r68b-raw-cleanup-pending.v1", "status": "PENDING",
               "runId": run_id, "taskId": task_id, "attemptId": attempt_id,
               "journalIdentity": journal["journalIdentity"],
               "journalAuthorityKind": journal["kind"],
               "rootPathSha256": inventory["rootPathSha256"],
               "inventorySha256": inventory_sha}
    _replace_reserved(pending_path, pending, root=root)
    return inventory_path, pending_path, inventory_sha

def verify_prestart_raw_inventory(
    project_root: Path, *, inventory_path: Path, pending_path: Path,
    state: dict[str, Any], plan_digest: str, started: bool = False,
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
    _require(isinstance(inventory, dict) and isinstance(pending, dict)
             and inventory.get("schemaVersion") == "alk-r68b-raw-inventory.v1"
             and pending.get("schemaVersion") == "alk-r68b-raw-cleanup-pending.v1"
             and pending.get("status") == "PENDING"
             and inventory.get("planDigest") == plan_digest
             and inventory.get("workflowStateDigest") == canonical_digest(state),
             "codex-exact-raw-inventory-stale", "raw inventory subject changed")
    run_id = _part(inventory.get("runId"), "rawInventoryRunId")
    task_id = _part(inventory.get("taskId"), "rawInventoryTaskId")
    attempt_id = _part(inventory.get("attemptId"), "rawInventoryAttemptId")
    private = (root / "work/release-2-16/private-details/codex-exact-prompt"
               / run_id / task_id / attempt_id)
    evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                / run_id / task_id / attempt_id)
    _require(Path(inventory_path).absolute() == private / "raw-inventory.json"
             and Path(pending_path).absolute() == evidence / "raw-cleanup-pending.json",
             "codex-exact-raw-inventory-stale", "raw inventory paths changed")
    journal = _workflow_journal_identity(root, state, run_id)
    _require(inventory.get("journalAuthorityKind") == journal["kind"]
             and inventory.get("journalIdentity") == journal["journalIdentity"]
             and inventory.get("eventLogFileIdentity") == journal["eventLogFileIdentity"]
             and inventory.get("rootFileIdentity") == journal["rootFileIdentity"]
             and inventory.get("rootPathSha256") == journal["rootPathSha256"],
             "codex-exact-raw-inventory-stale", "workflow journal/root identity changed")
    expected = [
        _raw_source_record(root, private / "input-request.json", "sealed-request"),
        _raw_source_record(root, private / "prompt-input.json", "diagnostic"),
        _raw_source_record(root, private / "effective-config.json", "effective-config"),
    ]
    snapshot = (root / "work/release-2-16/runtime-private/codex-exact-prompt"
                / run_id / task_id / attempt_id / "codex-home")
    if started:
        # The cleanup obligation covers the whole tree, including additions.
        # Its prestart digest is not a post-spawn whole-tree observation.
        _verify_private_ancestors(snapshot, root=root)
        info = snapshot.lstat()
        _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
                 "codex-exact-config-unsafe", "private CODEX_HOME is not protected")
        pinned = inventory.get("sources", [])[3:]
        _require(pinned and pinned[0].get("kind") == "codex-home-snapshot-tree"
                 and pinned[0].get("path") == str(snapshot.relative_to(root))
                 and pinned[0].get("pathSha256") == _sha(os.fsencode(str(snapshot)))
                 and pinned[0].get("fileIdentity") == {"device": info.st_dev, "inode": info.st_ino}
                 and pinned[0].get("cleanupScope") == "WHOLE_TREE_INCLUDING_POST_START_ADDITIONS",
                 "codex-exact-raw-inventory-stale", "snapshot root binding changed")
        expected.append(pinned[0])
        for row in pinned[1:]:
            path = root / str(row.get("path", ""))
            _require(row.get("kind") == "codex-home-snapshot-file"
                     and path.is_relative_to(snapshot) and ".." not in path.parts,
                     "codex-exact-raw-inventory-stale", "snapshot source path changed")
            raw_source = _read_private(path, root=root, allowed_modes=(0o400, 0o600), max_bytes=8_388_608)
            file_info = path.lstat()
            expected.append({"kind": "codex-home-snapshot-file", "path": str(path.relative_to(root)),
                "pathSha256": _sha(os.fsencode(str(path))),
                "fileIdentity": {"device": file_info.st_dev, "inode": file_info.st_ino},
                "sha256": _sha(raw_source), "bytes": len(raw_source), "mode": stat.S_IMODE(file_info.st_mode)})
    else:
        expected.extend(_snapshot_raw_sources(root, snapshot))
    _require(inventory.get("sources") == expected
             and pending.get("inventorySha256") == _sha(raw)
             and pending.get("journalIdentity") == journal["journalIdentity"]
             and all(pending.get(key) == inventory.get(key)
                     for key in ("runId", "taskId", "attemptId", "rootPathSha256")),
             "codex-exact-raw-inventory-stale", "raw source bytes or pending obligation changed")
    return _sha(raw)

def cleanup_prestart_raw(
    project_root: Path, *, run_id: str, task_id: str, attempt_id: str,
    staging_source: Path | None, proven_no_start: bool,
) -> None:
    """Remove attempt raw only after an in-process, proven no-Popen outcome."""
    root = Path(project_root).absolute()
    _require(proven_no_start, "codex-exact-start-uncertain",
             "raw sources cannot be removed after a possible child start")
    run_id, task_id, attempt_id = (_part(value, "rawCleanupIdentity")
                                   for value in (run_id, task_id, attempt_id))
    evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                / run_id / task_id / attempt_id)
    start = evidence / "process-start.json"
    _require(not any((evidence / name).exists() or (evidence / name).is_symlink()
                     for name in ("attempt-result-terminal.json", "attempt-result-terminal.pending.json")),
             "codex-exact-start-uncertain", "terminal or uncertain attempt forbids no-start cleanup")
    _require(not start.exists() or start.stat().st_size == 0,
             "codex-exact-start-uncertain", "observed child start forbids no-start cleanup")
    private = (root / "work/release-2-16/private-details/codex-exact-prompt"
               / run_id / task_id / attempt_id)
    failed: list[str] = []
    for name in ("input-request.json", "prompt-input.json", "effective-config.json", "raw-inventory.json"):
        path = private / name
        try:
            if path.exists() or path.is_symlink():
                _read_private(path, root=root)
            path.unlink(missing_ok=True)
        except (OSError, LifecycleError):
            failed.append(_sha(os.fsencode(str(path))))
    snapshot = (root / "work/release-2-16/runtime-private/codex-exact-prompt"
                / run_id / task_id / attempt_id / "codex-home")
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
            raise LifecycleError("codex-exact-private-cleanup-pending",
                                 "raw cleanup marker is corrupt") from exc
    else:
        previous = {}
    _require(previous.get("status") in {None, "PENDING", "PRIVATE_CLEANUP_PENDING", "DONE"},
             "codex-exact-private-cleanup-pending", "raw cleanup marker state is invalid")
    record = {**previous, "schemaVersion": "alk-r68b-raw-cleanup-pending.v1",
              "status": "PRIVATE_CLEANUP_PENDING" if failed else "DONE",
              "runId": run_id, "taskId": task_id, "attemptId": attempt_id,
              "failedRawPathSha256": sorted(set(failed))}
    temporary = marker.with_name(marker.name + ".tmp")
    _write_exclusive(temporary, canonical_bytes(record), root=root)
    os.replace(temporary, marker)
    if failed:
        raise LifecycleError("codex-exact-private-cleanup-pending",
                             "raw cleanup failed; durable privacy blocker retained")

def _reserve(path: Path, *, root: Path) -> None:
    _write_exclusive(path, b"", root=root)

def _replace_reserved(path: Path, record: dict[str, Any], *, root: Path) -> None:
    _require(path.exists() and path.stat().st_size == 0,
             "codex-exact-receipt-reservation-lost", "reserved receipt changed")
    temporary = path.with_name(path.name + ".tmp")
    _write_exclusive(temporary, canonical_bytes(record), root=root)
    os.replace(temporary, path)

def _finish_exact_prelaunch(*, root, run_id, task_id, attempt_id, operation_id, source_revision, request, manifest, manifest_path, lock_path, plan_digest, lock_digest, final_raw, final_sha, executable, executable_identity, selected_binary, selected_env, model, codex_home, snapshot_digest, catalog, diagnostic, config_manifest_sha, contract_sha, profile_sha, fit, packet_rel, selection, summary, binding, state, state_path, attempt, evidence, start_path, input_path, inventory_path, pending_path, inventory_sha, reserved, sealed, argv):
    intent = {'schemaVersion': 'alk-codex-prelaunch-intent.v1', 'runId': run_id, 'taskId': task_id, 'attemptId': attempt_id, 'role': request.get('role'), 'operationId': operation_id, 'lockDigest': lock_digest, 'sourceRevision': source_revision, 'requestSha256': _sha(canonical_bytes(request)), **capture_attempt_authority(root, lock_path=Path(lock_path), manifest_path=manifest_path), 'routeId': ROUTE_ID, 'requestedClaim': CLAIM, 'planDigest': plan_digest, 'packetSha256': request['packetSha256'], 'finalPromptSha256': final_sha, 'plannedStdinBytes': len(final_raw), 'commandIdentityHash': command_identity_hash(argv), 'binarySha256': executable_identity['executableContentSha256'], 'catalogObservation': catalog, 'diagnosticObservation': diagnostic, 'configManifestSha256': config_manifest_sha, 'codexHomePathSha256': _sha(os.fsencode(codex_home)), 'codexHomeContentDigest': snapshot_digest, 'rawInventorySha256': inventory_sha, 'rawCleanupPendingPath': str(pending_path.relative_to(root)), 'startReceiptPath': str(start_path.relative_to(root)), 'inputReceiptPath': str(input_path.relative_to(root)), 'hostLaunchStarted': False}
    intent_path = evidence / 'prelaunch-intent.json'
    _write_exclusive(intent_path, canonical_bytes(intent), root=root)
    reserved.append(intent_path)
    reserve_attempt_result(root, intent_path=intent_path)
    reserved.append(evidence / 'attempt-result-reservation.json')

    def verify_before_start() -> None:
        _recheck_active_workflow_state(root, state_path, state, run_id, task_id, attempt)
        _require(_selected_binary_path(executable, executable_identity, selected_env) == selected_binary, 'codex-exact-binary-mismatch', 'selected binary path changed')
        _require_current_manifest(root, manifest_path, manifest, plan_digest)
        _require(_sha(Path(lock_path).read_bytes()) == lock_digest, 'codex-exact-plan-stale', 'lock changed before start')
        _recheck_alk_fit_sources(root, request, packet_rel, request['packetSha256'], contract_sha, profile_sha, plan_digest, task_id, selection, summary, binding, fit['receiptDigest'])
        _require_fresh_catalog(root, executable, executable_identity, model, selected_env, catalog)
        _require(_snapshot_digest(Path(codex_home), root=root) == snapshot_digest, 'codex-exact-config-mismatch', 'private CODEX_HOME changed before start')
        _require(verify_prestart_raw_inventory(root, inventory_path=inventory_path, pending_path=pending_path, state=state, plan_digest=plan_digest) == inventory_sha, 'codex-exact-raw-inventory-stale', 'sealed raw inventory changed')
        _require(_read_private(intent_path, root=root) == canonical_bytes(intent) and start_path.stat().st_size == 0 and (input_path.stat().st_size == 0), 'codex-exact-receipt-reservation-lost', 'prelaunch intent or receipt reservation changed')
        verify_attempt_reservation(root, intent_path=intent_path)
        _require(_sha(_read_private(evidence / 'config-snapshot-manifest.json', root=root)) == config_manifest_sha, 'codex-exact-config-mismatch', 'ALK config-source manifest changed')

    def on_started(event: dict[str, Any]) -> None:
        _require(verify_prestart_raw_inventory(root, inventory_path=inventory_path, pending_path=pending_path, state=state, plan_digest=plan_digest, started=True) == inventory_sha, 'codex-exact-raw-inventory-stale', 'sealed raw inventory changed after spawn')
        _require(_read_private(intent_path, root=root) == canonical_bytes(intent) and _sha(_read_private(evidence / 'config-snapshot-manifest.json', root=root)) == config_manifest_sha, 'codex-exact-start-mismatch', 'sealed intent or config manifest changed')
        _require(event['commandIdentityHash'] == intent['commandIdentityHash'] and event.get('argv') == argv and (event.get('cwd') == str(root)) and (event.get('environmentSha256') == canonical_digest({**selected_env, 'CODEX_HOME': codex_home})) and (event['plannedStdinSha256'] == final_sha) and (event['plannedStdinBytes'] == len(final_raw)) and (event['codexHome'] == codex_home), 'codex-exact-start-mismatch', 'observed child differs from prelaunch intent')
        body = {**intent, 'schemaVersion': 'alk-codex-process-start.v1', 'hostLaunchStarted': True, 'observedPid': event['pid'], 'processIdentityHash': event['processIdentityHash'], 'groupIdentityHash': event['groupIdentityHash'], 'observedArgv': event['argv'], 'observedCwd': event['cwd'], 'observedCodexHome': event['codexHome'], 'observedEnvironmentSha256': event['environmentSha256'], 'observedConfigSourceSha256': config_manifest_sha, 'prelaunchCodexHomeContentDigest': snapshot_digest, 'observedCodexHomeContentDigest': 'UNPROVEN', 'postStartSnapshotScope': 'PRESTART_PINNED_FILES_ONLY', 'childInternalEffectiveConfig': 'UNPROVEN', 'stdinStatus': 'PENDING'}
        _replace_reserved(start_path, body, root=root)

    def on_input(event: dict[str, Any]) -> None:
        body = {'schemaVersion': 'alk-codex-process-input.v1', 'runId': run_id, 'taskId': task_id, 'attemptId': attempt_id, 'role': request.get('role'), 'routeId': ROUTE_ID, 'requestedClaim': CLAIM, 'planDigest': plan_digest, 'packetSha256': request['packetSha256'], 'finalPromptSha256': final_sha, **event}
        _replace_reserved(input_path, body, root=root)
        _record_transport_witness(root, evidence, run_id=run_id, task_id=task_id, attempt_id=attempt_id, role=str(request.get('role')), final_sha=final_sha, config_manifest_sha=config_manifest_sha, diagnostic=diagnostic, event=event)
        _require(event['status'] == 'COMPLETE' and event['acceptedBytes'] == len(final_raw) and (event['acceptedSha256'] == final_sha) and (event['closeSucceeded'] is True), 'codex-exact-input-incomplete', 'OS pipe did not accept complete final prompt')
    return {'argv': argv, 'stdinText': final_raw.decode('utf-8'), 'codexHome': codex_home, 'onStarted': on_started, 'onInput': on_input, 'verifyBeforeStart': verify_before_start, 'sealedRequest': sealed, 'sealedSha256': _sha(canonical_bytes(request)), 'finalPromptSha256': final_sha, 'fitReceiptDigest': fit['receiptDigest'], 'startReceiptPath': start_path, 'inputReceiptPath': input_path, 'intentPath': intent_path, 'rawInventoryPath': inventory_path, 'rawCleanupPendingPath': pending_path, 'runId': run_id, 'taskId': task_id, 'attemptId': attempt_id, 'role': request.get('role')}

def prepare_exact_prompt(*, project_root: Path, input_request: Path | None, route_id: str | None, requested_claim: str | None, state: dict[str, Any], task: dict[str, Any], manifest: dict[str, Any], lock_path: Path, source_revision: str, operation_id: str, executable_identity: dict[str, Any], executable: str, process_env: dict[str, str] | None=None, state_path: Path | None=None, manifest_path: Path | None=None) -> dict[str, Any]:
    """Seal and check one task-bound ALK request before any child is started."""
    root = Path(project_root).absolute()
    _require(route_id == ROUTE_ID and requested_claim == CLAIM and (input_request is not None), 'codex-exact-route-required', 'explicit supported route, claim and private request are required')
    run_id = _part(state.get('runId'), 'runId')
    task_id = _part(task.get('id'), 'taskId')
    attempt = task.get('attempt')
    _require(type(attempt) is int and attempt > 0 and (task.get('status') == 'RUNNING'), 'codex-exact-attempt-unverified', 'active task attempt is not verified')
    attempt_id = _part(str(attempt), 'attemptId')
    _require(state.get('sourceRevision') == source_revision, 'codex-exact-source-revision-mismatch', 'source revision changed')
    sealed: Path | None = None
    reserved: list[Path] = []
    try:
        reconcile_prelaunch_intents(root, active_staging_request=Path(input_request))
        _assert_no_cleanup_blockers(root)
        attempt_evidence = root / 'work/release-2-16/evidence/codex-exact-prompt' / run_id / task_id / attempt_id
        _require(not (attempt_evidence / 'prelaunch-intent.json').exists(), 'codex-exact-attempt-reused', 'this task attempt already has a prelaunch intent')
        sealed, request = _seal_request(root, Path(input_request), run_id, task_id, attempt_id)
        plan_digest = canonical_digest(manifest)
        lock_digest = _sha(Path(lock_path).read_bytes())
        for key, expected in (('routeId', ROUTE_ID), ('requestedClaim', CLAIM), ('runId', run_id), ('taskId', task_id), ('attemptId', attempt_id), ('planDigest', plan_digest), ('lockDigest', lock_digest), ('sourceRevision', source_revision), ('operationId', operation_id)):
            _require(request.get(key) == expected, 'codex-exact-request-binding-mismatch', f'{key} differs from the active attempt')
        packet_rel = request.get('packetPath')
        _require(isinstance(packet_rel, str) and packet_rel.startswith('work/release-2-16/') and ('..' not in Path(packet_rel).parts), 'codex-exact-packet-path-invalid', 'packet path is outside release work')
        packet_raw = read_authority_bytes(root / packet_rel, root=root, max_bytes=65536)
        _require(_sha(packet_raw) == request.get('packetSha256'), 'codex-exact-packet-stale', 'packet bytes changed')
        packet = json.loads(packet_raw)
        _require(packet.get('plan', {}).get('planDigest') == plan_digest and packet.get('task', {}).get('id') == task_id, 'codex-exact-packet-binding-mismatch', 'packet lineage differs')
        selection = request.get('selection')
        summary = request.get('summary')
        _require(isinstance(selection, dict) and isinstance(summary, dict), 'codex-exact-fit-input-missing', 'source selection or summary is missing')
        contract_raw = read_authority_bytes(root / 'tasks/release-2-16/alk-input-fit-contract.json', root=root, max_bytes=1048576)
        profile_raw = read_authority_bytes(root / 'profiles/small-context-profile.v1.json', root=root, max_bytes=65536)
        contract = json.loads(contract_raw)
        profile = json.loads(profile_raw)
        _require(contract.get('commonEnvelope', {}).get('reservedOutputEstimatedTokens') == 3072, 'codex-exact-output-reserve-mismatch', 'planned output reserve is not 3072 tokens')
        contract_sha, profile_sha = (_sha(contract_raw), _sha(profile_raw))
        binding = {key: selection.get(key) for key in ('runId', 'taskId', 'attemptId', 'planDigest', 'manifestSha256', 'candidateDigest', 'estimatorId')}
        fit = assess_local_input_fit(root, contract, profile, packet, summary, selection, role=str(request.get('role')), host_adapter_id='codex', host_version=str(request.get('hostVersion', '')), host_mode=str(request.get('hostMode', '')), estimator_id=str(request.get('estimatorId', '')), instruction=request.get('instruction'), schema=request.get('schema'), current_binding=binding, latest_user=str(request.get('latestUser', '')), window='16k')
        _require(fit['status'] == 'PASS_ALK_COMPONENTS_ONLY' and all((check['status'] == 'PASS' for check in fit['checks'])), 'codex-exact-fit-refused', 'ALK-controlled input exceeds a limit')
        rendered = render_context(profile, packet, summary, latest_user=str(request.get('latestUser', '')), window='16k')
        model_input = {'renderedEnvelope': rendered['envelope'], 'selectedSource': selection['selected'], 'instruction': request['instruction'], 'schema': request['schema']}
        final_raw = canonical_bytes(model_input)
        final_sha = _sha(final_raw)
        _require(request.get('selectedSource') == selection['selected'] and fit['inputComponentDigests']['fullAlkModelInput'] == final_sha, 'codex-exact-final-prompt-mismatch', 'final prompt differs from fit receipt')
        _require(Path(executable).name == 'codex' and executable_identity.get('status') == 'PASS', 'codex-exact-binary-unavailable', 'selected Codex binary is unavailable')
        selected_env = dict(os.environ) if process_env is None else process_env
        model, codex_home, snapshot_digest, catalog, diagnostic, config_manifest_sha = _selected_host_evidence(root, request, executable_identity, final_sha, run_id, task_id, attempt_id, executable, selected_env, str(request.get('role', '')))
        inventory_path, pending_path, inventory_sha = create_prestart_raw_inventory(root, run_id=run_id, task_id=task_id, attempt_id=attempt_id, sealed_request=sealed, state=state, plan_digest=plan_digest)
        selected_binary = _selected_binary_path(executable, executable_identity, selected_env)
        argv = [str(selected_binary), 'exec', '--json', '--ephemeral', '-m', model, '-C', str(root), '-']
        evidence = root / 'work/release-2-16/evidence/codex-exact-prompt' / run_id / task_id / attempt_id
        start_path = evidence / 'process-start.json'
        input_path = evidence / 'process-input.json'
        _reserve(start_path, root=root)
        reserved.append(start_path)
        _reserve(input_path, root=root)
        reserved.append(input_path)
        return _finish_exact_prelaunch(root=root, run_id=run_id, task_id=task_id, attempt_id=attempt_id, operation_id=operation_id, source_revision=source_revision, request=request, manifest=manifest, manifest_path=manifest_path, lock_path=lock_path, plan_digest=plan_digest, lock_digest=lock_digest, final_raw=final_raw, final_sha=final_sha, executable=executable, executable_identity=executable_identity, selected_binary=selected_binary, selected_env=selected_env, model=model, codex_home=codex_home, snapshot_digest=snapshot_digest, catalog=catalog, diagnostic=diagnostic, config_manifest_sha=config_manifest_sha, contract_sha=contract_sha, profile_sha=profile_sha, fit=fit, packet_rel=packet_rel, selection=selection, summary=summary, binding=binding, state=state, state_path=state_path, attempt=attempt, evidence=evidence, start_path=start_path, input_path=input_path, inventory_path=inventory_path, pending_path=pending_path, inventory_sha=inventory_sha, reserved=reserved, sealed=sealed, argv=argv)
    except Exception:
        if sealed is None:
            cleanup_no_start(root, None, Path(input_request))
        else:
            for path in reserved:
                path.unlink(missing_ok=True)
            cleanup_prestart_raw(root, run_id=run_id, task_id=task_id, attempt_id=attempt_id, staging_source=Path(input_request), proven_no_start=True)
        raise
