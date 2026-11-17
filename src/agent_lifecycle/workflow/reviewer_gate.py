"""Authenticate effect-bearing reviews with the adopted public authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.reviewer_identity_schemas import require_reviewer_attestation_authority
from agent_lifecycle.review.provenance import reviewer_observed_at, verify_reviewer_decision
from agent_lifecycle.workflow.artifacts import package_root, require_artifact_identity


def reviewer_decision_lineage(
    state: dict[str, Any], task: dict[str, Any] | None = None
) -> dict[str, Any]:
    lineage = {
        key: state.get(key) for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
    }
    if task is not None:
        lineage.update(
            taskId=task["id"],
            attempt=task["attempt"],
            resultHash=task["result"]["sha256"],
            packetHash=task["packet"]["sha256"],
        )
    else:
        lineage["acceptedTasks"] = [
            {
                "taskId": selected["id"],
                "attempt": selected["attempt"],
                "resultHash": selected["result"]["sha256"],
                "reviewHash": selected["review"]["sha256"],
            }
            for selected in state["tasks"]
            if selected["status"] == "ACCEPTED"
        ]
    return lineage


def _decision(
    state: dict[str, Any],
    report: dict[str, Any],
    *,
    phase: str,
    lineage: dict[str, Any],
    author: tuple[Any, Any],
    archived: dict[str, Any] | None,
) -> dict[str, Any] | None:
    policy = require_reviewer_attestation_authority(state, state=True)
    if policy is None or policy["mode"] != "required":
        return None
    observed_at = archived.get("observedAt") if archived is not None else reviewer_observed_at()
    if not isinstance(observed_at, str):
        raise LifecycleError("reviewer-admission-changed", "Archived reviewer admission time is unavailable")
    admission = verify_reviewer_decision(
        policy, report, phase=phase, lineage=lineage, author=author, observed_at=observed_at
    )
    if archived is not None and admission != archived:
        raise LifecycleError("reviewer-admission-changed", "Archived reviewer admission does not match the decision")
    return admission


def task_reviewer_decision(
    state: dict[str, Any],
    task: dict[str, Any],
    report: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    phase: str,
    archived: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if "reviewerAttestationAuthority" not in state:
        return None
    if result is None:
        raise LifecycleError("reviewer-author-required", "Strict task review needs a verified committed result")
    return _decision(
        state,
        report,
        phase=phase,
        lineage=reviewer_decision_lineage(state, task),
        author=(result.get("actor"), result.get("actorRunId")),
        archived=archived,
    )


def implementation_reviewer_decision(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    report: dict[str, Any],
    *,
    archived: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if "reviewerAttestationAuthority" not in state:
        return None
    result = require_artifact_identity(package_root(state_path, state), task["result"], label="reviewed task result")
    return task_reviewer_decision(state, task, report, result, phase="implementation-audit", archived=archived)


def final_reviewer_decision(
    state_path: Path,
    state: dict[str, Any],
    report: dict[str, Any],
    *,
    phase: str,
    archived: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if "reviewerAttestationAuthority" not in state:
        return None
    root = package_root(state_path, state)
    manifest_path = state.get("manifestPath")
    if not isinstance(manifest_path, str):
        raise LifecycleError("reviewer-authority-changed", "Strict review requires the adopted manifest")
    manifest = read_json_object(root / normalize_repo_path(manifest_path), label="reviewed manifest")
    if (
        canonical_digest(manifest) != state.get("planDigest")
        or manifest.get("reviewerAttestationAuthority") != state.get("reviewerAttestationAuthority")
    ):
        raise LifecycleError("reviewer-authority-changed", "Reviewer authority differs from the adopted plan")
    author = manifest.get("author")
    if not isinstance(author, dict):
        raise LifecycleError("reviewer-author-required", "Strict final review needs a bound manifest author")
    return _decision(
        state,
        report,
        phase=phase,
        lineage=reviewer_decision_lineage(state),
        author=(author.get("id"), author.get("runId")),
        archived=archived,
    )
