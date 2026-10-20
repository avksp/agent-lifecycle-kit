"""Safe host inspection probes for OpenCode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol.inspection_common import (
    CommandRunner,
    _check_json_plugin_config,
    _display_binary,
    _run_command_check,
    _run_command_check_with_text,
)
from agent_lifecycle.host_protocol.opencode_compatibility import effective_qualification, help_commands, opencode_family


def _opencode_configuration(
    descriptor_path: Path | None,
    project_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    configuration: dict[str, Any] = {}
    root_config = _check_json_plugin_config(
        project_root / "opencode.json",
        project_root=project_root,
        expected_plugin="./adapters/opencode/plugins/agent-lifecycle-kit.js",
        check_name="opencode-root-config",
    )
    checks.append(root_config)
    if root_config["status"] == "FAIL":
        blockers.append(
            {"code": "opencode-root-config-unavailable", "message": "OpenCode root plugin config is missing or invalid"}
        )
    configuration["rootConfig"] = root_config["details"]

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
            blockers.append(
                {
                    "code": "opencode-adapter-config-unavailable",
                    "message": "OpenCode adapter plugin config is missing or invalid",
                }
            )
        configuration["adapterConfig"] = adapter_config["details"]

    return checks, configuration, blockers


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
        "qualifiedLocalLaunch": {"status": "VERSION_BOUND", "implicitApproval": False},
        "authState": {"status": "NOT_PROBED", "reason": "credential-state-redacted"},
        "configuration": {},
    }

    config_checks, configuration, config_blockers = _opencode_configuration(descriptor_path, project_root)
    checks.extend(config_checks)
    blockers.extend(config_blockers)
    capabilities["configuration"] = configuration

    version_check, version_text, complete_version_text = _run_command_check_with_text(
        "opencode-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append(
            {
                "code": "opencode-binary-unavailable",
                "message": "OpenCode binary is unavailable or failed version probing",
            }
        )
    capabilities["hostVersion"] = version_text
    try:
        _, major = opencode_family(complete_version_text)
    except LifecycleError:
        blockers.append(
            {"code": "opencode-version-unsupported", "message": "OpenCode version is unknown, ambiguous or unsupported"}
        )
        capabilities["versionQualification"] = effective_qualification(complete_version_text, surfaces_ok=False)
        return checks, capabilities, blockers
    surfaces = help_commands(major)

    auth_help, _ = _run_command_check(
        "opencode-auth-help",
        [host_bin, "auth", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["auth", "login", "logout"],
    )
    checks.append(auth_help)
    if auth_help["status"] == "FAIL":
        blockers.append(
            {"code": "opencode-auth-surface-unavailable", "message": "OpenCode auth command surface is unavailable"}
        )
    else:
        capabilities["authState"] = {
            "status": "NOT_DISCLOSED",
            "commandSurface": "DISCOVERED",
            "reason": "credential-state-redacted",
        }

    run_help, _ = _run_command_check(
        "opencode-run-help",
        [host_bin, *surfaces["run"][0]],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=surfaces["run"][1],
    )
    checks.append(run_help)
    if run_help["status"] == "FAIL":
        blockers.append(
            {
                "code": "opencode-headless-run-unavailable",
                "message": "OpenCode run help does not expose required headless adapter flags",
            }
        )
    else:
        capabilities["headlessExecution"] = {
            "status": "SUPPORTED",
            "command": "run",
            "jsonFormat": "--format=json",
            "workingDirectory": "--dir" if major == 1 else "subprocess-cwd",
        }
        capabilities["eventStream"] = {
            "status": "DISCOVERED",
            "source": "run-json-output",
            "requiresReceiptValidation": True,
        }
        capabilities["permissionMode"] = {
            "status": "DISCOVERED",
            "autoApproveFlag": "--auto",
            "implicitApproval": False,
            "adapterPolicy": "fail-closed",
        }
        capabilities["modelSelection"] = {
            "status": "DISCOVERED",
            "selector": "--model",
            "variantSyntax": "--variant" if major == 1 else "provider/model#variant",
        }

    export_help, _ = _run_command_check(
        "opencode-export-help",
        [host_bin, *surfaces["export"][0]],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=surfaces["export"][1],
    )
    checks.append(export_help)
    if export_help["status"] == "FAIL":
        blockers.append({"code": "opencode-export-unavailable", "message": "OpenCode export command is unavailable"})
    else:
        capabilities["resultExport"] = {"status": "DISCOVERED", "command": "export" if major == 1 else "session export"}

    stats_help, _ = _run_command_check(
        "opencode-stats-help",
        [host_bin, *surfaces["stats"][0]],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=surfaces["stats"][1],
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

    capabilities["versionQualification"] = effective_qualification(
        complete_version_text,
        surfaces_ok=all(item["status"] == "PASS" for item in (version_check, run_help, export_help, stats_help)),
    )
    return checks, capabilities, blockers
