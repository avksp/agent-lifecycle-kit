"""Safe adapter capability inspection without live model invocation."""

from __future__ import annotations

import importlib
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
from agent_lifecycle.host_protocol.inspection_profile import load_inspection_profile
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
        "hostCapabilities": descriptor.get("hostCapabilities") if isinstance(descriptor.get("hostCapabilities"), list) else [],
    }

    host_checks, host_capabilities, host_blockers = _inspect_known_host(
        descriptor,
        descriptor_path=descriptor_path,
        host_bin=host_bin,
        project_root=root,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner or _default_command_runner,
        skip_host_commands=skip_host_commands,
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
    skip_host_commands: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    adapter_id = descriptor.get("adapterId")
    host = descriptor.get("host")
    try:
        profile, profile_info = load_inspection_profile(
            adapter_id if isinstance(adapter_id, str) else "",
            descriptor_path=descriptor_path,
            project_root=project_root,
            host=host if isinstance(host, str) else None,
        )
    except LifecycleError as exc:
        return (
            [
                {
                    "name": "inspection-profile",
                    "status": "FAIL",
                    "details": {"reason": exc.code},
                }
            ],
            {"hostCommands": {"status": "SKIPPED", "binary": _display_binary(host_bin or host), "profile": None}},
            [{"code": exc.code}],
        )

    profile_summary = {
        "status": profile_info["status"],
        "handler": profile_info.get("handler"),
        "profileDigest": profile_info["profileDigest"],
        "path": profile_info["path"],
    }
    if skip_host_commands:
        return (
            [
                {"name": "inspection-profile", "status": "PASS", "details": {"profile": profile_summary}},
                {
                    "name": "host-command-discovery",
                    "status": "SKIPPED",
                    "details": {"reason": "skip-host-commands", "profile": profile_summary},
                },
            ],
            {
                "hostCommands": {
                    "status": "SKIPPED",
                    "binary": _display_binary(host_bin or profile.get("binary") or host),
                    "profile": profile_summary,
                }
            },
            [],
        )
    if profile["status"] == "UNSUPPORTED":
        return (
            [
                {
                    "name": "inspection-profile",
                    "status": "PASS",
                    "details": {"profile": profile_summary},
                },
                {
                    "name": "host-command-profile",
                    "status": "SKIPPED",
                    "details": {"reason": "unsupported-adapter-inspection-profile", "profile": profile_summary},
                },
            ],
            {
                "hostCommands": {
                    "status": "SKIPPED",
                    "binary": _display_binary(host_bin or profile.get("binary") or host),
                    "profile": profile_summary,
                }
            },
            [],
        )

    handler = _load_inspection_handler(str(profile["handler"]))
    checks, capabilities, blockers = handler(
        descriptor_path=descriptor_path,
        host_bin=host_bin or str(profile.get("binary") or host),
        project_root=project_root,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        **({"descriptor_maturity": descriptor.get("maturity")} if profile["handler"] == "hermes" else {}),
    )
    checks.insert(0, {"name": "inspection-profile", "status": "PASS", "details": {"profile": profile_summary}})
    return checks, {**capabilities, "inspectionProfile": profile_summary}, blockers


def _load_inspection_handler(handler_id: str) -> Any:
    """Resolve only the allow-listed bundled evaluator for a profile handler."""

    module_name = f"agent_lifecycle.host_protocol.inspection_{handler_id.replace('-', '_')}"
    module = importlib.import_module(module_name)
    return getattr(module, f"_inspect_{handler_id.replace('-', '_')}")
