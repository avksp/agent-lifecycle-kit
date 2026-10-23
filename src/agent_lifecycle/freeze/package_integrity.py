"""Filesystem-backed integrity authority for frozen plan packages."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from agent_lifecycle.changesets.git import changed_files, resolve_revision
from agent_lifecycle.changesets.git_io import run_bounded_command
from agent_lifecycle.changesets.snapshot import read_baseline_entries
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    load_json_object,
    sha256_hex,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.plan_delta_schemas import PLAN_LOCK_SCOPE_SCHEMA
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids
from agent_lifecycle.review.validation import (
    review_policy,
    validate_independent_review,
    validate_review_composition,
)

PLAN_FILE_INVENTORY_SCHEMA = "agent-plan-file-inventory.v1"
PLAN_LOCK_V1_SCHEMA = "agent-plan-lock.v1"
PLAN_LOCK_V2_SCHEMA = "agent-plan-lock.v2"
PACKAGE_INTEGRITY_VERIFICATION_SCHEMA = "agent-plan-package-integrity-verification.v1"
MAX_PLAN_FILE_BYTES = 8 * 1024 * 1024


def plan_integrity_required(manifest: dict[str, Any]) -> bool:
    """Return whether a manifest opts into whole-package v2 verification."""

    integrity = manifest.get("packageIntegrity")
    return isinstance(integrity, dict) and integrity.get("required") is True


def _scope_lock_required(manifest: dict[str, Any]) -> bool:
    return _object(manifest.get("extensions")).get("reviewPolicy") is not None


def verify_plan_lock_envelope(manifest: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    """Verify lock metadata without claiming that filesystem bytes were checked."""

    if not isinstance(lock, dict):
        raise LifecycleError("invalid-plan-lock", "plan lock must be an object")
    schema = lock.get("schemaVersion")
    if _scope_lock_required(manifest) and schema != PLAN_LOCK_SCOPE_SCHEMA:
        raise LifecycleError("plan-lock-scope-required", "Review policy needs v3")
    if schema == PLAN_LOCK_V1_SCHEMA:
        digest = canonical_digest(manifest)
        if lock.get("manifestHash") != digest:
            raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash mismatch")
        if lock.get("planRevision") != manifest.get("planRevision"):
            raise LifecycleError("plan-lock-mismatch", "plan lock revision mismatch")
        if plan_integrity_required(manifest):
            raise LifecycleError("plan-lock-v2-required", "manifest requires an agent-plan-lock.v2 inventory binding")
        return {
            "schemaVersion": "agent-plan-lock-verification.v1",
            "packageId": lock.get("packageId") or _object(manifest.get("package")).get("id"),
            "planRevision": lock.get("planRevision"),
            "manifestHash": digest,
            "filesystemVerified": False,
            "lockSchemaVersion": PLAN_LOCK_V1_SCHEMA,
        }
    if schema not in {PLAN_LOCK_V2_SCHEMA, PLAN_LOCK_SCOPE_SCHEMA}:
        raise LifecycleError("invalid-plan-lock", "plan lock schemaVersion is unsupported")
    digest = canonical_digest(manifest)
    package = _object(manifest.get("package"))
    if lock.get("manifestHash") != digest:
        raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash mismatch")
    if lock.get("planRevision") != manifest.get("planRevision"):
        raise LifecycleError("plan-lock-mismatch", "plan lock revision mismatch")
    if lock.get("packageId") != package.get("id"):
        raise LifecycleError("plan-lock-package-mismatch", "plan lock packageId mismatch")
    entries = _validate_entries(lock.get("entries"))
    expected_inventory_digest = canonical_digest({"schemaVersion": PLAN_FILE_INVENTORY_SCHEMA, "entries": entries})
    if lock.get("planFilesHash") != expected_inventory_digest:
        raise LifecycleError("plan-lock-inventory-mismatch", "plan lock planFilesHash mismatch")
    if schema == PLAN_LOCK_SCOPE_SCHEMA:
        evidence = _validate_entries(lock.get("reviewEvidence"))
        if lock.get("reviewEvidenceDigest") != canonical_digest(evidence):
            raise LifecycleError("review-evidence-mismatch", "Invalid evidence digest")
        if lock.get("reviewScopeKind") != "COMPOSITE":
            raise LifecycleError("review-scope-invalid", "Incomplete lock scope")
    return {
        "schemaVersion": "agent-plan-lock-verification.v1",
        "packageId": package.get("id"),
        "planRevision": lock.get("planRevision"),
        "manifestHash": digest,
        "planFilesHash": expected_inventory_digest,
        "entries": entries,
        "filesystemVerified": False,
        "lockSchemaVersion": schema,
    }


def build_plan_lock_v2(manifest: dict[str, Any], *, repository_root: Path) -> dict[str, Any]:
    """Build a v2 lock from the exact bytes of a declared plan package."""

    if not plan_integrity_required(manifest):
        raise LifecycleError("plan-lock-v2-not-required", "manifest must require v2 package integrity")
    body = _inventory_lock(manifest, repository_root)
    verify_plan_lock_envelope(manifest, body)
    return body


def _inventory_lock(manifest: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    entries = _inventory_entries(manifest, repository_root)
    package = _object(manifest.get("package"))
    body = {
        "schemaVersion": PLAN_LOCK_V2_SCHEMA,
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "manifestHash": canonical_digest(manifest),
        "planFilesHash": canonical_digest({"schemaVersion": PLAN_FILE_INVENTORY_SCHEMA, "entries": entries}),
        "entries": entries,
    }
    return body


def build_reviewed_plan_lock_v2(
    manifest: dict[str, Any],
    review: dict[str, Any],
    *,
    review_path: str,
    review_sha256: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Build a v2 lock only after validating an exact independent review."""

    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "reviewed plan lock creation requires a FROZEN manifest")
    plan_review = manifest.get("planReview")
    if not isinstance(plan_review, dict) or plan_review.get("required") is not True:
        raise LifecycleError("plan-review-required", "manifest must require an independent plan review")
    normalized_review_path = normalize_repo_path(review_path, label="plan review path")
    if plan_review.get("report") != normalized_review_path:
        raise LifecycleError("plan-review-path-mismatch", "review path does not match manifest planReview.report")
    plan_files = manifest.get("planFiles")
    if not isinstance(plan_files, list) or normalized_review_path not in plan_files:
        raise LifecycleError("plan-review-unbound", "review path must be declared in planFiles")
    revision = manifest.get("planRevision")
    if plan_review.get("reviewedRevision") != revision:
        raise LifecycleError("plan-review-revision-mismatch", "manifest review revision does not match planRevision")
    if review.get("schemaVersion") in {"agent-plan-review.v2", "agent-plan-composite-review.v1"}:
        return _build_scope_lock(manifest, review, normalized_review_path, review_sha256, repository_root)
    if review.get("schemaVersion") != "agent-plan-review.v1":
        raise LifecycleError("invalid-review", "plan review schemaVersion is unsupported")
    validate_independent_review(review)
    if review.get("fullReview") is not True:
        raise LifecycleError("plan-review-incomplete", "plan lock creation requires a full independent review")
    if review.get("verdict") != "READY_TO_FREEZE":
        raise LifecycleError("plan-review-verdict-invalid", "plan review verdict must be READY_TO_FREEZE")
    if plan_review.get("verdict") != review.get("verdict"):
        raise LifecycleError("plan-review-verdict-mismatch", "manifest and report review verdicts differ")
    package = _object(manifest.get("package"))
    if review.get("packageId") != package.get("id"):
        raise LifecycleError("plan-review-package-mismatch", "review packageId does not match the manifest")
    if review.get("planRevision") != revision:
        raise LifecycleError("plan-review-revision-mismatch", "review planRevision does not match the manifest")
    digest = canonical_digest(manifest)
    if review.get("reviewedPlanHash") != digest:
        raise LifecycleError("plan-review-digest-mismatch", "reviewedPlanHash does not match the manifest")
    if not isinstance(review.get("reviewId"), str) or not review["reviewId"]:
        raise LifecycleError("invalid-review", "reviewId is required")
    reviewer = _object(review.get("reviewer"))
    for field in ("id", "runId", "surface"):
        if not isinstance(reviewer.get(field), str) or not reviewer[field]:
            raise LifecycleError("invalid-review", f"reviewer.{field} is required")
    if _open_blocking_review_findings(review):
        raise LifecycleError("review-open-findings", "review has unresolved Medium-or-higher findings")

    lock = build_plan_lock_v2(manifest, repository_root=repository_root)
    lock_entries = lock.get("entries")
    if not isinstance(lock_entries, list):
        raise LifecycleError("plan-lock-inventory-invalid", "reviewed plan lock has no entries")
    review_entry = next(
        (entry for entry in lock_entries if isinstance(entry, dict) and entry.get("path") == normalized_review_path),
        None,
    )
    if not isinstance(review_entry, dict) or review_entry.get("sha256") != review_sha256:
        raise LifecycleError("plan-review-file-changed", "review file changed while the lock was being built")
    return lock


