"""Read-only composition of canonical plan verification checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.freeze import verify_plan_lock, verify_plan_package_integrity
from agent_lifecycle.planning.acceptance_markdown import validate_acceptance_checklist
from agent_lifecycle.planning.completeness import validate_plan_completeness
from agent_lifecycle.planning.continuity import validate_repository_references
from agent_lifecycle.planning.validation import validate_plan_manifest

VERIFICATION_SCHEMA = "agent-plan-verification-receipt.v1"
_TERMINAL_WORKFLOW_PHASES = frozenset({"COMPLETE", "FAILED", "CANCELLED"})


def build_plan_verification(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
    lock: dict[str, Any] | None = None,
    acceptance_markdown: str | None = None,
    workflow_state: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    package_root: Path | None = None,
) -> dict[str, Any]:
    """Build one bounded receipt without executing manifest validation commands."""

    root = (repository_root or Path.cwd()).resolve()
    blockers: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    manifest_check = _check("manifest", lambda: validate_plan_manifest(manifest))
    checks["manifest"] = manifest_check
    _extend_blockers(blockers, manifest_check)

    package_only = package_root is not None and _is_package_inventory_fixture(manifest)
    completeness_check = (
        {"status": "NOT_APPLICABLE", "packageOnly": True, "blockers": []}
        if package_only
        else _check("completeness", lambda: validate_plan_completeness(manifest))
    )
    checks["completeness"] = completeness_check
    _extend_blockers(blockers, completeness_check)

    acceptance_check = (
        {"status": "NOT_APPLICABLE", "packageOnly": True, "blockers": []}
        if package_only
        else _acceptance_check(manifest, manifest_path, acceptance_markdown)
    )
    checks["acceptance"] = acceptance_check
    _extend_blockers(blockers, acceptance_check)

    references_check = validate_repository_references(manifest)
    checks["references"] = references_check
    _extend_blockers(blockers, references_check)

    state_check, lock_required = _workflow_lock_requirement(workflow_state)
    checks["workflowState"] = state_check
    _extend_blockers(blockers, state_check)

    package_root_check = _package_root_check(manifest, package_root, root)
    checks["packageRoot"] = package_root_check
    _extend_blockers(blockers, package_root_check)

    lock_check = _lock_check(
        manifest,
        _manifest_path=manifest_path,
        lock=lock,
        repository_root=root,
        required=manifest.get("status") == "FROZEN" or lock_required,
    )
    checks["lock"] = lock_check
    _extend_blockers(blockers, lock_check)

    body = {
        "schemaVersion": VERIFICATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageId": _package_id(manifest),
        "planStatus": manifest.get("status") if isinstance(manifest.get("status"), str) else None,
        "planRevision": manifest.get("planRevision") if isinstance(manifest.get("planRevision"), int) else None,
        "planDigest": canonical_digest(manifest),
        "manifestPath": _display_path(manifest_path, root),
        "packageRoot": _display_path(package_root, root) if package_root is not None else None,
        "checks": checks,
        "blockers": _sorted_blockers(blockers),
        "executedCommands": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "verificationDigest": canonical_digest(body)}


def require_plan_verification_pass(receipt: dict[str, Any]) -> dict[str, Any]:
    """Raise an explicit CLI gate while retaining the complete receipt in details."""

    if receipt.get("status") != "PASS":
        raise LifecycleError(
            "plan-verification-failed",
            "plan verification did not pass",
            {"verification": receipt},
        )
    return receipt


def _check(label: str, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        result = operation()
    except LifecycleError as exc:
        return {
            "status": "FAIL",
            "blockers": [_exception_blocker(exc)],
        }
    except (OSError, ValueError, TypeError):
        return {
            "status": "FAIL",
            "blockers": [{"code": f"plan-{label}-failed", "message": f"{label} check failed"}],
        }
    if isinstance(result, dict) and result.get("status") == "FAIL":
        return {"status": "FAIL", "result": result, "blockers": list(result.get("blockers", []))}
    return {"status": "PASS", "result": result, "blockers": []}


def _acceptance_check(manifest: dict[str, Any], manifest_path: Path, markdown: str | None) -> dict[str, Any]:
    if markdown is None:
        candidate = manifest_path.parent / "acceptance-criteria.md"
        if candidate.is_symlink():
            return {
                "status": "FAIL",
                "blockers": [
                    {"code": "acceptance-checklist-symlink", "message": "acceptance checklist must not be a symlink"}
                ],
            }
        if not candidate.is_file():
            return {
                "status": "FAIL",
                "blockers": [{"code": "acceptance-checklist-missing", "message": "acceptance checklist was not found"}],
            }
        try:
            markdown = candidate.read_text(encoding="utf-8")
        except OSError:
            return {
                "status": "FAIL",
                "blockers": [
                    {"code": "acceptance-checklist-unreadable", "message": "acceptance checklist could not be read"}
                ],
            }
    return _check("acceptance", lambda: validate_acceptance_checklist(manifest, markdown or ""))


def _workflow_lock_requirement(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if state is None:
        return {"status": "NOT_PROVIDED", "blockers": []}, False
    phase = state.get("phase")
    if not isinstance(phase, str) or not phase:
        return {
            "status": "FAIL",
            "blockers": [{"code": "workflow-state-phase-invalid", "message": "workflow state phase is required"}],
        }, True
    required = phase not in _TERMINAL_WORKFLOW_PHASES
    return {"status": "PASS", "phase": phase, "lockRequired": required, "blockers": []}, required


def _lock_check(
    manifest: dict[str, Any],
    *,
    _manifest_path: Path,
    lock: dict[str, Any] | None,
    repository_root: Path,
    required: bool,
) -> dict[str, Any]:
    if lock is None:
        if required:
            return {
                "status": "FAIL",
                "required": True,
                "blockers": [
                    {"code": "plan-lock-required", "message": "plan lock is required for this plan or workflow state"}
                ],
            }
        return {"status": "NOT_REQUIRED", "required": False, "blockers": []}
    try:
        if manifest.get("packageIntegrity"):
            result = verify_plan_package_integrity(manifest, lock, repository_root=repository_root)
        else:
            result = verify_plan_lock(manifest, lock)
    except LifecycleError as exc:
        return {"status": "FAIL", "required": required, "blockers": [_exception_blocker(exc)]}
    return {"status": "PASS", "required": required, "result": result, "blockers": []}


def load_verification_inputs(
    *,
    manifest_path: Path,
    lock_path: Path | None = None,
    acceptance_path: Path | None = None,
    state_path: Path | None = None,
    package_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None, dict[str, Any] | None, Path | None]:
    """Load only explicit or documented sibling artifacts for the CLI facade."""

    if manifest_path.is_symlink():
        raise LifecycleError("plan-manifest-symlink", "plan manifest must not be a symlink")
    manifest = read_json_object(manifest_path, label="plan manifest")
    resolved_lock = lock_path or manifest_path.with_name("plan.lock.json")
    if lock_path is not None and not resolved_lock.is_file():
        raise LifecycleError("plan-lock-missing", "explicit plan lock was not found")
    if resolved_lock.is_symlink():
        raise LifecycleError("plan-lock-symlink", "plan lock must not be a symlink")
    lock = read_json_object(resolved_lock, label="plan lock") if resolved_lock.is_file() else None
    resolved_acceptance = acceptance_path or manifest_path.with_name("acceptance-criteria.md")
    if acceptance_path is not None and not resolved_acceptance.is_file():
        raise LifecycleError("acceptance-checklist-missing", "explicit acceptance checklist was not found")
    if resolved_acceptance.is_symlink():
        raise LifecycleError("acceptance-checklist-symlink", "acceptance checklist must not be a symlink")
    markdown = resolved_acceptance.read_text(encoding="utf-8") if resolved_acceptance.is_file() else None
    state = read_json_object(state_path, label="workflow state") if state_path else None
    return manifest, lock, markdown, state, package_root


def _exception_blocker(exc: LifecycleError) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        blocker["context"] = exc.details
    return blocker


def _sorted_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        blockers,
        key=lambda item: (str(item.get("code", "")), str(item.get("message", "")), repr(item.get("context", {}))),
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _package_id(manifest: dict[str, Any]) -> str | None:
    package = manifest.get("package")
    return package.get("id") if isinstance(package, dict) and isinstance(package.get("id"), str) else None


def _is_package_inventory_fixture(manifest: dict[str, Any]) -> bool:
    return not isinstance(manifest.get("specification"), dict) and not isinstance(manifest.get("acceptance"), dict)


def _package_root_check(manifest: dict[str, Any], package_root: Path | None, repository_root: Path) -> dict[str, Any]:
    if package_root is None:
        return {"status": "NOT_PROVIDED", "blockers": []}
    package_value = manifest.get("package")
    package = package_value if isinstance(package_value, dict) else {}
    declared = package.get("planArtifactRoot")
    if not isinstance(declared, str) or not declared:
        return {
            "status": "FAIL",
            "blockers": [{"code": "plan-package-root-missing", "message": "package.planArtifactRoot is required"}],
        }
    try:
        expected = (repository_root / declared).resolve()
        actual = package_root.resolve()
    except OSError:
        return {
            "status": "FAIL",
            "blockers": [{"code": "plan-package-root-invalid", "message": "package root could not be resolved"}],
        }
    if expected != actual:
        return {
            "status": "FAIL",
            "blockers": [
                {"code": "plan-package-root-mismatch", "message": "package root does not match manifest authority"}
            ],
        }
    return {"status": "PASS", "path": _display_path(actual, repository_root), "blockers": []}


def _extend_blockers(target: list[dict[str, Any]], check: dict[str, Any]) -> None:
    value = check.get("blockers")
    if isinstance(value, list):
        target.extend(item for item in value if isinstance(item, dict))


__all__ = [
    "VERIFICATION_SCHEMA",
    "build_plan_verification",
    "load_verification_inputs",
    "require_plan_verification_pass",
]
