"""Private, fail-closed ALK input boundary for the scoped Codex exec route.

The local fit receipt proves only ALK-controlled bytes. Selected-host proof is
separate, and missing proof leaves the process unstarted.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import selectors
import shlex
import shutil
import stat
import subprocess
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.accounting.input_fit import assess_local_input_fit
from agent_lifecycle.adapter_sessions.codex_input_diagnostics import (
    _file_sha, _bounded_codex_debug_output, _selected_binary_path, _observed_bundled_catalog, _recheck_alk_fit_sources, _require_fresh_catalog, _require_current_manifest, _recheck_active_workflow_state, _snapshot_identity_inventory, _private_diagnostic_output, _observed_prompt_diagnostic,
)
from agent_lifecycle.adapter_sessions.input_lifecycle import (
    _part, _sha, stage_input_request, _seal_request, _cleanup_marker, _record_cleanup_pending, _finish_cleanup_marker, _complete_started_input, _assert_no_cleanup_blockers, _record_orphan_private_input, reconcile_prelaunch_intents, record_proven_no_start, _staging_request, _cleanup_input_paths, _cleanup_sealed_no_start, cleanup_no_start, _snapshot_digest, _snapshot_raw_sources, _remove_snapshot_no_start, _PART,
)
from agent_lifecycle.adapter_sessions.private_input import (
    _private_dir, _verify_private_ancestors, _write_exclusive, _read_private, _require, _MAX_REQUEST_BYTES,
)
from agent_lifecycle.adapter_sessions.attempt_authority import (
    capture_attempt_authority, read_attempt_result, require_positive_attempt_result,
    reserve_attempt_result, verify_attempt_reservation,
)
from agent_lifecycle.accounting.contracts import digest as accounting_digest, utc_instant
from agent_lifecycle.context import render_context
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, load_json_object, read_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash
from agent_lifecycle.adapter_sessions.codex_source_exposure import (
    _source_ast_ranges, _masked_noncontent, _r69h_codex_exposure, _check_required_route_bridge, _discover_bootstrap_test_ids, _check_source_exposure, _build_source_exposure_packet, _R69H_SOURCE_ORACLE_SHA256,
)
from agent_lifecycle.adapter_sessions.codex_source_subject import (
    _matches_closed_schema, _source_test_ids, _r69h_check_test_dependency_closure, _single_turn_projection, _review_findings_match_v4, _r69h_expand_test_support, _r69h_project_test_support, _recompute_bootstrap_subject, _FINDING_LINE,
)
from agent_lifecycle.adapter_sessions.codex_prompt_preparation import (
    _selected_host_evidence, _raw_source_record, _record_transport_witness, _workflow_journal_identity, create_prestart_raw_inventory, verify_prestart_raw_inventory, cleanup_prestart_raw, _reserve, _replace_reserved, prepare_exact_prompt, ROUTE_ID, CLAIM,
)

def assess_retention_pre_fixture(
    run_id: str, closed_run: dict[str, Any] | None, now_utc: str,
    *, reconciliation_clear: bool,
) -> dict[str, str]:
    """RB11-PRE only: inspect a verified Journal.closed_run fixture, never delete.

    The caller must separately establish journal/root authority and current
    exception state. Even DUE_PRE_ONLY is not permission to purge raw details.
    """
    result = {"caseId": "RB11-PRE", "runtimeStatus": "NOT_RUN"}
    try:
        _part(run_id, "runId")
        now = utc_instant(now_utc)
        if closed_run is None:
            return {**result, "status": "OPEN_NO_PURGE_CLOCK"}
        if type(reconciliation_clear) is not bool or not isinstance(closed_run, dict):
            raise ValueError("verified closure or exception state unavailable")
        if set(closed_run) != {"closure", "summary", "summary_digest", "eligible_after"}:
            raise ValueError("closed-run fixture incomplete")
        closure = closed_run["closure"]
        summary = closed_run["summary"]
        if not isinstance(closure, dict) or not isinstance(summary, dict):
            raise ValueError("closed-run fixture malformed")
        if closure.get("run_id") != run_id:
            raise ValueError("closure belongs to another run")
        _part(closure.get("closure_id"), "closureId")
        closed_at = utc_instant(closure.get("closed_at_utc"))
        eligible_after = utc_instant(closed_run["eligible_after"])
        if closed_at > now or eligible_after != closed_at + timedelta(days=30):
            raise ValueError("30-day clock does not match verified closure")
        if closed_run["summary_digest"] != accounting_digest(summary):
            raise ValueError("closure summary digest mismatch")
        scopes = closure.get("scope_revisions")
        actual = summary.get("scopes")
        if not isinstance(scopes, list) or not scopes or not isinstance(actual, dict):
            raise ValueError("full-run scope inventory missing")
        names: list[str] = []
        for row in scopes:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError("invalid scope revision")
            name, revision = row
            _part(name, "scope")
            if type(revision) is not int or revision < 0 or not isinstance(actual.get(name), dict):
                raise ValueError("invalid scope revision")
            if actual[name].get("revision") != revision + 1:
                raise ValueError("closed scope revision mismatch")
            names.append(name)
        if names != sorted(set(names)) or set(actual) != set(names):
            raise ValueError("incomplete full-run scope inventory")
        if not reconciliation_clear:
            raise ValueError("financial reconciliation remains open")
        return {**result, "status": "DUE_PRE_ONLY" if now >= eligible_after else "NOT_DUE_PRE_ONLY"}
    except (ValueError, TypeError, LifecycleError, OverflowError):
        return {**result, "status": "REFUSED_PRE_ONLY"}

_ONE_TURN_REVIEW_INSTRUCTION = (
    "ALK_ROUTE_BOOTSTRAP_REVIEW_V4. Review the entire bounded source packet below. "
    "Return one JSON object matching outputSchema. Do not request tools. "
    "Set coverageComplete=false, verdict=FAIL, reviewText=REVIEW_INCOMPLETE and "
    "findings=[] if the assigned packet cannot be fully assessed. A complete PASS "
    "requires reviewText=NO_CURRENT_FINDINGS and findings=[]. For a complete FAIL, "
    "write only one line per finding as '- [P1|P2|P3] ID | path:line | evidence'; "
    "copy each line exactly into rawSpan and map every field and ordinal. "
    "Preserve PRE_WS01 and NOT_RUN. Echo ASSIGNED_SUBJECT_SHA256 in subjectSha256; "
    "ALK independently checks it against the full JSON bytes below. Review delivered "
    "CONTENT; IDENTITY_ONLY proves lineage, not unseen implementation semantics. "
    "If the delivered scope cannot be assessed, return REVIEW_INCOMPLETE.\n"
)

def build_single_turn_bootstrap_review_request(
    *, request_id: int, thread_id: str, subject: dict[str, Any],
    packet: bytes, output_schema: dict[str, Any], cwd: Path,
) -> bytes:
    """Serialize the exact one-turn request with the full subject and source bytes."""
    _require(type(request_id) is int and request_id > 0 and isinstance(thread_id, str)
             and bool(thread_id) and isinstance(subject, dict)
             and isinstance(packet, bytes) and bool(packet),
             "codex-exact-bootstrap-review-unavailable", "one-turn input is incomplete")
    try:
        packet_text = packet.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleError("codex-exact-bootstrap-review-unavailable",
                             "source packet is not UTF-8") from exc
    prompt = (_ONE_TURN_REVIEW_INSTRUCTION
              + "ASSIGNED_SUBJECT_SHA256=" + _sha(canonical_bytes(subject)) + "\n"
              + "ASSIGNED_SUBJECT_JSON\n"
              + canonical_bytes(subject).decode("utf-8")
              + "\nSOURCE_PACKET_BEGIN\n" + packet_text + "\nSOURCE_PACKET_END\n")
    request = {"id": request_id, "method": "turn/start", "params": {
        "threadId": thread_id, "cwd": str(Path(cwd).absolute()),
        "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"},
        "input": [{"type": "text", "text": prompt}], "outputSchema": output_schema}}
    raw = canonical_bytes(request) + b"\n"
    _require(len(raw) <= 245_760,
             "codex-exact-bootstrap-review-unavailable", "one-turn request exceeds cap")
    return raw

def assess_single_turn_bootstrap_context_fit(
    *, request_bytes: bytes, model_context_window: int,
) -> dict[str, int | str]:
    """Check only ALK's added request; hidden host input remains unproven."""
    _require(isinstance(request_bytes, bytes) and 0 < len(request_bytes) <= 245_760
             and type(model_context_window) is int and model_context_window > 0,
             "codex-exact-bootstrap-review-context-unknown", "context evidence unavailable")
    required = len(request_bytes) + 8192 + 16384
    _require(required <= model_context_window,
             "codex-exact-bootstrap-review-context-overflow", "one turn exceeds conservative fit")
    return {"schemaVersion": "alk-route-bootstrap-one-turn-context-fit.v1",
            "serializedRequestUtf8Bytes": len(request_bytes),
            "structuredOutputReserveTokens": 8192, "contextSafetyTokens": 16384,
            "modelContextWindow": model_context_window,
            "requiredUpperBoundTokens": required, "hostHiddenInput": "UNPROVEN"}

