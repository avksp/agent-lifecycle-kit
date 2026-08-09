"""Bounded Qwen Code runner for host-operation requests."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, sha256_hex
from agent_lifecycle.host_protocol import (
    HostOperationReceipt,
    HostOperationRequest,
    build_model_usage_sidecar,
    normalize_host_operation_receipt,
)
from tools.live_hosts.adapter_module_loader import load_adapter_usage_normalizer
from tools.live_hosts.common import CommandResult


HOST = "qwen-code"
CommandRunner = Callable[[list[str], Path | None, float], CommandResult]
_USAGE_NORMALIZER = load_adapter_usage_normalizer(HOST)


def run_operation(
    request: dict[str, Any],
    *,
    qwen_bin: str = "qwen",
    qwen_model: str | None = None,
    qwen_fallback_model: str | None = None,
    cwd: str | Path | None = None,
    timeout_seconds: float = 120.0,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Execute one request through Qwen Code and return a portable receipt."""

    operation = HostOperationRequest.from_json(request)
    worktree = Path(cwd) if cwd is not None else None
    model = qwen_model or _string_from_sources("providerModel", "model", sources=(operation.model_route, operation.constraints, operation.inputs))
    fallback_model = qwen_fallback_model or _string_from_sources(
        "fallbackModel",
        "fallback_model",
        sources=(operation.model_route, operation.constraints, operation.inputs),
    )
    command = _qwen_command(
        qwen_bin=qwen_bin,
        capability=operation.capability,
        model=model,
        fallback_model=fallback_model,
    )
    runner = command_runner or _run_command
    result = runner(command, worktree, timeout_seconds)
    if result.returncode != 0:
        raise LifecycleError(
            "qwen-code-live-invocation-failed",
            "Qwen Code CLI returned a non-zero status",
            {"host": HOST, "capability": operation.capability, "returncode": result.returncode},
        )
    usage = _USAGE_NORMALIZER.parse_usage(
        result.stdout,
        wall_seconds=result.wall_seconds,
        max_bytes=_USAGE_NORMALIZER.max_artifact_bytes,
    )
    if not usage.has_usage_attestation:
        raise LifecycleError(
            "adapter-usage-attestation-missing",
            "Qwen Code stream-json did not expose trustworthy usage",
            {"host": HOST, "capability": operation.capability},
        )
    output = {
        "kind": "qwen-code-stream-json",
        "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")),
        "stderrSha256": sha256_hex(result.stderr.encode("utf-8")),
        "stdoutBytes": len(result.stdout.encode("utf-8")),
        "stderrBytes": len(result.stderr.encode("utf-8")),
        "eventCount": usage.event_count,
    }
    sidecar = _model_usage_sidecar(operation, usage, result.stdout, model, command_runner is not None)
    if sidecar is not None:
        output["modelUsageReceipt"] = sidecar
    receipt = HostOperationReceipt(
        operation_id=operation.operation_id,
        capability=operation.capability,
        status="PASS",
        outputs=[output],
        usage=usage.to_receipt_usage(),
    ).to_json()
    return normalize_host_operation_receipt(receipt)


def _qwen_command(
    *,
    qwen_bin: str,
    capability: str,
    model: str | None,
    fallback_model: str | None,
) -> list[str]:
    command = [qwen_bin, "--safe-mode", "--output-format", "stream-json"]
    if model:
        command.extend(["--model", model])
    if fallback_model:
        command.extend(["--fallback-model", fallback_model])
    command.extend(
        [
            "--prompt",
            (
                "Agent Lifecycle Kit Qwen Code adapter operation. "
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


def _string_from_sources(*keys: str, sources: tuple[dict[str, Any] | None, ...]) -> str | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _model_usage_sidecar(operation: HostOperationRequest, usage, stdout: str, model: str | None, fixture: bool) -> dict[str, Any] | None:
    route = operation.model_route
    if not isinstance(route, dict) or not _digest(route.get("decisionDigest")):
        return None
    model_class = route.get("modelClass") if isinstance(route.get("modelClass"), str) and route["modelClass"] else "standard-code"
    return build_model_usage_sidecar(
        usage=usage,
        operation_id=operation.operation_id,
        adapter_id=HOST,
        host=HOST,
        model_class=model_class,
        provider_model_hash=sha256_hex((model or HOST).encode("utf-8")),
        route_decision_digest=route["decisionDigest"],
        source_bytes=stdout.encode("utf-8"),
        source_format=_USAGE_NORMALIZER.artifact_format,
        source_kind="fixture" if fixture else "host",
        normalizer_status=_USAGE_NORMALIZER.status,
        normalizer_digest=_USAGE_NORMALIZER.digest,
    )


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())
