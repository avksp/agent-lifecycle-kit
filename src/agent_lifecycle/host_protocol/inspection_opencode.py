"""Safe host inspection probes for OpenCode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.host_protocol.inspection_common import (
    CommandRunner,
    _check_cursor_plugin_config,
    _check_hermes_registry,
    _check_hermes_skills_config,
    _check_hermes_slash_commands,
    _check_json_plugin_config,
    _check_scaffold_projection_files,
    _cursor_model_count,
    _cursor_subscription_tier,
    _display_binary,
    _first_non_empty_line,
    _missing_markers,
    _run_command_check,
    _run_command_check_with_text,
)

def _inspect_opencode(
    *,
    descriptor_path: Path | None,
    host_bin: str,
    project_root: Path,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    capabilities: dict[str, Any] = {
        "hostCommands": {
            "status": "CHECKED",
            "binary": _display_binary(host_bin),
            "profile": "opencode-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "resultExport": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "configuration": {},
    }

    root_config = _check_json_plugin_config(
        project_root / "opencode.json",
        project_root=project_root,
        expected_plugin="./adapters/opencode/plugins/agent-lifecycle-kit.js",
        check_name="opencode-root-config",
    )
    checks.append(root_config)
    if root_config["status"] == "FAIL":
        blockers.append({"code": "opencode-root-config-unavailable", "message": "OpenCode root plugin config is missing or invalid"})
    capabilities["configuration"]["rootConfig"] = root_config["details"]

    if descriptor_path is not None:
        adapter_config_path = descriptor_path.parent / "opencode.json"
        adapter_config = _check_json_plugin_config(
            adapter_config_path,
            project_root=project_root,
            expected_plugin="./plugins/agent-lifecycle-kit.js",
            check_name="opencode-adapter-config",
        )
        checks.append(adapter_config)
        if adapter_config["status"] == "FAIL":
            blockers.append({"code": "opencode-adapter-config-unavailable", "message": "OpenCode adapter plugin config is missing or invalid"})
        capabilities["configuration"]["adapterConfig"] = adapter_config["details"]

    version_check, version_text = _run_command_check(
        "opencode-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "opencode-binary-unavailable", "message": "OpenCode binary is unavailable or failed version probing"})
    capabilities["hostVersion"] = version_text

    auth_help, _ = _run_command_check(
        "opencode-auth-help",
        [host_bin, "auth", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["auth", "login", "logout"],
    )
    checks.append(auth_help)
    if auth_help["status"] == "FAIL":
        blockers.append({"code": "opencode-auth-surface-unavailable", "message": "OpenCode auth command surface is unavailable"})
    else:
        capabilities["authState"] = {
            "status": "NOT_DISCLOSED",
            "commandSurface": "DISCOVERED",
            "reason": "credential-state-redacted",
        }

    run_help, _ = _run_command_check(
        "opencode-run-help",
        [host_bin, "run", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--format", "json", "--dir", "--auto", "--model"],
    )
    checks.append(run_help)
    if run_help["status"] == "FAIL":
        blockers.append({"code": "opencode-headless-run-unavailable", "message": "OpenCode run help does not expose required headless adapter flags"})
    else:
        capabilities["headlessExecution"] = {"status": "SUPPORTED", "command": "run", "jsonFormat": "--format json", "workingDirectory": "--dir"}
        capabilities["eventStream"] = {"status": "DISCOVERED", "source": "run-json-output", "requiresReceiptValidation": True}
        capabilities["permissionMode"] = {"status": "DISCOVERED", "autoApproveFlag": "--auto", "adapterPolicy": "fail-closed"}
        capabilities["modelSelection"] = {"status": "DISCOVERED", "selector": "--model"}

    export_help, _ = _run_command_check(
        "opencode-export-help",
        [host_bin, "export", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(export_help)
    if export_help["status"] == "FAIL":
        blockers.append({"code": "opencode-export-unavailable", "message": "OpenCode export command is unavailable"})
    else:
        capabilities["resultExport"] = {"status": "DISCOVERED", "command": "export"}

    stats_help, _ = _run_command_check(
        "opencode-stats-help",
        [host_bin, "stats", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(stats_help)
    if stats_help["status"] == "FAIL":
        blockers.append({"code": "opencode-stats-unavailable", "message": "OpenCode stats command is unavailable"})
    else:
        capabilities["usageAttestation"] = {
            "status": "DISCOVERED",
            "source": "stats-and-run-json-output",
            "requiresLiveReceipt": True,
        }

    return checks, capabilities, blockers
