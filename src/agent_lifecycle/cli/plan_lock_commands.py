"""Reviewed plan-lock creation command."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.contracts.ownership_paths import (
    is_under_authority_path,
    repository_authority_name,
    require_declared_output_footprint,
    require_output_footprint,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.freeze.package_integrity import (
    _reject_undeclared_top_level_files,
    build_reviewed_plan_lock_v2,
    verify_plan_package_integrity,
)
from agent_lifecycle.planning.verification import build_plan_verification

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


def prepare_freeze_candidate(
    *,
    manifest_path: str,
    output_path: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Prepare exact candidate bytes before review, without review or lock authority."""
    root = repository_root.resolve(strict=True)
    manifest_rel, raw = _read_repository_json(root, manifest_path, label="draft manifest")
    manifest = load_json_object(raw)
    if manifest.get("status") != "DRAFT":
        raise LifecycleError("freeze-prepare-requires-draft", "Only a draft may be prepared")
    old = normalize_repo_path(manifest.get("package", {}).get("planArtifactRoot"))
    if manifest_rel != old + "/plan.manifest.json":
        raise LifecycleError("plan-manifest-path-mismatch", "Manifest must match its declared package")
    if not manifest.get("packageIntegrity", {}).get("required"):
        raise LifecycleError("plan-lock-v2-required", "Freeze preparation requires package integrity")
    if (root / old / "plan.lock.json").exists():
        raise LifecycleError("freeze-prepare-locked-input", "A locked package cannot be prepared again")
    target = repository_authority_name(root / output_path, root)
    receipt = target + ".preparation.json"
    reservation = target + ".reservation.json"
    require_declared_output_footprint(manifest, repository_root=root)
    require_output_footprint(
        manifest,
        [target, receipt, reservation],
        repository_root=root,
        manifest_path=root / manifest_rel,
    )
    for forbidden in manifest.get("forbiddenWrites", []):
        if is_under_authority_path(target, forbidden, operation_root=root):
            raise LifecycleError("freeze-prepare-output-forbidden", "Candidate is inside a forbidden write path")
    for name in (target, receipt, reservation):
        if (root / name).exists():
            raise LifecycleError("freeze-prepare-output-exists", "Candidate output already exists")
    inputs = _candidate_inputs(root, manifest, old)
    if canonical_digest(load_json_object(inputs[manifest_rel])) != canonical_digest(manifest):
        raise LifecycleError("freeze-prepare-input-changed", "Draft manifest changed during preparation")
    candidate, review = _relocated_candidate(manifest, old, target)
    prepared = _candidate_bytes(inputs, candidate, old, target)
    markdown = inputs.get(old + "/acceptance-criteria.md")
    verification = build_plan_verification(
        candidate,
        manifest_path=root / target / "plan.manifest.json",
        acceptance_markdown=markdown.decode("utf-8") if markdown is not None else None,
        repository_root=root,
        package_root=root / target,
    )
    blockers = [item for item in verification["blockers"] if item["code"] != "plan-lock-required"]
    if blockers:
        raise LifecycleError("freeze-prepare-preflight-failed", "Candidate preflight failed", {"blockers": blockers})
    for name, data in inputs.items():
        if read_stable_repository_file(root, name, max_bytes=8_388_608) != data:
            raise LifecycleError("freeze-prepare-input-changed", "Draft inputs changed during preparation")
    body = _preparation_receipt(manifest, candidate, inputs, prepared, review, receipt)
    # One exclusive reservation chooses the winner before any package-file write.
    create_authority_bytes(
        root / reservation,
        canonical_bytes(
            {
                "schemaVersion": "agent-freeze-candidate-reservation.v1",
                "candidateDigest": canonical_digest(candidate),
                "authorityClaimed": False,
            }
        )
        + b"\n",
        root=root,
    )
    for name, data in prepared.items():
        create_authority_bytes(root / name, data, root=root)
    create_authority_bytes(root / receipt, canonical_bytes(body) + b"\n", root=root)
    return {
        "schemaVersion": "agent-artifact-display-summary.v1",
        "status": "PASS",
        "artifact": {"path": receipt, "digest": canonical_digest(body)},
        "candidateManifest": target + "/plan.manifest.json",
        "authoritative": False,
        "authorityClaimed": False,
        "nativeAcceptanceClaimed": False,
    }


