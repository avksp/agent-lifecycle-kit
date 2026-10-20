"""Private runtime for bounded, process-backed external-tool jobs."""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.session_store import session_path
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.canonical import canonical_bytes, require_private_file
from agent_lifecycle.contracts.external_job_schemas import (
    TERMINAL_JOB_STATES,
    build_external_job_artifact,
    build_external_job_request,
    build_external_job_result,
    build_external_job_status,
    require_external_job_pass,
    validate_external_job_request,
    validate_external_job_result,
    validate_external_job_status,
)
from agent_lifecycle.contracts.paths import read_stable_repository_file
from agent_lifecycle.contracts.persistence import create_private_json, require_private_json
from agent_lifecycle.contracts.preparation_policy import (
    REVIEW_PREFLIGHT_FIELDS,
    PreparationAdmission,
    review_invocation_digest,
)
from agent_lifecycle.contracts.process_execution_schemas import (
    validate_process_execution_receipt,
)
from agent_lifecycle.contracts.redaction import redact_text, redact_value
from agent_lifecycle.host_protocol.external_jobs import validate_external_job_transition

DEFAULT_EXTERNAL_JOB_ROOT = ".alk/external-jobs"
_CANCEL_SCHEMA = "agent-external-job-cancel-request.v1"
_VIEW_SCHEMA = "agent-external-job-attempt-view.v1"
_POLL_SECONDS = 0.02
_HASH_CHUNK_BYTES = 128 * 1024
_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".html": "text/html",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".png": "image/png",
    ".txt": "text/plain",
    ".xml": "application/xml",
}

ProcessRunner = Callable[..., dict[str, Any]]
Clock = Callable[[], str]


@dataclass(frozen=True)
class _JobContext:
    request: dict[str, Any]
    root: Path
    attempt_root: Path
    artifact_root: Path
    children: list[dict[str, Any]]
    child_refs: list[dict[str, Any]]
    clock: Clock
    started_at: str
    running_status: dict[str, Any]


