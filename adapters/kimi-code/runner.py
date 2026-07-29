"""Bounded kimi-code runner for host-operation requests."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, sha256_hex
from agent_lifecycle.host_protocol import (
    HostOperationReceipt,
    HostOperationRequest,
    normalize_host_operation_receipt,
)
from tools.live_hosts.kimi_code_harness import (
    CommandResult,
    check_clean_worktree,
    parse_kimi_code_stream_json,
)


HOST = "kimi-code"
CommandRunner = Callable[[list[str], Path | None, float], CommandResult]


def run_operation(
    request: dict[str, Any],
    *,
    kimi_bin: str = "kimi",
    kimi_model: str | None = None,
    kimi_fallback_model: str | None = None,
    cwd: str | Path | None = None,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Execute one request through kimi-code and return a portable receipt."""

    operation = HostOperationRequest.from_json(request)
    worktree = Path(cwd) if cwd is not None else None
    model = kimi_model or _string_from_sources("providerModel", "model", sources=(operation.model_route, operation.constraints, operation.inputs))
    fallback_model = kimi_fallback_model or _string_from_sources(
        "fallbackModel",
        "fallback_model",
        sources=(operation.model_route, operation.constraints, operation.inputs),
    )
    command = _kimi_command(
        kimi_bin=kimi_bin,
        capability=operation.capability,
        model=model,
        fallback_model=fallback_model,
    )
    runner = command_runner or _run_command
    result = runner(command, worktree, timeout_seconds)
    _require_clean_git_worktree_after_invocation(worktree, operation.capability)
    if result.returncode != 0:
        raise LifecycleError(
            "kimi-code-live-invocation-failed",
            "kimi-code CLI returned a non-zero status",
            {"host": HOST, "capability": operation.capability, "returncode": result.returncode},
        )
    usage = parse_kimi_code_stream_json(result.stdout, wall_seconds=result.wall_seconds)
    if not usage.has_usage_attestation:
        raise LifecycleError(
            "adapter-usage-attestation-missing",
            "kimi-code stream-json did not expose trustworthy usage",
            {"host": HOST, "capability": operation.capability},
        )
    output = {
        "kind": "kimi-code-stream-json",
        "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")),
        "stderrSha256": sha256_hex(result.stderr.encode("utf-8")),
        "stdoutBytes": len(result.stdout.encode("utf-8")),
        "stderrBytes": len(result.stderr.encode("utf-8")),
        "eventCount": usage.event_count,
    }
    receipt = HostOperationReceipt(
        operation_id=operation.operation_id,
        capability=operation.capability,
        status="PASS",
        outputs=[output],
        usage=usage.to_receipt_usage(),
    ).to_json()
    return normalize_host_operation_receipt(receipt)


def _kimi_command(
    *,
    kimi_bin: str,
    capability: str,
    model: str | None,
    fallback_model: str | None,
) -> list[str]:
    command = [kimi_bin, "--output-format", "stream-json"]
    if model:
        command.extend(["--model", model])
    _ = fallback_model
    command.extend(
        [
            "--prompt",
            (
                "Agent Lifecycle Kit kimi-code adapter operation. "
                f"Operation: {capability}. "
                "Do not modify files. Return a compact JSON object with operation and status PASS."
            ),
        ]
    )
    return command


def _run_command(command: list[str], cwd: Path | None, timeout_seconds: float) -> CommandResult:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    return CommandResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        wall_seconds=round(time.monotonic() - started, 3),
    )


def _require_clean_git_worktree_after_invocation(worktree: Path | None, capability: str) -> None:
    if worktree is None or not (worktree / ".git").exists():
        return
    clean = check_clean_worktree(worktree)
    if not clean.get("clean"):
        raise LifecycleError(
            "kimi-code-worktree-mutated",
            "kimi-code CLI left the worktree dirty",
            {"host": HOST, "capability": capability, "details": clean},
        )


def _string_from_sources(*keys: str, sources: tuple[dict[str, Any] | None, ...]) -> str | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None
