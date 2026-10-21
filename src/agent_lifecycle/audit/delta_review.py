"""Bounded read-only plan review selection, without model orchestration."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.plan_delta_schemas import DELTA_REVIEW_SCHEMA
from agent_lifecycle.review.validation import (
    build_review_impact_graph,
    derive_delta_selection,
    make_review_scope,
    validate_bound_plan_review,
    validate_review_composition,
)

MAX_PACKET_BYTES = 98304


def build_delta_review_packet(
    subject: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    reports: dict[str, dict[str, Any]] | None = None,
    report_sizes: dict[str, int] | None = None,
    max_bytes: int = MAX_PACKET_BYTES,
) -> dict[str, Any]:
    """Select eligible impact; FULL_REQUIRED never starts a full audit.

    The caller still needs existing admission, independent review and freeze
    verification. A digest or eligibility decision grants none of those rights.
    """
    if type(max_bytes) is not int or max_bytes < 1024:
        raise LifecycleError("review-packet-limit", "Invalid packet limit")
    cap = min(max_bytes, MAX_PACKET_BYTES)
    try:
        scope = make_review_scope(subject)
    except LifecycleError as exc:
        return _input_refusal(subject, exc.code)
    body = {
        "schemaVersion": DELTA_REVIEW_SCHEMA,
        "mode": "FULL",
        "reasons": ["NO_BASELINE"],
        "baseHash": None,
        "candidateHash": scope["candidateHash"],
        "graphDigest": scope["graphDigest"],
        "changedNodes": [],
        "closure": scope["coveredNodes"],
        "readOnly": True,
        "modelCallsStarted": False,
        "admissionRequired": True,
    }
    if baseline is not None:
        try:
            previous = _baseline_subject(baseline, reports, report_sizes)
            body.update(derive_delta_selection(previous, subject))
            body["schemaVersion"] = DELTA_REVIEW_SCHEMA
        except LifecycleError as exc:
            body.update(mode="FULL_REQUIRED", reasons=[exc.code])
    if body["mode"] == "DELTA_ELIGIBLE":
        graph = build_review_impact_graph(subject["manifest"], file_digests=subject["fileDigests"])
        selected = set(body["closure"])
        body["selectedNodes"] = [n for n in graph["nodes"] if n["id"] in selected]
        body["unchangedNodes"] = [
            {"id": n["id"], "digest": n["digest"]} for n in graph["nodes"] if n["id"] not in selected
        ]
        body["baselineDigest"] = canonical_digest(baseline)
    if len(canonical_bytes(body)) + 100 > cap:
        body = {
            key: body[key]
            for key in ("schemaVersion", "candidateHash", "readOnly", "modelCallsStarted", "admissionRequired")
        }
        body.update(mode="FULL_REQUIRED", reasons=["PACKET_LIMIT_EXCEEDED"], baseHash=None, changedNodes=[], closure=[])
    return {**body, "packetDigest": canonical_digest(body)}


def _input_refusal(subject: dict[str, Any], reason: str) -> dict[str, Any]:
    manifest = subject.get("manifest") if isinstance(subject, dict) else None
    body = {
        "schemaVersion": DELTA_REVIEW_SCHEMA,
        "mode": "FULL_REQUIRED",
        "reasons": [reason],
        "baseHash": None,
        "candidateHash": canonical_digest(manifest),
        "changedNodes": [],
        "closure": [],
        "readOnly": True,
        "modelCallsStarted": False,
        "admissionRequired": True,
    }
    return {**body, "packetDigest": canonical_digest(body)}


def _baseline_subject(
    baseline: dict[str, Any],
    reports: dict[str, dict[str, Any]] | None,
    sizes: dict[str, int] | None,
) -> dict[str, Any]:
    if baseline.get("schemaVersion") == "agent-plan-composite-review.v1":
        if not reports or not sizes:
            raise LifecycleError("review-set-incomplete", "Composite evidence needed")
        current_paths = baseline.get("currentReports")
        if not isinstance(current_paths, list) or not current_paths:
            raise LifecycleError("review-set-incomplete", "Current selectors needed")
        candidate = reports.get(current_paths[0], {}).get("subject", {})
        result = validate_review_composition(candidate.get("manifest", {}), baseline, reports, report_sizes=sizes)
        return result["seats"][0]["subject"]
    bound = validate_bound_plan_review(baseline)
    if bound["scope"]["kind"] != "FULL":
        raise LifecycleError("review-incomplete", "Complete baseline needed")
    if len(canonical_bytes(baseline)) > 8 * 1024 * 1024:
        raise LifecycleError("review-chain-limit", "Baseline exceeds cap")
    return bound["subject"]
