"""Reviewer provenance test package; synthetic fixtures grant no approval."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_bytes, canonical_digest, sha256_hex
from agent_lifecycle.review.validation import (
    derive_delta_selection,
    make_review_scope,
    make_review_subject,
    review_output_paths,
)


def write_json(root: Path, path: str, value: dict[str, Any]) -> str:
    data = canonical_bytes(value) + b"\n"
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return sha256_hex(data)


def synthetic_manifest(revision: int) -> dict[str, Any]:
    directory = "plans/r" + str(revision)
    baseline = "plans/r1/review.json"
    current = baseline if revision == 1 else directory + "/delta.json"
    files = [directory + "/plan.manifest.json", directory + "/plan.md", directory + "/review.json"]
    if revision != 1:
        files.append(current)
    return {
        "schemaVersion": "agent-plan.v1",
        "status": "FROZEN",
        "planRevision": revision,
        "package": {"id": "synthetic", "planArtifactRoot": directory},
        "baseRevision": {"sha": "1" * 40},
        "planFiles": sorted(files),
        "packageIntegrity": {"required": True, "lockSchemaVersion": "agent-plan-lock.v2"},
        "specification": {
            "requirements": [
                {"id": "R1", "description": "first"},
                {"id": "R2", "description": "second"},
            ]
        },
        "acceptance": {
            "criteria": [
                {"id": "A1", "requirementIds": ["R1"], "evidenceIds": ["E1"]},
                {"id": "A2", "requirementIds": ["R2"], "evidenceIds": ["E2"]},
            ]
        },
        "workstreams": [
            {"id": "W1", "owner": "one", "acceptanceIds": ["A1"], "evidenceIds": ["E1"], "writes": ["src/one.py"]},
            {"id": "W2", "owner": "two", "acceptanceIds": ["A2"], "evidenceIds": ["E2"], "writes": ["src/two.py"]},
        ],
        "finalAuditGates": ["final"],
        "planReview": {
            "required": True,
            "report": directory + "/review.json",
            "reviewedRevision": revision,
            "verdict": "READY_TO_FREEZE",
        },
        "extensions": {
            "reviewPolicy": {
                "schemaVersion": "agent-plan-review-policy.v1",
                "requiredSeats": [
                    {
                        "id": "one",
                        "allowedReviewerIds": ["reviewer"],
                        "reports": list(dict.fromkeys([baseline, current])),
                        "baseline": baseline,
                        "current": current,
                    }
                ],
            }
        },
    }


def subject_for(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    files = set(manifest["planFiles"]) - review_output_paths(manifest)
    return make_review_subject(
        manifest,
        {p: sha256_hex((root / p).read_bytes()) for p in files},
        {p: sha256_hex((root / p).read_bytes()) for p in ("runtime.py", "authority.txt", "fix.txt")},
    )


def review_for(
    root: Path, subject: dict[str, Any], identifier: str, *, parent: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest = subject["manifest"]
    digest = canonical_digest(manifest)
    scope = (
        make_review_scope(subject)
        if parent is None
        else make_review_scope(subject, kind="DELTA", selection=derive_delta_selection(parent["subject"], subject))
    )
    authority = {
        "reviewId": identifier,
        "reviewerId": "reviewer",
        "runId": identifier,
        "subjectHash": digest,
        "status": "VALID",
        "notBefore": "2026-10-01T00:00:00Z",
        "completedAt": "2026-10-01T00:01:00Z",
        "expiresAt": "2026-10-01T00:02:00Z",
        "evidence": [{"path": "authority.txt", "sha256": sha256_hex((root / "authority.txt").read_bytes())}],
    }
    return {
        "schemaVersion": "agent-plan-review.v2",
        "reviewId": identifier,
        "reviewer": {"id": "reviewer", "runId": identifier, "surface": "synthetic", "independent": True},
        "packageId": manifest["package"]["id"],
        "planRevision": manifest["planRevision"],
        "reviewedPlanHash": digest,
        "subject": subject,
        "reviewScope": scope,
        "fullReview": parent is None,
        "verdict": "READY_TO_FREEZE",
        "findings": [],
        "reviewAuthority": authority,
        "dependsOn": [] if parent is None else [canonical_digest(parent)],
    }


def synthetic_case(
    root: Path,
    *,
    negative: bool = True,
    duplicate_seat: bool = False,
    policy_limits: dict[str, int] | None = None,
    git_repository: bool = False,
) -> dict[str, Any]:
    for path in ("runtime.py", "authority.txt", "fix.txt"):
        (root / path).write_text("synthetic " + path, encoding="utf-8")
    old, new = synthetic_manifest(1), synthetic_manifest(2)
    if git_repository:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
        subprocess.run(
            ["git", "add", "runtime.py", "authority.txt", "fix.txt"], cwd=root, check=True, capture_output=True
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.invalid",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "--quiet",
                "-m",
                "Synthetic runtime",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        for manifest in (old, new):
            manifest["baseRevision"] = {"sha": revision}
    for manifest in (old, new):
        policy = manifest["extensions"]["reviewPolicy"]
        if duplicate_seat:
            policy["requiredSeats"].append({**policy["requiredSeats"][0], "id": "two"})
        if policy_limits:
            policy["limits"] = policy_limits
    new["specification"]["requirements"][0]["description"] = "corrected"
    for manifest in (old, new):
        directory = manifest["package"]["planArtifactRoot"]
        write_json(root, directory + "/plan.manifest.json", manifest)
        (root / directory / "plan.md").write_text("unchanged normative body", encoding="utf-8")
    baseline = review_for(root, subject_for(root, old), "full")
    if negative:
        baseline.update(
            verdict="CHANGES_REQUIRED",
            findings=[{"id": "M1", "severity": "MEDIUM", "status": "OPEN", "title": "repair"}],
        )
    delta = review_for(root, subject_for(root, new), "delta", parent=baseline)
    delta["currentApplicability"] = {
        "baselineDigest": canonical_digest(baseline),
        "candidateHash": canonical_digest(new),
        "completeCoverage": True,
        "unchangedBaselineApplicable": True,
        "allChangesReviewed": True,
        "allBlockingFindingsResolved": True,
    }
    if negative:
        delta["findingClosures"] = [
            {
                "reportDigest": canonical_digest(baseline),
                "findingId": "M1",
                "status": "CLOSED",
                "evidence": [{"path": "fix.txt", "sha256": sha256_hex((root / "fix.txt").read_bytes())}],
            }
        ]
    reports = {"plans/r1/review.json": baseline, "plans/r2/delta.json": delta}
    bindings = {p: write_json(root, p, r) for p, r in reports.items()}
    scope = {**make_review_scope(delta["subject"]), "kind": "COMPOSITE"}
    composite = {
        "schemaVersion": "agent-plan-composite-review.v1",
        "reviewId": "composite",
        "packageId": "synthetic",
        "planRevision": 2,
        "reviewedPlanHash": canonical_digest(new),
        "fullReview": False,
        "verdict": "READY_TO_FREEZE",
        "reviewScope": scope,
        "reportBindings": bindings,
        "currentReports": [s["current"] for s in new["extensions"]["reviewPolicy"]["requiredSeats"]],
    }
    write_json(root, "plans/r2/review.json", composite)
    return {
        "manifest": new,
        "baseline": baseline,
        "delta": delta,
        "reports": reports,
        "composite": composite,
        "sizes": {p: (root / p).stat().st_size for p in reports},
    }


def refresh_candidate(root: Path, case: dict[str, Any]) -> None:
    """Rebind a deliberately changed synthetic candidate, preserving history."""
    manifest, delta = case["manifest"], case["delta"]
    directory = manifest["package"]["planArtifactRoot"]
    write_json(root, directory + "/plan.manifest.json", manifest)
    delta["subject"] = subject_for(root, manifest)
    delta["reviewedPlanHash"] = canonical_digest(manifest)
    delta["reviewAuthority"]["subjectHash"] = canonical_digest(manifest)
    delta["reviewScope"] = make_review_scope(
        delta["subject"], kind="DELTA", selection=derive_delta_selection(case["baseline"]["subject"], delta["subject"])
    )
    delta["currentApplicability"]["candidateHash"] = canonical_digest(manifest)
    composite = case["composite"]
    composite["reviewedPlanHash"] = canonical_digest(manifest)
    composite["reviewScope"] = {**make_review_scope(delta["subject"]), "kind": "COMPOSITE"}
    composite["currentReports"] = [s["current"] for s in manifest["extensions"]["reviewPolicy"]["requiredSeats"]]


def synthetic_chain(
    root: Path,
    edges: int,
    *,
    policy_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    case = synthetic_case(root, negative=False, policy_limits=policy_limits)
    reports = case["reports"]
    previous = case["delta"]
    for revision in range(3, edges + 2):
        manifest = synthetic_manifest(revision)
        if policy_limits:
            manifest["extensions"]["reviewPolicy"]["limits"] = policy_limits
        directory = manifest["package"]["planArtifactRoot"]
        path = directory + "/delta.json"
        seat = manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]
        seat["reports"] = [*reports, path]
        write_json(root, directory + "/plan.manifest.json", manifest)
        (root / directory / "plan.md").write_text("unchanged normative body", encoding="utf-8")
        report = review_for(root, subject_for(root, manifest), "delta" + str(revision), parent=previous)
        report["currentApplicability"] = {
            **previous["currentApplicability"],
            "candidateHash": canonical_digest(manifest),
        }
        reports[path] = report
        write_json(root, path, report)
        previous = report
    manifest = previous["subject"]["manifest"]
    composite = {
        **case["composite"],
        "planRevision": manifest["planRevision"],
        "reviewedPlanHash": canonical_digest(manifest),
        "reviewScope": {**make_review_scope(previous["subject"]), "kind": "COMPOSITE"},
        "currentReports": [manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]["current"]],
    }
    return {
        **case,
        "manifest": manifest,
        "composite": composite,
        "delta": previous,
        "sizes": {p: (root / p).stat().st_size for p in reports},
    }


def synthetic_full_case(root: Path, *, author: str = "implementer") -> dict[str, Any]:
    """One complete independent accepting seat, without a self-hash cycle."""
    import shutil

    case = synthetic_case(root, git_repository=True)
    manifest = case["baseline"]["subject"]["manifest"]
    shutil.rmtree(root / "plans/r2")
    manifest["author"] = author
    manifest["planReview"]["report"] = "plans/r1/composite.json"
    manifest["planFiles"] = sorted([*manifest["planFiles"], "plans/r1/composite.json"])
    write_json(root, "plans/r1/plan.manifest.json", manifest)
    report = review_for(root, subject_for(root, manifest), "single-full")
    report["currentApplicability"] = {
        "baselineDigest": None,
        "candidateHash": canonical_digest(manifest),
        "completeCoverage": True,
        "unchangedBaselineApplicable": True,
        "allChangesReviewed": True,
        "allBlockingFindingsResolved": True,
    }
    digest = write_json(root, "plans/r1/review.json", report)
    composite = {
        **case["composite"],
        "reviewId": "single-full-composite",
        "planRevision": 1,
        "reviewedPlanHash": canonical_digest(manifest),
        "reviewScope": {**make_review_scope(report["subject"]), "kind": "COMPOSITE"},
        "reportBindings": {"plans/r1/review.json": digest},
        "currentReports": ["plans/r1/review.json"],
    }
    write_json(root, "plans/r1/composite.json", composite)
    return {"manifest": manifest, "report": report, "composite": composite}
