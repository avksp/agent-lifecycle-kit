"""Application service for physical review inputs and advisory packet creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.audit.delta_review import build_delta_review_packet, build_review_input_refusal
from agent_lifecycle.changesets.snapshot import read_baseline_entries
from agent_lifecycle.contracts import LifecycleError, load_json_object, sha256_hex
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.ownership_paths import require_output_footprint
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.review_input_types import ReviewPacketRequest, ReviewSubject
from agent_lifecycle.freeze.review_inputs import (
    bind_review_inputs,
    read_composite_reports,
    read_review_artifact,
    runtime_paths,
    verify_runtime_inventory,
)
from agent_lifecycle.review.validation import (
    make_review_subject,
    review_output_paths,
    validate_bound_plan_review,
    validate_review_composition,
)


def prepare_review_packet(root: Path, request: ReviewPacketRequest) -> dict[str, Any]:
    """Bind physical inputs before advisory selection; refusal writes nothing."""
    root = root.resolve(strict=True)
    if type(request.max_bytes) is not int or request.max_bytes < 1024:
        raise LifecycleError("review-packet-limit", "Invalid packet limit")
    subject: dict[str, Any] = {}
    try:
        manifest = load_json_object(read_review_artifact(root, request.manifest), label="review manifest")
        subject = {"manifest": manifest}
        package = manifest.get("package")
        if not isinstance(package, dict):
            raise LifecycleError("review-input-incomplete", "Package needed")
        expected = package.get("planArtifactRoot", "")
        if not isinstance(expected, str) or not expected:
            raise LifecycleError("review-input-incomplete", "Plan root needed")
        if request.manifest != expected + "/plan.manifest.json":
            raise LifecycleError("review-subject-mismatch", "Manifest location")
        baseline, reports, sizes = _packet_baseline(root, request.baseline)
        subject = dict(_packet_subject(root, manifest, reports))
        # A stable second read detects changes during inventory collection.
        bind_review_inputs(
            {
                "subject": subject,
                "reviewAuthority": {"evidence": []},
            },
            root,
            {},
        )
        verify_runtime_inventory(
            {**reports, "candidate": {"subject": subject}},
            root,
            require_current=True,
        )
        payload = build_delta_review_packet(
            subject,
            baseline=baseline,
            reports=reports or None,
            report_sizes=sizes or None,
            max_bytes=request.max_bytes,
        )
    except LifecycleError as exc:
        return build_review_input_refusal(subject, exc.code)
    if payload["mode"] == "FULL_REQUIRED":
        return payload
    outputs = [(request.out, payload, ".review-packet.json")]
    if request.subject_out:
        outputs.append((request.subject_out, subject, ".review-subject.json"))
    names = [name for name, _, _ in outputs if name]
    require_output_footprint(manifest, names, repository_root=root)
    for name, _, suffix in outputs:
        if name:
            _packet_output_preflight(root, name, suffix, manifest)
    for name, value, _ in outputs:
        if name:
            create_authority_bytes(root / name, canonical_bytes(value) + b"\n", root=root)
    return payload


def _packet_baseline(
    root: Path,
    path: str | None,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, int]]:
    if path is None:
        return None, {}, {}
    raw = read_review_artifact(root, path)
    baseline = load_json_object(raw, label="review baseline")
    evidence: dict[str, dict[str, Any]] = {}
    if baseline.get("schemaVersion") == "agent-plan-composite-review.v1":
        current = baseline.get("currentReports")
        if not isinstance(current, list) or not current:
            raise LifecycleError("review-set-incomplete", "Current report needed")
        report = load_json_object(read_review_artifact(root, current[0]))
        bound = validate_bound_plan_review(report)
        manifest = bound["subject"]["manifest"]
        reports, sizes = read_composite_reports(manifest, baseline, root, evidence)
        validate_review_composition(manifest, baseline, reports, report_sizes=sizes)
    else:
        bound = validate_bound_plan_review(baseline)
        if bound["scope"]["kind"] != "FULL":
            raise LifecycleError("review-incomplete", "Full baseline needed")
        reports, sizes = {path: baseline}, {path: len(raw)}
    for report in reports.values():
        bind_review_inputs(report, root, evidence)
    return baseline, reports, sizes


def _packet_subject(
    root: Path,
    manifest: dict[str, Any],
    reports: dict[str, dict[str, Any]],
) -> ReviewSubject:
    subjects = [r["subject"] for r in reports.values()]
    manifests = [manifest, *(s["manifest"] for s in subjects)]
    roots = {normalize_repo_path(m["package"]["planArtifactRoot"]) + "/" for m in manifests}
    base = manifest.get("baseRevision")
    source = base.get("sha") if isinstance(base, dict) else None
    if not isinstance(source, str) or len(source) not in {40, 64}:
        raise LifecycleError("review-source-unavailable", "Exact source needed")
    if any(c not in "0123456789abcdef" for c in source):
        raise LifecycleError("review-source-unavailable", "Invalid source hash")
    paths = runtime_paths(root, ["ls-tree", "-r", "--name-only", "-z", source], roots)
    if len(paths) > 4096:
        raise LifecycleError("review-input-limit", "Runtime inventory cap")
    blobs = read_baseline_entries(root, source, sorted(paths))
    files = manifest.get("planFiles")
    if not isinstance(files, list) or any(not isinstance(p, str) for p in files):
        raise LifecycleError("review-input-incomplete", "Plan inventory needed")
    if len(files) > 4096:
        raise LifecycleError("review-input-limit", "Plan inventory cap")
    digests = {p: sha256_hex(read_review_artifact(root, p)) for p in set(files) - review_output_paths(manifest)}
    bound = make_review_subject(manifest, digests, {p: entry["sha256"] for p, entry in blobs.items()})
    return ReviewSubject(
        manifest=bound["manifest"], fileDigests=bound["fileDigests"], runtimeInputs=bound["runtimeInputs"]
    )


def _packet_output_preflight(
    root: Path,
    path: str,
    suffix: str,
    manifest: dict[str, Any],
) -> None:
    name = normalize_repo_path(path)
    if name != path or not name.endswith(suffix):
        raise LifecycleError("review-output-invalid", "Advisory suffix required")
    forbidden = {".git", ".alk", ".claude", ".codex"}
    if any(p.casefold() in forbidden for p in Path(name).parts):
        raise LifecycleError("review-output-invalid", "Protected destination")
    policy = manifest.get("orchestration", {})
    declared = {value for value in policy.values() if isinstance(value, str)} if isinstance(policy, dict) else set()
    if name in declared or (root / name).exists():
        raise LifecycleError("review-output-invalid", "Destination reserved")
