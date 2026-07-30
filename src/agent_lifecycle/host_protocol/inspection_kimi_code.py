"""Safe host inspection probes for Kimi Code."""

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

def _inspect_kimi_code(
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
            "profile": "kimi-code-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "skillDiscovery": {"status": "UNKNOWN"},
        "providerDiscovery": {"status": "UNKNOWN"},
        "agentProtocol": {"status": "UNKNOWN"},
        "resultExport": {"status": "UNKNOWN"},
        "configurationValidation": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "configuration": {},
    }

    if descriptor_path is not None:
        projection = _check_scaffold_projection_files(descriptor_path.parent, project_root=project_root, host="kimi-code")
        checks.append(projection)
        if projection["status"] == "FAIL":
            blockers.append({"code": "kimi-code-projection-unavailable", "message": "Kimi Code scaffold projection files are missing or invalid"})
        capabilities["configuration"]["projection"] = projection["details"]

    version_check, version_text = _run_command_check(
        "kimi-code-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "kimi-code-binary-unavailable", "message": "Kimi Code binary is unavailable or failed version probing"})
        capabilities["hostCommands"]["status"] = "BINARY_MISSING"
        capabilities["hostVersion"] = None
        return checks, capabilities, blockers
    capabilities["hostVersion"] = version_text

    help_check, _ = _run_command_check(
        "kimi-code-help",
        [host_bin, "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=[
            "--prompt",
            "--output-format",
            "stream-json",
            "--model",
            "--yolo",
            "--auto",
            "--skills-dir",
            "--session",
            "--continue",
            "--plan",
            "export",
            "provider",
            "acp",
            "login",
            "doctor",
        ],
    )
    checks.append(help_check)
    if help_check["status"] == "FAIL":
        blockers.append({"code": "kimi-code-help-unavailable", "message": "Kimi Code help surface is unavailable"})
    else:
        capabilities["headlessExecution"] = {"status": "SUPPORTED", "command": "--prompt", "streamJson": "--output-format stream-json"}
        capabilities["eventStream"] = {"status": "DISCOVERED", "source": "stream-json-output", "requiresReceiptValidation": True}
        capabilities["usageAttestation"] = {"status": "UNPROVEN", "requiresLiveReceipt": True}
        capabilities["permissionMode"] = {
            "status": "DISCOVERED",
            "yoloFlag": "--yolo",
            "autoFlag": "--auto",
            "planFlag": "--plan",
            "adapterPolicy": "fail-closed",
        }
        capabilities["modelSelection"] = {"status": "DISCOVERED", "selector": "--model"}
        capabilities["skillDiscovery"] = {"status": "DISCOVERED", "source": "skills-dir"}
        capabilities["authState"] = {"status": "NOT_PROBED", "commandSurface": "DISCOVERED", "reason": "login-is-device-code-flow"}

    provider_help, _ = _run_command_check(
        "kimi-code-provider-help",
        [host_bin, "provider", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["add", "remove", "list", "catalog"],
    )
    checks.append(provider_help)
    if provider_help["status"] == "FAIL":
        blockers.append({"code": "kimi-code-provider-surface-unavailable", "message": "Kimi Code provider command surface is unavailable"})
    else:
        capabilities["providerDiscovery"] = {"status": "DISCOVERED", "source": "provider-command"}

    export_help, _ = _run_command_check(
        "kimi-code-export-help",
        [host_bin, "export", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["sessionId", "--output", "--yes"],
    )
    checks.append(export_help)
    if export_help["status"] == "FAIL":
        blockers.append({"code": "kimi-code-export-surface-unavailable", "message": "Kimi Code export command surface is unavailable"})
    else:
        capabilities["resultExport"] = {"status": "DISCOVERED", "command": "export"}

    acp_help, _ = _run_command_check(
        "kimi-code-acp-help",
        [host_bin, "acp", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["Agent Client Protocol", "stdio", "--login"],
    )
    checks.append(acp_help)
    if acp_help["status"] == "FAIL":
        blockers.append({"code": "kimi-code-acp-surface-unavailable", "message": "Kimi Code ACP command surface is unavailable"})
    else:
        capabilities["agentProtocol"] = {"status": "DISCOVERED", "source": "acp-stdio-server"}

    doctor_help, _ = _run_command_check(
        "kimi-code-doctor-help",
        [host_bin, "doctor", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["config", "tui"],
    )
    checks.append(doctor_help)
    if doctor_help["status"] == "FAIL":
        blockers.append({"code": "kimi-code-doctor-surface-unavailable", "message": "Kimi Code configuration validation surface is unavailable"})
    else:
        capabilities["configurationValidation"] = {"status": "DISCOVERED", "source": "doctor-command"}

    return checks, capabilities, blockers