_APP_SERVER_MAX_REQUEST_BYTES = 245_760
_APP_SERVER_TIMEOUT_SECONDS = 15.0

def read_codex_app_server_thread(
    project_root: Path, *, executable: str, expected_binary_sha256: str, thread_id: str,
    process_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read a thread through bounded, deadline-aware local stdio requests."""
    root = Path(project_root).absolute()
    environment = dict(os.environ) if process_env is None else process_env
    selected = (Path(executable) if Path(executable).is_absolute()
                else Path(shutil.which(executable, path=environment.get("PATH", "")) or ""))
    _require(selected.is_file() and selected.name == "codex"
             and isinstance(thread_id, str) and 0 < len(thread_id) <= _APP_SERVER_MAX_REQUEST_BYTES,
             "codex-exact-bootstrap-review-unavailable", "selected App Server binary is unavailable")
    binary = selected.resolve(strict=True)
    _require(_sha(binary.read_bytes()) == expected_binary_sha256,
             "codex-exact-bootstrap-review-unavailable", "selected App Server binary differs")
    requests = [
        {"method": "initialize", "id": 1,
         "params": {"clientInfo": {"name": "agent_lifecycle_kit",
                                   "title": "Agent Lifecycle Kit", "version": "2.16.0"}}},
        {"method": "initialized", "params": {}},
        {"method": "thread/read", "id": 2,
         "params": {"threadId": thread_id, "includeTurns": True}},
    ]
    request_bytes = [canonical_bytes(message) + b"\n" for message in requests]
    _require(all(len(raw) <= _APP_SERVER_MAX_REQUEST_BYTES for raw in request_bytes),
             "codex-exact-bootstrap-review-unavailable", "local App Server request exceeded the bound")
    try:
        process = subprocess.Popen(
            [str(binary), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=root, env=environment, bufsize=0,
        )
    except OSError as exc:
        raise LifecycleError("codex-exact-bootstrap-review-unavailable",
                             "local App Server could not start") from exc
    deadline = time.monotonic() + _APP_SERVER_TIMEOUT_SECONDS
    buffered = bytearray()
    total = 0
    try:
        def require_timely() -> None:
            _require(time.monotonic() < deadline,
                     "codex-exact-bootstrap-review-unavailable", "local App Server timed out")

        _require(process.stdin is not None and process.stdout is not None,
                 "codex-exact-bootstrap-review-unavailable", "local App Server pipes unavailable")
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        with (selectors.DefaultSelector() as selector,
              selectors.DefaultSelector() as writer):
            selector.register(process.stdout, selectors.EVENT_READ)
            writer.register(process.stdin, selectors.EVENT_WRITE)

            def send(raw: bytes) -> None:
                pending = memoryview(raw)
                while pending:
                    remaining = deadline - time.monotonic()
                    _require(remaining > 0 and bool(writer.select(max(0.0, remaining))),
                             "codex-exact-bootstrap-review-unavailable", "local App Server timed out")
                    require_timely()
                    try:
                        written = os.write(process.stdin.fileno(), pending)
                    except BlockingIOError:
                        continue
                    _require(0 < written <= len(pending),
                             "codex-exact-bootstrap-review-unavailable", "local App Server request incomplete")
                    pending = pending[written:]

            def receive(request_id: int) -> dict[str, Any]:
                nonlocal total
                while time.monotonic() < deadline:
                    while b"\n" in buffered:
                        require_timely()
                        line, _, rest = buffered.partition(b"\n")
                        buffered[:] = rest
                        if not line:
                            continue
                        try:
                            message = load_json_object(line, label="App Server response")
                        except LifecycleError as exc:
                            raise LifecycleError("codex-exact-bootstrap-review-unavailable",
                                                 "invalid App Server JSONL") from exc
                        require_timely()
                        _require(isinstance(message, dict),
                                 "codex-exact-bootstrap-review-unavailable", "invalid App Server message")
                        if type(message.get("id")) is int and message["id"] == request_id:
                            _require("error" not in message and isinstance(message.get("result"), dict),
                                     "codex-exact-bootstrap-review-unavailable",
                                     "App Server refused the request")
                            return message["result"]
                        _require("id" not in message,
                                 "codex-exact-bootstrap-review-unavailable",
                                 "unexpected App Server response")
                    events = selector.select(max(0.0, deadline - time.monotonic()))
                    _require(bool(events), "codex-exact-bootstrap-review-unavailable",
                             "local App Server timed out")
                    try:
                        chunk = os.read(process.stdout.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    _require(bool(chunk), "codex-exact-bootstrap-review-unavailable",
                             "local App Server closed before responding")
                    total += len(chunk)
                    _require(total <= 4_194_304, "codex-exact-bootstrap-review-unavailable",
                             "local App Server response exceeded the bound")
                    buffered.extend(chunk)
                raise LifecycleError("codex-exact-bootstrap-review-unavailable",
                                     "local App Server timed out")

            send(request_bytes[0])
            receive(1)
            send(request_bytes[1])
            send(request_bytes[2])
            result = receive(2)
        _require(_sha(binary.read_bytes()) == expected_binary_sha256,
                 "codex-exact-bootstrap-review-unavailable", "selected App Server binary changed")
    except (OSError, ValueError, TypeError) as exc:
        raise LifecycleError("codex-exact-bootstrap-review-unavailable",
                             "local App Server read failed") from exc
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
    require_timely()
    return result

def require_bootstrap_audit(
    project_root: Path, *, plan_digest: str, lock_sha256: str,
    selected_binary_sha256: str,
    fresh_thread_read: Callable[[str], dict[str, Any]] | None = None,
    intent_path: Path | None = None, state_path: Path | None = None,
    profile: dict[str, Any] | None = None, executable_identity: dict[str, Any] | None = None,
    process_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ordinary independent audit plus current reserved task; no callback PASS."""
    from .ordinary_audit import require_fresh_task_gate
    root = Path(project_root).absolute()
    audit_path = root / "work/release-2-16/evidence/ordinary-audit/integration-selection.json"
    _require(audit_path.exists(), "codex-exact-bootstrap-audit-missing",
             "independent bootstrap evidence is unavailable")
    _require(fresh_thread_read is None and isinstance(intent_path, Path) and isinstance(state_path, Path)
             and isinstance(profile, dict) and isinstance(executable_identity, dict) and isinstance(process_env, dict),
             "codex-exact-bootstrap-task-required", "current reserved task and actual selected launch inputs required")
    return require_fresh_task_gate(root, intent_path=intent_path, state_path=state_path,
        plan_digest=plan_digest, lock_sha256=lock_sha256, selected_binary_sha256=selected_binary_sha256,
        profile=profile, executable_identity=executable_identity, process_env=process_env)