def _candidate_inputs(root: Path, manifest: dict[str, Any], old: str) -> dict[str, bytes]:
    names = manifest.get("planFiles")
    if not isinstance(names, list) or not 1 <= len(names) <= 64:
        raise LifecycleError("freeze-prepare-inventory-invalid", "Declare between 1 and 64 plan files")
    normalized = [normalize_repo_path(name) for name in names]
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise LifecycleError("plan-file-duplicate", "Plan inventory has duplicate or aliased paths")
    if old + "/plan.manifest.json" not in normalized:
        raise LifecycleError("plan-manifest-unbound", "Manifest must be inventoried")
    pending = manifest.get("planReview", {}).get("report")
    inputs: dict[str, bytes] = {}
    for name in normalized:
        if not name.startswith(old + "/"):
            raise LifecycleError("plan-file-outside-package", "Declared input escapes its package")
        if name == pending:
            if (root / name).exists():
                raise LifecycleError("freeze-prepare-old-review", "A new candidate needs a new review")
            continue
        inputs[name] = read_stable_repository_file(root, name, max_bytes=8_388_608)
        if sum(map(len, inputs.values())) > 8_388_608:
            raise LifecycleError("freeze-prepare-input-too-large", "Candidate inventory exceeds 8 MiB")
    # Bound the shared inventory check before its sorted directory enumeration.
    import itertools

    if len(list(itertools.islice((root / old).iterdir(), 97))) > 96:
        raise LifecycleError("freeze-prepare-inventory-too-large", "Package has too many entries")
    _reject_undeclared_top_level_files(
        manifest,
        root / old,
        [{"path": name} for name in normalized],
        repository_root=root,
    )
    return inputs


def _relocated_candidate(
    manifest: dict[str, Any],
    old: str,
    target: str,
) -> tuple[dict[str, Any], str]:
    candidate = load_json_object(canonical_bytes(manifest))

    def relocate(name: str) -> str:
        return target + name[len(old) :] if name.startswith(old + "/") else name

    candidate["package"]["planArtifactRoot"] = target
    candidate["status"] = "FROZEN"
    candidate["planFiles"] = [relocate(name) for name in manifest["planFiles"]]
    if isinstance(candidate.get("developerOverview"), str):
        candidate["developerOverview"] = relocate(candidate["developerOverview"])
    spec = candidate.get("specification")
    if isinstance(spec, dict):
        spec["status"] = "FROZEN"
        if isinstance(spec.get("source"), str):
            spec["source"] = relocate(spec["source"])
    review = relocate(
        manifest.get("planReview", {}).get(
            "report",
            old + "/independent-plan-review.json",
        )
    )
    if not review.startswith(target + "/"):
        raise LifecycleError("plan-review-path-mismatch", "Review must be inside the candidate")
    candidate["planFiles"] = sorted(set([*candidate["planFiles"], review]))
    candidate["planReview"] = {
        "required": True,
        "report": review,
        "reviewedRevision": candidate["planRevision"],
        "verdict": "READY_TO_FREEZE",
    }
    return candidate, review


def _candidate_bytes(
    inputs: dict[str, bytes],
    candidate: dict[str, Any],
    old: str,
    target: str,
) -> dict[str, bytes]:
    prepared = {}
    for name, data in inputs.items():
        output = target + name[len(old) :]
        if name == old + "/plan.manifest.json":
            data = canonical_bytes(candidate) + b"\n"
        elif name.endswith(".json"):
            data = canonical_bytes(load_json_object(data)) + b"\n"
        prepared[output] = data
    return prepared


def _preparation_receipt(
    manifest: dict[str, Any],
    candidate: dict[str, Any],
    inputs: dict[str, bytes],
    prepared: dict[str, bytes],
    review: str,
    receipt_path: str,
) -> dict[str, Any]:
    def inventory(values: dict[str, bytes]) -> list[dict[str, Any]]:
        return [{"path": name, "bytes": len(data), "sha256": sha256_hex(data)} for name, data in sorted(values.items())]

    return {
        "schemaVersion": "agent-freeze-preparation-receipt.v1",
        "status": "CANDIDATE_PREPARED",
        "draftDigest": canonical_digest(manifest),
        "candidateDigest": canonical_digest(candidate),
        "inputs": inventory(inputs),
        "candidateFiles": inventory(prepared),
        "pendingReviewPath": review,
        "receiptPath": receipt_path,
        "reviewCreated": False,
        "lockCreated": False,
        "authorityClaimed": False,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
    }