def verify_plan_package_integrity(
    manifest: dict[str, Any],
    lock: dict[str, Any],
    *,
    repository_root: Path,
    require_current_review_source: bool = False,
) -> dict[str, Any]:
    """Verify a lock and, when required, every declared package file."""

    envelope = verify_plan_lock_envelope(manifest, lock)
    if envelope["lockSchemaVersion"] == PLAN_LOCK_V1_SCHEMA:
        body = {
            "schemaVersion": PACKAGE_INTEGRITY_VERIFICATION_SCHEMA,
            "status": "PASS",
            "required": False,
            "lockSchemaVersion": PLAN_LOCK_V1_SCHEMA,
            "filesystemVerified": False,
            "manifestHash": envelope["manifestHash"],
            "planFilesHash": None,
            "entries": [],
            "blockers": [],
        }
        return {**body, "verificationDigest": canonical_digest(body)}

    expected_entries = _inventory_entries(manifest, repository_root)
    actual_entries = envelope["entries"]
    if actual_entries != expected_entries:
        raise LifecycleError(
            "plan-package-files-mismatch",
            "plan lock entries do not match the current declared package files",
            {"expected": expected_entries, "actual": actual_entries},
        )
    if envelope["lockSchemaVersion"] == PLAN_LOCK_SCOPE_SCHEMA:
        review_path = _object(manifest.get("planReview")).get("report")
        if not isinstance(review_path, str):
            raise LifecycleError("review-scope-invalid", "Review path required")
        review_data = _read_review_artifact(repository_root, review_path)
        review = load_json_object(review_data, label="scoped review")
        evidence = _scope_review_evidence(
            manifest,
            review,
            repository_root,
            require_current_source=require_current_review_source,
        )
        evidence[review_path] = _byte_entry(review_path, review_data)
        if sorted(evidence.values(), key=lambda e: e["path"]) != lock["reviewEvidence"]:
            raise LifecycleError("review-evidence-mismatch", "Bound evidence changed")
        if lock.get("reviewScopeKind") != review["reviewScope"]["kind"]:
            raise LifecycleError("review-scope-mismatch", "Lock scope changed")
    package = _object(manifest.get("package"))
    package_root = _package_root(repository_root, package.get("planArtifactRoot"))
    _reject_undeclared_top_level_files(manifest, package_root, expected_entries, repository_root=repository_root)
    body = {
        "schemaVersion": PACKAGE_INTEGRITY_VERIFICATION_SCHEMA,
        "status": "PASS",
        "required": plan_integrity_required(manifest),
        "lockSchemaVersion": envelope["lockSchemaVersion"],
        "filesystemVerified": True,
        "manifestHash": envelope["manifestHash"],
        "planFilesHash": envelope["planFilesHash"],
        "entries": expected_entries,
        "blockers": [],
    }
    return {**body, "verificationDigest": canonical_digest(body)}


