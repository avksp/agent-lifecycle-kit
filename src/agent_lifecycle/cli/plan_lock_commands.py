"""Reviewed plan-lock creation command."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.changesets.git import resolve_revision
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
from agent_lifecycle.planning.preparation_budget import evaluate_preparation_budget
from agent_lifecycle.planning.verification import build_plan_verification, require_manifest_package_location

PLAN_LOCK_CREATION_RECEIPT = "agent-plan-lock-creation-receipt.v1"


def create_reviewed_plan_lock(
    *,
    manifest_path: str,
    review_path: str,
    repository_root: Path,
    review_preflight_path: str | None = None,
) -> dict[str, Any]:
    """Create and verify the canonical lock for one reviewed frozen plan."""

    root = repository_root.resolve(strict=True)
    manifest_rel, manifest_data = _read_repository_json(root, manifest_path, label="plan manifest")
    manifest = load_json_object(manifest_data, label="plan manifest")
    plan_root = require_manifest_package_location(manifest, root / manifest_rel, root)

    review_rel, review_data = _read_repository_json(root, review_path, label="plan review")
    review = load_json_object(review_data, label="plan review")
    if review_preflight_path is not None:
        _require_review_preflight(root, manifest_rel, review, review_preflight_path)
    lock = build_reviewed_plan_lock_v2(
        manifest,
        review,
        review_path=review_rel,
        review_sha256=sha256_hex(review_data),
        repository_root=root,
    )
    # Reject malformed or drifting package bytes before creating the
    # no-replace authority artifact. The second check still detects drift.
    verify_plan_package_integrity(manifest, lock, repository_root=root, require_current_review_source=True)
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
        "packageId": manifest["package"].get("id"),
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
    old = require_manifest_package_location(manifest, root / manifest_rel, root)
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
    blockers = [
        item
        for item in verification["blockers"]
        if item["code"] not in {"plan-lock-required", "operator-signature-missing"}
    ]
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
    workstreams = candidate.get("workstreams")
    if isinstance(workstreams, list):
        for workstream in workstreams:
            if not isinstance(workstream, dict):
                continue
            references = workstream.get("contextRefs")
            if isinstance(references, list):
                workstream["contextRefs"] = [relocate(name) if isinstance(name, str) else name for name in references]
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


_REVIEW_PREFLIGHT = "agent-plan-review-preflight-receipt.v1"
_REVIEW_REQUEST = "agent-plan-review-preflight-request.v1"
_PACKET_LIMIT = 256 * 1024
_BUDGET_LIMIT = 64 * 1024


def _review_input(root: Path, path: str, limit: int) -> tuple[dict[str, Any], bytes]:
    rel = normalize_repo_path(path, label="review preflight input")
    raw = read_stable_repository_file(root, rel, max_bytes=limit, label="review preflight input")
    return {"path": rel, "bytes": len(raw), "sha256": sha256_hex(raw)}, raw


def _check_prepared_inventory(root: Path, manifest: dict[str, Any], prepared: dict[str, Any], path: str) -> None:
    summary = (
        "agent-freeze-preparation-receipt.v1",
        "CANDIDATE_PREPARED",
        canonical_digest(manifest),
        manifest.get("planReview", {}).get("report"),
        path,
    )
    actual = tuple(
        prepared.get(key) for key in ("schemaVersion", "status", "candidateDigest", "pendingReviewPath", "receiptPath")
    )
    if (
        manifest.get("status") != "FROZEN"
        or summary != actual
        or any(
            prepared.get(flag) is not False
            for flag in ("reviewCreated", "lockCreated", "authorityClaimed", "modelCallsStarted")
        )
    ):
        raise LifecycleError("review-preflight-preparation-mismatch", "Prepared candidate identity does not match")
    inventory = prepared.get("candidateFiles")
    if not isinstance(inventory, list) or not 1 <= len(inventory) <= 128:
        raise LifecycleError("review-preflight-inventory-invalid", "Prepared candidate inventory is not bounded")
    paths = {row["path"] for row in inventory if isinstance(row, dict) and isinstance(row.get("path"), str)}
    expected = set(manifest.get("planFiles", [])) - {prepared["pendingReviewPath"]}
    if paths != expected or len(paths) != len(inventory):
        raise LifecycleError(
            "review-preflight-inventory-invalid", "Prepared candidate inventory differs from planFiles"
        )
    for row in inventory:
        actual_file, _ = _review_input(root, row["path"], MAX_JSON_INPUT_BYTES)
        if actual_file != row:
            raise LifecycleError("review-preflight-candidate-drift", "Prepared candidate files changed")


def _check_prepared_structure(root: Path, manifest: dict[str, Any], plan_root: str) -> None:
    manifest_path = root / plan_root / "plan.manifest.json"
    acceptance = f"{plan_root}/acceptance-criteria.md"
    markdown = None
    if acceptance in manifest.get("planFiles", []):
        _, raw = _review_input(root, acceptance, MAX_JSON_INPUT_BYTES)
        markdown = raw.decode("utf-8")
    verification = build_plan_verification(
        manifest,
        manifest_path=manifest_path,
        acceptance_markdown=markdown,
        repository_root=root,
        package_root=root / plan_root,
    )
    blockers = [
        row
        for row in verification["blockers"]
        if row["code"] not in {"plan-lock-required", "operator-signature-missing"}
    ]
    if blockers:
        raise LifecycleError(
            "review-preflight-structure-invalid", "Prepared candidate structural checks failed", {"blockers": blockers}
        )


def _read_review_command(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schemaVersion") != _REVIEW_REQUEST:
        raise LifecycleError("review-preflight-request-invalid", "Unsupported preflight request")
    command = request.get("command")
    if not isinstance(command, dict):
        raise LifecycleError("review-preflight-argv-invalid", "Expected structured argv and cwd")
    argv = command.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or not all(_safe_review_argument(arg) for arg in argv):
        raise LifecycleError("review-preflight-argv-invalid", "Expected bounded argv with non-empty executable")
    if not argv[0] or command.get("shell", False) is not False or len(canonical_bytes(argv)) > 16384:
        raise LifecycleError("review-preflight-argv-invalid", "Expected a bounded literal argument vector")
    scoped = command.get("cwd")
    if not isinstance(scoped, str):
        raise LifecycleError("review-preflight-cwd-invalid", "Review cwd is required")
    if scoped != ".":
        scoped = normalize_repo_path(scoped, label="review command cwd")
        cwd = root / scoped
        if not cwd.is_dir() or cwd.resolve() != cwd:
            raise LifecycleError("review-preflight-cwd-invalid", "Review cwd must be a contained directory")
    return {"argv": argv, "cwd": scoped, "shell": False}


def _safe_review_argument(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 4096 and not any(ch in value for ch in "\x00\r\n")


def _budget_input(
    root: Path, path: object, *, packet_sha256: str, command_digest: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding: dict[str, Any] = {"path": path if isinstance(path, str) else None, "sha256": None, "bytes": None}
    try:
        if not isinstance(path, str):
            raise LifecycleError("review-preflight-budget-path-missing", "Budget snapshot path is required")
        binding, raw = _review_input(root, path, _BUDGET_LIMIT)
        snapshot = load_json_object(raw, label="review budget snapshot")
    except LifecycleError as error:
        return binding, {
            "status": "DEFERRED",
            "reasonCode": "BUDGET_SNAPSHOT_UNAVAILABLE",
            "inputError": error.code,
            "lowerBoundTokens": None,
            "upperBoundTokens": None,
        }
    return binding, evaluate_preparation_budget(
        snapshot, now=datetime.now(UTC), packet_sha256=packet_sha256, command_digest=command_digest
    )


def _build_review_preflight(
    root: Path, manifest_path: str, preparation_path: str, packet_path: str, request_path: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_binding, raw = _review_input(root, manifest_path, MAX_JSON_INPUT_BYTES)
    manifest = load_json_object(raw, label="prepared manifest")
    plan_root = require_manifest_package_location(manifest, root / manifest_binding["path"], root)
    preparation, raw = _review_input(root, preparation_path, MAX_JSON_INPUT_BYTES)
    if preparation["path"] != f"{plan_root}.preparation.json":
        raise LifecycleError("review-preflight-preparation-mismatch", "Preparation receipt path is not adjacent")
    prepared = load_json_object(raw, label="candidate preparation receipt")
    _check_prepared_inventory(root, manifest, prepared, preparation["path"])
    _check_prepared_structure(root, manifest, plan_root)
    packet, raw = _review_input(root, packet_path, _PACKET_LIMIT)
    if not raw:
        raise LifecycleError("review-preflight-packet-empty", "Reviewer packet must not be empty")
    request_binding, raw = _review_input(root, request_path, _BUDGET_LIMIT)
    request = load_json_object(raw, label="review preflight request")
    command = _read_review_command(root, request)
    source_revision = resolve_revision(root, "HEAD", label="review source revision")
    if (
        source_revision != request.get("sourceRevision")
        or source_revision != manifest.get("baseRevision", {}).get("sha")
        or packet["sha256"] != request.get("packetSha256")
    ):
        raise LifecycleError("review-preflight-subject-mismatch", "Checkout or packet differs from the request")
    bound, decision = _budget_input(
        root, request.get("budgetSnapshot"), packet_sha256=packet["sha256"], command_digest=canonical_digest(command)
    )
    body = {
        "schemaVersion": _REVIEW_PREFLIGHT,
        "status": decision["status"],
        "planDigest": prepared["candidateDigest"],
        "sourceRevision": source_revision,
        "bindings": {
            "manifest": manifest_binding,
            "preparation": preparation,
            "packet": packet,
            "request": request_binding,
            "budget": bound,
        },
        "commandDigest": canonical_digest(command),
        "cwd": command["cwd"],
        "budgetDecision": decision,
        "modelCallsStarted": False,
        "authorityClaimed": False,
    }
    return manifest, {**body, "receiptDigest": canonical_digest(body)}


def prepare_review_preflight(
    *,
    manifest_path: str,
    preparation_path: str,
    packet_path: str,
    request_path: str,
    output_path: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Inspect and bind the prepared candidate, packet, request, and local budget."""
    root = repository_root.resolve(strict=True)
    manifest, receipt = _build_review_preflight(root, manifest_path, preparation_path, packet_path, request_path)
    if receipt["status"] == "READY":
        output = normalize_repo_path(output_path, label="review preflight output")
        restricted = [".git", *manifest.get("forbiddenWrites", []), *manifest.get("readOnly", [])]
        if any(is_under_authority_path(output, prefix, operation_root=root) for prefix in restricted):
            raise LifecycleError("review-preflight-output-forbidden", "Output overlaps a restricted path")
        require_output_footprint(manifest, [output], repository_root=root, manifest_path=root / manifest_path)
        _require_pending_review(root, manifest)
        create_authority_bytes(root / output, canonical_bytes(receipt) + b"\n", root=root)
    return receipt


