"""Exercise conservative plan review with labelled synthetic evidence.

This is a deterministic release check, not a model benchmark or review voice.
The historical activation baseline remains private, source-native evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from agent_lifecycle.audit.delta_review import build_delta_review_packet
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    read_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.metrics.audit_efficiency import compare_plan_review_observations
from agent_lifecycle.review.validation import (
    build_review_impact_graph,
    derive_delta_selection,
    make_review_scope,
    validate_bound_plan_review,
    validate_review_composition,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/audit/fixtures"


def _load(name: str, directory: Path) -> dict[str, Any]:
    value = read_json_object(directory / name, label="synthetic review fixture")
    if value.get("synthetic") is not True:
        raise LifecycleError("review-fixture-unlabelled", "Synthetic label needed")
    return value


def _policy_findings(manifest: dict[str, Any], checks: set[str]) -> list[str]:
    """Fixed workload oracle, independent of the impact graph's edge builder."""
    findings = []
    criteria = manifest["acceptance"]["criteria"]
    tasks = manifest["workstreams"]
    required = {x["id"] for x in manifest["specification"]["requirements"]}
    linked = {r for c in criteria for r in c.get("requirementIds", [])}
    if "requirement" in checks and (linked != required or any(not c.get("requirementIds") for c in criteria)):
        findings.append("requirement-links")
    if "evidence" in checks and any(not x.get("evidenceIds") for x in [*criteria, *tasks]):
        findings.append("evidence-links")
    if "ownership" in checks and any(
        not isinstance(t.get("owner"), str) or not t["owner"] or not t.get("writes") for t in tasks
    ):
        findings.append("ownership-complete")
    if "final" in checks and "final" not in manifest.get("finalAuditGates", []):
        findings.append("mandatory-final-gate")
    return sorted(findings)


def _observation(
    findings: list[str],
    packet: dict[str, Any],
    graph: dict[str, Any],
    selected: set[str],
) -> dict[str, Any]:
    return {
        "findings": findings,
        "readiness": "CHANGES_REQUIRED" if findings else "READY_TO_FREEZE",
        "blockingGates": findings,
        "packetBytes": len(canonical_bytes(packet)),
        "selectedNodes": len(selected),
        "selectedEdges": sum(e["from"] in selected and e["to"] in selected for e in graph["edges"]),
    }


