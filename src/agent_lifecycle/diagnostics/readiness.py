"""Read-only readiness diagnostics for the current source checkout."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.context import load_context_profile
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.diagnostics.installation_catalog import load_installation_facts
from agent_lifecycle.host_protocol import (
    inspect_adapter_descriptor,
    validate_adapter_descriptor,
)
from agent_lifecycle.model_routing import validate_model_routing_profile

READINESS_SCHEMA_VERSION = "agent-readiness-report.v1"
INSTALL_PLAN_SCHEMA_VERSION = "agent-adapter-install-plan.v1"
EVIDENCE_SUMMARY_INDEX_SCHEMA_VERSION = "agent-adapter-evidence-summary-index.v1"
DEFAULT_EVIDENCE_SUMMARY_INDEX = Path("docs/adapters/evidence/adapter-evidence-summary.v1.json")


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
    evidence_summary_index: Path | None = None,
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
    evidence_index_path = _resolve(root, evidence_summary_index or DEFAULT_EVIDENCE_SUMMARY_INDEX)
    descriptors = [_resolve(root, item) for item in adapter_paths] if adapter_paths else _discover_adapters(root)

    checks: list[dict[str, Any]] = []
    checks.extend(_checkout_checks(root))
    checks.extend(_package_checks(root))
    checks.append(_context_profile_check(root, context_profile_path))
    checks.append(_model_profile_check(root, model_profile_path))

    baseline = _read_optional_json(root, baseline_path, "adapter baseline", checks)
    tracked_evidence = _read_tracked_evidence_index(root, evidence_index_path, checks)
    adapters: list[dict[str, Any]] = []
    install_plans: list[dict[str, Any]] = []
    host_probe_count = 0
    for descriptor_path in descriptors:
        adapter_record, probe_used = _adapter_record(
            root,
            descriptor_path,
            baseline=baseline,
            tracked_evidence=tracked_evidence,
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
    installation = (
        load_installation_facts(descriptor)
        if "installation" in descriptor
        else _undeclared_installation_facts()
    )
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
        "installationStatus": "DECLARED" if "installation" in descriptor else "NOT_DECLARED",
        "binaryAliases": installation["binaryAliases"],
        "files": installation["files"],
        "commands": [*_diagnostic_commands(adapter_id), *installation["commands"]],
        "operatorActions": installation["operatorActions"],
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
    tracked_evidence: dict[str, dict[str, Any]],
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
    adapter_id = descriptor.get("adapterId")
    local_evidence = _local_evidence_status(
        root,
        evidence_paths,
        tracked_summary=tracked_evidence.get(adapter_id) if isinstance(adapter_id, str) else None,
        tracked_summary_required=maturity == "VERIFIED",
    )
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
            "missingTrackedEvidencePaths": [],
            "missingLocalRawReceiptPaths": [],
            "localOnlyEvidenceCount": 0,
            "missingLocalRawReceiptCount": 0,
            "trackedSummaryPath": None,
            "trackedSummaryStatus": "NOT_REQUIRED",
            "status": "SKIPPED",
        },
        "validationSummary": validation_summary,
    }


def _checkout_checks(root: Path) -> list[dict[str, Any]]:
    return [
        _file_check(root, Path("pyproject.toml"), name="checkout:pyproject"),
        _file_check(root, Path("src/agent_lifecycle"), name="checkout:package-source"),
        _file_check(root, Path("adapters"), name="checkout:adapters"),
    ]


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


def _read_tracked_evidence_index(root: Path, path: Path, checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    display_path = _display_path(path, root)
    try:
        payload = read_json_object(path, label=display_path)
    except OSError as exc:
        checks.append({"name": "evidence:tracked-summary-index", "status": "WARN", "details": {"path": display_path, "reason": type(exc).__name__}})
        return {}
    except LifecycleError as exc:
        checks.append({"name": "evidence:tracked-summary-index", "status": "WARN", "details": {"path": display_path, "reason": exc.code}})
        return {}

    invalid: list[dict[str, Any]] = []
    entries = payload.get("adapters")
    if payload.get("schemaVersion") != EVIDENCE_SUMMARY_INDEX_SCHEMA_VERSION:
        invalid.append({"code": "invalid-schema-version", "value": payload.get("schemaVersion")})
    if not isinstance(entries, list):
        invalid.append({"code": "invalid-adapters", "message": "adapters must be a list"})
        entries = []

    by_adapter: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            invalid.append({"code": "invalid-adapter-entry", "index": index})
            continue
        adapter_id = item.get("adapterId")
        summary_path = item.get("summaryPath")
        if not isinstance(adapter_id, str) or not adapter_id:
            invalid.append({"code": "invalid-adapter-id", "index": index})
            continue
        if not isinstance(summary_path, str) or not summary_path:
            invalid.append({"code": "invalid-summary-path", "adapterId": adapter_id})
            continue
        if not (root / summary_path).is_file():
            invalid.append({"code": "missing-summary-path", "adapterId": adapter_id, "path": summary_path})
        by_adapter[adapter_id] = item

    checks.append(
        {
            "name": "evidence:tracked-summary-index",
            "status": "PASS" if not invalid else "WARN",
            "details": {
                "path": display_path,
                "schemaVersion": payload.get("schemaVersion"),
                "adapterCount": len(by_adapter),
                "invalidCount": len(invalid),
                "invalid": invalid,
            },
        }
    )
    return by_adapter


def _discover_adapters(root: Path) -> list[Path]:
    adapters = root / "adapters"
    if not adapters.is_dir():
        return []
    return sorted(adapters.glob("*/adapter.descriptor.json"))


def _evidence_summary(root: Path, adapters: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [item for item in adapters if item.get("maturity") == "VERIFIED"]
    missing_local_raw = []
    missing_tracked = []
    local_only = 0
    tracked_summary_count = 0
    for item in verified:
        evidence = item["liveEvidence"]
        missing_local_raw.extend(
            {
                "host": item["host"],
                "path": path,
                "kind": "local-raw-receipt",
                "nextAction": "restore local raw receipt only when re-running live promotion review",
            }
            for path in evidence["missingLocalRawReceiptPaths"]
        )
        missing_tracked.extend(
            {
                "host": item["host"],
                "path": path,
                "kind": "tracked-redacted-summary",
                "nextAction": "restore the tracked redacted evidence summary before a release claim",
            }
            for path in evidence["missingTrackedEvidencePaths"]
        )
        if evidence["localOnlyEvidenceCount"]:
            local_only += evidence["localOnlyEvidenceCount"]
        if evidence["trackedSummaryStatus"] == "AVAILABLE":
            tracked_summary_count += 1
    status = "WARN" if missing_tracked else "PASS"
    return {
        "status": status,
        "verifiedAdapterCount": len(verified),
        "trackedSummaryCount": tracked_summary_count,
        "missingTrackedEvidenceSummaryCount": len(missing_tracked),
        "missingLocalEvidenceCount": len(missing_local_raw),
        "missingLocalRawReceiptCount": len(missing_local_raw),
        "localOnlyEvidenceCount": local_only,
        "missingTrackedEvidenceSummaries": missing_tracked,
        "missingLocalRawReceipts": missing_local_raw,
        "missing": missing_tracked + missing_local_raw,
        "productionPromotionClaimed": False,
    }


def _evidence_paths(live_range: Any) -> list[str]:
    if not isinstance(live_range, dict):
        return []
    evidence = live_range.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [item for item in evidence if isinstance(item, str)]


def _local_evidence_status(
    root: Path,
    evidence_paths: list[str],
    *,
    tracked_summary: dict[str, Any] | None,
    tracked_summary_required: bool,
) -> dict[str, Any]:
    existing = []
    missing = []
    missing_tracked = []
    missing_local_raw = []
    local_only = 0
    tracked_summary_path = tracked_summary.get("summaryPath") if isinstance(tracked_summary, dict) else None
    for raw_path in evidence_paths:
        is_local_raw = raw_path.startswith("work/")
        if raw_path.startswith("work/"):
            local_only += 1
        path = root / raw_path
        if path.is_file():
            existing.append(raw_path)
        else:
            missing.append(raw_path)
            if is_local_raw:
                missing_local_raw.append(raw_path)
            else:
                missing_tracked.append(raw_path)
    tracked_summary_status = "NOT_REQUIRED"
    if tracked_summary_required:
        if isinstance(tracked_summary_path, str) and (root / tracked_summary_path).is_file():
            tracked_summary_status = "AVAILABLE"
        else:
            tracked_summary_status = "MISSING"
            if isinstance(tracked_summary_path, str):
                if tracked_summary_path not in missing_tracked:
                    missing_tracked.append(tracked_summary_path)
            else:
                missing_tracked.append("<tracked-summary-index-entry>")
    status = "WARN" if missing_tracked else "PASS"
    if not evidence_paths and not tracked_summary_required:
        status = "SKIPPED"
    return {
        "declaredPaths": evidence_paths,
        "existingPaths": existing,
        "missingPaths": missing,
        "missingTrackedEvidencePaths": missing_tracked,
        "missingLocalRawReceiptPaths": missing_local_raw,
        "localOnlyEvidenceCount": local_only,
        "missingLocalRawReceiptCount": len(missing_local_raw),
        "trackedSummaryPath": tracked_summary_path if isinstance(tracked_summary_path, str) else None,
        "trackedSummaryStatus": tracked_summary_status,
        "status": status,
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
        "missingLocalRawReceiptCount": evidence.get("missingLocalRawReceiptCount", 0),
        "missingTrackedEvidenceSummaryCount": evidence.get("missingTrackedEvidenceSummaryCount", 0),
    }


def _next_actions(checks: list[dict[str, Any]], adapters: list[dict[str, Any]], evidence: dict[str, Any]) -> list[str]:
    actions = []
    for item in checks:
        if item.get("status") == "FAIL":
            actions.append(f"fix {item['name']}")
    for adapter in adapters:
        if adapter.get("validationStatus") == "FAIL":
            actions.append(f"fix adapter descriptor {adapter['descriptorPath']}")
    if evidence.get("missingTrackedEvidenceSummaryCount"):
        actions.append("restore tracked redacted evidence summaries before a release claim")
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


def _diagnostic_commands(adapter_id: str) -> list[dict[str, Any]]:
    descriptor_arg = f"adapters/{adapter_id}/adapter.descriptor.json"
    return [
        {
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
        },
        {
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
        },
    ]


def _undeclared_installation_facts() -> dict[str, Any]:
    """Keep scaffold diagnostics read-only until a descriptor adds installation facts."""

    return {
        "binaryAliases": [],
        "files": [],
        "commands": [],
        "operatorActions": ["Add validated installation facts to the adapter descriptor before host-local setup."],
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


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
