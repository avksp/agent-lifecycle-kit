"""Read-only readiness diagnostics for the current source checkout."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.context import load_context_profile
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.host_protocol import (
    inspect_adapter_descriptor,
    validate_adapter_descriptor,
)
from agent_lifecycle.model_routing import validate_model_routing_profile

READINESS_SCHEMA_VERSION = "agent-readiness-report.v1"
INSTALL_PLAN_SCHEMA_VERSION = "agent-adapter-install-plan.v1"


def build_readiness_report(
    *,
    project_root: Path,
    adapter_paths: list[Path] | None = None,
    include_install_plans: bool = True,
    include_host_probes: bool = False,
    timeout_seconds: float = 5.0,
    max_host_probes: int = 1,
    context_profile: Path | None = None,
    model_profile: Path | None = None,
    adapter_baseline: Path | None = None,
) -> dict[str, Any]:
    """Build one redacted readiness report without mutating the checkout."""

    root = project_root.resolve()
    if timeout_seconds <= 0:
        raise LifecycleError("invalid-diagnose-timeout", "diagnose timeout must be positive")
    if max_host_probes < 0:
        raise LifecycleError("invalid-diagnose-probe-cap", "diagnose probe cap must be non-negative")

    context_profile_path = _resolve(root, context_profile or Path("profiles/small-context-profile.v1.json"))
    model_profile_path = _resolve(root, model_profile or Path("profiles/model-routing-profile.v1.json"))
    baseline_path = _resolve(root, adapter_baseline or Path("conformance/core/adapter-baseline.v1.json"))
    descriptors = [_resolve(root, item) for item in adapter_paths] if adapter_paths else _discover_adapters(root)

    checks: list[dict[str, Any]] = []
    checks.extend(_checkout_checks(root))
    checks.extend(_package_checks(root))
    checks.append(_context_profile_check(root, context_profile_path))
    checks.append(_model_profile_check(root, model_profile_path))

    baseline = _read_optional_json(root, baseline_path, "adapter baseline", checks)
    adapters: list[dict[str, Any]] = []
    install_plans: list[dict[str, Any]] = []
    host_probe_count = 0
    for descriptor_path in descriptors:
        adapter_record, probe_used = _adapter_record(
            root,
            descriptor_path,
            baseline=baseline,
            include_host_probe=include_host_probes and host_probe_count < max_host_probes,
            timeout_seconds=timeout_seconds,
        )
        adapters.append(adapter_record)
        checks.append(adapter_record["validationSummary"])
        if probe_used:
            host_probe_count += 1
        if include_install_plans and adapter_record.get("descriptor"):
            install_plans.append(build_adapter_install_plan(project_root=root, descriptor_path=descriptor_path))

    evidence = _evidence_summary(root, adapters)
    status = _report_status(checks, evidence)
    return {
        "schemaVersion": READINESS_SCHEMA_VERSION,
        "status": status,
        "projectRoot": "<checkout>",
        "version": __version__,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
        "maturityChangesClaimed": False,
        "hostProbePolicy": {
            "enabled": include_host_probes,
            "safeHostCommandsOnly": True,
            "timeoutSeconds": timeout_seconds,
            "maxInvocations": max_host_probes if include_host_probes else 0,
            "invocationsUsed": host_probe_count,
        },
        "summary": _summary(checks, adapters, evidence),
        "checks": checks,
        "profiles": {
            "context": _display_path(context_profile_path, root),
            "modelRouting": _display_path(model_profile_path, root),
        },
        "adapters": adapters,
        "installPlans": install_plans,
        "evidence": evidence,
        "nextActions": _next_actions(checks, adapters, evidence),
    }


def build_adapter_install_plan(*, project_root: Path, descriptor_path: Path) -> dict[str, Any]:
    """Return a dry-run host setup plan for one adapter descriptor."""

    root = project_root.resolve()
    path = _resolve(root, descriptor_path)
    descriptor = read_json_object(path, label=_display_path(path, root))
    host = _required_str(descriptor, "host", path)
    adapter_id = _required_str(descriptor, "adapterId", path)
    maturity = descriptor.get("maturity")
    files, commands, operator_actions = _install_instructions(host, adapter_id=adapter_id)
    return {
        "schemaVersion": INSTALL_PLAN_SCHEMA_VERSION,
        "status": "DRY_RUN",
        "adapterId": adapter_id,
        "host": host,
        "maturity": maturity,
        "descriptorPath": _display_path(path, root),
        "dryRun": True,
        "writesStarted": False,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
        "maturityChangeClaimed": False,
        "files": files,
        "commands": commands,
        "operatorActions": operator_actions,
        "nextActions": [
            "review this plan",
            "run adapter validate before any host-local setup",
            "collect live conformance and calibration receipts before any maturity change",
        ],
    }


def _adapter_record(
    root: Path,
    descriptor_path: Path,
    *,
    baseline: dict[str, Any] | None,
    include_host_probe: bool,
    timeout_seconds: float,
) -> tuple[dict[str, Any], bool]:
    display_path = _display_path(descriptor_path, root)
    try:
        descriptor = read_json_object(descriptor_path, label=display_path)
    except OSError as exc:
        return _unavailable_adapter_record(display_path, descriptor_path, type(exc).__name__), False
    except LifecycleError as exc:
        return _unavailable_adapter_record(display_path, descriptor_path, exc.code), False
    validation = validate_adapter_descriptor(descriptor, baseline=baseline)
    inspection = inspect_adapter_descriptor(
        descriptor,
        descriptor_path=descriptor_path,
        project_root=root,
        skip_host_commands=not include_host_probe,
        timeout_seconds=timeout_seconds,
    )
    maturity = descriptor.get("maturity")
    live_range = descriptor.get("liveTestedHostRange")
    evidence_paths = _evidence_paths(live_range)
    local_evidence = _local_evidence_status(root, evidence_paths)
    validation_summary = {
        "name": f"adapter:{descriptor.get('host') or descriptor_path.parent.name}",
        "status": validation["status"],
        "details": {
            "descriptorPath": display_path,
            "adapterId": descriptor.get("adapterId"),
            "host": descriptor.get("host"),
            "maturity": maturity,
            "operationCount": validation["operationCount"],
            "blockerCount": len(validation["blockers"]),
        },
    }
    if validation["blockers"]:
        validation_summary["details"]["blockerCodes"] = [item.get("code") for item in validation["blockers"]]
    return (
        {
            "adapterId": descriptor.get("adapterId"),
            "host": descriptor.get("host"),
            "descriptorPath": display_path,
            "maturity": maturity,
            "descriptorDigest": canonical_digest(descriptor),
            "validationStatus": validation["status"],
            "validationBlockers": validation["blockers"],
            "inspectionStatus": inspection["status"],
            "hostProbeUsed": include_host_probe,
            "liveCallsStarted": False,
            "productionPromotionClaimed": False,
            "maturityChangeClaimed": False,
            "descriptor": {
                "nativeProjection": descriptor.get("nativeProjection"),
                "unsupportedOperationPolicy": descriptor.get("unsupportedOperationPolicy"),
                "coreSemantics": descriptor.get("coreSemantics"),
                "liveVerified": (descriptor.get("modelRouting") or {}).get("liveVerified")
                if isinstance(descriptor.get("modelRouting"), dict)
                else None,
            },
            "liveEvidence": local_evidence,
            "validationSummary": validation_summary,
        },
        include_host_probe,
    )


def _unavailable_adapter_record(display_path: str, descriptor_path: Path, reason: str) -> dict[str, Any]:
    host = descriptor_path.parent.name
    validation_summary = {
        "name": f"adapter:{host}",
        "status": "FAIL",
        "details": {
            "descriptorPath": display_path,
            "host": host,
            "reason": reason,
            "blockerCount": 1,
        },
    }
    return {
        "adapterId": None,
        "host": host,
        "descriptorPath": display_path,
        "maturity": None,
        "descriptorDigest": None,
        "validationStatus": "FAIL",
        "validationBlockers": [{"code": reason, "message": "adapter descriptor is unavailable"}],
        "inspectionStatus": "SKIPPED",
        "hostProbeUsed": False,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
        "maturityChangeClaimed": False,
        "descriptor": None,
        "liveEvidence": {
            "declaredPaths": [],
            "existingPaths": [],
            "missingPaths": [],
            "ignoredTasksEvidenceCount": 0,
            "status": "SKIPPED",
        },
        "validationSummary": validation_summary,
    }


def _checkout_checks(root: Path) -> list[dict[str, Any]]:
    checks = [
        _file_check(root, Path("pyproject.toml"), name="checkout:pyproject"),
        _file_check(root, Path("src/agent_lifecycle"), name="checkout:package-source"),
        _file_check(root, Path("adapters"), name="checkout:adapters"),
    ]
    ignored = _tasks_ignore_check(root)
    if ignored:
        checks.append(ignored)
    return checks


def _package_checks(root: Path) -> list[dict[str, Any]]:
    pyproject = root / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = ((payload.get("project") or {}).get("version")) if isinstance(payload.get("project"), dict) else None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [{"name": "package:version", "status": "FAIL", "details": {"reason": type(exc).__name__}}]
    status = "PASS" if version == __version__ else "FAIL"
    return [
        {
            "name": "package:version",
            "status": status,
            "details": {
                "pyprojectVersion": version,
                "moduleVersion": __version__,
                "versionMatched": version == __version__,
            },
        }
    ]


def _context_profile_check(root: Path, path: Path) -> dict[str, Any]:
    try:
        validation = load_context_profile(path)
    except OSError as exc:
        return {"name": "profile:context", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": type(exc).__name__}}
    except LifecycleError as exc:
        return {"name": "profile:context", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": exc.code}}
    return {
        "name": "profile:context",
        "status": "PASS",
        "details": {
            "path": _display_path(path, root),
            "defaultWindow": validation["defaultWindow"],
            "windowCount": len(validation["windows"]),
            "profileDigest": validation["profileDigest"],
        },
    }


def _model_profile_check(root: Path, path: Path) -> dict[str, Any]:
    try:
        validation = validate_model_routing_profile(read_json_object(path, label=_display_path(path, root)))
    except OSError as exc:
        return {"name": "profile:model-routing", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": type(exc).__name__}}
    except LifecycleError as exc:
        return {"name": "profile:model-routing", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": exc.code}}
    return {
        "name": "profile:model-routing",
        "status": "PASS",
        "details": {
            "path": _display_path(path, root),
            "classCount": len(validation["classes"]),
            "phaseRuleCount": validation["phaseRuleCount"],
            "profileDigest": validation["profileDigest"],
        },
    }


def _read_optional_json(root: Path, path: Path, label: str, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        payload = read_json_object(path, label=label)
    except OSError as exc:
        checks.append({"name": "adapter:baseline", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": type(exc).__name__}})
        return None
    except LifecycleError as exc:
        checks.append({"name": "adapter:baseline", "status": "FAIL", "details": {"path": _display_path(path, root), "reason": exc.code}})
        return None
    checks.append({"name": "adapter:baseline", "status": "PASS", "details": {"path": _display_path(path, root)}})
    return payload


def _discover_adapters(root: Path) -> list[Path]:
    adapters = root / "adapters"
    if not adapters.is_dir():
        return []
    return sorted(adapters.glob("*/adapter.descriptor.json"))


def _evidence_summary(root: Path, adapters: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [item for item in adapters if item.get("maturity") == "VERIFIED"]
    missing = []
    local_only = 0
    for item in verified:
        evidence = item["liveEvidence"]
        missing.extend(
            {
                "host": item["host"],
                "path": path,
                "nextAction": "restore local ignored evidence or rely on tracked redacted docs summary before promotion review",
            }
            for path in evidence["missingPaths"]
        )
        if evidence["ignoredTasksEvidenceCount"]:
            local_only += evidence["ignoredTasksEvidenceCount"]
    status = "WARN" if missing else "PASS"
    return {
        "status": status,
        "verifiedAdapterCount": len(verified),
        "missingLocalEvidenceCount": len(missing),
        "ignoredTasksEvidenceCount": local_only,
        "missing": missing,
        "productionPromotionClaimed": False,
    }


def _evidence_paths(live_range: Any) -> list[str]:
    if not isinstance(live_range, dict):
        return []
    evidence = live_range.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [item for item in evidence if isinstance(item, str)]


def _local_evidence_status(root: Path, evidence_paths: list[str]) -> dict[str, Any]:
    existing = []
    missing = []
    ignored_tasks = 0
    for raw_path in evidence_paths:
        if raw_path.startswith("tasks/"):
            ignored_tasks += 1
        path = root / raw_path
        if path.is_file():
            existing.append(raw_path)
        else:
            missing.append(raw_path)
    return {
        "declaredPaths": evidence_paths,
        "existingPaths": existing,
        "missingPaths": missing,
        "ignoredTasksEvidenceCount": ignored_tasks,
        "status": "PASS" if not missing else "WARN",
    }


def _report_status(checks: list[dict[str, Any]], evidence: dict[str, Any]) -> str:
    if any(item.get("status") == "FAIL" for item in checks):
        return "FAIL"
    if evidence.get("status") == "WARN" or any(item.get("status") == "WARN" for item in checks):
        return "WARN"
    return "PASS"


def _summary(checks: list[dict[str, Any]], adapters: list[dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    fail_count = sum(1 for item in checks if item.get("status") == "FAIL")
    return {
        "checkCount": len(checks),
        "failedCheckCount": fail_count,
        "adapterCount": len(adapters),
        "verifiedAdapterCount": sum(1 for item in adapters if item.get("maturity") == "VERIFIED"),
        "experimentalAdapterCount": sum(1 for item in adapters if item.get("maturity") == "EXPERIMENTAL"),
        "missingLocalEvidenceCount": evidence.get("missingLocalEvidenceCount", 0),
    }


def _next_actions(checks: list[dict[str, Any]], adapters: list[dict[str, Any]], evidence: dict[str, Any]) -> list[str]:
    actions = []
    for item in checks:
        if item.get("status") == "FAIL":
            actions.append(f"fix {item['name']}")
    for adapter in adapters:
        if adapter.get("validationStatus") == "FAIL":
            actions.append(f"fix adapter descriptor {adapter['descriptorPath']}")
    if evidence.get("missingLocalEvidenceCount"):
        actions.append("restore or regenerate missing local live evidence before a promotion/release claim")
    if not actions:
        actions.append("continue with the next lifecycle step")
    return actions


def _file_check(root: Path, relative: Path, *, name: str) -> dict[str, Any]:
    path = root / relative
    return {
        "name": name,
        "status": "PASS" if path.exists() else "FAIL",
        "details": {"path": relative.as_posix()},
    }


def _tasks_ignore_check(root: Path) -> dict[str, Any] | None:
    git = root / ".git"
    if not git.exists():
        return None
    result = subprocess.run(
        ["git", "ls-files", "tasks"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=5,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    return {
        "name": "checkout:tasks-untracked",
        "status": "PASS" if result.returncode == 0 and not tracked else "FAIL",
        "details": {
            "trackedTasksCount": len(tracked),
            "gitAvailable": result.returncode == 0,
        },
    }


def _install_instructions(host: str, *, adapter_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    descriptor_arg = f"adapters/{adapter_id}/adapter.descriptor.json"
    common_validate = {
        "argv": [
            "agent-lifecycle",
            "adapter",
            "validate",
            "--descriptor",
            descriptor_arg,
            "--baseline",
            "conformance/core/adapter-baseline.v1.json",
        ],
        "purpose": "validate adapter descriptor before setup",
        "mutatesHost": False,
        "requiresOperator": False,
    }
    common_inspect = {
        "argv": [
            "agent-lifecycle",
            "adapter",
            "inspect",
            "--descriptor",
            descriptor_arg,
            "--skip-host-commands",
        ],
        "purpose": "inspect source projection without host commands",
        "mutatesHost": False,
        "requiresOperator": False,
    }
    table: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]] = {
        "codex": (
            [
                {"path": ".codex-plugin/plugin.json", "action": "read", "required": True},
                {"path": ".agents/plugins/marketplace.json", "action": "read", "required": True},
            ],
            [
                common_validate,
                common_inspect,
                {
                    "argv": ["codex", "plugin", "marketplace", "add", "avksp/agent-lifecycle-kit", "--ref", "vX.Y.Z"],
                    "purpose": "add trusted tagged source marketplace",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
                {
                    "argv": ["codex", "plugin", "add", "agent-lifecycle-kit@agent-lifecycle-kit"],
                    "purpose": "install plugin from configured marketplace",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
            ],
            ["choose the release tag", "restart the host session after installation"],
        ),
        "claude-code": (
            [
                {"path": ".claude-plugin/plugin.json", "action": "read", "required": True},
                {"path": ".claude-plugin/marketplace.json", "action": "read", "required": True},
            ],
            [
                common_validate,
                common_inspect,
                {
                    "argv": ["claude", "plugin", "marketplace", "add", "avksp/agent-lifecycle-kit"],
                    "purpose": "add repository marketplace",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
                {
                    "argv": ["claude", "plugin", "install", "agent-lifecycle-kit@agent-lifecycle-kit"],
                    "purpose": "install plugin from configured marketplace",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
            ],
            ["run reload command in the host session after installation"],
        ),
        "cursor": (
            [
                {"path": ".cursor-plugin/plugin.json", "action": "read", "required": True},
                {"path": ".cursor-plugin/marketplace.json", "action": "read", "required": True},
            ],
            [
                common_validate,
                common_inspect,
                {
                    "argv": ["ln", "-s", "<checkout>", "~/.cursor/plugins/local/agent-lifecycle-kit"],
                    "purpose": "link trusted checkout into the local plugin directory",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
            ],
            ["reload the host window", "do not claim VERIFIED until live receipts exist"],
        ),
        "opencode": (
            [
                {"path": "skills/*", "action": "copy-preview", "required": True},
                {"path": "adapters/opencode/plugins/agent-lifecycle-kit.js", "action": "copy-preview", "required": True},
                {"path": "opencode.json", "action": "read", "required": True},
            ],
            [
                common_validate,
                common_inspect,
                {
                    "argv": ["cp", "-R", "<checkout>/skills/*", ".opencode/skills/"],
                    "purpose": "copy shared skills into target project",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
            ],
            ["choose project-level or user-level installation"],
        ),
        "hermes": (
            [
                {"path": "skills.sh.json", "action": "read", "required": True},
                {"path": "adapters/hermes/hermes.registry.json", "action": "read", "required": True},
                {"path": "adapters/hermes/slash-commands.json", "action": "read", "required": True},
            ],
            [
                common_validate,
                common_inspect,
                {
                    "argv": ["hermes", "skills", "install", "https://raw.githubusercontent.com/avksp/agent-lifecycle-kit/vX.Y.Z/skills/agent-workflow-orchestrator/SKILL.md"],
                    "purpose": "install a tagged lifecycle skill",
                    "mutatesHost": True,
                    "requiresOperator": True,
                },
            ],
            ["install every required lifecycle skill from the chosen tag"],
        ),
    }
    if host in table:
        return table[host]
    files = [
        {"path": f"adapters/{adapter_id}/adapter.descriptor.json", "action": "read", "required": True},
        {"path": f"adapters/{adapter_id}/runner.py", "action": "read", "required": True},
        {"path": f"adapters/{adapter_id}/receipt_normalizer.py", "action": "read", "required": True},
    ]
    commands = [
        common_validate,
        common_inspect,
        {
            "argv": ["python", "-m", "pip", "install", "-e", "<checkout>"],
            "purpose": "install the core CLI from a trusted checkout",
            "mutatesHost": True,
            "requiresOperator": True,
        },
        {
            "argv": [_host_binary(host), "--version"],
            "purpose": "confirm host CLI is available before live proof",
            "mutatesHost": False,
            "requiresOperator": True,
        },
    ]
    return files, commands, ["configure host-local model/profile settings outside portable core", "keep adapter EXPERIMENTAL until receipts are accepted"]


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _host_binary(host: str) -> str:
    return {
        "gemini-cli": "gemini",
        "qwen-code": "qwen",
        "kimi-code": "kimi",
    }.get(host, host)


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _required_str(payload: dict[str, Any], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-adapter-descriptor", f"{_display_path(path, path.parent)}: {field} must be a non-empty string")
    return value
