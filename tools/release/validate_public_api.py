"""Validate the explicit, supported Python import surface."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from release_common import digest_value, write_json
except ModuleNotFoundError:  # pragma: no cover - package imports use the relative path
    from tools.release.release_common import digest_value, write_json


SCHEMA = "agent-public-api-validation.v1"
POLICY_SCHEMA = "agent-python-public-api-policy.v1"


def validate_public_api(
    *,
    policy_path: Path,
    package_root: Path,
    english_path: Path,
    russian_path: Path,
) -> dict[str, Any]:
    """Check exports, annotations and bilingual documentation for the API policy."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    policy = _load_object(policy_path, blockers, code="public-api-policy-unreadable")
    package_name = policy.get("package")
    modules = policy.get("modules")
    if policy.get("schemaVersion") != POLICY_SCHEMA:
        blockers.append({"code": "public-api-policy-schema", "expected": POLICY_SCHEMA})
    if not isinstance(package_name, str) or not package_name:
        blockers.append({"code": "public-api-package-missing"})
        package_name = "agent_lifecycle"
    if not isinstance(modules, list) or not modules:
        blockers.append({"code": "public-api-modules-missing"})
        modules = []

    english = _read_text(english_path, blockers, code="public-api-english-unreadable")
    russian = _read_text(russian_path, blockers, code="public-api-russian-unreadable")
    _prepare_import_path(package_root)

    seen_modules: set[str] = set()
    inventory: list[dict[str, Any]] = []
    for entry in modules:
        if not isinstance(entry, dict):
            blockers.append({"code": "public-api-module-entry-invalid"})
            continue
        module_name = entry.get("module")
        exports = entry.get("exports")
        if not isinstance(module_name, str) or not module_name:
            blockers.append({"code": "public-api-module-name-invalid"})
            continue
        if module_name in seen_modules:
            blockers.append({"code": "public-api-module-duplicate", "module": module_name})
        seen_modules.add(module_name)
        if not isinstance(exports, list) or not all(isinstance(name, str) and name for name in exports):
            blockers.append({"code": "public-api-exports-invalid", "module": module_name})
            exports = []
        if len(set(exports)) != len(exports):
            blockers.append({"code": "public-api-export-duplicate", "module": module_name})
        inventory.append({"module": module_name, "exports": list(exports)})
        _check_module(module_name, list(exports), english, russian, blockers, checks)

    checks.append(
        {
            "id": "explicit-module-inventory",
            "status": "PASS"
            if not any(item.get("code", "").startswith("public-api-module") for item in blockers)
            else "FAIL",
            "modules": inventory,
        }
    )
    body: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "package": package_name,
        "packageRoot": _display_path(package_root),
        "moduleCount": len(inventory),
        "exportCount": sum(len(item["exports"]) for item in inventory),
        "modules": inventory,
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_module(
    module_name: str,
    expected_exports: list[str],
    english: str,
    russian: str,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    try:
        module = importlib.import_module(module_name)
    except (ImportError, AttributeError, OSError, RuntimeError) as exc:
        blockers.append({"code": "public-api-import-failed", "module": module_name, "error": type(exc).__name__})
        return

    actual_all = getattr(module, "__all__", None)
    expected_set = set(expected_exports)
    actual_set = set(actual_all) if isinstance(actual_all, (list, tuple)) else set()
    if actual_set != expected_set or len(actual_set) != len(expected_exports):
        blockers.append(
            {
                "code": "public-api-export-inventory-mismatch",
                "module": module_name,
                "expected": sorted(expected_set),
                "actual": sorted(actual_set),
            }
        )

    implicit = sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and name not in expected_set and not isinstance(value, ModuleType)
    )
    if implicit:
        blockers.append({"code": "public-api-implicit-export", "module": module_name, "exports": implicit})

    missing_docs: list[str] = []
    incomplete_annotations: list[str] = []
    missing: list[str] = []
    for name in expected_exports:
        try:
            value = getattr(module, name)
        except AttributeError:
            missing.append(name)
            continue
        if not _documented(module_name, name, english, russian):
            missing_docs.append(name)
        if inspect.isfunction(value) and not _has_complete_annotations(value):
            incomplete_annotations.append(name)
    if missing:
        blockers.append({"code": "public-api-export-missing", "module": module_name, "exports": missing})
    if missing_docs:
        blockers.append({"code": "public-api-documentation-missing", "module": module_name, "exports": missing_docs})
    if incomplete_annotations:
        blockers.append(
            {"code": "public-api-annotations-incomplete", "module": module_name, "exports": incomplete_annotations}
        )
    checks.append(
        {
            "id": f"module:{module_name}",
            "status": "PASS"
            if not missing
            and not missing_docs
            and not incomplete_annotations
            and actual_set == expected_set
            and not implicit
            else "FAIL",
            "exportCount": len(expected_exports),
            "missing": missing,
            "missingDocumentation": missing_docs,
            "incompleteAnnotations": incomplete_annotations,
            "implicitExports": implicit,
        }
    )


def _has_complete_annotations(value: Any) -> bool:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return False
    return signature.return_annotation is not inspect.Signature.empty and all(
        parameter.annotation is not inspect.Signature.empty for parameter in signature.parameters.values()
    )


def _documented(module_name: str, name: str, english: str, russian: str) -> bool:
    full_token = f"`{module_name}.{name}`"
    module_token = f"`{module_name}`"
    name_token = f"`{name}`"
    return all(
        (full_token in document or (module_token in document and name_token in document))
        for document in (english, russian)
    )


def _prepare_import_path(package_root: Path) -> None:
    parent = package_root.resolve().parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    importlib.invalidate_caches()


def _load_object(path: Path, blockers: list[dict[str, Any]], *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        blockers.append({"code": code, "path": _display_path(path)})
        return {}
    if not isinstance(value, dict):
        blockers.append({"code": code, "path": _display_path(path)})
        return {}
    return value


def _read_text(path: Path, blockers: list[dict[str, Any]], *, code: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        blockers.append({"code": code, "path": _display_path(path)})
        return ""


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--english", required=True)
    parser.add_argument("--russian", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    evidence = validate_public_api(
        policy_path=Path(args.policy),
        package_root=Path(args.package_root),
        english_path=Path(args.english),
        russian_path=Path(args.russian),
    )
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
