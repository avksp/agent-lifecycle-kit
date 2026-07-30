"""Safe host inspection probes for Cursor."""

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

def _inspect_cursor(
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
            "profile": "cursor-safe-cli",
        },
        "headlessExecution": {"status": "UNKNOWN"},
        "eventStream": {"status": "UNKNOWN"},
        "usageAttestation": {"status": "UNKNOWN", "requiresLiveReceipt": True},
        "permissionMode": {"status": "UNKNOWN"},
        "modelSelection": {"status": "UNKNOWN"},
        "modelCatalog": {"status": "UNKNOWN"},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "subscriptionConstraints": {"status": "UNKNOWN"},
        "configuration": {},
    }

    root_plugin = _check_cursor_plugin_config(project_root / ".cursor-plugin" / "plugin.json", project_root=project_root, check_name="cursor-root-plugin")
    checks.append(root_plugin)
    if root_plugin["status"] == "FAIL":
        blockers.append({"code": "cursor-root-plugin-unavailable", "message": "Cursor root plugin metadata is missing or invalid"})
    capabilities["configuration"]["rootPlugin"] = root_plugin["details"]

    if descriptor_path is not None:
        adapter_plugin = _check_cursor_plugin_config(
            descriptor_path.parent / ".cursor-plugin" / "plugin.json",
            project_root=project_root,
            check_name="cursor-adapter-plugin",
        )
        checks.append(adapter_plugin)
        if adapter_plugin["status"] == "FAIL":
            blockers.append({"code": "cursor-adapter-plugin-unavailable", "message": "Cursor adapter plugin metadata is missing or invalid"})
        capabilities["configuration"]["adapterPlugin"] = adapter_plugin["details"]

    version_check, version_text = _run_command_check(
        "cursor-agent-version",
        [host_bin, "agent", "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-binary-unavailable", "message": "Cursor Agent binary is unavailable or failed version probing"})
    capabilities["hostVersion"] = version_text

    help_check, _ = _run_command_check(
        "cursor-agent-help",
        [host_bin, "agent", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--print", "stream-json", "--model", "--force", "--yolo", "--auto-review", "--workspace", "--plugin-dir", "status", "models", "about"],
    )
    checks.append(help_check)
    if help_check["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-help-unavailable", "message": "Cursor Agent help does not expose required adapter surfaces"})
    else:
        capabilities["headlessExecution"] = {"status": "SUPPORTED", "command": "agent --print", "streamJson": "--output-format stream-json"}
        capabilities["eventStream"] = {"status": "DISCOVERED", "source": "stream-json-output", "requiresReceiptValidation": True}
        capabilities["usageAttestation"] = {
            "status": "DISCOVERED",
            "source": "stream-json-output",
            "requiresLiveReceipt": True,
        }
        capabilities["permissionMode"] = {"status": "DISCOVERED", "forceFlag": "--force", "autoReviewFlag": "--auto-review", "adapterPolicy": "fail-closed"}
        capabilities["modelSelection"] = {"status": "DISCOVERED", "selector": "--model"}

    status_help, _ = _run_command_check(
        "cursor-agent-status-help",
        [host_bin, "agent", "status", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--format", "json"],
    )
    checks.append(status_help)
    if status_help["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-status-surface-unavailable", "message": "Cursor Agent status command surface is unavailable"})

    about_help, _ = _run_command_check(
        "cursor-agent-about-help",
        [host_bin, "agent", "about", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--format", "json"],
    )
    checks.append(about_help)
    if about_help["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-about-surface-unavailable", "message": "Cursor Agent about command surface is unavailable"})

    about_check, _, about_text = _run_command_check_with_text(
        "cursor-agent-about",
        [host_bin, "agent", "about"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["CLI Version", "Subscription Tier"],
    )
    checks.append(about_check)
    if about_check["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-about-unavailable", "message": "Cursor Agent about command is unavailable"})
    else:
        subscription_tier = _cursor_subscription_tier(about_text)
        capabilities["subscriptionConstraints"] = {
            "status": "DISCOVERED",
            "tier": subscription_tier,
            "boundedSmokeCanPromote": False,
            "requiresUsageCalibration": True,
        }
        capabilities["authState"] = {
            "status": "LOGGED_IN_REDACTED" if "User Email" in about_text else "NOT_DISCLOSED",
            "commandSurface": "DISCOVERED",
            "reason": "account-identifier-redacted",
        }

    models_check, _, models_text = _run_command_check_with_text(
        "cursor-agent-models",
        [host_bin, "agent", "models"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["Available models"],
    )
    checks.append(models_check)
    if models_check["status"] == "FAIL":
        blockers.append({"code": "cursor-agent-model-catalog-unavailable", "message": "Cursor Agent model catalog command is unavailable"})
    else:
        capabilities["modelCatalog"] = {
            "status": "DISCOVERED",
            "modelCount": _cursor_model_count(models_text),
            "modelNamesRedacted": True,
        }

    return checks, capabilities, blockers
