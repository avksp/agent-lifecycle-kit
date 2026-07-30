"""Safe host inspection probes for Gemini CLI."""

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

def _inspect_gemini_cli(
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
            "profile": "gemini-cli-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "skillDiscovery": {"status": "UNKNOWN"},
        "extensionDiscovery": {"status": "UNKNOWN"},
        "mcpDiscovery": {"status": "UNKNOWN"},
        "localModelRouting": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "no-safe-auth-status-command-discovered"},
        "configuration": {},
    }

    if descriptor_path is not None:
        projection = _check_scaffold_projection_files(descriptor_path.parent, project_root=project_root, host="gemini-cli")
        checks.append(projection)
        if projection["status"] == "FAIL":
            blockers.append({"code": "gemini-cli-projection-unavailable", "message": "Gemini CLI scaffold projection files are missing or invalid"})
        capabilities["configuration"]["projection"] = projection["details"]

    version_check, version_text = _run_command_check(
        "gemini-cli-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-binary-unavailable", "message": "Gemini CLI binary is unavailable or failed version probing"})
    capabilities["hostVersion"] = version_text

    help_check, _ = _run_command_check(
        "gemini-cli-help",
        [host_bin, "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=[
            "--prompt",
            "--output-format",
            "stream-json",
            "--model",
            "--yolo",
            "--approval-mode",
            "--sandbox",
            "--worktree",
            "skills",
            "mcp",
            "extensions",
        ],
    )
    checks.append(help_check)
    if help_check["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-help-unavailable", "message": "Gemini CLI help does not expose required adapter surfaces"})
    else:
        capabilities["headlessExecution"] = {"status": "SUPPORTED", "command": "--prompt", "streamJson": "--output-format stream-json"}
        capabilities["eventStream"] = {"status": "DISCOVERED", "source": "stream-json-output", "requiresReceiptValidation": True}
        capabilities["usageAttestation"] = {
            "status": "UNPROVEN",
            "source": "stream-json-output",
            "requiresLiveReceipt": True,
        }
        capabilities["permissionMode"] = {
            "status": "DISCOVERED",
            "yoloFlag": "--yolo",
            "approvalMode": "--approval-mode",
            "sandboxFlag": "--sandbox",
            "adapterPolicy": "fail-closed",
        }
        capabilities["modelSelection"] = {"status": "DISCOVERED", "selector": "--model"}

    skills_help, _ = _run_command_check(
        "gemini-cli-skills-help",
        [host_bin, "skills", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["list", "install", "enable", "disable"],
    )
    checks.append(skills_help)
    if skills_help["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-skills-surface-unavailable", "message": "Gemini CLI skills command surface is unavailable"})
    else:
        capabilities["skillDiscovery"] = {"status": "DISCOVERED", "source": "skills-command"}

    extensions_help, _ = _run_command_check(
        "gemini-cli-extensions-help",
        [host_bin, "extensions", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["install", "validate", "list"],
    )
    checks.append(extensions_help)
    if extensions_help["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-extensions-surface-unavailable", "message": "Gemini CLI extensions command surface is unavailable"})
    else:
        capabilities["extensionDiscovery"] = {"status": "DISCOVERED", "source": "extensions-command"}

    mcp_help, _ = _run_command_check(
        "gemini-cli-mcp-help",
        [host_bin, "mcp", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["add", "list", "enable", "disable"],
    )
    checks.append(mcp_help)
    if mcp_help["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-mcp-surface-unavailable", "message": "Gemini CLI MCP command surface is unavailable"})
    else:
        capabilities["mcpDiscovery"] = {"status": "DISCOVERED", "source": "mcp-command"}

    gemma_help, _ = _run_command_check(
        "gemini-cli-gemma-help",
        [host_bin, "gemma", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["setup", "start", "status"],
    )
    checks.append(gemma_help)
    if gemma_help["status"] == "FAIL":
        blockers.append({"code": "gemini-cli-local-model-surface-unavailable", "message": "Gemini CLI local model routing surface is unavailable"})
    else:
        capabilities["localModelRouting"] = {"status": "DISCOVERED", "source": "gemma-command"}

    return checks, capabilities, blockers
