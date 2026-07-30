"""Shared helpers for safe host inspection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, read_json_object, sha256_hex


@dataclass(frozen=True)
class CommandRun:
    """Captured output from a safe host command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], float], CommandRun]


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