def _build_scope_lock(
    manifest: dict[str, Any],
    review: dict[str, Any],
    review_path: str,
    review_sha256: str,
    repository_root: Path,
) -> dict[str, Any]:
    if not _scope_lock_required(manifest):
        raise LifecycleError("plan-lock-scope-required", "Declare v3 scope before review")
    if _object(manifest.get("planReview")).get("verdict") != "READY_TO_FREEZE" or not plan_integrity_required(manifest):
        raise LifecycleError("plan-review-verdict-invalid", "Reviewed integrity needed")
    evidence = _scope_review_evidence(manifest, review, repository_root, require_current_source=True)
    raw = _read_review_artifact(repository_root, review_path)
    if sha256_hex(raw) != review_sha256 or load_json_object(raw) != review:
        raise LifecycleError("plan-review-file-changed", "Review file changed")
    evidence[review_path] = _byte_entry(review_path, raw)
    entries = sorted(evidence.values(), key=lambda entry: entry["path"])
    lock = _inventory_lock(manifest, repository_root)
    lock.update(
        schemaVersion=PLAN_LOCK_SCOPE_SCHEMA,
        reviewEvidence=entries,
        reviewEvidenceDigest=canonical_digest(entries),
        reviewScopeKind=review["reviewScope"]["kind"],
    )
    verify_plan_lock_envelope(manifest, lock)
    return lock