def _require_pending_review(root: Path, manifest: dict[str, Any]) -> None:
    pending = normalize_repo_path(manifest["planReview"]["report"], label="pending review path")
    try:
        (root / pending).lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise LifecycleError("review-preflight-review-unavailable", "Pending review path is unavailable") from error
    raise LifecycleError("review-preflight-review-exists", "Initial preflight requires a pending independent review")


def _require_review_preflight(root: Path, manifest_path: str, review: dict[str, Any], receipt_path: str) -> None:
    _, data = _review_input(root, receipt_path, _BUDGET_LIMIT)
    receipt = load_json_object(data, label="review preflight receipt")
    if data != canonical_bytes(receipt) + b"\n" or receipt.get("status") != "READY":
        raise LifecycleError("review-preflight-receipt-invalid", "Expected a canonical READY local preflight")
    try:
        bindings = receipt["bindings"]
        _, current = _build_review_preflight(
            root,
            manifest_path,
            bindings["preparation"]["path"],
            bindings["packet"]["path"],
            bindings["request"]["path"],
        )
        packet_digest = bindings["packet"]["sha256"]
    except (KeyError, TypeError) as error:
        raise LifecycleError("review-preflight-receipt-invalid", "Preflight bindings are malformed") from error
    if current != receipt or review.get("reviewedPacketSha256") != packet_digest:
        raise LifecycleError("review-preflight-report-mismatch", "Current preflight and independent report must match")