def _paired_case(
    identifier: str,
    subject: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    full = build_delta_review_packet(subject)
    delta = build_delta_review_packet(subject, baseline=baseline)
    # The oracle describes the fixed workload, not an invented model verdict.
    checks = {"requirement", "evidence", "ownership", "final"}
    full_findings = _policy_findings(subject["manifest"], checks)
    try:
        graph = build_review_impact_graph(subject["manifest"], file_digests=subject["fileDigests"])
    except LifecycleError:
        graph = {"nodes": [], "edges": []}
    all_nodes = {n["id"] for n in graph["nodes"]}
    if delta["mode"] == "DELTA_ELIGIBLE":
        closure = set(delta["closure"])
        unchanged = {n["id"] for n in delta["unchangedNodes"]}
        if closure | unchanged != all_nodes or closure & unchanged:
            raise LifecycleError("review-equivalence-coverage", "Partition lost")
        groups = {
            "requirement": {"requirement", "acceptance"},
            "evidence": {"evidence", "acceptance", "workstream"},
            "ownership": {"workstream", "ownership", "path"},
            "final": {"final", "workstream"},
        }
        selected_kinds = {n["kind"] for n in graph["nodes"] if n["id"] in closure}
        affected = {key for key, kinds in groups.items() if kinds & selected_kinds}
        delta_findings = sorted(
            set(
                _policy_findings(subject["manifest"], affected)
                + _policy_findings(baseline["subject"]["manifest"], checks - affected)
            )
        )
        selected = closure
    else:
        # A refused optimization still requires full review. This executes
        # only the deterministic oracle, never a redundant model generation.
        delta_findings = _policy_findings(subject["manifest"], checks)
        selected = all_nodes
    return {
        "caseId": identifier,
        "full": _observation(full_findings, full, graph, all_nodes),
        "delta": _observation(delta_findings, delta, graph, selected),
        "mode": delta["mode"],
        "fallbackOracleOnly": delta["mode"] != "DELTA_ELIGIBLE",
    }


def _mutated_subject(subject: dict[str, Any], identifier: str) -> dict[str, Any]:
    subject = copy.deepcopy(subject)
    manifest = subject["manifest"]
    if identifier == "requirement-edge-omission":
        manifest["acceptance"]["criteria"][0]["requirementIds"] = []
    elif identifier == "evidence-edge-omission":
        manifest["acceptance"]["criteria"][0]["evidenceIds"] = []
    elif identifier == "ownership-edge-omission":
        manifest["workstreams"][0]["owner"] = None
    elif identifier == "final-gate-omission":
        manifest["finalAuditGates"] = []
    path = manifest["package"]["planArtifactRoot"] + "/plan.manifest.json"
    subject["fileDigests"][path] = sha256_hex(canonical_bytes(manifest) + b"\n")
    return subject


def _composition_failure(case: dict[str, Any], identifier: str) -> str:
    case = copy.deepcopy(case)
    reports, manifest = case["reports"], case["subject"]["manifest"]
    current = reports["plans/r2/delta.json"]
    current["subject"] = case["subject"]
    seat = manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]
    if identifier == "open-medium":
        current["findings"] = [{"id": "new", "severity": "MEDIUM", "status": "OPEN"}]
    elif identifier == "missing-closure":
        current["findingClosures"] = []
    elif identifier == "missing-applicability":
        current.pop("currentApplicability")
    elif identifier == "omitted-scope":
        current["reviewScope"]["coveredNodes"] = []
    elif identifier in {"duplicate-seat", "conflicting-seat"}:
        other = {**seat, "id": "two"}
        manifest["extensions"]["reviewPolicy"]["requiredSeats"].append(other)
        baseline = reports["plans/r1/review.json"]
        old_policy = baseline["subject"]["manifest"]["extensions"]["reviewPolicy"]
        old_policy["requiredSeats"].append(
            {
                **old_policy["requiredSeats"][0],
                "id": "two",
            }
        )
        _refresh_review(baseline)
        current["dependsOn"] = [canonical_digest(baseline)]
        current["findingClosures"][0]["reportDigest"] = canonical_digest(baseline)
        current["currentApplicability"]["baselineDigest"] = canonical_digest(baseline)
        _refresh_review(current, baseline)
        if identifier == "conflicting-seat":
            current["verdict"] = "CHANGES_REQUIRED"
    elif identifier == "replayed-delivery":
        path = "plans/r2/replay.json"
        reports[path] = copy.deepcopy(reports[seat["baseline"]])
        case["sizes"][path] = case["sizes"][seat["baseline"]]
        seat["reports"].append(path)
        _refresh_review(current, reports[seat["baseline"]])
    elif identifier == "report-count-cap":
        for i in range(16):
            path = "plans/r2/extra" + str(i) + ".json"
            seat["reports"].append(path)
            reports[path] = copy.deepcopy(current)
            case["sizes"][path] = 1
    elif identifier == "report-byte-cap":
        case["sizes"][seat["current"]] = 8 * 1024 * 1024 + 1
    elif identifier == "stricter-report-cap":
        manifest["extensions"]["reviewPolicy"]["limits"] = {"reports": 1}
    else:
        raise LifecycleError("review-fixture-unknown", identifier)
    # Rebind the outer envelope only: a mutated signed subject or report must
    # still be rejected by the actual consumer, not silently refreshed here.
    case["composite"]["reviewedPlanHash"] = canonical_digest(manifest)
    case["composite"]["currentReports"] = [
        s["current"] for s in manifest["extensions"]["reviewPolicy"]["requiredSeats"]
    ]
    case["composite"]["reviewScope"] = {
        **make_review_scope(current["subject"]),
        "kind": "COMPOSITE",
    }
    try:
        result = validate_review_composition(manifest, case["composite"], reports, report_sizes=case["sizes"])
    except LifecycleError as exc:
        return exc.code
    if identifier == "replayed-delivery" and result["seats"][0]["reportCount"] == 2:
        return "DEDUPLICATED_WITHOUT_NEW_VOICE"
    return "UNEXPECTED_ACCEPTANCE"


