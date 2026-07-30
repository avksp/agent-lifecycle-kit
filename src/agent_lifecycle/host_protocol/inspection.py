"""Safe adapter capability inspection without live model invocation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.host_protocol.inspection_common import (
    CommandRun,
    CommandRunner,
    _default_command_runner,
    _display_binary,
    _relative_display_path,
)
from agent_lifecycle.host_protocol.inspection_cursor import _inspect_cursor
from agent_lifecycle.host_protocol.inspection_gemini_cli import _inspect_gemini_cli
from agent_lifecycle.host_protocol.inspection_hermes import _inspect_hermes
from agent_lifecycle.host_protocol.inspection_kimi_code import _inspect_kimi_code
from agent_lifecycle.host_protocol.inspection_opencode import _inspect_opencode
from agent_lifecycle.host_protocol.inspection_qwen_code import _inspect_qwen_code
from agent_lifecycle.host_protocol.validation import validate_adapter_descriptor

SCHEMA_VERSION = "agent-host-adapter-inspection.v1"


def inspect_adapter_descriptor(
    descriptor: dict[str, Any],
    *,
    descriptor_path: Path | None = None,
    host_bin: str | None = None,
    project_root: Path | None = None,
    skip_host_commands: bool = False,
    timeout_seconds: float = 10.0,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Inspect descriptor and safe host capabilities without starting a task."""

    if timeout_seconds <= 0:
        raise LifecycleError("invalid-adapter-inspect-timeout", "adapter inspect timeout must be positive")

    root = (project_root or Path(".")).resolve()
    validation = validate_adapter_descriptor(descriptor)
    blockers = list(validation["blockers"])
    checks: list[dict[str, Any]] = [
        {
            "name": "descriptor-validation",
            "status": validation["status"],
            "details": {
                "operationCount": validation["operationCount"],
                "blockerCount": len(validation["blockers"]),
            },
        }
    ]
    operations = descriptor.get("operations", [])
    operation_names = [item.get("name") for item in operations if isinstance(item, dict) and isinstance(item.get("name"), str)]
    capabilities: dict[str, Any] = {
        "descriptor": {
            "operationNames": operation_names,
            "unsupportedOperationPolicy": descriptor.get("unsupportedOperationPolicy"),
            "coreSemantics": descriptor.get("coreSemantics"),
        },
        "modelRouting": {
            "profileSupport": (descriptor.get("modelRouting") or {}).get("profileSupport")
            if isinstance(descriptor.get("modelRouting"), dict)
            else None,
            "liveVerified": (descriptor.get("modelRouting") or {}).get("liveVerified")
            if isinstance(descriptor.get("modelRouting"), dict)
            else None,
            "providerModelNamesInCore": (descriptor.get("modelRouting") or {}).get("providerModelNamesInCore")
            if isinstance(descriptor.get("modelRouting"), dict)
            else None,
        },
        "hostCommands": {
            "status": "SKIPPED" if skip_host_commands else "UNKNOWN",
            "binary": _display_binary(host_bin or descriptor.get("host")),
        },
    }

    if skip_host_commands:
        checks.append(
            {
                "name": "host-command-discovery",
                "status": "SKIPPED",
                "details": {"reason": "skip-host-commands"},
            }
        )
    else:
        host_checks, host_capabilities, host_blockers = _inspect_known_host(
            descriptor,
            descriptor_path=descriptor_path,
            host_bin=host_bin,
            project_root=root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner or _default_command_runner,
        )
        checks.extend(host_checks)
        capabilities.update(host_capabilities)
        blockers.extend(host_blockers)

    status = "PASS" if not blockers else "FAIL"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "maturity": descriptor.get("maturity"),
        "descriptorDigest": canonical_digest(descriptor),
        "descriptorPath": _relative_display_path(descriptor_path, root) if descriptor_path else None,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
        "capabilities": capabilities,
        "checks": checks,
        "blockers": blockers,
    }


def require_adapter_inspection_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("adapter-inspection-failed", "adapter inspection failed", {"inspection": payload})
    return payload


def _inspect_known_host(
    descriptor: dict[str, Any],
    *,
    descriptor_path: Path | None,
    host_bin: str | None,
    project_root: Path,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    host = descriptor.get("host")
    if host == "opencode":
        return _inspect_opencode(
            descriptor_path=descriptor_path,
            host_bin=host_bin or "opencode",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if host == "hermes":
        return _inspect_hermes(
            descriptor_maturity=descriptor.get("maturity"),
            descriptor_path=descriptor_path,
            host_bin=host_bin or "hermes",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if host == "cursor":
        return _inspect_cursor(
            descriptor_path=descriptor_path,
            host_bin=host_bin or "cursor",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if host == "gemini-cli":
        return _inspect_gemini_cli(
            descriptor_path=descriptor_path,
            host_bin=host_bin or "gemini",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if host == "qwen-code":
        return _inspect_qwen_code(
            descriptor_path=descriptor_path,
            host_bin=host_bin or "qwen",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if host == "kimi-code":
        return _inspect_kimi_code(
            descriptor_path=descriptor_path,
            host_bin=host_bin or "kimi",
            project_root=project_root,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    return (
        [
            {
                "name": "host-command-profile",
                "status": "SKIPPED",
                "details": {"reason": "no-safe-command-profile", "host": host},
            }
        ],
        {"hostCommands": {"status": "SKIPPED", "binary": _display_binary(host_bin or host), "profile": None}},
        [],
    )