def _scope_review_evidence(
    manifest: dict[str, Any],
    review: dict[str, Any],
    root: Path,
    *,
    require_current_source: bool = False,
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    if review.get("schemaVersion") != "agent-plan-composite-review.v1":
        raise LifecycleError("review-set-incomplete", "New scope needs policy and composition")
    reports, sizes = _read_composite_reports(manifest, review, root, evidence)
    validate_review_composition(manifest, review, reports, report_sizes=sizes)
    for report in reports.values():
        _bind_review_inputs(report, root, evidence)
    runtime = _verify_runtime_inventory(reports, root, require_current=require_current_source)
    for path, entry in runtime.items():
        if path in evidence and evidence[path] != entry:
            raise LifecycleError("review-evidence-mismatch", "Conflicting source binding")
        evidence[path] = entry
    return evidence


def _verify_runtime_inventory(
    reports: dict[str, dict[str, Any]],
    root: Path,
    *,
    require_current: bool,
) -> dict[str, dict[str, Any]]:
    """Verify historical source from pinned Git objects, not later task output.

    Creation additionally checks current inventory/bytes immediately before
    publication. Later lifecycle checks retain that historical source proof.
    """
    subjects = [report["subject"] for report in reports.values()]
    plan_roots = {normalize_repo_path(subject["manifest"]["package"]["planArtifactRoot"]) + "/" for subject in subjects}
    cached: dict[str, dict[str, dict[str, Any]]] = {}
    result: dict[str, dict[str, Any]] = {}
    for subject in subjects:
        source = _object(subject["manifest"].get("baseRevision")).get("sha")
        if not isinstance(source, str) or resolve_revision(root, source) != source:
            raise LifecycleError("review-source-unavailable", "Exact source commit needed")
        if source not in cached:
            paths = _runtime_paths(root, ["ls-tree", "-r", "--name-only", "-z", source], plan_roots)
            if len(paths) > 4096:
                raise LifecycleError("review-input-limit", "Runtime inventory cap exceeded")
            blobs = read_baseline_entries(root, source, sorted(paths))
            entries = {}
            for path, entry in blobs.items():
                if entry["kind"] != "file" or entry["bytes"] > MAX_PLAN_FILE_BYTES:
                    raise LifecycleError("review-source-unavailable", "Unsupported source object")
                entries[path] = {"path": path, "sha256": entry["sha256"], "bytes": entry["bytes"]}
            cached[source] = entries
            if require_current:
                _require_current_runtime(root, source, plan_roots, entries)
        entries = cached[source]
        if subject["runtimeInputs"] != {p: e["sha256"] for p, e in entries.items()}:
            raise LifecycleError("review-runtime-incomplete", "Complete pinned runtime inventory needed")
        for path, entry in entries.items():
            if path in result and result[path] != entry:
                raise LifecycleError("review-runtime-changed", "Historical sources differ")
            result[path] = entry
    return result


def _runtime_paths(root: Path, args: list[str], plan_roots: set[str]) -> set[str]:
    command = run_bounded_command(
        ["git", *args],
        cwd=root,
        timeout_seconds=30,
        max_stdout_bytes=1024 * 1024,
    )
    if command.returncode:
        raise LifecycleError("review-source-unavailable", "Git inventory unavailable")
    try:
        paths = {normalize_repo_path(p.decode("utf-8")) for p in command.stdout.split(b"\0") if p}
    except UnicodeError as exc:
        raise LifecycleError("review-source-unavailable", "Source path encoding") from exc
    return {p for p in paths if not any(p.startswith(prefix) for prefix in plan_roots)}


def _require_current_runtime(
    root: Path,
    source: str,
    plan_roots: set[str],
    entries: dict[str, dict[str, Any]],
) -> None:
    paths = _runtime_paths(root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], plan_roots)
    if paths != set(entries):
        raise LifecycleError("review-runtime-incomplete", "Current source inventory differs")
    if any(not any(p.startswith(prefix) for prefix in plan_roots) for p in changed_files(root, base=source)):
        raise LifecycleError("review-runtime-changed", "Current source changed outside plans")
    for path, entry in entries.items():
        data = _read_review_artifact(root, path)
        if _byte_entry(path, data) != entry:
            raise LifecycleError("review-runtime-changed", "Current source bytes differ")


