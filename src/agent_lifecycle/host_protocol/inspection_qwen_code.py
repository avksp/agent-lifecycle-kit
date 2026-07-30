"""Safe host inspection probes for Qwen Code."""

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

def _inspect_qwen_code(
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
            "profile": "qwen-code-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "resourceCaps": {"status": "UNKNOWN"},
        "extensionDiscovery": {"status": "UNKNOWN"},
        "mcpDiscovery": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "configuration": {},
    }

    if descriptor_path is not None:
        projection = _check_scaffold_projection_files(descriptor_path.parent, project_root=project_root, host="qwen-code")
        checks.append(projection)
        if projection["status"] == "FAIL":
            blockers.append({"code": "qwen-code-projection-unavailable", "message": "Qwen Code scaffold projection files are missing or invalid"})
        capabilities["configuration"]["projection"] = projection["details"]

    version_check, version_text = _run_command_check(
        "qwen-code-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "qwen-code-binary-unavailable", "message": "Qwen Code binary is unavailable or failed version probing"})
    capabilities["hostVersion"] = version_text

    help_check, _ = _run_command_check(
        "qwen-code-help",
        [host_bin, "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=[
            "--prompt",
            "--output-format",
            "stream-json",
            "--model",
            "--fallback-model",
            "--safe-mode",
            "--sandbox",
            "--continue",
            "--resume",
            "mcp",
            "extensions",
            "sessions",
            "serve",
        ],
    )
    checks.append(help_check)
    if help_check["status"] == "FAIL":
        blockers.append({"code": "qwen-code-help-unavailable", "message": "Qwen Code help does not expose required adapter surfaces"})
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
            "safeModeFlag": "--safe-mode",
            "sandboxFlag": "--sandbox",
            "adapterPolicy": "fail-closed",
        }
        capabilities["modelSelection"] = {
            "status": "DISCOVERED",
            "selector": "--model",
            "fallbackSelector": "--fallback-model",
        }
        capabilities["resourceCaps"] = {"status": "NOT_DISCOVERED", "reason": "root-help-does-not-expose-bounded-cap-flags"}
        capabilities["authState"] = {"status": "NOT_PROBED", "reason": "auth-command-marked-removed"}

    extensions_help, _ = _run_command_check(
        "qwen-code-extensions-help",
        [host_bin, "extensions", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["install", "list", "enable", "disable"],
    )
    checks.append(extensions_help)
    if extensions_help["status"] == "FAIL":
        blockers.append({"code": "qwen-code-extensions-surface-unavailable", "message": "Qwen Code extensions command surface is unavailable"})
    else:
        capabilities["extensionDiscovery"] = {"status": "DISCOVERED", "source": "extensions-command"}

    mcp_help, _ = _run_command_check(
        "qwen-code-mcp-help",
        [host_bin, "mcp", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["add", "list", "approve", "reject"],
    )
    checks.append(mcp_help)
    if mcp_help["status"] == "FAIL":
        blockers.append({"code": "qwen-code-mcp-surface-unavailable", "message": "Qwen Code MCP command surface is unavailable"})
    else:
        capabilities["mcpDiscovery"] = {"status": "DISCOVERED", "source": "mcp-command"}

    return checks, capabilities, blockers
