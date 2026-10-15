"""Staging, reconciliation and guarded cleanup of private model input."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.adapter_sessions.attempt_authority import (
    read_attempt_result, require_positive_attempt_result, _invocation_namespace,
)
from agent_lifecycle.adapter_sessions.private_input import (
    _require, _read_private, _write_exclusive, _verify_private_ancestors,
)

_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

def _part(value: Any, label: str) -> str:
    if not isinstance(value, str) or _PART.fullmatch(value) is None or value in {".", ".."}:
        raise LifecycleError("codex-exact-identity-invalid", f"{label} is not one path component")
    return value

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def stage_input_request(project_root: Path, request_id: str, request: dict[str, Any]) -> Path:
    """Create a caller-supplied private source; never infer route or prompt."""
    root = Path(project_root).absolute()
    request_id = _part(request_id, "requestId")
    if not isinstance(request, dict) or "attemptId" in request:
        raise LifecycleError("codex-exact-request-invalid", "caller request must precede attempt binding")
    path = root / "work/release-2-16/private-details/codex-exact-prompt/staging" / request_id / "input-request.json"
    _write_exclusive(path, canonical_bytes(request), root=root)
    return path

def _seal_request(root: Path, source: Path, run_id: str, task_id: str, attempt_id: str, *, operation_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    staging = root / "work/release-2-16/private-details/codex-exact-prompt/staging"
    source = Path(source).absolute()
    if source.name != "input-request.json" or source.parent.parent != staging:
        raise LifecycleError("codex-exact-request-source-invalid", "request is not an ALK staging artifact")
    _part(source.parent.name, "requestId")
    raw = _read_private(source, root=root)
    try:
        request = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-request-invalid", "private request is not JSON") from exc
    if not isinstance(request, dict) or "attemptId" in request:
        raise LifecycleError("codex-exact-request-invalid", "private request has invalid attempt binding")
    if operation_id is not None:
        _require(request.get("operationId") == operation_id, "codex-exact-request-binding-mismatch",
                 "operation differs before sealing")
    request = {**request, "attemptId": attempt_id}
    sealed = root / "work/release-2-16/private-details/codex-exact-prompt" / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "input-request.json"
    _write_exclusive(sealed, canonical_bytes(request), root=root)
    try:
        source.unlink()
        source.parent.rmdir()
    except OSError as exc:
        _cleanup_sealed_no_start(root, sealed, source, run_id, task_id, attempt_id, operation_id=operation_id)
        raise LifecycleError("codex-exact-request-staging-finalize-failed", "staging directory could not be finalized") from exc
    return sealed, request

def _cleanup_marker(root: Path, path: Path) -> tuple[Path, dict[str, str]]:
    private = root / "work/release-2-16/private-details/codex-exact-prompt"
    relative = path.relative_to(private).parts
    evidence = root / "work/release-2-16/evidence/codex-exact-prompt"
    if len(relative) == 3 and relative[0] == "staging" and relative[2] == "input-request.json":
        request_id = _part(relative[1], "requestId")
        return (evidence / "prestart" / request_id / "raw-cleanup-pending.json",
                {"requestId": request_id})
    if len(relative) in (4, 6) and relative[-1] == "input-request.json":
        run_id, task_id, attempt_id = (_part(value, "cleanupIdentity") for value in relative[:3])
        identity = {"runId": run_id, "taskId": task_id, "attemptId": attempt_id}
        if len(relative) == 6:
            _require(relative[3] == "operations" and re.fullmatch(r"[0-9a-f]{64}", relative[4]) is not None,
                     "codex-exact-private-path-unsafe", "operation input path is invalid")
            identity["operationKey"] = relative[4]
        return (evidence.joinpath(*relative[:-1]) / "raw-cleanup-pending.json", identity)
    raise LifecycleError("codex-exact-private-path-unsafe", "cleanup target is not an ALK input request")

def _record_cleanup_pending(root: Path, path: Path) -> None:
    marker, identity = _cleanup_marker(root, path)
    record = {"schemaVersion": "alk-codex-raw-cleanup-pending.v1",
              "status": "PRIVATE_CLEANUP_PENDING", **identity,
              "rawPathSha256": _sha(os.fsencode(str(path)))}
    if marker.exists():
        previous = json.loads(_read_private(marker, root=root))
        _require(previous == record, "codex-exact-private-cleanup-pending",
                 "cleanup marker differs from the pending raw path")
        return
    _write_exclusive(marker, canonical_bytes(record), root=root)

def _finish_cleanup_marker(root: Path, path: Path) -> None:
    marker, identity = _cleanup_marker(root, path)
    if not marker.exists():
        return
    previous = json.loads(_read_private(marker, root=root))
    _require(previous.get("status") in {"PRIVATE_CLEANUP_PENDING", "DONE"}
             and all(previous.get(key) == value for key, value in identity.items())
             and previous.get("rawPathSha256") == _sha(os.fsencode(str(path))),
             "codex-exact-private-cleanup-pending", "cleanup marker identity differs")
    if previous["status"] == "DONE":
        return
    temporary = marker.with_name(marker.name + ".tmp")
    _write_exclusive(temporary, canonical_bytes({**previous, "status": "DONE"}), root=root)
    os.replace(temporary, marker)

def _complete_started_input(root: Path, evidence: Path, intent: dict[str, Any]) -> bool:
    """Historical observations never substitute for current terminal PASS."""
    try:
        path = evidence / "prelaunch-intent.json"
        if json.loads(_read_private(path, root=root)) != intent:
            return False
        require_positive_attempt_result(root, intent_path=path)
    except (OSError, ValueError, UnicodeDecodeError, LifecycleError):
        return False
    return True

def _assert_no_cleanup_blockers(root: Path) -> None:
    evidence = root / "work/release-2-16/evidence/codex-exact-prompt"
    if not evidence.exists():
        return
    for marker in evidence.rglob("raw-cleanup-pending.json"):
        try:
            record = json.loads(_read_private(marker, root=root))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LifecycleError("codex-exact-private-cleanup-pending",
                                 "a raw cleanup marker is incomplete") from exc
        _require(record.get("status") in {"DONE", "PENDING"},
                 "codex-exact-private-cleanup-pending", "a previous raw cleanup remains unresolved")
        if record["status"] == "PENDING":
            start = marker.with_name("process-start.json")
            intent_path = marker.with_name("prelaunch-intent.json")
            try:
                observed = json.loads(_read_private(start, root=root))
                intent = json.loads(_read_private(intent_path, root=root))
            except (OSError, ValueError, UnicodeDecodeError, LifecycleError) as exc:
                raise LifecycleError("codex-exact-start-uncertain",
                                     "pending raw details have no verified child start") from exc
            _require(observed.get("schemaVersion") == "alk-codex-process-start.v1"
                     and observed.get("hostLaunchStarted") is True
                     and all(observed.get(key) == record.get(key)
                             for key in ("runId", "taskId", "attemptId")),
                     "codex-exact-start-uncertain", "pending raw details differ from child start")
            namespace = _invocation_namespace(record.get("runId"), record.get("taskId"), record.get("attemptId"))
            if marker.parent == evidence / namespace:
                _require("operationId" not in record, "codex-exact-start-uncertain",
                         "legacy pending marker has an unexpected operation binding")
            else:
                operation = record.get("operationId")
                _require(isinstance(operation, str) and bool(operation)
                         and marker.parent == evidence / _invocation_namespace(
                             record["runId"], record["taskId"], record["attemptId"], operation)
                         and isinstance(intent, dict)
                         and observed.get("operationId") == intent.get("operationId") == operation,
                         "codex-exact-start-uncertain", "pending raw operation binding differs")
            _require(_complete_started_input(root, marker.parent, intent),
                     "codex-exact-start-uncertain", "pending raw details lack a completed pipe receipt")

def _record_orphan_private_input(root: Path, path: Path, marker: Path) -> None:
    record = {"schemaVersion": "alk-codex-orphan-private-input.v1",
              "status": "START_UNCERTAIN", "costStatus": "UNAVAILABLE",
              "rawPathSha256": _sha(os.fsencode(str(path)))}
    if marker.exists():
        _require(json.loads(_read_private(marker, root=root)) == record,
                 "codex-exact-start-uncertain", "orphan private input marker differs")
    else:
        _write_exclusive(marker, canonical_bytes(record), root=root)
    raise LifecycleError("codex-exact-start-uncertain",
                         "an orphan private input needs reconciliation before another attempt")

def reconcile_prelaunch_intents(
    project_root: Path, *, active_staging_request: Path | None = None,
) -> None:
    """Reconcile intents and raw requests before a new child can start."""
    root = Path(project_root).absolute()
    evidence = root / "work/release-2-16/evidence/codex-exact-prompt"
    private = root / "work/release-2-16/private-details/codex-exact-prompt"
    active = (_staging_request(root, active_staging_request)
              if active_staging_request is not None else None)
    if evidence.exists():
        for pattern in ("start-uncertain.json", "orphan-private-input.json"):
            for marker in evidence.rglob(pattern):
                _read_private(marker, root=root)
                raise LifecycleError("codex-exact-start-uncertain",
                                     "a previous uncertain start or orphan input remains unresolved")
    if private.exists():
        _require(stat.S_ISDIR(private.lstat().st_mode),
                 "codex-exact-private-path-unsafe", "private input root is unsafe")
        for path in sorted(private.rglob("input-request.json")):
            relative = path.relative_to(private).parts
            if len(relative) == 3 and relative[0] == "staging":
                request_id = _part(relative[1], "requestId")
                if path == active:
                    _read_private(path, root=root)
                    continue
                cleanup_marker = (evidence / "prestart" / request_id
                                  / "raw-cleanup-pending.json")
                if cleanup_marker.exists():
                    pending = json.loads(_read_private(cleanup_marker, root=root))
                    if pending.get("status") == "PRIVATE_CLEANUP_PENDING":
                        continue  # The existing sticky privacy blocker has priority.
                _record_orphan_private_input(
                    root, path, evidence / "prestart" / request_id / "orphan-private-input.json")
            _require(len(relative) in (4, 6) and relative[-1] == "input-request.json",
                     "codex-exact-private-path-unsafe", "private input has an unexpected path")
            run_id, task_id, attempt_id = (_part(value, "orphanIdentity") for value in relative[:3])
            if len(relative) == 6:
                request = json.loads(_read_private(path, root=root))
                _require(isinstance(request, dict) and isinstance(request.get("operationId"), str)
                         and bool(request["operationId"])
                         and Path(*relative[:-1]) == _invocation_namespace(
                             run_id, task_id, attempt_id, request["operationId"]),
                         "codex-exact-private-path-unsafe", "sealed operation identity differs")
            attempt_evidence = evidence.joinpath(*relative[:-1])
            if not (attempt_evidence / "prelaunch-intent.json").exists():
                cleanup_marker = attempt_evidence / "raw-cleanup-pending.json"
                if cleanup_marker.exists():
                    pending = json.loads(_read_private(cleanup_marker, root=root))
                    if pending.get("status") == "PRIVATE_CLEANUP_PENDING":
                        continue  # Preserve the more specific existing blocker.
                _record_orphan_private_input(
                    root, path, attempt_evidence / "orphan-private-input.json")
    if not evidence.exists():
        return
    for path in evidence.rglob("prelaunch-intent.json"):
        raw = _read_private(path, root=root)
        try:
            intent = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise LifecycleError("codex-exact-start-uncertain", "prelaunch intent is unreadable") from exc
        _require(isinstance(intent, dict) and intent.get("schemaVersion") == "alk-codex-prelaunch-intent.v1"
                 and intent.get("hostLaunchStarted") is False,
                 "codex-exact-start-uncertain", "prelaunch intent cannot establish no-start")
        try:
            terminal = read_attempt_result(root, intent_path=path)
        except (OSError, ValueError, LifecycleError):
            terminal = None
        _require(terminal is None or terminal["status"] == "PASS",
                 "codex-exact-terminal-retry-required",
                 "failed terminal attempt retains cost hold and requires a separate retry decision")
        resolved = _complete_started_input(root, path.parent, intent)
        if not resolved:
            no_start = path.with_name("proven-no-start.json")
            if no_start.exists():
                try:
                    record = json.loads(_read_private(no_start, root=root))
                    resolved = (record.get("schemaVersion") == "alk-codex-proven-no-start.v1"
                                and record.get("status") == "PROVEN_NO_START"
                                and record.get("prelaunchIntentSha256") == _sha(raw)
                                and path.with_name("process-start.json").exists()
                                and path.with_name("process-start.json").stat().st_size == 0
                                and (not path.with_name("process-input.json").exists()
                                     or path.with_name("process-input.json").stat().st_size == 0))
                except (OSError, ValueError, UnicodeDecodeError, LifecycleError):
                    resolved = False
        if resolved:
            continue
        marker = path.with_name("start-uncertain.json")
        record = {"schemaVersion": "alk-codex-start-uncertain.v1", "status": "START_UNCERTAIN",
                  "runId": intent.get("runId"), "taskId": intent.get("taskId"),
                  "attemptId": intent.get("attemptId"), "prelaunchIntentSha256": _sha(raw),
                  "costStatus": "UNAVAILABLE"}
        if marker.exists():
            _require(json.loads(_read_private(marker, root=root)) == record,
                     "codex-exact-start-uncertain", "uncertain-start marker differs")
        else:
            _write_exclusive(marker, canonical_bytes(record), root=root)
        raise LifecycleError("codex-exact-start-uncertain", "a prior possible child start needs reconciliation")

def record_proven_no_start(project_root: Path, start_receipt_path: Path) -> None:
    """Resolve a reserved intent only after the runner reports no Popen success."""
    root = Path(project_root).absolute()
    start = Path(start_receipt_path).absolute()
    intent = start.with_name("prelaunch-intent.json")
    _require(start.name == "process-start.json" and intent.is_relative_to(
        root / "work/release-2-16/evidence/codex-exact-prompt"),
        "codex-exact-start-uncertain", "no-start receipt has an invalid path")
    raw = _read_private(intent, root=root)
    _require(not any(start.with_name(name).exists() or start.with_name(name).is_symlink()
                     for name in ("attempt-result-terminal.json", "attempt-result-terminal.pending.json")),
             "codex-exact-start-uncertain", "terminal or uncertain attempt cannot become no-start")
    _require(start.stat().st_size == 0, "codex-exact-start-uncertain",
             "observed start cannot be resolved as no-start")
    record = {"schemaVersion": "alk-codex-proven-no-start.v1", "status": "PROVEN_NO_START",
              "prelaunchIntentSha256": _sha(raw), "costStatus": "NOT_STARTED"}
    _write_exclusive(start.with_name("proven-no-start.json"), canonical_bytes(record), root=root)

def _staging_request(root: Path, source: Path) -> Path:
    staging = root / "work/release-2-16/private-details/codex-exact-prompt/staging"
    path = Path(source).absolute()
    _require(path.name == "input-request.json" and path.parent.parent == staging,
             "codex-exact-private-path-unsafe", "cleanup target is not an ALK staged request")
    _part(path.parent.name, "requestId")
    return path

def _cleanup_input_paths(root: Path, *paths: Path) -> None:
    failed = False
    for path in paths:
        try:
            if path.exists() or path.is_symlink():
                _read_private(path, root=root)
            path.unlink(missing_ok=True)
            _finish_cleanup_marker(root, path)
        except (OSError, LifecycleError):
            _record_cleanup_pending(root, path)
            failed = True
    if failed:
        raise LifecycleError("codex-exact-private-cleanup-pending", "raw request cleanup failed; durable privacy blocker retained")

def _cleanup_sealed_no_start(
    root: Path, sealed: Path, source: Path, run_id: str, task_id: str, attempt_id: str,
    *, operation_id: str | None = None,
) -> None:
    """Only the sealing transaction may remove its newly created attempt copy."""
    source = _staging_request(root, source)
    expected = (root / "work/release-2-16/private-details/codex-exact-prompt"
                / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "input-request.json")
    _require(Path(sealed).absolute() == expected,
             "codex-exact-private-path-unsafe", "sealed cleanup identity differs")
    start = (root / "work/release-2-16/evidence/codex-exact-prompt"
             / _invocation_namespace(run_id, task_id, attempt_id, operation_id) / "process-start.json")
    _require(not start.exists() or start.stat().st_size == 0,
             "codex-exact-start-uncertain", "observed child start forbids sealed cleanup")
    _cleanup_input_paths(root, expected, source)

def cleanup_no_start(project_root: Path, sealed: Path | None, source: Path | None) -> None:
    """Remove only a caller-supplied ALK staging request on a no-start return."""
    root = Path(project_root).absolute()
    _require(sealed is None, "codex-exact-private-path-unsafe",
             "public no-start cleanup cannot remove a sealed attempt request")
    if source is not None:
        _cleanup_input_paths(root, _staging_request(root, source))

def _snapshot_digest(snapshot: Path, *, root: Path) -> str:
    _verify_private_ancestors(snapshot, root=root)
    info = snapshot.lstat()
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
             "codex-exact-config-unsafe", "private CODEX_HOME is not protected")
    rows: list[dict[str, Any]] = []
    total = 0
    for path in sorted(snapshot.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            _require(stat.S_IMODE(info.st_mode) == 0o700,
                     "codex-exact-config-unsafe", "snapshot directory mode is unsafe")
            continue
        _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) in {0o400, 0o600},
                 "codex-exact-config-unsafe", "snapshot has unsafe file or symlink")
        total += info.st_size
        _require(len(rows) < 128 and total <= 8_388_608,
                 "codex-exact-config-overflow", "snapshot exceeds inventory limit")
        data = path.read_bytes()
        rows.append({"path":path.relative_to(snapshot).as_posix(), "sha256":_sha(data),
                     "bytes":len(data), "mode":stat.S_IMODE(info.st_mode)})
    return canonical_digest(rows)

def _snapshot_raw_sources(root: Path, snapshot: Path) -> list[dict[str, Any]]:
    """Inventory the whole child CODEX_HOME tree and every prestart file."""
    info = snapshot.lstat()
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
             "codex-exact-config-unsafe", "private CODEX_HOME is not protected")
    tree_digest = _snapshot_digest(snapshot, root=root)
    sources: list[dict[str, Any]] = []
    total = 0
    for path in sorted(snapshot.rglob("*")):
        file_info = path.lstat()
        if stat.S_ISDIR(file_info.st_mode):
            continue
        _require(stat.S_ISREG(file_info.st_mode)
                 and stat.S_IMODE(file_info.st_mode) in {0o400, 0o600},
                 "codex-exact-config-unsafe", "snapshot contains an unsafe raw file")
        raw = path.read_bytes()
        _require(len(raw) == file_info.st_size,
                 "codex-exact-raw-inventory-invalid", "snapshot file changed during inventory")
        total += len(raw)
        sources.append({"kind": "codex-home-snapshot-file",
                        "path": str(path.relative_to(root)),
                        "pathSha256": _sha(os.fsencode(str(path))),
                        "fileIdentity": {"device": file_info.st_dev, "inode": file_info.st_ino},
                        "sha256": _sha(raw), "bytes": len(raw),
                        "mode": stat.S_IMODE(file_info.st_mode)})
    _require(_snapshot_digest(snapshot, root=root) == tree_digest,
             "codex-exact-raw-inventory-invalid", "snapshot changed during inventory")
    return [{"kind": "codex-home-snapshot-tree",
             "path": str(snapshot.relative_to(root)),
             "pathSha256": _sha(os.fsencode(str(snapshot))),
             "fileIdentity": {"device": info.st_dev, "inode": info.st_ino},
             "sha256": tree_digest, "bytes": total,
             "cleanupScope": "WHOLE_TREE_INCLUDING_POST_START_ADDITIONS"}, *sources]

def _remove_snapshot_no_start(snapshot: Path, *, root: Path) -> None:
    """Remove a known unstarted snapshot without following links or unknown types."""
    if not snapshot.exists() and not snapshot.is_symlink():
        return
    _verify_private_ancestors(snapshot, root=root)
    info = snapshot.lstat()
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
             "codex-exact-private-path-unsafe", "snapshot cleanup root is unsafe")
    entries = sorted(snapshot.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in entries:
        item = path.lstat()
        _require((stat.S_ISDIR(item.st_mode) and stat.S_IMODE(item.st_mode) == 0o700)
                 or (stat.S_ISREG(item.st_mode) and stat.S_IMODE(item.st_mode) in {0o400, 0o600}),
                 "codex-exact-private-path-unsafe", "snapshot cleanup contains an unsafe entry")
    for path in entries:
        if stat.S_ISDIR(path.lstat().st_mode):
            path.rmdir()
        else:
            path.unlink()
    snapshot.rmdir()
