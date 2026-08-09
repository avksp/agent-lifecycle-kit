"""Safe Codex CLI qualification inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.host_protocol.inspection_common import CommandRunner, _display_binary, _run_command_check


def _inspect_codex(
    *, descriptor_path: Path | None, host_bin: str, project_root: Path, timeout_seconds: float, command_runner: CommandRunner
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    del descriptor_path, project_root
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    version, version_text = _run_command_check("codex-version", [host_bin, "--version"], timeout_seconds=timeout_seconds, command_runner=command_runner)
    help_check, _ = _run_command_check(
        "codex-exec-help",
        [host_bin, "exec", "--help"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
        required_markers=["--json", "--sandbox"],
    )
    checks.extend((version, help_check))
    if version["status"] == "FAIL":
        blockers.append({"code": "codex-binary-unavailable"})
    if help_check["status"] == "FAIL":
        blockers.append({"code": "codex-qualified-surface-unavailable"})
    return checks, {
        "hostCommands": {"status": "CHECKED", "binary": _display_binary(host_bin), "profile": "codex-qualified-cli"},
        "hostVersion": version_text,
        "headlessExecution": {"status": "SUPPORTED" if help_check["status"] == "PASS" else "UNKNOWN", "command": "exec --json"},
        "permissionMode": {"status": "DECLARED", "sandboxFlag": "--sandbox", "implicitApproval": False},
        "usageAttestation": {"status": "FIXTURE_ONLY", "acceptedForS1S2": False},
    }, blockers