def _read_composite_reports(
    manifest: dict[str, Any],
    review: dict[str, Any],
    root: Path,
    evidence: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    policy = review_policy(manifest)
    paths = {p for seat in policy["requiredSeats"] for p in seat["reports"]}
    bindings = review.get("reportBindings")
    if not isinstance(bindings, dict) or set(bindings) != paths or len(paths) > 8 * 16:
        raise LifecycleError("review-set-incomplete", "Invalid report binding set")
    reports, sizes = {}, {}
    for path in sorted(paths):
        data = _read_review_artifact(root, path)
        sizes[path] = len(data)
        _bind_evidence(path, bindings[path], data, evidence)
        # Check aggregate limits before parsing/retaining each report body.
        for seat in policy["requiredSeats"]:
            limit = min(policy.get("limits", {}).get("reportBytes", 8 * 1024 * 1024), 8 * 1024 * 1024)
            if sum(sizes.get(p, 0) for p in seat["reports"]) > limit:
                raise LifecycleError("review-chain-limit", "Report bytes exceeded")
            if len(seat["reports"]) > min(policy.get("limits", {}).get("reports", 16), 16):
                raise LifecycleError("review-chain-limit", "Report count exceeded")
        reports[path] = load_json_object(data, label="independent scoped report")
    return reports, sizes


def _bind_review_inputs(
    report: dict[str, Any],
    root: Path,
    evidence: dict[str, dict[str, Any]],
) -> None:
    subject = report["subject"]
    inventories = [subject["fileDigests"]]
    supporting = list(report["reviewAuthority"]["evidence"])
    for closure in report.get("findingClosures", []):
        supporting.extend(closure["evidence"])
    for item in supporting:
        data = _read_review_artifact(root, item["path"])
        _bind_evidence(item["path"], item["sha256"], data, evidence)
    for inventory in inventories:
        for path, digest in inventory.items():
            data = _read_review_artifact(root, path)
            _bind_evidence(path, digest, data, evidence)
    package = _object(subject["manifest"].get("package"))
    manifest_path = str(package.get("planArtifactRoot")) + "/plan.manifest.json"
    if manifest_path not in subject["fileDigests"]:
        raise LifecycleError("review-input-incomplete", "Manifest input not bound")
    data = _read_review_artifact(root, manifest_path)
    if load_json_object(data) != subject["manifest"]:
        raise LifecycleError("review-subject-mismatch", "Historical manifest drift")


def _bind_evidence(
    path: str,
    digest: str,
    data: bytes,
    evidence: dict[str, dict[str, Any]],
) -> None:
    entry = _byte_entry(path, data)
    if digest != entry["sha256"] or (path in evidence and evidence[path] != entry):
        raise LifecycleError("review-evidence-mismatch", "Evidence bytes changed")
    evidence[path] = entry


def _byte_entry(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": sha256_hex(data), "bytes": len(data)}


def _read_review_artifact(root: Path, path: str) -> bytes:
    normalized = normalize_repo_path(path, label="review artifact")
    if normalized != path:
        raise LifecycleError("review-path-invalid", "Noncanonical artifact path")
    return read_stable_repository_file(root, normalized, max_bytes=MAX_PLAN_FILE_BYTES, label="review artifact")


def _inventory_entries(manifest: dict[str, Any], repository_root: Path) -> list[dict[str, Any]]:
    plan_files = manifest.get("planFiles")
    if not isinstance(plan_files, list) or not plan_files:
        raise LifecycleError("plan-files-missing", "v2 plan package must declare a non-empty planFiles inventory")
    package = _object(manifest.get("package"))
    package_root = _package_root(repository_root, package.get("planArtifactRoot"))
    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(plan_files):
        if not isinstance(raw, str):
            raise LifecycleError("plan-file-path-invalid", "planFiles entries must be strings", {"index": index})
        path = normalize_repo_path(raw, label="planFiles entry")
        if path in seen:
            raise LifecycleError("plan-file-duplicate", "planFiles contains a duplicate path", {"path": path})
        seen.add(path)
        candidate = _resolve_declared_path(repository_root, package_root, path)
        # Reading through the shared stable repository boundary rejects missing,
        # symlinked, changing and over-sized authoritative files.
        data = read_stable_repository_file(
            repository_root,
            path,
            max_bytes=MAX_PLAN_FILE_BYTES,
            label="declared plan file",
        )
        if candidate.is_symlink():
            raise LifecycleError("plan-file-symlink", "declared plan files must not be symlinks", {"path": path})
        normalized.append(path)
        # Keep bytes in a side table only through the local list below.
        del data
    if normalized != sorted(normalized):
        raise LifecycleError("plan-files-unsorted", "planFiles must be sorted lexicographically")
    manifest_path = _manifest_path(package_root, repository_root)
    if manifest_path not in seen:
        raise LifecycleError("plan-manifest-unbound", "plan.manifest.json must be part of the v2 inventory")
    entries: list[dict[str, Any]] = []
    for path in normalized:
        data = read_stable_repository_file(
            repository_root,
            path,
            max_bytes=MAX_PLAN_FILE_BYTES,
            label="declared plan file",
        )
        entries.append({"path": path, "bytes": len(data), "sha256": sha256_hex(data)})
    return entries


def _validate_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entries must be a non-empty list")
    result: list[dict[str, Any]] = []
    previous: str | None = None
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry shape is invalid", {"index": index})
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry path is invalid", {"index": index})
        path = normalize_repo_path(raw_path, label="plan lock entry")
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry byte count is invalid", {"path": path})
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise LifecycleError("plan-lock-inventory-invalid", "v2 lock entry digest is invalid", {"path": path})
        if previous is not None and path <= previous:
            raise LifecycleError(
                "plan-lock-inventory-order",
                "v2 lock entries must be unique and sorted",
                {"path": path},
            )
        previous = path
        result.append({"path": path, "bytes": size, "sha256": digest})
    return result


def _open_blocking_review_findings(review: dict[str, Any]) -> list[str]:
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise LifecycleError("invalid-review", "findings must be an array")
    return open_blocking_finding_ids(findings)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _package_root(repository_root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required for v2 integrity")
    root = repository_root.resolve()
    if raw == ".":
        candidate = root
    else:
        normalized = normalize_repo_path(raw, label="package.planArtifactRoot")
        candidate = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise LifecycleError("plan-package-root-invalid", "plan package root must remain in the repository") from exc
    if not resolved.is_dir() or candidate.is_symlink():
        raise LifecycleError("plan-package-root-invalid", "plan package root must be a regular directory")
    return resolved


def _resolve_declared_path(repository_root: Path, package_root: Path, path: str) -> Path:
    candidate = repository_root.resolve().joinpath(*PurePosixPath(path).parts)
    try:
        candidate.relative_to(package_root)
    except ValueError as exc:
        raise LifecycleError(
            "plan-file-outside-package",
            "declared plan file escapes package root",
            {"path": path},
        ) from exc
    return candidate


def _manifest_path(package_root: Path, repository_root: Path) -> str:
    try:
        return package_root.joinpath("plan.manifest.json").relative_to(repository_root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError("plan-package-root-invalid", "plan package root is outside repository") from exc


def _reject_undeclared_top_level_files(
    manifest: dict[str, Any],
    package_root: Path,
    entries: list[dict[str, Any]],
    *,
    repository_root: Path,
) -> None:
    integrity = _object(manifest.get("packageIntegrity"))
    allowed = integrity.get("allowedUnlistedFiles", ["plan.lock.json"])
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item for item in allowed):
        raise LifecycleError("plan-integrity-policy-invalid", "allowedUnlistedFiles must be a list of names")
    package_relative = package_root.relative_to(repository_root.resolve()).as_posix()
    declared_top_level: set[str] = set()
    declared_directories: set[str] = set()
    for entry in entries:
        path = PurePosixPath(entry["path"])
        try:
            relative = path.relative_to(PurePosixPath(package_relative))
        except ValueError:
            continue
        if len(relative.parts) == 1:
            declared_top_level.add(relative.as_posix())
        elif relative.parts:
            declared_directories.add(relative.parts[0])
    for child in sorted(package_root.iterdir(), key=lambda item: item.name):
        if child.is_symlink():
            raise LifecycleError(
                "plan-file-symlink",
                "package top-level entries must not be symlinks",
                {"path": child.name},
            )
        if child.is_dir():
            if child.name not in declared_directories:
                raise LifecycleError(
                    "plan-directory-undeclared",
                    "package contains an undeclared top-level directory",
                    {"path": child.name},
                )
            continue
        if child.name in allowed:
            continue
        if child.name not in declared_top_level:
            raise LifecycleError(
                "plan-file-undeclared",
                "package contains an undeclared top-level file",
                {"path": child.name},
            )
