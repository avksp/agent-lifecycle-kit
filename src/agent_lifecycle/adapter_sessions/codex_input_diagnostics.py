"""Bounded local diagnostics and current ALK input-source checks for Codex."""
from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.input_fit import assess_local_input_fit
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, read_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.adapter_sessions.input_lifecycle import _sha, _snapshot_digest
from agent_lifecycle.adapter_sessions.private_input import (
    _require, _verify_private_ancestors, _write_exclusive, _MAX_REQUEST_BYTES,
)

def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _bounded_codex_debug_output(
    binary: Path, args: tuple[str, ...], *, root: Path,
    process_env: dict[str, str], limit: int,
) -> bytes:
    """Run a local no-model diagnostic with a wall-clock and output bound."""
    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(
            [str(binary), *args], cwd=root, env=process_env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 15.0
        chunks: list[bytes] = []
        total = 0
        while True:
            ready = selector.select(max(0.0, deadline - time.monotonic()))
            _require(bool(ready), "codex-exact-catalog-unavailable", "selected binary diagnostic timed out")
            chunk = os.read(process.stdout.fileno(), 65_536)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= limit, "codex-exact-catalog-overflow", "selected binary diagnostic is oversized")
            chunks.append(chunk)
        remaining = max(0.0, deadline - time.monotonic())
        _require(process.wait(timeout=remaining) == 0,
                 "codex-exact-catalog-unavailable", "selected binary diagnostic failed")
        return b"".join(chunks)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("codex-exact-catalog-unavailable",
                             "selected binary diagnostic could not complete") from exc
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()

def _selected_binary_path(
    executable: str, identity: dict[str, Any], process_env: dict[str, str],
) -> Path:
    """Resolve and rehash the exact executable selected by launch preflight."""
    candidate = (Path(executable) if Path(executable).is_absolute()
                 else Path(shutil.which(executable, path=process_env.get("PATH", "")) or ""))
    _require(candidate.is_file(),
             "codex-exact-binary-unavailable", "selected binary path is unavailable")
    binary = candidate.resolve(strict=True)
    binary_sha = _file_sha(binary)
    _require(identity.get("status") == "PASS"
             and identity.get("resolvedPathSha256") == _sha(os.fsencode(str(binary)))
             and identity.get("executableContentSha256") == binary_sha,
             "codex-exact-binary-mismatch", "binary differs from selected executable")
    return binary