def _refresh_review(
    report: dict[str, Any],
    parent: dict[str, Any] | None = None,
) -> None:
    """Rebuild deliberately synthetic data, never repair actual evidence."""
    subject = report["subject"]
    manifest = subject["manifest"]
    path = manifest["package"]["planArtifactRoot"] + "/plan.manifest.json"
    subject["fileDigests"][path] = sha256_hex(canonical_bytes(manifest) + b"\n")
    digest = canonical_digest(manifest)
    report["reviewedPlanHash"] = digest
    report["planRevision"] = manifest["planRevision"]
    report["reviewAuthority"]["subjectHash"] = digest
    report["reviewScope"] = (
        make_review_scope(subject)
        if parent is None
        else make_review_scope(subject, kind="DELTA", selection=derive_delta_selection(parent["subject"], subject))
    )
    if "currentApplicability" in report:
        report["currentApplicability"]["candidateHash"] = digest


def _chain_observation(case: dict[str, Any], edges: int) -> str:
    case = copy.deepcopy(case)
    reports = case["reports"]
    previous = reports["plans/r2/delta.json"]
    for revision in range(3, edges + 2):
        report = copy.deepcopy(previous)
        manifest = report["subject"]["manifest"]
        old_root = manifest["package"]["planArtifactRoot"]
        new_root = "plans/r" + str(revision)
        manifest["planRevision"] = revision
        manifest["package"]["planArtifactRoot"] = new_root
        manifest["planFiles"] = [p.replace(old_root + "/", new_root + "/") for p in manifest["planFiles"]]
        manifest["planReview"]["report"] = new_root + "/review.json"
        seat = manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]
        path = new_root + "/delta.json"
        seat["current"] = path
        seat["reports"] = [*reports, path]
        report["subject"]["fileDigests"] = {
            p.replace(old_root + "/", new_root + "/"): d for p, d in report["subject"]["fileDigests"].items()
        }
        report["findingClosures"] = []
        report["reviewId"] = "synthetic-chain-" + str(revision)
        report["reviewer"]["runId"] = report["reviewId"]
        report["reviewAuthority"]["reviewId"] = report["reviewId"]
        report["reviewAuthority"]["runId"] = report["reviewId"]
        report["dependsOn"] = [canonical_digest(previous)]
        _refresh_review(report, previous)
        reports[path] = report
        previous = report
    manifest = previous["subject"]["manifest"]
    envelope = {
        **case["composite"],
        "planRevision": manifest["planRevision"],
        "reviewedPlanHash": canonical_digest(manifest),
        "reviewScope": {**make_review_scope(previous["subject"]), "kind": "COMPOSITE"},
        "currentReports": [manifest["extensions"]["reviewPolicy"]["requiredSeats"][0]["current"]],
    }
    try:
        result = validate_review_composition(
            manifest,
            envelope,
            reports,
            report_sizes={p: len(canonical_bytes(r)) for p, r in reports.items()},
        )
    except LifecycleError as exc:
        return exc.code
    return "ACCEPTED_" + str(result["seats"][0]["dependencyEdges"])


def _packet_failure(case: dict[str, Any], identifier: str) -> dict[str, Any]:
    subject = copy.deepcopy(case["subject"])
    baseline = copy.deepcopy(case["baseline"])
    cap = 98304
    if identifier == "missing-baseline":
        baseline = {"schemaVersion": "agent-plan-review.v2"}
    elif identifier == "partial-baseline":
        baseline = copy.deepcopy(case["reports"]["plans/r2/delta.json"])
    elif identifier == "blocked-baseline":
        baseline["verdict"] = "BLOCKED"
    elif identifier == "stale-subject":
        baseline["subject"]["manifest"]["planRevision"] += 10
    elif identifier == "runtime-change":
        subject["runtimeInputs"]["runtime.py"] = "0" * 64
    elif identifier == "security-change":
        subject["manifest"]["securityGates"] = ["new-gate"]
    elif identifier == "unknown-impact":
        subject["manifest"]["unknownFuturePolicy"] = True
    elif identifier == "packet-cap":
        cap = 1024
    else:
        raise LifecycleError("review-fixture-unknown", identifier)
    return build_delta_review_packet(subject, baseline=baseline, max_bytes=cap)


