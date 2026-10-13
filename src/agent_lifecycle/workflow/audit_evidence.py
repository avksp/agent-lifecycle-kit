"""Validate typed evidence against current task bytes and frozen expectations."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.canonical import sha256_hex
from agent_lifecycle.contracts.evidence_receipt_schemas import (
    classify_evidence_candidate,
    load_evidence_receipt_bytes,
    validate_expected_evidence,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.changesets.snapshot import capture_task_change_set
from agent_lifecycle.quality.validation_ladder import require_release_full_validation_receipt
from agent_lifecycle.workflow.artifacts import artifact_identity


def validate_task_evidence_paths(
    root: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
    result_identity: dict[str, Any],
    snapshot: dict[str, Any] | None,
    evidence_paths: list[str],
) -> dict[str, Any]:
    """Bind each typed receipt to a frozen descriptor and the current task subject."""
    required = task.get("evidenceIds", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise LifecycleError("evidence-contract-invalid", "task evidence IDs are invalid")
    acceptance = manifest.get("acceptance")
    entries = acceptance.get("evidence", []) if isinstance(acceptance, dict) else []
    typed = isinstance(entries, list) and any(
        isinstance(item, dict) and isinstance(item.get("validation"), dict) for item in entries
    )
    if not typed:
        supplied = []
        for path in evidence_paths:
            rel = normalize_repo_path(path, label="evidence")
            supplied.append(artifact_identity(root, rel, read_json_object(root / rel, label="evidence")))
        return {"requiredEvidenceIds": required, "suppliedEvidence": supplied,
                "missingEvidenceIds": required if required and not supplied else []}
    workstreams = manifest.get("workstreams")
    if isinstance(workstreams, list):
        owners = [item for item in workstreams if isinstance(item, dict) and item.get("id") == task.get("id")]
        if len(owners) != 1 or owners[0].get("evidenceIds") != required:
            raise LifecycleError("evidence-contract-invalid", "task evidence IDs differ from the frozen plan")
    descriptor_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise LifecycleError("evidence-contract-invalid", "plan evidence entry is invalid")
        evidence_id = entry["id"]
        if evidence_id in descriptor_by_id:
            raise LifecycleError("evidence-id-duplicate", "plan evidence ID is duplicated")
        descriptor_by_id[evidence_id] = entry
    if len(set(required)) != len(required):
        raise LifecycleError("evidence-id-duplicate", "task evidence ID is duplicated")
    if snapshot is None or not isinstance(snapshot.get("snapshotHash"), str):
        raise LifecycleError("evidence-subject-mismatch", "current task snapshot is unavailable")
    seen: set[str] = set()
    supplied = []
    for path in evidence_paths:
        rel = normalize_repo_path(path, label="evidence")
        raw = read_stable_repository_file(root, rel, max_bytes=262_144, label="evidence receipt")
        receipt = load_evidence_receipt_bytes(raw)
        evidence_id = receipt["evidenceId"]
        if evidence_id in seen:
            raise LifecycleError("evidence-id-duplicate", "receipt evidence ID is duplicated")
        seen.add(evidence_id)
        entry = descriptor_by_id.get(evidence_id)
        if evidence_id not in required or entry is None or rel != entry.get("artifactPath"):
            raise LifecycleError("evidence-contract-invalid", "receipt path or ID is not required by the task")
        descriptor = validate_expected_evidence(entry.get("validation"))
        if descriptor["scope"] != "TASK":
            raise LifecycleError("evidence-contract-invalid", "task receipt has final scope")
        _validate_command_inventory(manifest, descriptor)
        subject = _expected_task_evidence_subject(root, state, task, result_identity, snapshot, descriptor)
        candidate = classify_evidence_candidate(
            receipt, descriptor=descriptor, evidence_id=evidence_id, expected_subject=subject
        )
        if candidate["status"] != "DATA_CANDIDATE":
            raise LifecycleError("evidence-provenance-unsupported", "required producer guarantee is unsupported")
        _validate_evidence_references(root, receipt, descriptor=descriptor)
        supplied.append({"path": rel, "sha256": sha256_hex(raw), "bytes": len(raw),
                         "evidenceId": evidence_id, "receiptDigest": receipt["receiptDigest"],
                         "validationStatus": "PASS"})
    return {"requiredEvidenceIds": required, "suppliedEvidence": supplied,
            "missingEvidenceIds": sorted(set(required) - seen)}


def _validate_command_inventory(manifest: dict[str, Any], descriptor: dict[str, Any]) -> None:
    if descriptor["kind"] == "composite-applicability" and "originValidation" in descriptor:
        _validate_command_inventory(manifest, descriptor["originValidation"])
        return
    if descriptor["kind"] != "command-observation":
        return
    validation = manifest.get("validation")
    commands = validation.get("commands") if isinstance(validation, dict) else None
    if not isinstance(commands, list) or any(not isinstance(item, str) for item in commands):
        raise LifecycleError("evidence-contract-invalid", "frozen command inventory is unavailable")
    for digest in descriptor["requirements"]["commandDigests"]:
        if sum(canonical_digest(command) == digest for command in commands) != 1:
            raise LifecycleError("evidence-contract-invalid", "required command mapping is missing or ambiguous")


def _expected_task_evidence_subject(
    root: Path, state: dict[str, Any], task: dict[str, Any],
    result_identity: dict[str, Any], snapshot: dict[str, Any], descriptor: dict[str, Any],
) -> dict[str, Any]:
    components = [_current_evidence_component(root, item, snapshot["changedFiles"])
                  for item in descriptor["components"]]
    return {
        "packageId": state["packageId"], "runId": state["runId"],
        "planRevision": state["planRevision"], "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"], "scope": "TASK",
        "taskBindings": [{"taskId": task["id"], "attempt": task["attempt"],
                          "resultDigest": result_identity["sha256"], "snapshotHash": snapshot["snapshotHash"]}],
        "components": sorted(components, key=lambda item: item["id"]),
    }


def _current_evidence_component(root: Path, descriptor: dict[str, Any], changed: list[str]) -> dict[str, Any]:
    component_root = descriptor["repositoryPath"]
    try:
        command = subprocess.run(["git", "ls-files", "-z", "--cached"], cwd=root, capture_output=True,
                                 check=False, timeout=20)
        tracked = {item.decode("utf-8") for item in command.stdout.split(b"\0") if item}
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        raise LifecycleError("evidence-subject-mismatch", "tracked source inventory is unavailable") from None
    if command.returncode or len(command.stdout) > 8_388_608:
        raise LifecycleError("evidence-subject-mismatch", "tracked source inventory is unavailable")
    paths = sorted(path for path in tracked.union(changed) if component_root == "." or
                   path == component_root or path.startswith(component_root + "/"))
    if len(paths) > 10_000:
        raise LifecycleError("evidence-subject-mismatch", "source inventory exceeds file limit")
    inventory = []
    total_bytes = 0
    for path in paths:
        normalized = normalize_repo_path(path, label="evidence source")
        candidate = root / normalized
        try:
            mode = candidate.lstat().st_mode
        except OSError:
            raise LifecycleError("evidence-subject-mismatch", "source inventory file is unavailable") from None
        if stat.S_ISLNK(mode):
            try:
                target = str(candidate.readlink())
                resolved = candidate.resolve(strict=True)
            except OSError:
                raise LifecycleError("evidence-subject-mismatch", "source symlink is unavailable") from None
            if not resolved.is_relative_to(root.resolve()):
                raise LifecycleError("evidence-subject-mismatch", "source symlink escapes repository")
            data = os.fsencode(target)
            entry_mode = "120000"
        elif stat.S_ISREG(mode):
            data = read_stable_repository_file(root, normalized, max_bytes=64 * 1024 * 1024,
                                               label="evidence source")
            entry_mode = "100755" if mode & stat.S_IXUSR else "100644"
        else:
            raise LifecycleError("evidence-subject-mismatch", "unsupported source inventory file")
        total_bytes += len(data)
        if total_bytes > 512 * 1024 * 1024:
            raise LifecycleError("evidence-subject-mismatch", "source inventory exceeds byte limit")
        inventory.append({"path": normalized, "mode": entry_mode, "sha256": sha256_hex(data)})
    content = canonical_digest(inventory)
    build_path = descriptor["buildArtifactPath"]
    return {
        "id": descriptor["id"], "commitOid": _current_git_commit(root), "contentDigest": content,
        "buildDigest": sha256_hex(read_stable_repository_file(root, build_path,
            max_bytes=64 * 1024 * 1024, label="evidence build")) if build_path is not None else content,
        "configurationDigest": _path_inventory_digest(root, descriptor["configurationPaths"]),
        "oracleDigest": _path_inventory_digest(root, descriptor["oraclePaths"]),
    }


def _current_git_commit(root: Path) -> str:
    try:
        process = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True,
                                 check=False, timeout=20)
        value = process.stdout.decode("ascii").strip()
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        raise LifecycleError("evidence-subject-mismatch", "component commit is unavailable") from None
    if process.returncode or len(value) not in {40, 64}:
        raise LifecycleError("evidence-subject-mismatch", "component commit is unavailable")
    return value


def _path_inventory_digest(root: Path, paths: list[str]) -> str:
    return canonical_digest([
        {"path": path, "sha256": sha256_hex(read_stable_repository_file(
            root, path, max_bytes=64 * 1024 * 1024, label="evidence configuration or oracle"
        ))} for path in paths
    ])


def _validate_evidence_references(
    root: Path, receipt: dict[str, Any], *, descriptor: dict[str, Any] | None = None,
    _depth: int = 0, _origin: dict[str, Any] | None = None,
) -> None:
    # Bound inherited chains as well as each individual referenced artifact.
    if _depth > 32:
        raise LifecycleError("evidence-artifact-invalid", "inherited evidence chain is too deep")
    payload = receipt["payload"]
    kind = payload["schemaVersion"]
    if not _depth and kind == "agent-composite-applicability.v1":
        # Only the independently frozen expected descriptor supplies the origin.
        # Neither a predecessor's payload nor its claimed PASS chooses requirements.
        if descriptor is None or "originValidation" not in descriptor:
            raise LifecycleError("evidence-provenance-unsupported", "predecessor expectations are unbound")
        _origin = descriptor["originValidation"]
    if _depth:
        if receipt["producer"]["guarantee"] != "DECLARED":
            raise LifecycleError("evidence-provenance-unsupported", "unsupported inherited producer guarantee")
        if kind != "agent-composite-applicability.v1":
            if _origin is None:
                raise LifecycleError("evidence-provenance-unsupported", "predecessor expectations are unbound")
            # Each intervening subject is hash-bound and compared below against its
            # parent. Thus this historic subject differs from the current independently
            # computed subject only by commitOid before it reaches this leaf.
            candidate = classify_evidence_candidate(receipt, descriptor=_origin,
                evidence_id=receipt["evidenceId"], expected_subject=receipt["subject"])
            if candidate["status"] != "DATA_CANDIDATE":
                raise LifecycleError("evidence-provenance-unsupported", "unsupported inherited evidence")
    refs = []
    if kind == "agent-command-observation.v1":
        for command in payload["commands"]:
            refs.extend((command["stdout"], command["stderr"]))
            refs.extend(case["evidence"] for case in command["cases"] if case["evidence"] is not None)
    elif kind == "agent-composite-applicability.v1":
        refs.append(payload["previousReceipt"])
    else:
        refs.append(payload["observationArtifact"])
    previous_raw = None
    for ref in refs:
        raw = read_stable_repository_file(root, ref["path"], max_bytes=8_388_608,
                                          label="evidence referenced artifact")
        if len(raw) != ref["bytes"] or sha256_hex(raw) != ref["sha256"]:
            raise LifecycleError("evidence-artifact-invalid", "referenced evidence bytes differ")
        if kind == "agent-composite-applicability.v1":
            previous_raw = raw
    if kind != "agent-composite-applicability.v1":
        return
    previous = load_evidence_receipt_bytes(previous_raw)
    if previous["evidenceId"] != receipt["evidenceId"]:
        raise LifecycleError("evidence-subject-mismatch", "inherited evidence id differs")
    if payload["currentSubjectDigest"] != canonical_digest(receipt["subject"]):
        raise LifecycleError("evidence-subject-mismatch", "current subject digest differs")
    if payload["componentIds"] != [item["id"] for item in receipt["subject"]["components"]]:
        raise LifecycleError("evidence-subject-mismatch", "inherited component ids differ")
    if payload["previousSubjectDigest"] != canonical_digest(previous["subject"]):
        raise LifecycleError("evidence-subject-mismatch", "previous subject digest differs")
    current = receipt["subject"]
    prior = previous["subject"]
    current_lineage = {key: value for key, value in current.items() if key != "components"}
    prior_lineage = {key: value for key, value in prior.items() if key != "components"}
    current_components = [{key: value for key, value in item.items() if key != "commitOid"}
                          for item in current["components"]]
    prior_components = [{key: value for key, value in item.items() if key != "commitOid"}
                        for item in prior["components"]]
    if current_lineage != prior_lineage or current_components != prior_components:
        raise LifecycleError("evidence-subject-mismatch", "composite changed more than history")
    _validate_evidence_references(root, previous, _depth=_depth + 1, _origin=_origin)


def _validate_release_full_validation(
    state: dict[str, Any],
    root: Path,
    *,
    release_full_receipt_path: str | None,
) -> dict[str, Any] | None:
    manifest_path = state.get("manifestPath")
    if not isinstance(manifest_path, str) or not manifest_path:
        if release_full_receipt_path is None:
            return None
        raise LifecycleError(
            "release-full-validation-not-enabled",
            "release-full validation is not enabled for this legacy workflow state",
        )
    manifest_rel = normalize_repo_path(manifest_path, label="plan manifest")
    manifest = read_json_object(root / manifest_rel, label="plan manifest")
    manifest_validation = manifest.get("validation")
    if not (
        isinstance(manifest_validation, dict)
        and ("checkCatalog" in manifest_validation or "validationLadderProfile" in manifest_validation)
    ):
        if release_full_receipt_path is None:
            return None
        raise LifecycleError(
            "release-full-validation-not-enabled", "release-full validation is not enabled by the frozen manifest"
        )
    if release_full_receipt_path is None:
        raise LifecycleError(
            "release-full-validation-required", "the frozen validation ladder requires a fresh release-full receipt"
        )
    if not isinstance(manifest_validation, dict):
        raise LifecycleError("release-full-validation-invalid", "manifest validation authority is invalid")
    catalog = manifest_validation.get("checkCatalog")
    profile_reference = manifest_validation.get("validationLadderProfile")
    if not isinstance(catalog, dict) or not isinstance(profile_reference, dict):
        raise LifecycleError("release-full-validation-invalid", "validation ladder authority is incomplete")
    checks = catalog.get("checks")
    if not isinstance(checks, list) or not checks:
        raise LifecycleError("release-full-validation-invalid", "validation check catalog is empty")
    required_check_ids = sorted(
        item["id"] for item in checks if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    if len(required_check_ids) != len(checks):
        raise LifecycleError("release-full-validation-invalid", "validation check catalog is malformed")
    manifest_digest = canonical_digest(manifest)
    if state.get("planDigest") != manifest_digest:
        raise LifecycleError("release-full-validation-stale", "workflow plan lineage is stale")
    lock_rel = str(Path(manifest_rel).parent / "plan.lock.json")
    lock = read_json_object(root / lock_rel, label="plan lock")
    if lock.get("manifestHash") != manifest_digest:
        raise LifecycleError("release-full-validation-stale", "plan lock lineage is stale")
    current = _capture_release_current_tree(root, source_revision=str(state.get("sourceRevision")), state=state)
    receipt_rel = normalize_repo_path(release_full_receipt_path, label="release-full validation receipt")
    receipt = read_json_object(root / receipt_rel, label="release-full validation receipt")
    validation = require_release_full_validation_receipt(
        receipt,
        source_revision=str(state.get("sourceRevision")),
        current_tree_digest=current["currentTreeDigest"],
        plan_digest=manifest_digest,
        plan_lock_digest=canonical_digest(lock),
        catalog_digest=str(catalog.get("catalogDigest")),
        required_check_ids=required_check_ids,
    )
    identity = artifact_identity(root, receipt_rel, receipt)
    return {"receipt": identity, "validation": validation, "currentTree": current}


def _capture_release_current_tree(
    root: Path,
    *,
    source_revision: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    write_paths = sorted(
        {
            path
            for task in state.get("tasks", [])
            if isinstance(task, dict)
            for path in task.get("writes", [])
            if isinstance(path, str)
        }
    )
    inventory = capture_task_change_set(root, baseline=source_revision, write_paths=write_paths)
    changed_paths = inventory["allChangedFiles"]
    current = capture_task_change_set(root, baseline=source_revision, write_paths=changed_paths)
    if current["allChangedFiles"] != changed_paths or current["changedFiles"] != changed_paths:
        raise LifecycleError(
            "release-full-validation-tree-race",
            "repository changes moved while the release-full tree identity was captured",
        )
    body = {
        "schemaVersion": "agent-release-current-tree.v1",
        "baselineSha": current["baselineSha"],
        "changedFiles": current["changedFiles"],
        "fileSetHash": current["fileSetHash"],
        "diffHash": current["diffHash"],
        "snapshotHash": current["snapshotHash"],
    }
    return {**current, "currentTreeDigest": canonical_digest(body)}
