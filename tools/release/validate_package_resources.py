"""Validate the single, digest-bound package copy of built-in profiles."""

from __future__ import annotations

import argparse
import hashlib
import tomllib
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, write_json
except ModuleNotFoundError:  # pragma: no cover - direct script execution uses the branch above
    from tools.release.release_common import digest_value, write_json

RESOURCE_PATHS = (
    "lifecycle-baselines.v1.json",
    "model-routing-profile.v1.json",
    "risk-execution-policy.v1.json",
    "small-context-profile.v1.json",
    "project-workflow-presets/feature-implementation.v1.json",
    "project-workflow-presets/quick-change.v1.json",
    "project-workflow-presets/research-review.v1.json",
    "external-checks/import-boundaries.v1.json",
    "external-checks/module-dependencies.v1.json",
    "external-checks/declared-dependencies.v1.json",
)
PACKAGE_DATA_PATTERN = "data/profiles/**/*.json"


def validate_package_resources(
    *,
    pyproject_path: Path,
    source_root: Path,
    package_root: Path,
) -> dict[str, Any]:
    """Compare canonical profile bytes with the package-data copies."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    pyproject = _load_pyproject(pyproject_path, blockers)
    package_data = _package_data(pyproject)
    data_files = _data_files(pyproject)
    if PACKAGE_DATA_PATTERN not in package_data:
        blockers.append({"code": "package-data-pattern-missing", "pattern": PACKAGE_DATA_PATTERN})
    legacy_preset_entries = [
        item for item in data_files if item.replace("\\", "/").startswith("profiles/project-workflow-presets/")
    ]
    if legacy_preset_entries:
        blockers.append({"code": "legacy-preset-data-files", "paths": sorted(legacy_preset_entries)})
    checks.append(
        {
            "id": "package-data-declaration",
            "status": "PASS" if PACKAGE_DATA_PATTERN in package_data and not legacy_preset_entries else "FAIL",
            "packageData": sorted(package_data),
            "legacyPresetDataFiles": sorted(legacy_preset_entries),
        }
    )

    resource_records: list[dict[str, Any]] = []
    for relative in RESOURCE_PATHS:
        source = source_root / relative
        packaged = package_root / relative
        source_exists = source.is_file()
        package_exists = packaged.is_file()
        if not source_exists or not package_exists:
            blockers.append(
                {
                    "code": "resource-file-missing",
                    "path": relative,
                    "sourceExists": source_exists,
                    "packageExists": package_exists,
                }
            )
            resource_records.append(
                {
                    "path": relative,
                    "source": _identity(source) if source_exists else None,
                    "package": _identity(packaged) if package_exists else None,
                }
            )
            continue
        source_identity = _identity(source)
        package_identity = _identity(packaged)
        if (
            source_identity["sha256"] != package_identity["sha256"]
            or source_identity["bytes"] != package_identity["bytes"]
        ):
            blockers.append(
                {
                    "code": "resource-content-drift",
                    "path": relative,
                    "sourceSha256": source_identity["sha256"],
                    "packageSha256": package_identity["sha256"],
                }
            )
        resource_records.append({"path": relative, "source": source_identity, "package": package_identity})

    expected = set(RESOURCE_PATHS)
    actual_package = (
        {path.relative_to(package_root).as_posix() for path in package_root.rglob("*") if path.is_file()}
        if package_root.is_dir()
        else set()
    )
    unexpected = sorted(actual_package - expected)
    missing = sorted(expected - actual_package)
    if unexpected:
        blockers.append({"code": "unexpected-package-resource", "paths": unexpected})
    if missing:
        blockers.append({"code": "package-resource-inventory-incomplete", "paths": missing})
    checks.append(
        {
            "id": "resource-inventory",
            "status": "PASS" if not unexpected and not missing else "FAIL",
            "expected": sorted(expected),
            "actual": sorted(actual_package),
        }
    )

    resolver_path = package_root.parent.parent / "resources.py"
    resolver_text = resolver_path.read_text(encoding="utf-8") if resolver_path.is_file() else ""
    forbidden_markers = [
        marker
        for marker in ("subprocess", "socket", "urllib", "httpx", "requests", "adapter_sessions")
        if marker in resolver_text
    ]
    if "importlib.resources" not in resolver_text or "agent_lifecycle.data" not in resolver_text:
        blockers.append({"code": "resource-resolver-not-package-based"})
    if forbidden_markers:
        blockers.append({"code": "resource-resolver-forbidden-import", "markers": forbidden_markers})
    checks.append(
        {
            "id": "resource-resolver-boundary",
            "status": "PASS"
            if "importlib.resources" in resolver_text
            and "agent_lifecycle.data" in resolver_text
            and not forbidden_markers
            else "FAIL",
            "usesImportlibResources": "importlib.resources" in resolver_text,
            "usesPackageData": "agent_lifecycle.data" in resolver_text,
            "forbiddenMarkers": forbidden_markers,
        }
    )

    body: dict[str, Any] = {
        "schemaVersion": "agent-package-resources-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "sourceRoot": _display_path(source_root),
        "packageRoot": _display_path(package_root),
        "resourceCount": len(resource_records),
        "resources": resource_records,
        "checks": checks,
        "blockers": blockers,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _load_pyproject(path: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        blockers.append({"code": "pyproject-unreadable", "reason": type(exc).__name__})
        return {}
    return payload


def _package_data(pyproject: dict[str, Any]) -> list[str]:
    value = pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {})
    entries = value.get("agent_lifecycle", []) if isinstance(value, dict) else []
    return [str(item) for item in entries] if isinstance(entries, list) else []


def _data_files(pyproject: dict[str, Any]) -> list[str]:
    value = pyproject.get("tool", {}).get("setuptools", {}).get("data-files", {})
    if not isinstance(value, dict):
        return []
    return [str(item) for paths in value.values() if isinstance(paths, list) for item in paths]


def _identity(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    evidence = validate_package_resources(
        pyproject_path=Path(args.pyproject),
        source_root=Path(args.source_root),
        package_root=Path(args.package_root),
    )
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
