"""Reviewed plan-lock creation command."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    load_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.freeze.package_integrity import (
    build_reviewed_plan_lock_v2,
    verify_plan_package_integrity,
)

PLAN_LOCK_CREATION_RECEIPT = "agent-plan-lock-creation-receipt.v1"


def create_reviewed_plan_lock(
    *,
    manifest_path: str,
    review_path: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Create and verify the canonical lock for one reviewed frozen plan."""

    root = repository_root.resolve(strict=True)
    manifest_rel, manifest_data = _read_repository_json(root, manifest_path, label="plan manifest")
    manifest = load_json_object(manifest_data, label="plan manifest")
    package_value = manifest.get("package")
    package = package_value if isinstance(package_value, dict) else {}
    raw_plan_root = package.get("planArtifactRoot")
    if not isinstance(raw_plan_root, str):
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    plan_root = normalize_repo_path(raw_plan_root, label="package.planArtifactRoot")
    expected_manifest = f"{plan_root}/plan.manifest.json"
    if manifest_rel != expected_manifest:
        raise LifecycleError("plan-manifest-path-mismatch", "manifest path does not match package.planArtifactRoot")

    review_rel, review_data = _read_repository_json(root, review_path, label="plan review")
    review = load_json_object(review_data, label="plan review")
    lock = build_reviewed_plan_lock_v2(
        manifest,
        review,
        review_path=review_rel,
        review_sha256=sha256_hex(review_data),
        repository_root=root,
    )
    # Reject malformed or drifting package bytes before creating the
    # no-replace authority artifact. The second check still detects drift.
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    lock_rel = f"{plan_root}/plan.lock.json"
    lock_path = root.joinpath(*PurePosixPath(lock_rel).parts)
    try:
        write_json_create(lock_path, lock)
    except FileExistsError as exc:
        raise LifecycleError("plan-lock-exists", "canonical plan lock already exists", {"path": lock_rel}) from exc
    except OSError as exc:
        raise LifecycleError(
            "plan-lock-write-failed",
            "canonical plan lock could not be created",
            {"path": lock_rel},
        ) from exc
    verification = verify_plan_package_integrity(manifest, lock, repository_root=root)
    body = {
        "schemaVersion": PLAN_LOCK_CREATION_RECEIPT,
        "status": "PASS",
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "manifestPath": manifest_rel,
        "manifestHash": canonical_digest(manifest),
        "reviewPath": review_rel,
        "reviewId": review.get("reviewId"),
        "reviewedPlanHash": review.get("reviewedPlanHash"),
        "lockPath": lock_rel,
        "lockSchemaVersion": lock.get("schemaVersion"),
        "planFilesHash": lock.get("planFilesHash"),
        "filesystemVerified": verification.get("filesystemVerified") is True,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _read_repository_json(root: Path, raw_path: str, *, label: str) -> tuple[str, bytes]:
    relative = normalize_repo_path(raw_path, label=f"{label} path")
    data = read_stable_repository_file(root, relative, max_bytes=MAX_JSON_INPUT_BYTES, label=label)
    return relative, data


__all__ = ["PLAN_LOCK_CREATION_RECEIPT", "create_reviewed_plan_lock"]