def _observed_bundled_catalog(
    root: Path, executable: str, identity: dict[str, Any], model: str,
    process_env: dict[str, str],
) -> dict[str, Any]:
    """Bind a bundled catalog candidate to the exact selected binary."""
    binary = _selected_binary_path(executable, identity, process_env)
    binary_sha = identity["executableContentSha256"]
    version_raw = _bounded_codex_debug_output(
        binary, ("--version",), root=root, process_env=process_env, limit=1024)
    catalog_raw = _bounded_codex_debug_output(
        binary, ("debug", "models", "--bundled"), root=root,
        process_env=process_env, limit=1_048_576)
    _require(_file_sha(binary) == binary_sha,
             "codex-exact-binary-mismatch", "catalog binary changed during diagnostic")
    try:
        version = version_raw.decode("utf-8").strip()
        catalog = json.loads(catalog_raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LifecycleError("codex-exact-catalog-unavailable",
                             "selected binary catalog is malformed") from exc
    _require(bool(version) and len(version) <= 256 and isinstance(catalog, dict)
             and isinstance(catalog.get("models"), list),
             "codex-exact-catalog-unavailable", "selected binary catalog is incomplete")
    selected = [row for row in catalog["models"]
                if isinstance(row, dict) and row.get("slug") == model]
    _require(len(selected) == 1, "codex-exact-model-unavailable",
             "selected model is absent or ambiguous in the bundled catalog")
    row = selected[0]
    window = row.get("context_window")
    _require(type(window) is int and window >= 16_384,
             "codex-exact-window-unavailable", "bundled catalog has no usable 16k window")
    return {"source": "SELECTED_BINARY_BUNDLED_CATALOG_CANDIDATE",
            "binarySha256": binary_sha, "version": version,
            "catalogSha256": _sha(catalog_raw), "model": model,
            "modelEntryDigest": canonical_digest(row),
            "catalogWindowTokens": window, "actualChildWindow": "UNPROVEN"}

def _recheck_alk_fit_sources(
    root: Path, request: dict[str, Any], packet_rel: str, packet_sha: str,
    contract_sha: str, profile_sha: str, plan_digest: str, task_id: str,
    selection: dict[str, Any], summary: dict[str, Any],
    binding: dict[str, Any], fit_digest: str,
) -> None:
    """Reopen every mutable ALK fit source at the last no-start boundary."""
    packet_raw = read_authority_bytes(root / packet_rel, root=root, max_bytes=65_536)
    contract_raw = read_authority_bytes(
        root / "tasks/release-2-16/alk-input-fit-contract.json", root=root,
        max_bytes=1_048_576)
    profile_raw = read_authority_bytes(
        root / "profiles/small-context-profile.v1.json", root=root,
        max_bytes=65_536)
    _require(_sha(packet_raw) == packet_sha and _sha(contract_raw) == contract_sha
             and _sha(profile_raw) == profile_sha,
             "codex-exact-fit-source-stale", "packet, fit contract or profile changed before start")
    try:
        packet = json.loads(packet_raw)
        contract = json.loads(contract_raw)
        profile = json.loads(profile_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-fit-source-stale", "ALK fit source is malformed") from exc
    _require(packet.get("plan", {}).get("planDigest") == plan_digest
             and packet.get("task", {}).get("id") == task_id
             and contract.get("commonEnvelope", {}).get("reservedOutputEstimatedTokens") == 3072,
             "codex-exact-fit-source-stale", "packet lineage or output reserve changed")
    fresh = assess_local_input_fit(
        root, contract, profile, packet, summary, selection,
        role=str(request.get("role")), host_adapter_id="codex",
        host_version=str(request.get("hostVersion", "")), host_mode=str(request.get("hostMode", "")),
        estimator_id=str(request.get("estimatorId", "")), instruction=request.get("instruction"),
        schema=request.get("schema"), current_binding=binding,
        latest_user=str(request.get("latestUser", "")), window="16k",
    )
    _require(fresh["status"] == "PASS_ALK_COMPONENTS_ONLY"
             and fresh["receiptDigest"] == fit_digest,
             "codex-exact-fit-source-stale", "selected source or output plan changed before start")

def _require_fresh_catalog(
    root: Path, executable: str, identity: dict[str, Any], model: str,
    process_env: dict[str, str], expected: dict[str, Any],
) -> None:
    _require(_observed_bundled_catalog(root, executable, identity, model, process_env) == expected,
             "codex-exact-catalog-stale", "selected binary catalog changed before start")

def _require_current_manifest(
    root: Path, manifest_path: Path | None, captured: dict[str, Any], plan_digest: str,
) -> None:
    """Reopen the authoritative manifest at the final process-start boundary."""
    _require(manifest_path is not None,
             "codex-exact-plan-stale", "manifest source is unavailable before start")
    try:
        current = json.loads(read_authority_bytes(
            manifest_path, root=root, max_bytes=1_048_576))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-plan-stale", "manifest changed before start") from exc
    _require(isinstance(current, dict)
             and canonical_digest(current) == plan_digest
             and canonical_digest(captured) == plan_digest,
             "codex-exact-plan-stale", "manifest changed before start")

def _recheck_active_workflow_state(
    root: Path, state_path: Path | None, captured_state: dict[str, Any],
    run_id: str, task_id: str, attempt: int,
) -> None:
    """Reopen the authoritative task state at the last ALK pre-Popen boundary."""
    _require(state_path is not None, "codex-exact-state-stale",
             "authoritative workflow state path is missing")
    path = Path(state_path).absolute()
    _require(path.is_relative_to(root), "codex-exact-state-stale",
             "authoritative workflow state lies outside the project root")
    try:
        fresh = read_json_object(path, label="fresh workflow state")
    except (OSError, ValueError, LifecycleError) as exc:
        raise LifecycleError("codex-exact-state-stale",
                             "authoritative workflow state cannot be reopened") from exc
    tasks = fresh.get("tasks")
    active = ([task for task in tasks if isinstance(task, dict) and task.get("id") == task_id]
              if isinstance(tasks, list) else [])
    _require(fresh.get("runId") == run_id
             and canonical_digest(fresh) == canonical_digest(captured_state)
             and len(active) == 1
             and active[0].get("status") == "RUNNING"
             and active[0].get("attempt") == attempt,
             "codex-exact-state-stale", "task or attempt changed before child start")

def _snapshot_identity_inventory(snapshot: Path) -> list[tuple[str, int, int, int, int, int]]:
    entries = [snapshot, *snapshot.rglob("*")]
    _require(len(entries) <= 1024, "codex-exact-config-overflow", "snapshot identity inventory exceeds limit")
    rows = []
    for path in entries:
        info = path.lstat()
        rows.append((path.relative_to(snapshot).as_posix(), info.st_dev, info.st_ino,
                     info.st_mode, info.st_uid, info.st_nlink))
    return sorted(rows)

def _private_diagnostic_output(
    root: Path, binary: Path, tag: str, snapshot: Path,
    environment: dict[str, str],
) -> bytes:
    """Restore only an unchanged, pre-existing installation_id permission reset."""
    before_digest = _snapshot_digest(snapshot, root=root)
    before_identities = _snapshot_identity_inventory(snapshot)
    path = snapshot / "installation_id"
    fd: int | None = None
    directory_fd: int | None = None
    try:
        try:
            before = path.lstat()
        except FileNotFoundError:
            before = None
        if before is not None:
            _verify_private_ancestors(path, root=root)
            _require(hasattr(os, "getuid")
                     and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
                     and snapshot.lstat().st_uid == os.getuid()
                     and stat.S_ISREG(before.st_mode)
                     and before.st_uid == os.getuid() and before.st_nlink == 1
                     and stat.S_IMODE(before.st_mode) in {0o400, 0o600}
                     and 0 < before.st_size <= _MAX_REQUEST_BYTES,
                     "codex-exact-config-unsafe", "installation metadata is unsafe")
            directory_fd = os.open(snapshot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory = os.fstat(directory_fd)
            fd = os.open("installation_id", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0), dir_fd=directory_fd)
            opened = os.fstat(fd)
            _require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                     "codex-exact-config-unsafe", "installation metadata was replaced")
            raw_before = os.read(fd, _MAX_REQUEST_BYTES + 1)
            _require(len(raw_before) == before.st_size,
                     "codex-exact-config-unsafe", "installation metadata read changed")
        try:
            raw = _bounded_codex_debug_output(
                binary, ("debug", "prompt-input", tag), root=root,
                process_env=environment, limit=_MAX_REQUEST_BYTES)
        finally:
            if fd is not None and before is not None:
                current = os.stat("installation_id", dir_fd=directory_fd, follow_symlinks=False)
                opened = os.fstat(fd)
                os.lseek(fd, 0, os.SEEK_SET)
                raw_after = os.read(fd, _MAX_REQUEST_BYTES + 1)
                _verify_private_ancestors(path, root=root)
                current_directory = snapshot.lstat()
                _require(stat.S_ISDIR(current_directory.st_mode)
                         and (current_directory.st_dev, current_directory.st_ino)
                         == (directory.st_dev, directory.st_ino)
                         and stat.S_ISREG(current.st_mode)
                         and (current.st_dev, current.st_ino) == (before.st_dev, before.st_ino)
                         and current.st_uid == before.st_uid and current.st_nlink == 1
                         and opened.st_size == current.st_size == before.st_size
                         and raw_after == raw_before
                         and stat.S_IMODE(current.st_mode) in {stat.S_IMODE(before.st_mode), 0o644},
                         "codex-exact-config-unsafe", "installation metadata changed")
                if stat.S_IMODE(current.st_mode) == 0o644:
                    os.fchmod(fd, stat.S_IMODE(before.st_mode))
                    os.fsync(fd)
            _require(_snapshot_digest(snapshot, root=root) == before_digest,
                     "codex-exact-config-unsafe", "snapshot changed during diagnostic")
            _require(_snapshot_identity_inventory(snapshot) == before_identities,
                     "codex-exact-config-unsafe", "snapshot identities changed during diagnostic")
        return raw
    except OSError as exc:
        raise LifecycleError("codex-exact-config-unsafe", "diagnostic snapshot cannot be verified") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)

