from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, load_json, write_json
except ModuleNotFoundError:  # pragma: no cover - supports package-style test imports
    from tools.release.release_common import digest_value, file_identity, load_json, write_json

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.freeze import verify_plan_package_integrity

PACKAGE_INTEGRITY_VALIDATION_SCHEMA = "agent-plan-package-integrity-validation.v1"


def validate_plan_package(
    *,
    repository_root: Path,
    package_root: Path,
    manifest_path: Path,
    lock_path: Path,
    require_schema: str = "agent-plan-lock.v2",
    reject_undeclared: bool = False,
) -> dict[str, Any]:
    """Run the same package-integrity authority used by runtime consumers."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    try:
        manifest = load_json(manifest_path)
        lock = load_json(lock_path)
        expected_package = package_root.resolve()
        declared_package = (repository_root / manifest["package"]["planArtifactRoot"]).resolve()
        if declared_package != expected_package:
            raise LifecycleError("plan-package-root-mismatch", "manifest package root does not match validator input")
        if lock.get("schemaVersion") != require_schema:
            raise LifecycleError("plan-lock-schema-mismatch", "plan lock does not use the required schema", {"required": require_schema})
        verification = verify_plan_package_integrity(manifest, lock, repository_root=repository_root)
        if reject_undeclared and verification.get("filesystemVerified") is not True:
            raise LifecycleError("plan-package-filesystem-unverified", "package inventory was not verified against filesystem bytes")
        checks = [
            {"id": "lock-envelope", "status": "PASS"},
            {"id": "declared-inventory", "status": "PASS", "entryCount": len(verification.get("entries", []))},
            {"id": "filesystem-bytes-and-digests", "status": "PASS"},
            {"id": "undeclared-top-level", "status": "PASS" if reject_undeclared else "NOT_REQUESTED"},
        ]
    except (LifecycleError, OSError, KeyError, TypeError, ValueError) as exc:
        blockers.append(
            {
                "code": getattr(exc, "code", "plan-package-integrity-validation-failed"),
                "message": getattr(exc, "message", str(exc)),
                "context": getattr(exc, "details", {}),
            }
        )
        checks.append({"id": "package-integrity", "status": "FAIL"})
        verification = None
        manifest = {}
        lock = {}
    body = {
        "schemaVersion": PACKAGE_INTEGRITY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "repositoryRoot": repository_root.resolve().as_posix(),
        "packageRoot": package_root.resolve().as_posix(),
        "manifest": file_identity(manifest_path) if manifest_path.is_file() else None,
        "lock": file_identity(lock_path) if lock_path.is_file() else None,
        "requiredLockSchema": require_schema,
        "rejectUndeclared": reject_undeclared,
        "checks": checks,
        "verification": verification,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--require-schema", default="agent-plan-lock.v2")
    parser.add_argument("--reject-undeclared", action="store_true")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_plan_package(
        repository_root=Path.cwd(),
        package_root=Path(args.package_root),
        manifest_path=Path(args.manifest),
        lock_path=Path(args.lock),
        require_schema=args.require_schema,
        reject_undeclared=args.reject_undeclared,
    )
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
