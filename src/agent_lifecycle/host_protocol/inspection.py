"""Safe adapter capability inspection without live model invocation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, sha256_hex
from agent_lifecycle.host_protocol.validation import validate_adapter_descriptor

SCHEMA_VERSION = "agent-host-adapter-inspection.v1"


@dataclass(frozen=True)
class CommandRun:
    """Captured output from a safe host command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], float], CommandRun]


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
            blockers.append({"code": "qwen-code-projection-unavailable", "message": "qwen-code scaffold projection files are missing or invalid"})
        capabilities["configuration"]["projection"] = projection["details"]

    version_check, version_text = _run_command_check(
        "qwen-code-version",
        [host_bin, "--version"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    checks.append(version_check)
    if version_check["status"] == "FAIL":
        blockers.append({"code": "qwen-code-binary-unavailable", "message": "qwen-code binary is unavailable or failed version probing"})
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
        blockers.append({"code": "qwen-code-help-unavailable", "message": "qwen-code help does not expose required adapter surfaces"})
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
        blockers.append({"code": "qwen-code-extensions-surface-unavailable", "message": "qwen-code extensions command surface is unavailable"})
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
        blockers.append({"code": "qwen-code-mcp-surface-unavailable", "message": "qwen-code MCP command surface is unavailable"})
    else:
        capabilities["mcpDiscovery"] = {"status": "DISCOVERED", "source": "mcp-command"}

    return checks, capabilities, blockers


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


def _check_json_plugin_config(
    path: Path,
    *,
    project_root: Path,
    expected_plugin: str,
    check_name: str,
) -> dict[str, Any]:
    display_path = _relative_display_path(path, project_root)
    details: dict[str, Any] = {"path": display_path, "expectedPlugin": expected_plugin}
    if not path.is_file():
        details["reason"] = "missing"
        return {"name": check_name, "status": "FAIL", "details": details}
    try:
        payload = read_json_object(path, label=display_path)
    except LifecycleError as exc:
        details["reason"] = exc.code
        return {"name": check_name, "status": "FAIL", "details": details}
    plugins = payload.get("plugin")
    details["pluginCount"] = len(plugins) if isinstance(plugins, list) else 0
    details["pluginMatched"] = isinstance(plugins, list) and expected_plugin in plugins
    if not details["pluginMatched"]:
        details["reason"] = "expected-plugin-missing"
        return {"name": check_name, "status": "FAIL", "details": details}
    return {"name": check_name, "status": "PASS", "details": details}


def _check_hermes_skills_config(path: Path, *, project_root: Path) -> dict[str, Any]:
    display_path = _relative_display_path(path, project_root)
    details: dict[str, Any] = {"path": display_path, "requiredSkill": "agent-workflow-orchestrator"}
    if not path.is_file():
        details["reason"] = "missing"
        return {"name": "hermes-skills-config", "status": "FAIL", "details": details}
    try:
        payload = read_json_object(path, label=display_path)
    except LifecycleError as exc:
        details["reason"] = exc.code
        return {"name": "hermes-skills-config", "status": "FAIL", "details": details}
    skills = [
        skill
        for group in payload.get("groupings", [])
        if isinstance(group, dict)
        for skill in group.get("skills", [])
        if isinstance(skill, str)
    ]
    details["skillCount"] = len(skills)
    details["skillMatched"] = "agent-workflow-orchestrator" in skills
    if not details["skillMatched"]:
        details["reason"] = "required-skill-missing"
        return {"name": "hermes-skills-config", "status": "FAIL", "details": details}
    return {"name": "hermes-skills-config", "status": "PASS", "details": details}


def _check_hermes_registry(path: Path, *, project_root: Path, expected_maturity: str | None) -> dict[str, Any]:
    display_path = _relative_display_path(path, project_root)
    details: dict[str, Any] = {"path": display_path}
    if not path.is_file():
        details["reason"] = "missing"
        return {"name": "hermes-registry", "status": "FAIL", "details": details}
    try:
        payload = read_json_object(path, label=display_path)
    except LifecycleError as exc:
        details["reason"] = exc.code
        return {"name": "hermes-registry", "status": "FAIL", "details": details}
    details.update(
        {
            "packageMatched": payload.get("package") == "agent-lifecycle-kit",
            "skillsDirectoryMatched": payload.get("skillsDirectory") == "./skills",
            "descriptorMatched": payload.get("adapterDescriptor") == "./adapter.descriptor.json",
            "maturity": payload.get("maturity"),
            "commandsMatched": payload.get("commands") == "./slash-commands.json",
        }
    )
    if not all(details[key] for key in ("packageMatched", "skillsDirectoryMatched", "descriptorMatched", "commandsMatched")):
        details["reason"] = "registry-metadata-mismatch"
        return {"name": "hermes-registry", "status": "FAIL", "details": details}
    if expected_maturity not in {"EXPERIMENTAL", "VERIFIED"} or payload.get("maturity") != expected_maturity:
        details["reason"] = "registry-maturity-mismatch"
        details["expectedMaturity"] = expected_maturity
        return {"name": "hermes-registry", "status": "FAIL", "details": details}
    return {"name": "hermes-registry", "status": "PASS", "details": details}


def _check_hermes_slash_commands(path: Path, *, project_root: Path) -> dict[str, Any]:
    display_path = _relative_display_path(path, project_root)
    details: dict[str, Any] = {"path": display_path}
    if not path.is_file():
        details["reason"] = "missing"
        return {"name": "hermes-slash-commands", "status": "FAIL", "details": details}
    try:
        payload = read_json_object(path, label=display_path)
    except LifecycleError as exc:
        details["reason"] = exc.code
        return {"name": "hermes-slash-commands", "status": "FAIL", "details": details}
    commands = payload.get("commands")
    details["commandCount"] = len(commands) if isinstance(commands, list) else 0
    details["policyMatched"] = payload.get("unsupportedOperationPolicy") == "fail-closed"
    details["workflowCommandMatched"] = isinstance(commands, list) and any(
        isinstance(item, dict) and item.get("skill") == "agent-workflow-orchestrator" for item in commands
    )
    if not details["policyMatched"] or not details["workflowCommandMatched"]:
        details["reason"] = "slash-command-metadata-mismatch"
        return {"name": "hermes-slash-commands", "status": "FAIL", "details": details}
    return {"name": "hermes-slash-commands", "status": "PASS", "details": details}


def _check_cursor_plugin_config(path: Path, *, project_root: Path, check_name: str) -> dict[str, Any]:
    display_path = _relative_display_path(path, project_root)
    details: dict[str, Any] = {"path": display_path}
    if not path.is_file():
        details["reason"] = "missing"
        return {"name": check_name, "status": "FAIL", "details": details}
    try:
        payload = read_json_object(path, label=display_path)
    except LifecycleError as exc:
        details["reason"] = exc.code
        return {"name": check_name, "status": "FAIL", "details": details}
    details.update(
        {
            "nameMatched": payload.get("name") == "agent-lifecycle-kit",
            "skillsMatched": payload.get("skills") == "./skills",
            "displayNameMatched": (payload.get("interface") or {}).get("displayName") == "Agent Lifecycle Kit"
            if isinstance(payload.get("interface"), dict)
            else False,
        }
    )
    if not all(details.values()):
        details["reason"] = "plugin-metadata-mismatch"
        return {"name": check_name, "status": "FAIL", "details": details}
    return {"name": check_name, "status": "PASS", "details": details}


def _check_scaffold_projection_files(path: Path, *, project_root: Path, host: str) -> dict[str, Any]:
    details: dict[str, Any] = {"path": _relative_display_path(path, project_root)}
    expected_files = [
        "adapter.descriptor.json",
        "capabilities.manifest.json",
        "projection.manifest.json",
        "event-bridge.md",
        "runner.py",
        "receipt_normalizer.py",
        "validation.md",
    ]
    missing = [name for name in expected_files if not (path / name).is_file()]
    details["missing"] = missing
    if missing:
        return {"name": f"{host}-projection-files", "status": "FAIL", "details": details}
    projection = read_json_object(path / "projection.manifest.json", label=f"{host} projection manifest")
    details["runnerStatus"] = (projection.get("runner") or {}).get("status") if isinstance(projection.get("runner"), dict) else None
    details["receiptNormalizerStatus"] = (projection.get("receiptNormalizer") or {}).get("status") if isinstance(projection.get("receiptNormalizer"), dict) else None
    details["eventBridgeStatus"] = (projection.get("eventBridge") or {}).get("status") if isinstance(projection.get("eventBridge"), dict) else None
    details["productionPromotionClaimed"] = projection.get("productionPromotionClaimed")
    allowed_runner_statuses = {"fail-closed-skeleton", "bounded-live-runner"}
    if details["runnerStatus"] not in allowed_runner_statuses or details["productionPromotionClaimed"] is not False:
        details["reason"] = "projection-metadata-mismatch"
        return {"name": f"{host}-projection-files", "status": "FAIL", "details": details}
    if details["runnerStatus"] == "bounded-live-runner" and details["receiptNormalizerStatus"] != "contract-normalizer":
        details["reason"] = "projection-live-runner-normalizer-mismatch"
        return {"name": f"{host}-projection-files", "status": "FAIL", "details": details}
    return {"name": f"{host}-projection-files", "status": "PASS", "details": details}


def _run_command_check(
    name: str,
    command: list[str],
    *,
    timeout_seconds: float,
    command_runner: CommandRunner,
    required_markers: list[str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    check, first_line, _ = _run_command_check_with_text(
        name,
        command,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=required_markers,
    )
    return check, first_line


def _run_command_check_with_text(
    name: str,
    command: list[str],
    *,
    timeout_seconds: float,
    command_runner: CommandRunner,
    required_markers: list[str] | None = None,
) -> tuple[dict[str, Any], str | None, str]:
    display_argv = [_display_binary(command[0]), *command[1:]]
    try:
        result = command_runner(command, timeout_seconds)
    except FileNotFoundError:
        return (
            {
                "name": name,
                "status": "FAIL",
                "details": {
                    "argv": display_argv,
                    "reason": "binary-not-found",
                },
            },
            None,
            "",
        )
    except subprocess.TimeoutExpired:
        return (
            {
                "name": name,
                "status": "FAIL",
                "details": {
                    "argv": display_argv,
                    "reason": "timeout",
                    "timeoutSeconds": timeout_seconds,
                },
            },
            None,
            "",
        )

    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    missing_markers = _missing_markers(text, required_markers or [])
    status = "PASS" if result.returncode == 0 and not missing_markers else "FAIL"
    details: dict[str, Any] = {
        "argv": display_argv,
        "exitCode": result.returncode,
        "stdoutBytes": len(result.stdout.encode("utf-8")),
        "stderrBytes": len(result.stderr.encode("utf-8")),
        "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")),
        "stderrSha256": sha256_hex(result.stderr.encode("utf-8")),
    }
    if missing_markers:
        details["missingMarkers"] = missing_markers
    first_line = _first_non_empty_line(text)
    if first_line:
        details["firstLine"] = first_line[:120]
    return {"name": name, "status": status, "details": details}, first_line, text


def _default_command_runner(command: list[str], timeout_seconds: float) -> CommandRun:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_seconds,
    )
    return CommandRun(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def _missing_markers(text: str, markers: list[str]) -> list[str]:
    lower_text = text.lower()
    return [marker for marker in markers if marker.lower() not in lower_text]


def _first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _cursor_subscription_tier(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip().lower().startswith("subscription tier"):
            value = line.split("Subscription Tier", 1)[-1].strip()
            return value or None
    return None


def _cursor_model_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if " - " in line)


def _display_binary(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name if "/" in value else value


def _relative_display_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