def validate_equivalence(directory: Path = FIXTURES) -> dict[str, Any]:
    full = _load("delta-review-full.json", directory)
    case = _load("delta-review-eligible.json", directory)
    forced = _load("delta-review-forced-full.json", directory)
    reference = validate_bound_plan_review(full["review"])
    composition = validate_review_composition(
        case["subject"]["manifest"],
        case["composite"],
        case["reports"],
        report_sizes=case["sizes"],
    )
    if reference["subject"] != case["subject"]:
        raise LifecycleError("review-fixture-subject-mismatch", "Same workload needed")
    if full["review"]["verdict"] != composition["verdict"]:
        raise LifecycleError("review-equivalence-verdict", "Verdicts differ")
    pairs = [_paired_case("anchored-negative-baseline-closed", case["subject"], case["baseline"])]
    if (
        pairs[0]["full"]["findings"] != full["expectedFindings"]
        or pairs[0]["full"]["readiness"] != full["expectedReadiness"]
        or full["review"]["findings"]
    ):
        raise LifecycleError("review-fixture-oracle-mismatch", "Reference changed")
    accepting = copy.deepcopy(case["baseline"])
    accepting.update(verdict="READY_TO_FREEZE", findings=[])
    pairs.append(_paired_case("accepting-complete-baseline", case["subject"], accepting))
    for identifier in forced["cases"]:
        if identifier.endswith("omission"):
            subject = _mutated_subject(case["subject"], identifier)
            pairs.append(_paired_case(identifier, subject, case["baseline"]))
    comparison = compare_plan_review_observations(pairs)
    refusals = []
    packet_cases = {
        "missing-baseline",
        "partial-baseline",
        "blocked-baseline",
        "stale-subject",
        "runtime-change",
        "security-change",
        "unknown-impact",
        "packet-cap",
    }
    for identifier in forced["cases"]:
        if identifier.endswith("omission"):
            continue
        if identifier == "chain-depth-cap":
            boundary = _chain_observation(case, 8)
            code = _chain_observation(case, 9)
            passed = boundary == "ACCEPTED_8" and code == "review-chain-limit"
        elif identifier in packet_cases:
            packet = _packet_failure(case, identifier)
            code = ",".join(packet["reasons"])
            passed = packet["mode"] == "FULL_REQUIRED" and not packet["modelCallsStarted"]
        else:
            code = _composition_failure(case, identifier)
            passed = (
                code == "DEDUPLICATED_WITHOUT_NEW_VOICE"
                if identifier == "replayed-delivery"
                else code != "UNEXPECTED_ACCEPTANCE"
            )
            if identifier in {"report-count-cap", "report-byte-cap", "stricter-report-cap"}:
                passed = code == "review-chain-limit"
            if identifier == "duplicate-seat":
                passed = code == "review-duplicate-seat"
        refusals.append({"caseId": identifier, "passed": passed, "reason": code})
    body = {
        "status": "PASS" if comparison["status"] == "PASS" and all(r["passed"] for r in refusals) else "FAIL",
        "boundary": "SYNTHETIC_DETERMINISTIC_RELEASE_CHECK",
        "planReviewComparison": comparison,
        "refusalCases": refusals,
        "caseCount": len(pairs) + len(refusals),
        "fixtureDigests": {
            name: sha256_hex((directory / name).read_bytes())
            for name in ("delta-review-full.json", "delta-review-eligible.json", "delta-review-forced-full.json")
        },
        "actualModelGeneration": False,
        "modelTokens": None,
        "modelTokenReductionPercent": None,
        "modelUsageStatus": "UNAVAILABLE",
        "historicalBaselineRecharged": False,
        "authorityWrites": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = validate_equivalence(args.fixtures)
    if args.out:
        write_json_create(args.out, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
