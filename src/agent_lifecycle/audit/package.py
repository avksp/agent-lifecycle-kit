"""Package-level audit facade for ALK plan and implementation handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.audit.implementation import (
    build_final_implementation_audit,
    validate_final_implementation_audit,
)
from agent_lifecycle.audit.ownership import build_ownership_report, report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.planning import (
    load_plan_completeness_profile,
    require_repository_references_pass,
    validate_acceptance_checklist,
    validate_plan_completeness,
    validate_plan_manifest,
    validate_repository_references,
)
from agent_lifecycle.workflow.artifacts import package_root
from agent_lifecycle.workflow.state import load_state


PACKAGE_AUDIT_SCHEMA = "agent-plan-package-audit-report.v1"
_PLAN_FILES = (
    "README.md",
    "00-developer-overview.md",
    "acceptance-criteria.md",
    "write-set.md",
    "evidence-plan.md",
    "plan-review.md",
    "plan.manifest.json",
    "plan.lock.json",
)
_IMPLEMENTATION_REPORT_SCHEMA = "agent-implementation-audit-report.v1"


def build_package_audit(
    *,
    plan_dir: Path,
    state_path: Path | None = None,
    report_paths: list[str] | None = None,
    changed_paths: list[str] | None = None,
    base: str | None = None,
    require_frozen: bool = False,
    require_implementation: bool = False,
    completeness_profile_path: Path | None = None,
    auditor_id: str = "package-auditor",
    auditor_surface: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Audit a plan directory and optionally its completed implementation.

    The function is deliberately a read-only composition layer. It does not
    execute validation commands from the plan; those commands remain evidence
    supplied by the implementer and independent reviewer.
    """

    package_dir = plan_dir.expanduser().resolve()
    if not package_dir.is_dir():
        raise LifecycleError("plan-directory-missing", "plan directory was not found", {"path": str(package_dir)})
    manifest_path = package_dir / "plan.manifest.json"
    if manifest_path.is_symlink():
        raise LifecycleError("plan-manifest-symlink", "plan manifest must not be a symlink", {"path": str(manifest_path)})
    manifest = read_json_object(manifest_path, label="plan manifest")
    package_id = _package_id(manifest)
    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    package_files = _package_file_check(package_dir)
    _capture_check_failure("package-files", package_files, findings, blockers)

    profile = _load_profile(completeness_profile_path)
    manifest_check = _run_check(lambda: validate_plan_manifest(manifest))
    completeness_check = _run_check(lambda: validate_plan_completeness(manifest, profile=profile))
    _capture_check_failure("manifest", manifest_check, findings, blockers)
    _capture_check_failure("completeness", completeness_check, findings, blockers)

    lock_path = package_dir / "plan.lock.json"
    lock_check = _lock_check(manifest, lock_path, require_frozen=require_frozen)
    _capture_check_failure("lock", lock_check, findings, blockers)

    acceptance_path = package_dir / "acceptance-criteria.md"
    acceptance_check = _run_check(
        lambda: validate_acceptance_checklist(
            manifest,
            acceptance_path.read_text(encoding="utf-8"),
        )
    ) if acceptance_path.is_file() and not acceptance_path.is_symlink() else _missing_check(
        "acceptance-checklist-symlink" if acceptance_path.is_symlink() else "acceptance-checklist-missing",
        "acceptance checklist must not be a symlink" if acceptance_path.is_symlink() else "acceptance checklist was not found",
    )
    _capture_check_failure("acceptance", acceptance_check, findings, blockers)

    references_check = _run_check(
        lambda: require_repository_references_pass(validate_repository_references(manifest))
    )
    _capture_check_failure("references", references_check, findings, blockers)

    plan_status = _plan_status(
        manifest=manifest,
        checks={
            "packageFiles": package_files,
            "manifest": manifest_check,
            "completeness": completeness_check,
            "lock": lock_check,
            "acceptance": acceptance_check,
            "references": references_check,
        },
        require_frozen=require_frozen,
    )
    if require_frozen and manifest.get("status") != "FROZEN":
        _add_finding(
            findings,
            blockers,
            code="plan-not-frozen",
            severity="HIGH",
            category="plan",
            message="strict package review requires a FROZEN plan",
            context={"status": manifest.get("status")},
        )

    implementation = _build_implementation_section(
        manifest_path=manifest_path,
        manifest=manifest,
        state_path=state_path,
        report_paths=report_paths or [],
        changed_paths=changed_paths,
        base=base,
        require_frozen=require_frozen,
        require_implementation=require_implementation,
        project_root=project_root or Path.cwd(),
        findings=findings,
        blockers=blockers,
        package_id=package_id,
    )

    status = _overall_status(plan_status, implementation["status"], blockers)
    body = {
        "schemaVersion": PACKAGE_AUDIT_SCHEMA,
        "status": status,
        "packageId": package_id,
        "auditor": {"id": auditor_id, "surface": auditor_surface, "independent": True},
        "plan": {
            "directory": str(package_dir),
            "manifestPath": str(manifest_path),
            "status": plan_status,
            "manifestStatus": manifest.get("status"),
            "planRevision": manifest.get("planRevision"),
            "planDigest": canonical_digest(manifest),
            "checks": {
                "packageFiles": package_files,
                "manifest": manifest_check,
                "completeness": completeness_check,
                "lock": lock_check,
                "acceptance": acceptance_check,
                "references": references_check,
            },
        },
        "implementation": implementation,
        "findings": _sorted_findings(findings),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


def require_package_audit_pass(audit: dict[str, Any]) -> dict[str, Any]:
    """Raise at an explicit CLI gate while preserving the complete receipt."""

    if audit.get("status") != "PASS":
        raise LifecycleError(
            "package-audit-failed",
            "package audit did not pass",
            {"audit": audit},
        )
    return audit


def validate_package_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Validate the integrity and top-level semantics of a package receipt."""

    blockers: list[dict[str, Any]] = []
    if audit.get("schemaVersion") != PACKAGE_AUDIT_SCHEMA:
        blockers.append({"code": "package-audit-schema", "message": "unsupported package audit schemaVersion"})
    body = {key: value for key, value in audit.items() if key != "auditDigest"}
    if audit.get("auditDigest") != canonical_digest(body):
        blockers.append({"code": "package-audit-digest", "message": "auditDigest does not match package audit body"})
    if audit.get("status") not in {"PASS", "FAIL", "REVIEW_REQUIRED"}:
        blockers.append({"code": "package-audit-status", "message": "package audit status is unsupported"})
    if audit.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "package-audit-production-claim", "message": "package audit must not claim production promotion"})
    auditor = audit.get("auditor")
    if not isinstance(auditor, dict) or auditor.get("independent") is not True:
        blockers.append({"code": "package-audit-auditor", "message": "package auditor must be independent"})
    if audit.get("status") == "PASS" and audit.get("blockers"):
        blockers.append({"code": "package-audit-open-blockers", "message": "PASS package audit must not contain blockers"})
    result = {
        "schemaVersion": "agent-plan-package-audit-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "auditDigest": audit.get("auditDigest"),
    }
    return {**result, "validationDigest": canonical_digest(result)}


def _build_implementation_section(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    state_path: Path | None,
    report_paths: list[str],
    changed_paths: list[str] | None,
    base: str | None,
    require_frozen: bool,
    require_implementation: bool,
    project_root: Path,
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    package_id: str,
) -> dict[str, Any]:
    if state_path is None:
        status = "FAIL" if require_implementation else "NOT_PROVIDED"
        if require_implementation:
            _add_finding(
                findings,
                blockers,
                code="implementation-state-missing",
                severity="HIGH",
                category="implementation",
                message="implementation review requires --state",
                context={},
            )
        return {
            "status": status,
            "statePath": None,
            "reportPaths": [],
            "finalAudit": None,
            "finalValidation": None,
            "ownership": None,
        }

    state_file = state_path.expanduser().resolve()
    state_result = _run_check(lambda: load_state(state_file))
    if state_result["status"] != "PASS":
        _capture_check_failure("implementation-state", state_result, findings, blockers)
        return {
            "status": "FAIL",
            "statePath": str(state_file),
            "reportPaths": [],
            "finalAudit": None,
            "finalValidation": None,
            "ownership": None,
        }
    state = state_result["result"]
    lineage_blockers = _lineage_blockers(state, manifest, package_id)
    for item in lineage_blockers:
        _add_finding(
            findings,
            blockers,
            code=item["code"],
            severity="BLOCKER",
            category="implementation-lineage",
            message=item["message"],
            context=item.get("context", {}),
        )

    root = package_root(state_file, state).resolve()
    resolved_reports = _resolve_report_paths(root, report_paths, findings, blockers)
    if not report_paths:
        resolved_reports = _discover_report_paths(state_file, root, findings, blockers)

    final_audit: dict[str, Any] | None = None
    final_validation: dict[str, Any] | None = None
    report_status = "PASS" if resolved_reports else "REVIEW_REQUIRED"
    if resolved_reports:
        aggregate = _run_check(
            lambda: build_final_implementation_audit(
                manifest_path=manifest_path,
                state_path=state_file,
                report_paths=resolved_reports,
                auditor_id="package-auditor",
                auditor_surface="cli",
            )
        )
        if aggregate["status"] != "PASS":
            _capture_check_failure("final-implementation", aggregate, findings, blockers)
            report_status = "FAIL"
        else:
            final_audit = aggregate["result"]
            final_validation = validate_final_implementation_audit(final_audit, state=state)
            if final_validation.get("status") != "PASS":
                _capture_check_failure("final-implementation-validation", {"status": "FAIL", "blockers": final_validation.get("blockers", []), "result": final_validation}, findings, blockers)
                report_status = "FAIL"
            elif final_audit.get("status") != "PASS":
                _capture_check_failure("final-implementation", {"status": "FAIL", "blockers": final_audit.get("blockers", []), "result": final_audit}, findings, blockers)
                report_status = "FAIL"
    elif require_implementation:
        _add_finding(
            findings,
            blockers,
            code="implementation-reports-missing",
            severity="HIGH",
            category="implementation",
            message="no implementation audit reports were supplied or discovered",
            context={"stateDirectory": str(state_file.parent)},
        )
        report_status = "FAIL"

    ownership = _build_ownership(
        manifest_path=manifest_path,
        changed_paths=changed_paths,
        base=base,
        project_root=project_root,
        findings=findings,
        blockers=blockers,
    )
    if ownership is not None and report_has_category(ownership, {"forbidden", "read-only", "unowned"}):
        _add_finding(
            findings,
            blockers,
            code="package-ownership-failed",
            severity="HIGH",
            category="ownership",
            message="changed files include forbidden, read-only or unowned paths",
            context=ownership.get("summary", {}),
        )
        report_status = "FAIL"

    if lineage_blockers:
        report_status = "FAIL"
    if require_frozen and manifest.get("status") != "FROZEN":
        report_status = "FAIL"
    if report_status == "PASS" and blockers:
        report_status = "FAIL"
    return {
        "status": report_status,
        "statePath": str(state_file),
        "packageRoot": str(root),
        "reportPaths": resolved_reports,
        "finalAudit": final_audit,
        "finalValidation": final_validation,
        "ownership": ownership,
    }


def _build_ownership(
    *,
    manifest_path: Path,
    changed_paths: list[str] | None,
    base: str | None,
    project_root: Path,
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    paths = changed_paths
    try:
        if paths is None:
            paths = changed_files(project_root, base=base)
        return build_ownership_report(manifest_path, paths, base=base)
    except (LifecycleError, OSError) as exc:
        _add_finding(
            findings,
            blockers,
            code=getattr(exc, "code", "ownership-check-failed"),
            severity="HIGH",
            category="ownership",
            message=getattr(exc, "message", str(exc)),
            context=getattr(exc, "details", {}),
        )
        return None


def _resolve_report_paths(
    root: Path,
    raw_paths: list[str],
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> list[str]:
    resolved: list[str] = []
    for raw in raw_paths:
        try:
            resolved.append(_contained_relative_path(root, raw))
        except LifecycleError as exc:
            _add_finding(
                findings,
                blockers,
                code=exc.code,
                severity="HIGH",
                category="implementation-reports",
                message=exc.message,
                context={"path": raw, **exc.details},
            )
    return sorted(set(resolved))


def _discover_report_paths(
    state_path: Path,
    root: Path,
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> list[str]:
    discovered: list[str] = []
    candidates = sorted(state_path.parent.rglob("*.json"))
    if len(candidates) > 2048:
        _add_finding(
            findings,
            blockers,
            code="implementation-report-discovery-limit",
            severity="HIGH",
            category="implementation-reports",
            message="implementation report discovery exceeded its file limit",
            context={"limit": 2048, "directory": str(state_path.parent)},
        )
        candidates = candidates[:2048]
    for candidate in candidates:
        try:
            payload = read_json_object(candidate, label="implementation audit report")
        except LifecycleError:
            continue
        if payload.get("schemaVersion") != _IMPLEMENTATION_REPORT_SCHEMA:
            continue
        try:
            discovered.append(_contained_relative_path(root, str(candidate)))
        except LifecycleError:
            continue
    return sorted(set(discovered))


def _contained_relative_path(root: Path, raw: str) -> str:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise LifecycleError(
            "implementation-report-outside-root",
            "implementation audit report must remain under the workflow package root",
            {"root": str(root), "path": str(resolved)},
        ) from exc
    if not resolved.is_file():
        raise LifecycleError("implementation-report-missing", "implementation audit report was not found", {"path": str(resolved)})
    return normalize_repo_path(relative.as_posix(), label="implementation audit report")


def _package_file_check(package_dir: Path) -> dict[str, Any]:
    entries = []
    missing = []
    for name in _PLAN_FILES:
        path = package_dir / name
        exists = path.is_file()
        is_symlink = path.is_symlink()
        optional_draft_lock = name == "plan.lock.json" and not exists and not is_symlink
        status = "SYMLINK" if is_symlink else ("PASS" if exists else ("REVIEW_REQUIRED" if optional_draft_lock else "MISSING"))
        entries.append({"path": name, "status": status, "bytes": path.stat().st_size if exists and not is_symlink else 0})
        if (not exists and not optional_draft_lock) or is_symlink:
            missing.append(name)
    body = {
        "schemaVersion": "agent-plan-package-files.v1",
        "status": "PASS" if not missing else "FAIL",
        "requiredFiles": list(_PLAN_FILES),
        "entries": entries,
        "missing": missing,
    }
    return {**body, "checkDigest": canonical_digest(body)}


def _lock_check(manifest: dict[str, Any], lock_path: Path, *, require_frozen: bool) -> dict[str, Any]:
    if lock_path.is_symlink():
        return _missing_check("plan-lock-symlink", "plan lock must not be a symlink")
    if not lock_path.is_file():
        if require_frozen or manifest.get("status") == "FROZEN":
            return _missing_check("plan-lock-missing", "frozen plan lock was not found")
        return {"status": "REVIEW_REQUIRED", "reason": "draft plan has no lock yet", "path": str(lock_path)}
    return _run_check(lambda: verify_plan_lock(manifest, read_json_object(lock_path, label="plan lock")))


def _load_profile(path: Path | None) -> dict[str, Any] | None:
    return load_plan_completeness_profile(path) if path else None


def _run_check(callback: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"status": "PASS", "result": callback()}
    except LifecycleError as exc:
        return {"status": "FAIL", "blockers": [_error(exc)]}
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "blockers": [{"code": "audit-check-error", "message": str(exc), "context": {}}]}


def _missing_check(code: str, message: str) -> dict[str, Any]:
    return {"status": "FAIL", "blockers": [{"code": code, "message": message, "context": {}}]}


def _capture_check_failure(category: str, check: dict[str, Any], findings: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    if check.get("status") != "FAIL":
        return
    for item in check.get("blockers", []):
        if not isinstance(item, dict):
            continue
        _add_finding(
            findings,
            blockers,
            code=str(item.get("code") or f"{category}-failed"),
            severity="HIGH" if category in {"manifest", "completeness", "lock", "implementation-state", "implementation-reports"} else "MEDIUM",
            category=category,
            message=str(item.get("message") or f"{category} check failed"),
            context=item.get("context") if isinstance(item.get("context"), dict) else item,
        )


def _lineage_blockers(state: dict[str, Any], manifest: dict[str, Any], package_id: str) -> list[dict[str, Any]]:
    expected_digest = canonical_digest(manifest)
    checks = (
        ("implementation-package-mismatch", "workflow state packageId does not match the plan package", state.get("packageId"), package_id),
        ("implementation-revision-mismatch", "workflow state planRevision does not match the plan", state.get("planRevision"), manifest.get("planRevision")),
        ("implementation-digest-mismatch", "workflow state planDigest does not match the plan", state.get("planDigest"), expected_digest),
    )
    return [
        {"code": code, "message": message, "context": {"actual": actual, "expected": expected}}
        for code, message, actual, expected in checks
        if actual != expected
    ]


def _plan_status(*, manifest: dict[str, Any], checks: dict[str, dict[str, Any]], require_frozen: bool) -> str:
    if any(check.get("status") == "FAIL" for check in checks.values()):
        return "FAIL"
    if require_frozen and manifest.get("status") != "FROZEN":
        return "FAIL"
    if manifest.get("status") != "FROZEN" or checks["lock"].get("status") != "PASS":
        return "REVIEW_REQUIRED"
    return "PASS"


def _overall_status(plan_status: str, implementation_status: str, blockers: list[dict[str, Any]]) -> str:
    if blockers or plan_status == "FAIL" or implementation_status == "FAIL":
        return "FAIL"
    if plan_status == "PASS" and implementation_status == "PASS":
        return "PASS"
    return "REVIEW_REQUIRED"


def _package_id(manifest: dict[str, Any]) -> str:
    package = manifest.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("id"), str):
        raise LifecycleError("invalid-plan-manifest", "package.id is required")
    return package["id"]


def _error(exc: LifecycleError) -> dict[str, Any]:
    return {"code": exc.code, "message": exc.message, "context": exc.details}


def _add_finding(
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    *,
    code: str,
    severity: str,
    category: str,
    message: str,
    context: dict[str, Any],
) -> None:
    finding = {
        "id": f"finding-{canonical_digest({'code': code, 'category': category, 'message': message})[:16]}",
        "code": code,
        "severity": severity,
        "category": category,
        "status": "open",
        "message": message,
        "context": context,
    }
    findings.append(finding)
    blockers.append({"code": code, "severity": severity, "category": category, "message": message, "context": context})


def _sorted_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranks = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    return sorted(findings, key=lambda item: (ranks.get(str(item.get("severity")), 5), str(item.get("id"))))
