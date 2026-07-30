"""Safe host inspection probes for Hermes."""

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

def _inspect_hermes(
    *,
    descriptor_maturity: Any,
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
            "profile": "hermes-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "skillDiscovery": {"status": "UNKNOWN"},
        "slashCommands": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "configuration": {},
    }

    root_skills = _check_hermes_skills_config(project_root / "skills.sh.json", project_root=project_root)
    checks.append(root_skills)
    if root_skills["status"] == "FAIL":
        blockers.append({"code": "hermes-skills-config-unavailable", "message": "Hermes skills config is missing or invalid"})
    capabilities["configuration"]["skillsConfig"] = root_skills["details"]

    if descriptor_path is not None:
        registry = _check_hermes_registry(
            descriptor_path.parent / "hermes.registry.json",
            project_root=project_root,
            expected_maturity=str(descriptor_maturity) if isinstance(descriptor_maturity, str) else None,
        )
        checks.append(registry)
        if registry["status"] == "FAIL":
            blockers.append({"code": "hermes-registry-unavailable", "message": "Hermes registry metadata is missing or invalid"})
        capabilities["configuration"]["registry"] = registry["details"]

        slash_commands = _check_hermes_slash_commands(descriptor_path.parent / "slash-commands.json", project_root=project_root)
        checks.append(slash_commands)
        if slash_commands["status"] == "FAIL":
            blockers.append({"code": "hermes-slash-commands-unavailable", "message": "Hermes slash-command metadata is missing or invalid"})
        capabilities["configuration"]["slashCommands"] = slash_commands["details"]
        if slash_commands["status"] == "PASS":
            capabilities["slashCommands"] = {"status": "DISCOVERED", "unsupportedOperationPolicy": "fail-closed"}

    version_check, version_text = _run_command_check(
        "hermes-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "hermes-binary-unavailable", "message": "Hermes binary is unavailable or failed version probing"})
    capabilities["hostVersion"] = version_text

    root_help, _ = _run_command_check(
        "hermes-root-help",
        [host_bin, "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--oneshot", "--usage-file", "--model", "--provider", "--yolo", "--safe-mode", "skills", "auth", "status"],
    )
    checks.append(root_help)
    if root_help["status"] == "FAIL":
        blockers.append({"code": "hermes-root-help-unavailable", "message": "Hermes root help does not expose required adapter surfaces"})
    else:
        capabilities["headlessExecution"] = {"status": "DISCOVERED", "command": "--oneshot", "usageFile": "--usage-file"}
        capabilities["usageAttestation"] = {
            "status": "DISCOVERED",
            "source": "usage-file",
            "requiresLiveReceipt": True,
        }
        capabilities["permissionMode"] = {"status": "DISCOVERED", "autoApproveFlag": "--yolo", "safeModeFlag": "--safe-mode", "adapterPolicy": "fail-closed"}
        capabilities["modelSelection"] = {"status": "DISCOVERED", "selector": "--model", "providerSelector": "--provider"}

    chat_help, _ = _run_command_check(
        "hermes-chat-help",
        [host_bin, "chat", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--query", "--model", "--provider", "--toolsets", "--skills", "--yolo", "--safe-mode"],
    )
    checks.append(chat_help)
    if chat_help["status"] == "FAIL":
        blockers.append({"code": "hermes-chat-help-unavailable", "message": "Hermes chat help does not expose required adapter surfaces"})

    skills_help, _ = _run_command_check(
        "hermes-skills-help",
        [host_bin, "skills", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["install", "list", "check"],
    )
    checks.append(skills_help)
    if skills_help["status"] == "FAIL":
        blockers.append({"code": "hermes-skills-help-unavailable", "message": "Hermes skills help does not expose required adapter surfaces"})
    else:
        capabilities["skillDiscovery"] = {"status": "DISCOVERED", "source": "skills-command"}

    auth_help, _ = _run_command_check(
        "hermes-auth-help",
        [host_bin, "auth", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["status", "list", "logout"],
    )
    checks.append(auth_help)
    if auth_help["status"] == "FAIL":
        blockers.append({"code": "hermes-auth-surface-unavailable", "message": "Hermes auth command surface is unavailable"})
    else:
        capabilities["authState"] = {
            "status": "NOT_DISCLOSED",
            "commandSurface": "DISCOVERED",
            "reason": "credential-state-redacted",
        }

    status_help, _ = _run_command_check(
        "hermes-status-help",
        [host_bin, "status", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--all", "redacted"],
    )
    checks.append(status_help)
    if status_help["status"] == "FAIL":
        blockers.append({"code": "hermes-status-surface-unavailable", "message": "Hermes status command surface is unavailable"})

    return checks, capabilities, blockers