def _observed_prompt_diagnostic(
    root: Path, executable: str, identity: dict[str, Any], *,
    snapshot: Path, model: str, role: str, run_id: str,
    task_id: str, attempt_id: str, final_sha: str,
    process_env: dict[str, str],
) -> dict[str, Any]:
    """Collect a private per-role candidate; never assert exec-stdin equivalence."""
    _require(role in {"worker", "validator", "auditor", "retry", "coordinator", "closing"},
             "codex-exact-role-unsupported", "diagnostic role is unsupported")
    _require(re.fullmatch(r"[0-9a-f]{64}", final_sha) is not None,
             "codex-exact-diagnostic-invalid", "final input digest is invalid")
    binary = _selected_binary_path(executable, identity, process_env)
    binary_sha = identity["executableContentSha256"]
    _require(snapshot.is_relative_to(root) and snapshot.is_dir()
             and stat.S_IMODE(snapshot.lstat().st_mode) == 0o700,
             "codex-exact-config-unsafe", "diagnostic CODEX_HOME is not protected")
    tag = (f"ALK_DIAGNOSTIC role={role} run={run_id} task={task_id} "
           f"attempt={attempt_id} inputSha256={final_sha}")
    environment = {**process_env, "CODEX_HOME": str(snapshot)}
    raw = _private_diagnostic_output(root, binary, tag, snapshot, environment)
    _require(_file_sha(binary) == binary_sha,
             "codex-exact-binary-mismatch", "diagnostic binary changed")
    try:
        items = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError("codex-exact-diagnostic-invalid",
                             "selected binary diagnostic is not JSON") from exc
    _require(isinstance(items, list) and 0 < len(items) <= 256
             and all(isinstance(item, dict) for item in items),
             "codex-exact-diagnostic-invalid", "selected binary diagnostic items are invalid")
    private = (root / "work/release-2-16/private-details/codex-exact-prompt"
               / run_id / task_id / attempt_id / "prompt-input.json")
    _write_exclusive(private, raw, root=root)
    return {"source": "SELECTED_BINARY_DEBUG_PROMPT_INPUT_CANDIDATE",
            "binarySha256": binary_sha, "model": model, "role": role,
            "safeTagSha256": _sha(tag.encode("utf-8")),
            "rawSha256": _sha(raw), "rawBytes": len(raw),
            "itemCount": len(items),
            "items": [{"index": index, "type": item.get("type"),
                       "role": item.get("role"),
                       "canonicalBytes": len(canonical_bytes(item)),
                       "canonicalSha256": _sha(canonical_bytes(item))}
                      for index, item in enumerate(items)],
            "execStdinEquivalence": "UNPROVEN"}