def run_external_job(
    request: dict[str, Any],
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    job_root: Path | None = None,
    verdict: str = "PASS",
    complete: bool = True,
    cost_micros: int = 0,
    reported_tokens: int = 0,
    child_requests: list[dict[str, Any]] | None = None,
    cancel_event: threading.Event | None = None,
    process_runner: ProcessRunner = run_process,
    now: Clock | None = None,
    post_terminal_quiet_seconds: float = 0.05,
    preparation: PreparationAdmission | None = None,
    review_preflight: Callable[[], dict[str, Any]] | None = None,
    recover_existing: bool = False,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    """Execute one adapter-owned process and persist an immutable attempt record."""

    require_external_job_pass(validate_external_job_request(request), "request")
    _require_portable_request_metadata(request)
    if recover_existing and external_job_attempt_path(
        request, job_root=job_root,
    ).exists():
        return recover_external_job_attempt(request, job_root=job_root)
    if not argv or not all(isinstance(item, str) and item and "\x00" not in item for item in argv):
        raise LifecycleError("external-job-argv-invalid", "external job argv must be a non-empty string list")
    limits = request["limits"]
    _require_usage_bound(cost_micros, limits["maxCostMicros"], "costMicros")
    _require_usage_bound(reported_tokens, limits["maxReportedTokens"], "reportedTokens")
    children = _validated_children(request, child_requests or [])
    preflight_receipt = None
    if review_preflight is not None:
        # The callback cannot replace the invocation while qualifying it.
        request, argv, env = copy.deepcopy(request), list(argv), dict(env)
        cwd = (cwd or Path.cwd()).resolve()
        preflight_receipt = _require_review_preflight(
            review_preflight, request=request, argv=argv, cwd=cwd,
            stdin_text=stdin_text,
        )
    if preparation is not None:
        _require_prior_job_settled(
            request, job_root=job_root, preparation=preparation,
        )
        preparation.check(repository_root=cwd or Path.cwd())
    context = _prepare_external_job(request, children, job_root=job_root, now=now)
    if preflight_receipt is not None:
        create_private_json(
            context.attempt_root / "review-preflight.json", preflight_receipt,
        )
    invocation_started_ns = time.monotonic_ns()

    def invoke() -> tuple[dict[str, Any], threading.Event]:
        if preparation is not None:
            _require_prior_job_settled(
                request, job_root=job_root, preparation=preparation,
            )
        if review_preflight is not None:
            current_preflight = _require_review_preflight(
                review_preflight, request=request, argv=argv,
                cwd=cwd or Path.cwd(), stdin_text=stdin_text,
            )
            if current_preflight != preflight_receipt:
                raise LifecycleError(
                    "REVIEW_PREFLIGHT_UNAVAILABLE", "Review qualification changed",
                )
        return _invoke_external_job_process(
            context, argv, env=env, cwd=cwd, cancel_event=cancel_event,
            process_runner=process_runner,
            stdin_text=stdin_text,
        )

    process, local_cancel = (
        preparation.invoke(
            invoke, input_digest=request["requestDigest"],
            repository_root=cwd or Path.cwd(),
        )
        if preparation is not None else invoke()
    )
    observed_elapsed_ms = max(0, (time.monotonic_ns() - invocation_started_ns) // 1_000_000)
    return _finalize_external_job(
        context,
        process,
        local_cancel,
        observed_elapsed_ms=observed_elapsed_ms,
        verdict=verdict,
        complete=complete,
        cost_micros=cost_micros,
        reported_tokens=reported_tokens,
        post_terminal_quiet_seconds=post_terminal_quiet_seconds,
    )


def _require_review_preflight(
    check: Callable[[], dict[str, Any]], *, request: dict[str, Any],
    argv: list[str], cwd: Path, stdin_text: str | None,
) -> dict[str, Any]:
    try:
        if not isinstance(stdin_text, str):
            raise ValueError("Qualified STDIN delivery required")
        expected = review_invocation_digest(
            request=request, argv=argv,
            root_digest=canonical_digest(str(cwd.resolve())),
            rendered_input=stdin_text.encode("utf-8"),
        )
        receipt = check()
        if set(receipt) != REVIEW_PREFLIGHT_FIELDS:
            raise ValueError("Closed portable preflight required")
        body = {k: v for k, v in receipt.items() if k != "preflightDigest"}
        if (
            receipt.get("status") != "PASS"
            or receipt.get("requestDigest") != request["requestDigest"]
            or receipt.get("sourceSnapshotDigest")
            != request["sourceSnapshotDigest"]
            or receipt.get("invocationDigest") != expected
            or receipt.get("preflightDigest") != canonical_digest(body)
            or receipt.get("schemaVersion") != "agent-reviewer-preflight.v1"
            or receipt.get("reason") != "READY"
            or receipt.get("authorityClaimed") is not False
            or receipt.get("productionPromotionClaimed") is not False
            or type(receipt.get("modelCalls")) is not int
            or receipt["modelCalls"] != 0
            or not isinstance(receipt.get("packetDigest"), str)
            or len(receipt["packetDigest"]) != 64
            or any(v not in "0123456789abcdef"
                   for v in receipt["packetDigest"])
        ):
            raise ValueError("Qualified actual invocation required")
        return dict(receipt)
    except (ValueError, KeyError, TypeError, LifecycleError) as exc:
        raise LifecycleError(
            "REVIEW_PREFLIGHT_UNAVAILABLE", "Qualified reviewer input required",
        ) from exc


def _require_prior_job_settled(
    request: dict[str, Any], *, job_root: Path | None,
    preparation: PreparationAdmission,
) -> None:
    """Generation retry defaults to zero on selected preparation routes."""
    if request["attempt"] <= 1:
        return
    root = external_job_attempt_path(request, job_root=job_root).parent
    previous = root / ("attempt-" + str(request["attempt"] - 1))
    try:
        prior_request = _load_private_json(previous / "request.json", "prior request")
        if any(prior_request[k] != value for k, value in request.items()
               if k not in {"attempt", "requestDigest"}):
            raise ValueError("Immutable review subject changed")
        prior = load_external_job_attempt(prior_request, job_root=job_root)
        status, result, process = (
            prior["jobStatus"], prior["result"], prior["processReceipt"],
        )
        require_external_job_pass(
            validate_external_job_status(status, request=prior_request), "status",
        )
        require_external_job_pass(validate_external_job_result(
            result, request=prior_request, status=status,
        ), "result")
        if (
            status["state"] != "FAILED" or result["complete"] is not False
            or result["outputBytes"] != 0 or not isinstance(process, dict)
            or validate_process_execution_receipt(process)["status"] != "PASS"
            or process["exitCode"] != 75 or process["timedOut"] is not False
            or process["cancelled"] is not False
            or process["cleanup"]["status"] != "PASS"
        ):
            raise ValueError("No settled bounded transient failure")
        preparation.check_retry(
            prior_request_digest=prior_request["requestDigest"],
            prior_result_digest=result["resultDigest"],
            retry_ordinal=request["attempt"] - 1,
        )
    except (OSError, TypeError, ValueError, KeyError, LifecycleError) as exc:
        raise LifecycleError(
            "REVIEW_ROUTE_SUSPENDED", "Recover/resolve the original attempt first",
        ) from exc


def recover_external_job_attempt(
    request: dict[str, Any], *, job_root: Path | None = None,
) -> dict[str, Any]:
    """Retrieve the same complete response without generation or new usage."""
    try:
        return _recover_complete_attempt(request, job_root=job_root)
    except (OSError, ValueError, KeyError, TypeError, LifecycleError) as exc:
        reason = "REVIEW_RECOVERY_INVALID"
        if isinstance(exc, LifecycleError) and exc.code in {
            "REVIEW_REMOTE_UNRESOLVED", "REVIEW_ROUTE_SUSPENDED",
            "REVIEW_RESPONSE_UNAVAILABLE",
        }:
            reason = exc.code
        raise LifecycleError(reason, "Complete reusable response unavailable") from exc


def _recover_complete_attempt(
    request: dict[str, Any], *, job_root: Path | None,
) -> dict[str, Any]:
    view = load_external_job_attempt(request, job_root=job_root)
    status, result = view["jobStatus"], view["result"]
    require_external_job_pass(
        validate_external_job_status(status, request=request), "status",
    )
    if result is None or status["state"] not in TERMINAL_JOB_STATES:
        raise LifecycleError(
            "REVIEW_REMOTE_UNRESOLVED", "Remote outcome remains unavailable",
        )
    require_external_job_pass(
        validate_external_job_result(result, request=request, status=status),
        "result",
    )
    if result["complete"] is not True or not result["blockingEligible"]:
        raise LifecycleError(
            "REVIEW_ROUTE_SUSPENDED", "No complete reusable response",
        )
    _require_portable_recovery_records(request, status, result)
    root = external_job_attempt_path(request, job_root=job_root)
    running = _load_private_json(_status_path(root, 1), "running status")
    transition = validate_external_job_transition(running, status, request=request)
    require_external_job_pass(transition, "transition")
    for artifact in result["artifacts"]:
        path = root / artifact["locator"]
        if not path.resolve().is_relative_to(root.resolve()):
            raise LifecycleError("REVIEW_RECOVERY_INVALID", "Artifact changed")
        data = read_stable_repository_file(
            root, artifact["locator"], max_bytes=max(1, artifact["bytes"]),
            label="recovered artifact",
        )
        if (hashlib.sha256(data).hexdigest() != artifact["sha256"]
                or len(data) != artifact["bytes"]):
            raise LifecycleError("REVIEW_RECOVERY_INVALID", "Artifact changed")
    # Original process diagnostics remain in the immutable local attempt.
    # Recovery exports the same semantic result/usage, never raw stored extras.
    _read_complete_response(root, request, result)
    view = _attempt_view(request, status, result, None, transition)
    if len(canonical_bytes(view)) > 65536:
        raise ValueError("Portable recovery exceeds its bound")
    return view


def _require_portable_recovery_records(
    request: dict[str, Any], status: dict[str, Any], result: dict[str, Any],
) -> None:
    """Refuse unsupported extras without rewriting an accepting identity."""
    normalized_request = build_external_job_request(
        job_id=request["jobId"], attempt=request["attempt"],
        adapter_id=request["adapterId"], operation=request["operation"],
        execution_kind=request["executionKind"],
        descriptor_digest=request["descriptorDigest"],
        plan_digest=request["planDigest"], plan_lock_digest=request["planLockDigest"],
        source_revision=request["sourceRevision"],
        source_snapshot_digest=request["sourceSnapshotDigest"], limits=request["limits"],
        parent_job_id=request["parentJobId"], parent_attempt=request["parentAttempt"],
        parent_request_digest=request["parentRequestDigest"],
    )
    normalized_status = build_external_job_status(
        request=request, state=status["state"], sequence=status["sequence"],
        observed_at=status["observedAt"], usage=status["usage"],
        started_at=status["startedAt"], ended_at=status["endedAt"],
        children=status["children"], cancel_requested=status["cancelRequested"],
        process_cleanup_status=status["processCleanupStatus"],
        post_terminal_write_detected=status["postTerminalWriteDetected"],
        observation=status.get("observation"),
    )
    artifacts = [build_external_job_artifact(
        request=request, artifact_id=item["artifactId"], media_type=item["mediaType"],
        bytes_count=item["bytes"], sha256=item["sha256"], locator=item["locator"],
    ) for item in result["artifacts"]]
    normalized_result = build_external_job_result(
        result_id=result["resultId"], request=request, status=status,
        verdict=result["verdict"], complete=result["complete"], artifacts=artifacts,
        output_digest=result["outputDigest"], output_bytes=result["outputBytes"],
        blockers=[],
    )
    for original, normalized in (
        (request, normalized_request), (status, normalized_status),
        (result, normalized_result),
    ):
        _, changed = redact_value(original)
        if original != normalized or changed:
            raise ValueError("Unsupported or sensitive recovery metadata")


def _read_complete_response(
    root: Path, request: dict[str, Any], result: dict[str, Any],
) -> dict[str, str]:
    body = {}
    for stream in ("stdout", "stderr"):
        name = "response." + stream
        try:
            require_private_file(root / name)
            data = read_stable_repository_file(
                root, name, max_bytes=request["limits"]["maxOutputBytes"],
                label="private recovered response",
            )
        except (OSError, LifecycleError) as exc:
            raise LifecycleError(
                "REVIEW_RESPONSE_UNAVAILABLE", "Durable response unavailable",
            ) from exc
        body[stream] = data.decode("utf-8")
    count = sum(len(value.encode("utf-8")) for value in body.values())
    expected = canonical_digest(body) if count else None
    if count != result["outputBytes"] or expected != result["outputDigest"]:
        raise ValueError("Durable response identity changed")
    return body


def load_external_job_response(
    request: dict[str, Any], *, job_root: Path | None = None,
) -> dict[str, str]:
    """Host-local bounded response input for parsing/import; never CLI output."""
    view = recover_external_job_attempt(request, job_root=job_root)
    return _read_complete_response(
        external_job_attempt_path(request, job_root=job_root), request,
        view["result"],
    )


def _prepare_external_job(
    request: dict[str, Any],
    children: list[dict[str, Any]],
    *,
    job_root: Path | None,
    now: Clock | None,
) -> _JobContext:
    root = _external_job_root(job_root)
    attempt_root = _create_attempt_root(request, root)
    artifact_root = attempt_root / "artifacts"
    create_private_json(attempt_root / "request.json", request)
    _ensure_artifact_directory(artifact_root)
    clock = now or _utc_now
    child_refs = [_child_reference(item) for item in children]
    queued = build_external_job_status(
        request=request,
        state="QUEUED",
        sequence=0,
        observed_at=clock(),
        children=child_refs,
    )
    create_private_json(_status_path(attempt_root, 0), queued)
    started_at = clock()
    running = build_external_job_status(
        request=request,
        state="RUNNING",
        sequence=1,
        observed_at=started_at,
        started_at=started_at,
        children=child_refs,
    )
    running_transition = validate_external_job_transition(queued, running, request=request)
    _require_transition_pass(running_transition)
    create_private_json(_status_path(attempt_root, 1), running)
    create_private_json(attempt_root / "transition-000001.json", running_transition)
    return _JobContext(
        request=request,
        root=root,
        attempt_root=attempt_root,
        artifact_root=artifact_root,
        children=children,
        child_refs=child_refs,
        clock=clock,
        started_at=started_at,
        running_status=running,
    )


def _invoke_external_job_process(
    context: _JobContext,
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None,
    cancel_event: threading.Event | None,
    process_runner: ProcessRunner,
    stdin_text: str | None = None,
) -> tuple[dict[str, Any], threading.Event]:
    local_cancel = threading.Event()
    monitor_stop = threading.Event()
    monitor = threading.Thread(
        target=_monitor_cancel,
        args=(context.attempt_root / "cancel-request.json", local_cancel, monitor_stop, cancel_event),
        daemon=True,
    )
    monitor.start()
    process_env = dict(env)
    process_env["ALK_EXTERNAL_JOB_ARTIFACT_DIR"] = str(context.artifact_root.resolve())
    request = context.request
    limits = request["limits"]
    try:
        process = process_runner(
            argv,
            env=process_env,
            timeout_seconds=float(limits["maxWallSeconds"]),
            cwd=cwd,
            max_output_bytes=limits["maxOutputBytes"],
            operation_id=request["operation"],
            attempt_id=f"{request['jobId']}-attempt-{request['attempt']}",
            adapter_id=request["adapterId"],
            cancel_event=local_cancel,
            cleanup_grace_seconds=float(limits["cancelGraceSeconds"]),
            **({"stdin_text": stdin_text, "max_input_bytes": 1024 * 1024}
               if stdin_text is not None else {}),
        )
    finally:
        create_private_json(
            context.attempt_root / "completion-observed.json",
            {"schemaVersion": "agent-external-job-completion-observed.v1", "observedAt": context.clock()},
        )
        if (context.attempt_root / "cancel-request.json").exists():
            local_cancel.set()
        monitor_stop.set()
        monitor.join(timeout=1.0)
    return process, local_cancel


def _finalize_external_job(
    context: _JobContext,
    process: dict[str, Any],
    local_cancel: threading.Event,
    *,
    observed_elapsed_ms: int,
    verdict: str,
    complete: bool,
    cost_micros: int,
    reported_tokens: int,
    post_terminal_quiet_seconds: float,
) -> dict[str, Any]:
    request = context.request
    limits = request["limits"]
    child_statuses, child_blockers = _cancel_and_settle_children(
        context.children,
        root=context.root,
        grace_seconds=float(limits["cancelGraceSeconds"]),
        clock=context.clock,
    )
    artifacts, artifact_blockers, post_terminal_write = _settle_artifacts(
        request, context.artifact_root, quiet_seconds=post_terminal_quiet_seconds
    )

    response_blockers = _capture_private_response(context, process)
    blockers = [*process.get("blockers", []), *child_blockers, *artifact_blockers,
                *response_blockers]
    elapsed_ms = _elapsed_ms(process, observed_elapsed_ms=observed_elapsed_ms)
    wall_limit_ms = int(limits["maxWallSeconds"]) * 1000
    if elapsed_ms > wall_limit_ms:
        blockers.append({"code": "external-job-wall-limit-exceeded"})
    if local_cancel.is_set() and not process.get("cancelled"):
        blockers.append({"code": "external-job-cancelled-after-process-exit"})
    if post_terminal_write:
        blockers.append({"code": "external-job-post-terminal-write"})
    state = _terminal_state(
        process, verdict=verdict, complete=complete, blockers=blockers, cancel_requested=local_cancel.is_set()
    )
    cleanup_status = "PASS" if process.get("cleanup", {}).get("status") == "PASS" else "FAIL"
    if child_blockers:
        cleanup_status = "FAIL"
    usage = {
        # The process receipt retains cleanup-inclusive elapsed time. Portable job
        # usage is bounded to the execution budget so timeout cleanup can still
        # produce immutable terminal evidence instead of failing finalization.
        "wallMilliseconds": min(elapsed_ms, wall_limit_ms),
        "outputBytes": int(process.get("outputBytes", 0)),
        "artifactBytes": sum(item["bytes"] for item in artifacts),
        "costMicros": cost_micros,
        "reportedTokens": reported_tokens,
    }
    ended_at = context.clock()
    terminal = build_external_job_status(
        request=request,
        state=state,
        sequence=2,
        observed_at=ended_at,
        started_at=context.started_at,
        ended_at=ended_at,
        children=context.child_refs,
        usage=usage,
        cancel_requested=bool(process.get("cancelled") or local_cancel.is_set()),
        process_cleanup_status=cleanup_status,
        post_terminal_write_detected=post_terminal_write,
    )
    terminal_transition = validate_external_job_transition(
        context.running_status,
        terminal,
        request=request,
        child_requests=context.children,
        child_statuses=child_statuses,
    )
    if terminal_transition["status"] != "PASS":
        blockers.extend(terminal_transition["blockers"])
    blockers = _bounded_blockers(blockers)
    result_verdict = verdict if state == "SUCCEEDED" else "NO_FINAL_VERDICT"
    output_bytes = int(process.get("outputBytes", 0))
    output_digest = _output_digest(process) if output_bytes else None
    result = build_external_job_result(
        result_id=f"{request['jobId']}-attempt-{request['attempt']}",
        request=request,
        status=terminal,
        verdict=result_verdict,
        complete=bool(complete and state == "SUCCEEDED" and not blockers),
        artifacts=artifacts,
        output_digest=output_digest,
        output_bytes=output_bytes,
        blockers=blockers,
    )
    create_private_json(_status_path(context.attempt_root, 2), terminal)
    create_private_json(context.attempt_root / "transition-000002.json", terminal_transition)
    if process["processReceipt"] is not None:
        create_private_json(context.attempt_root / "process-receipt.json", process["processReceipt"])
    create_private_json(context.attempt_root / "result.json", result)
    return _attempt_view(request, terminal, result, process["processReceipt"], terminal_transition)


def _capture_private_response(
    context: _JobContext, process: dict[str, Any],
) -> list[dict[str, str]]:
    """Durable complete/partial delivery in the existing private attempt."""
    limit = context.request["limits"]["maxOutputBytes"]
    remaining = limit
    truncated = False
    for stream in ("stdout", "stderr"):
        value = process.get(stream, "")
        if not isinstance(value, str):
            raise LifecycleError(
                "REVIEW_RESPONSE_UNAVAILABLE", "Response encoding unavailable",
            )
        data = value.encode("utf-8")
        truncated = truncated or len(data) > remaining
        selected = data[:remaining]
        remaining -= len(selected)
        create_authority_bytes(
            context.attempt_root / ("response." + stream), selected, private=True,
        )
    return [{"code": "external-job-response-byte-limit"}] if truncated else []


def _settle_artifacts(
    request: dict[str, Any], artifact_root: Path, *, quiet_seconds: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    artifacts, blockers, first_snapshot = _collect_artifacts(request, artifact_root)
    if quiet_seconds > 0:
        time.sleep(min(quiet_seconds, 1.0))
    _, quiet_blockers, second_snapshot = _collect_artifacts(request, artifact_root)
    return artifacts, [*blockers, *quiet_blockers], first_snapshot != second_snapshot


def request_external_job_cancel(
    request: dict[str, Any],
    *,
    job_root: Path | None = None,
    now: Clock | None = None,
) -> dict[str, Any]:
    """Acknowledge cancellation-request publication, not process termination."""

    require_external_job_pass(validate_external_job_request(request), "request")
    attempt_root = external_job_attempt_path(request, job_root=job_root)
    stored = _load_private_json(attempt_root / "request.json", "external job request")
    if stored.get("requestDigest") != request.get("requestDigest"):
        raise LifecycleError("external-job-cancel-lineage-mismatch", "cancel request does not match stored attempt")
    latest = _latest_status(attempt_root)
    if latest.get("state") in TERMINAL_JOB_STATES:
        return _cancel_receipt(request, latest, requested_at=None, idempotent=True, terminal=True)
    completion_path = attempt_root / "completion-observed.json"
    if completion_path.exists():
        return _cancel_receipt(request, latest, requested_at=None, idempotent=True, terminal=True)
    path = attempt_root / "cancel-request.json"
    if path.exists():
        existing = _load_private_json(path, "external job cancel request")
        return _cancel_receipt(request, latest, requested_at=existing.get("requestedAt"), idempotent=True)
    requested_at = (now or _utc_now)()
    body = {
        "schemaVersion": _CANCEL_SCHEMA,
        "jobId": request["jobId"],
        "attempt": request["attempt"],
        "requestDigest": request["requestDigest"],
        "requestedAt": requested_at,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    try:
        create_private_json(path, {**body, "cancelDigest": canonical_digest(body)})
    except FileExistsError:
        existing = _load_private_json(path, "external job cancel request")
        return _cancel_receipt(request, latest, requested_at=existing.get("requestedAt"), idempotent=True)
    # Completion after publication cannot turn this creator into a no-op retry.
    return _cancel_receipt(request, latest, requested_at=requested_at, idempotent=False)


def load_external_job_attempt(request: dict[str, Any], *, job_root: Path | None = None) -> dict[str, Any]:
    """Load the latest bounded view of one immutable attempt namespace."""

    require_external_job_pass(validate_external_job_request(request), "request")
    attempt_root = external_job_attempt_path(request, job_root=job_root)
    stored = _load_private_json(attempt_root / "request.json", "external job request")
    if stored.get("requestDigest") != request.get("requestDigest"):
        raise LifecycleError("external-job-attempt-lineage-mismatch", "stored attempt request does not match")
    status = _latest_status(attempt_root)
    result_path = attempt_root / "result.json"
    process_path = attempt_root / "process-receipt.json"
    transition_path = attempt_root / "transition-000002.json"
    result = _load_private_json(result_path, "external job result") if result_path.exists() else None
    process = _load_private_json(process_path, "external job process receipt") if process_path.exists() else None
    transition = _load_private_json(transition_path, "external job transition") if transition_path.exists() else None
    return _attempt_view(stored, status, result, process, transition)


def external_job_attempt_path(request: dict[str, Any], *, job_root: Path | None = None) -> Path:
    """Resolve an existing attempt below the controlled external-job root."""

    require_external_job_pass(validate_external_job_request(request), "request")
    root = _external_job_root(job_root)
    session_path(request["jobId"], session_root=root)
    path = root / request["jobId"] / f"attempt-{request['attempt']}"
    if not path.resolve().is_relative_to(root.resolve()):
        raise LifecycleError("external-job-path-escape", "external job attempt escapes its storage root")
    return path


def _external_job_root(job_root: Path | None) -> Path:
    return job_root or Path(DEFAULT_EXTERNAL_JOB_ROOT)


def _create_attempt_root(request: dict[str, Any], root: Path) -> Path:
    from agent_lifecycle.contracts.canonical import ensure_private_directory

    session_path(request["jobId"], session_root=root)
    ensure_private_directory(root)
    job_path = root / request["jobId"]
    ensure_private_directory(job_path)
    attempt_path = job_path / f"attempt-{request['attempt']}"
    if not attempt_path.resolve().is_relative_to(root.resolve()):
        raise LifecycleError("external-job-path-escape", "external job attempt escapes its storage root")
    try:
        attempt_path.mkdir(mode=0o700, exist_ok=False)
        if os.name != "nt":
            attempt_path.chmod(0o700)
    except FileExistsError as exc:
        raise LifecycleError("external-job-attempt-exists", "external job attempt namespace already exists") from exc
    except OSError as exc:
        raise LifecycleError("external-job-attempt-create-failed", "external job attempt could not be created") from exc
    return attempt_path


def _ensure_artifact_directory(path: Path) -> None:
    from agent_lifecycle.contracts.canonical import ensure_private_directory

    ensure_private_directory(path)


def _status_path(attempt_root: Path, sequence: int) -> Path:
    return attempt_root / f"status-{sequence:06d}.json"


def _latest_status(attempt_root: Path) -> dict[str, Any]:
    paths = sorted(attempt_root.glob("status-*.json"))
    if not paths:
        raise LifecycleError("external-job-status-missing", "external job attempt has no status")
    return _load_private_json(paths[-1], "external job status")


def _load_private_json(path: Path, label: str) -> dict[str, Any]:
    last_error: LifecycleError | None = None
    for _ in range(5):
        try:
            require_private_json(path)
            return read_json_object(path, label=label)
        except LifecycleError as exc:
            last_error = exc
            time.sleep(0.01)
    assert last_error is not None
    raise last_error


def _monitor_cancel(
    cancel_path: Path,
    local_event: threading.Event,
    stop_event: threading.Event,
    caller_event: threading.Event | None,
) -> None:
    while not stop_event.is_set():
        if cancel_path.exists() or (caller_event is not None and caller_event.is_set()):
            local_event.set()
            return
        stop_event.wait(_POLL_SECONDS)


def _validated_children(parent: dict[str, Any], children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for child in children:
        require_external_job_pass(validate_external_job_request(child), "child request")
        identity = (child["jobId"], child["attempt"])
        if identity in seen:
            raise LifecycleError("external-job-child-duplicate", "child request is duplicated")
        seen.add(identity)
        if (
            child.get("parentJobId") != parent.get("jobId")
            or child.get("parentAttempt") != parent.get("attempt")
            or child.get("parentRequestDigest") != parent.get("requestDigest")
        ):
            raise LifecycleError(
                "external-job-child-parent-lineage-mismatch", "child request has different parent lineage"
            )
        checked.append(dict(child))
    return checked


def _child_reference(child: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": child["jobId"],
        "attempt": child["attempt"],
        "requestDigest": child["requestDigest"],
        "parentRequestDigest": child["parentRequestDigest"],
    }


def _cancel_and_settle_children(
    children: list[dict[str, Any]],
    *,
    root: Path,
    grace_seconds: float,
    clock: Clock,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    for child in children:
        try:
            request_external_job_cancel(child, job_root=root, now=clock)
        except LifecycleError as exc:
            blockers.append({"code": "external-job-child-cancel-failed", "jobId": child["jobId"], "reason": exc.code})
    # ProcessGroupOwner may spend one grace window on TERM and another on
    # verifying or escalating the group. Keep the parent wait bounded while
    # allowing the composed cleanup contract to finish and publish status.
    deadline = time.monotonic() + max(0.15, grace_seconds * 3)
    statuses: list[dict[str, Any]] = []
    for child in children:
        status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                status = load_external_job_attempt(child, job_root=root)["jobStatus"]
            except LifecycleError:
                status = None
            if status is not None and status.get("state") in TERMINAL_JOB_STATES:
                break
            time.sleep(_POLL_SECONDS)
        if status is None:
            blockers.append({"code": "external-job-child-status-missing", "jobId": child["jobId"]})
            continue
        statuses.append(status)
        if status.get("state") not in TERMINAL_JOB_STATES:
            blockers.append({"code": "external-job-child-live", "jobId": child["jobId"]})
        elif status.get("processCleanupStatus") not in {"PASS", "NOT_REQUIRED"}:
            blockers.append({"code": "external-job-child-cleanup-failed", "jobId": child["jobId"]})
        elif status.get("postTerminalWriteDetected") is not False:
            blockers.append({"code": "external-job-child-post-terminal-write", "jobId": child["jobId"]})
    return statuses, blockers


def _collect_artifacts(
    request: dict[str, Any], artifact_root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    limits = request["limits"]
    artifacts: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    snapshot: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        entries = sorted(artifact_root.rglob("*"), key=lambda item: item.relative_to(artifact_root).as_posix())
        for path in entries:
            relative = path.relative_to(artifact_root).as_posix()
            if path.is_symlink():
                raise LifecycleError("external-job-artifact-symlink", "artifact namespace must not contain symlinks")
            if path.is_dir():
                if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o700:
                    path.chmod(0o700)
                directory_stat = path.stat()
                snapshot.append(
                    {
                        "locator": f"artifacts/{relative}/",
                        "device": directory_stat.st_dev,
                        "inode": directory_stat.st_ino,
                        "modifiedNs": directory_stat.st_mtime_ns,
                        "changedNs": directory_stat.st_ctime_ns,
                    }
                )
                continue
            if not path.is_file():
                raise LifecycleError("external-job-artifact-type", "artifact namespace contains a special file")
            if len(artifacts) >= limits["maxArtifacts"]:
                raise LifecycleError("external-job-artifact-count-limit", "artifact count exceeds request limit")
            if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
                path.chmod(0o600)
            digest, size, file_identity = _stable_file_digest(path)
            total_bytes += size
            if total_bytes > limits["maxArtifactBytes"]:
                raise LifecycleError("external-job-artifact-byte-limit", "artifact bytes exceed request limit")
            locator = f"artifacts/{relative}"
            media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
            artifact = build_external_job_artifact(
                request=request,
                artifact_id=f"artifact-{canonical_digest({'locator': locator})[:24]}",
                media_type=media_type,
                bytes_count=size,
                sha256=digest,
                locator=locator,
            )
            artifacts.append(artifact)
            snapshot.append({"locator": locator, "bytes": size, "sha256": digest, **file_identity})
    except (LifecycleError, OSError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "external-job-artifact-read-failed"
        blockers.append({"code": code})
    return artifacts, blockers, canonical_digest(snapshot)


def _stable_file_digest(path: Path) -> tuple[str, int, dict[str, int]]:
    before = path.stat()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    after = path.stat()
    if _stat_identity(before) != _stat_identity(after) or size != after.st_size:
        raise LifecycleError("external-job-artifact-read-race", "artifact changed while it was read")
    return (
        digest.hexdigest(),
        size,
        {
            "device": after.st_dev,
            "inode": after.st_ino,
            "modifiedNs": after.st_mtime_ns,
            "changedNs": after.st_ctime_ns,
        },
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _terminal_state(
    process: dict[str, Any],
    *,
    verdict: str,
    complete: bool,
    blockers: list[dict[str, Any]],
    cancel_requested: bool,
) -> str:
    if process.get("cancelled") or cancel_requested:
        return "CANCELLED"
    if process.get("timedOut"):
        return "EXPIRED"
    if process.get("status") != "PASS" or blockers:
        return "FAILED"
    if verdict == "NO_FINAL_VERDICT" or not complete:
        return "FAILED"
    return "SUCCEEDED"


def _elapsed_ms(process: dict[str, Any], *, observed_elapsed_ms: int) -> int:
    receipt = process.get("processReceipt")
    timing = receipt.get("timing") if isinstance(receipt, dict) else None
    value = timing.get("elapsedMs") if isinstance(timing, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, int(value))
    # Started failures deliberately withhold process authority. Retain the real
    # caller-observed execution/cleanup interval without inventing a receipt.
    return observed_elapsed_ms


def _output_digest(process: dict[str, Any]) -> str:
    return canonical_digest({"stdout": process.get("stdout", ""), "stderr": process.get("stderr", "")})


def _require_usage_bound(value: int, maximum: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise LifecycleError("external-job-usage-limit", f"{label} exceeds the request limit")


def _require_portable_request_metadata(request: dict[str, Any]) -> None:
    for field in ("adapterId", "operation", "sourceRevision"):
        value = request[field]
        if redact_text(value)[1]:
            raise LifecycleError(
                "external-job-request-sensitive-metadata",
                f"{field} contains a private path or secret-like value",
            )


def _bounded_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        digest = canonical_digest(blocker)
        if digest in seen:
            continue
        seen.add(digest)
        result.append(blocker)
        if len(result) == 128:
            break
    return result


def _require_transition_pass(validation: dict[str, Any]) -> None:
    if validation.get("status") != "PASS":
        raise LifecycleError("external-job-transition-invalid", "external job transition failed", validation)


def _cancel_receipt(
    request: dict[str, Any],
    status: dict[str, Any],
    *,
    requested_at: str | None,
    idempotent: bool,
    terminal: bool = False,
) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-external-job-cancel-receipt.v1",
        "status": "NOT_REQUIRED" if terminal else "PASS",
        "jobId": request["jobId"],
        "attempt": request["attempt"],
        "requestDigest": request["requestDigest"],
        "observedState": status.get("state"),
        "requestedAt": requested_at,
        "idempotent": idempotent,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _attempt_view(
    request: dict[str, Any],
    status: dict[str, Any],
    result: dict[str, Any] | None,
    process_receipt: dict[str, Any] | None,
    transition: dict[str, Any] | None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": _VIEW_SCHEMA,
        "status": "FAIL" if transition is not None and transition.get("status") != "PASS" else "PASS",
        "request": request,
        "jobStatus": status,
        "result": result,
        "processReceipt": process_receipt,
        "transitionValidation": transition,
        "privatePathsStored": False,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "viewDigest": canonical_digest(body)}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "DEFAULT_EXTERNAL_JOB_ROOT",
    "external_job_attempt_path",
    "load_external_job_attempt",
    "request_external_job_cancel",
    "run_external_job",
]
