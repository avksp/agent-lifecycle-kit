"""Validate H04 inputs and source-only profiles against their actual review origin.

Catalog and explicit preflight modes produce diagnostics. Final mode requires
published independent reviews and current core proof before emitting a DECLARED
command witness; task and release acceptance remain separate workflow checks.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.host_bridge import (
    _CEILING_KEYS,
    ARTIFACT_BYTES,
    PROFILE_BYTES,
    TASK_BYTES,
    _fail,
    _json,
    _read,
    _refs,
    read_source_lifecycle_qualifications,
)
from agent_lifecycle.accounting.host_bridge import (
    BoundedReader as BoundedReader,
)
from agent_lifecycle.accounting.host_bridge import (
    EvidenceGraph as EvidenceGraph,
)
from agent_lifecycle.accounting.support_profiles import match_requested_claims, validate_profile_payload
from agent_lifecycle.adapter_sessions.launch_execution import (
    _read_reviewed_final_profile_snapshot,
    _require_matching_final_profile_snapshots,
)
from agent_lifecycle.adapter_sessions.ordinary_audit import verify_area_report
from agent_lifecycle.adapter_sessions.limited_native_evidence import verify_native_observations
from agent_lifecycle.changesets import capture_task_change_set, require_current_task_change_set
from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.contracts.evidence_receipt_schemas import validate_evidence_receipt_shape
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity
from agent_lifecycle.workflow.audit_evidence import (
    _expected_task_evidence_subject, _validate_evidence_references, validate_task_evidence_paths,
)

EXPECTED_ADAPTERS = frozenset(
    {"codex", "claude", "opencode", "grok-build", "gemini-cli", "pi", "hermes",
     "qwen-code", "kimi-code", "cursor", "goose", "openinterpreter"}
)


def exact_resolver_requests(payload: dict, joins: dict) -> dict[str, dict]:
    """The exact-profile producer and final validator share explicit mutations."""
    baseline = {"schemaVersion": "alk-accounting-capability-request.v1", "requestId": "supported",
                **joins, "operationId": "exact-profile-test", "requestedModes": ["LIFECYCLE_ONLY"],
                "requiredClaims": [], "routeIds": ["worker"], "requestedUpperBound": None}
    cases = {"supported": baseline}

    def add(case_id, field, value):
        request = copy.deepcopy(baseline)
        request["requestId"] = case_id
        request[field] = value
        cases[case_id] = request

    for mode in ("OBSERVATION", "ALK_INVOCATION_ADMISSION", "HOST_PARTIAL_CONTROL", "FULL_FINANCIAL"):
        add("mode." + mode, "requestedModes", [mode])
    for field in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest"):
        add("join." + field, field, "0" * 64)
    for field, value in (("adapterId", "claude" if payload["binding"]["adapterId"] != "claude" else "codex"),
                         ("hostVersion", payload["binding"]["hostVersion"] + ".mismatch"),
                         ("launchMode", "MISMATCH"), ("providerId", "MISMATCH"), ("transportId", "MISMATCH"),
                         ("executableSha256", "0" * 64), ("configurationSha256", "0" * 64),
                         ("evidenceMode", "RUNTIME_OBSERVED")):
        binding = {**payload["binding"], field: value}
        if (payload["binding"]["evidenceMode"] == "SOURCE_BOUND_LIMITATION"
                and field in ("providerId", "transportId", "executableSha256", "configurationSha256", "evidenceMode")):
            # A negative runtime tuple must satisfy the request schema. These
            # zero identities are mismatching inputs, never host observations.
            binding["evidenceMode"] = "RUNTIME_OBSERVED"
            for identity in ("executableSha256", "configurationSha256"):
                if binding[identity] is None:
                    binding[identity] = "0" * 64
        add("binding." + field, "binding", binding)
    for dimension, guarantee in (("ACCOUNTING", "FULL_TOTAL"), ("CONTROL", "ATOMIC_TASK_RUN"),
                                 ("COVERAGE", "ALL_ROUTES"), ("ACCOUNTING", "ATOMIC_TASK_RUN")):
        add("claim." + dimension + "." + guarantee, "requiredClaims", [{
            "dimension": dimension, "guarantee": guarantee, "unitId": "unavailable-unit", "routeIds": ["worker"],
            "limitKind": "NONE", "boundMethodId": None, "requireFailClosed": True}])
    add("route.unknown", "routeIds", ["unknown-route"])
    add("route.excluded-positive", "requestedModes", ["FULL_FINANCIAL"])
    for field, value in (("unitId", "wrong-unit"), ("boundMethodId", "wrong-bound-method")):
        claim = {"dimension": "CONTROL", "guarantee": "ALK_PRE_LAUNCH", "unitId": "alk-owned-invocations",
                 "routeIds": ["worker"], "limitKind": "ADMISSION_ONLY", "boundMethodId": None, "requireFailClosed": True}
        claim[field] = value
        add("claim." + field, "requiredClaims", [claim])
    for case_id in ("artifact.missing", "artifact.stale", "artifact.forged", "artifact.forged-result"):
        add(case_id, "operationId", case_id)
    return cases


def exact_qualification_mutations(qualification: dict, requests: dict) -> dict:
    """Exact inputs that the resolver producer must actually exercise."""
    stale = copy.deepcopy(qualification)
    stale["alkCandidateDigest"] = "0" * 64
    forged = copy.deepcopy(qualification)
    forged["reviewEvidenceRef"]["sha256"] = "0" * 64
    replay = {"schemaVersion": "alk-accounting-capability-result.v1", "outcome": "ALLOW_CAPABILITY",
              "requestDigest": canonical_digest(requests["artifact.forged-result"]), "dispatchEntitlement": True}
    return {"artifact.missing": None, "artifact.stale": stale,
            "artifact.forged": forged, "artifact.forged-result": replay}


def _check_resolver_observations(item: dict) -> None:
    resolver = item["resolver"]
    expected = exact_resolver_requests(item["payload"], item["joins"])
    observations = {row["caseId"]: row for row in resolver["observations"]}
    if set(observations) != set(expected):
        _fail("accounting-exact-resolver-case-inventory-mismatch")
    for case_id, request in expected.items():
        row = observations[case_id]
        result = row["result"]
        if row["request"] != request or type(row["alkOwnedDispatchCount"]) is not int or row["alkOwnedDispatchCount"] != 0:
            _fail("accounting-exact-resolver-request-or-dispatch-mismatch")
        trace = item["resolverTraces"][row["rawTraceRef"]["path"]]
        if (set(trace) != {"schemaVersion", "profileDigest", "commandDigest", "observations", "qualificationMutations"}
                or trace["schemaVersion"] != "alk-accounting-resolver-trace.v1"
                or trace["profileDigest"] != item["joins"]["profileDigest"]
                or trace["commandDigest"] != resolver["commandDigest"] or not isinstance(trace["observations"], list)):
            _fail("accounting-exact-resolver-trace-invalid")
        mutations = exact_qualification_mutations(item["qualification"], expected)
        expected_mutations = {case: {"originalQualificationDigest": canonical_digest(item["qualification"]),
                                    "replacementJson": None if value is None else json.dumps(
                                        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}
                              for case, value in mutations.items()}
        # Deliberately invalid inputs stay opaque strings, never authority refs.
        # The ordinary resolver review covers the trace and its actual producer.
        if trace["qualificationMutations"] != expected_mutations:
            _fail("accounting-exact-resolver-artifact-mutation-mismatch")
        ids = [observed.get("caseId") for observed in trace["observations"] if isinstance(observed, dict)]
        if len(ids) != len(trace["observations"]) or len(set(ids)) != len(ids):
            _fail("accounting-exact-resolver-trace-invalid")
        raw_rows = [observed for observed in trace["observations"] if observed["caseId"] == case_id]
        if raw_rows != [{k: v for k, v in row.items() if k != "rawTraceRef"}]:
            _fail("accounting-exact-resolver-trace-mismatch")
        should_allow = case_id == "supported"
        unqualified = case_id.startswith("artifact.")
        # A refused evidence graph establishes no validated profile identity.
        # The public resolver uses its exact sentinel for these denials.
        marker = canonical_digest({"invalidInput": True})
        expected_profile = marker if unqualified else item["joins"]["profileDigest"]
        expected_expectation = marker if unqualified else item["joins"]["expectationDigest"]
        if (result["requestDigest"] != canonical_digest(request)
                or result["profileDigest"] != expected_profile
                or result["expectationDigest"] != expected_expectation
                or result["outcome"] != ("ALLOW_CAPABILITY" if should_allow else "DENY")
                or result["reason"] != ("CAPABILITY_MATCH" if should_allow else "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE")
                or result["matchedClaimIds"] or result["dispatchEntitlement"] is not False):
            _fail("accounting-exact-resolver-result-mismatch")
        if should_allow and result["detail"] != "MATCH":
            _fail("accounting-exact-resolver-result-mismatch")
        if case_id.startswith("artifact.") and result["detail"] != "UNQUALIFIED_EVIDENCE":
            _fail("accounting-exact-resolver-result-mismatch")
        if not should_allow and not case_id.startswith("artifact."):
            matched = match_requested_claims(item["payload"], request,
                                             expectation_digest=item["joins"]["expectationDigest"],
                                             plan_digest=item["joins"]["planDigest"],
                                             candidate_digest=item["joins"]["alkCandidateDigest"])
            if matched["status"] != "MISMATCH" or result["detail"] != matched["detail"]:
                _fail("accounting-exact-resolver-result-mismatch")


def _read_current_run_state(root: Path, manifest: dict, reader: BoundedReader, *,
                            state_path: str | None = None, run_id: str | None = None) -> dict:
    """Use the selected frozen ordinary route, not inherited state defaults."""
    policy = manifest.get("runtimePolicy", {})
    if not isinstance(policy, dict):
        _fail("accounting-current-route-binding-mismatch")
    if (state_path is None) != (run_id is None):
        _fail("accounting-current-runtime-selector-incomplete")
    if "remainingWorkR88" not in policy:
        if state_path is not None:
            _fail("accounting-current-runtime-selector-unsupported")
        return _json(reader.read(root, manifest["orchestration"]["stateFile"], ARTIFACT_BYTES))
    route = policy["remainingWorkR88"]
    if (not isinstance(route, dict) or not isinstance(route.get("dispatchContract"), str)
            or not isinstance(route.get("contract"), str)):
        _fail("accounting-current-route-binding-mismatch")
    dispatch_path = normalize_repo_path(route["dispatchContract"], label="ordinary dispatch")
    contract_path = normalize_repo_path(route["contract"], label="ordinary contract")
    if dispatch_path not in manifest["planFiles"] or contract_path not in manifest["planFiles"]:
        _fail("accounting-current-route-not-frozen")
    lock = _json(reader.read(root, "tasks/release-2-16/plan.lock.json", ARTIFACT_BYTES))
    if (lock["schemaVersion"] != "agent-plan-lock.v2"
            or lock["manifestHash"] != canonical_digest(manifest)
            or lock["planRevision"] != manifest["planRevision"]):
        _fail("accounting-current-route-lock-mismatch")
    documents = {}
    for path in (dispatch_path, contract_path):
        raw = reader.read(root, path, ARTIFACT_BYTES)
        pins = [entry for entry in lock["entries"] if entry["path"] == path]
        if len(pins) != 1 or pins[0]["bytes"] != len(raw) or pins[0]["sha256"] != hashlib.sha256(raw).hexdigest():
            _fail("accounting-current-route-artifact-mismatch")
        documents[path] = raw
    dispatch = _json(documents[dispatch_path])
    if (dispatch["schemaVersion"] != "alk-ordinary-release-dispatch.v1"
            or type(dispatch["revision"]) is not int or dispatch["revision"] != manifest["planRevision"]
            or dispatch["contractPath"] != contract_path
            or dispatch["stateFile"] != manifest["budgets"]["stateFile"]
            or dispatch["eventLog"] != manifest["budgets"]["eventLog"]
            or dispatch["workspace"] != str(root.absolute())):
        _fail("accounting-current-route-binding-mismatch")
    selected = dispatch["stateFile"] if state_path is None else state_path
    state_path = normalize_repo_path(selected, label="ordinary state")
    normalize_repo_path(dispatch["eventLog"], label="ordinary event log")
    state = _json(reader.read(root, state_path, ARTIFACT_BYTES))
    if (state["planDigest"] != canonical_digest(manifest)
            or state["planRevision"] != manifest["planRevision"]
            or state["runId"] != (dispatch["runId"] if run_id is None else run_id)):
        _fail("accounting-current-route-state-mismatch")
    return state


def _prepared_task_result(root: Path, state: dict, reader: BoundedReader) -> tuple[dict, dict, dict]:
    """Qualify the existing prepared result without claiming task acceptance."""
    task = next(t for t in state["tasks"] if t["id"] == "WS216-02")
    deadline = min(datetime.fromisoformat(v.replace("Z", "+00:00"))
                   for v in (task["attemptDeadlineAt"], state["runDeadlineAt"]))
    if task["status"] != "RUNNING" or datetime.now(UTC) >= deadline:
        _fail("accounting-final-task-not-current")
    path = task["artifactPaths"]["result"].format(attempt=task["attempt"])
    raw = reader.read(root, path, PROFILE_BYTES)
    result = _json(raw)
    if (result["planDigest"] != state["planDigest"] or result["runId"] != state["runId"]
            or result["taskId"] != task["id"] or result["attempt"] != task["attempt"]):
        _fail("accounting-final-result-subject-mismatch")
    snapshot = capture_task_change_set(root, baseline=state["sourceRevision"], write_paths=task["writes"])
    require_current_task_change_set(result, snapshot)
    return task, artifact_identity(root, path, result), snapshot


def _check_current_core(root: Path, manifest: dict, reader: BoundedReader, *,
                        state_path: str | None = None, run_id: str | None = None) -> dict:
    """Reuse the existing receipt/subject/origin validator; never trust PASS labels."""
    state = (_read_current_run_state(root, manifest, reader) if state_path is None and run_id is None
             else _read_current_run_state(root, manifest, reader, state_path=state_path, run_id=run_id))
    if state["planDigest"] != canonical_digest(manifest):
        _fail("accounting-core-plan-mismatch")
    owners = [w for w in manifest["workstreams"] if "EV216-ACCOUNTING-CORE" in w["evidenceIds"]]
    if len(owners) != 1:
        _fail("accounting-core-owner-mismatch")
    task = next(t for t in state["tasks"] if t["id"] == owners[0]["id"])
    if task["status"] not in {"ACCEPTED", "RUNNING"}:
        _fail("accounting-core-task-not-current")
    descriptor = next(e for e in manifest["acceptance"]["evidence"] if e["id"] == "EV216-ACCOUNTING-CORE")
    path = descriptor["artifactPath"]
    receipt = validate_evidence_receipt_shape(_json(reader.read(root, path, PROFILE_BYTES)))
    if task["status"] == "RUNNING":
        _state_task, result_ref, snapshot = _prepared_task_result(root, state, reader)
        if _state_task["id"] != task["id"]:
            _fail("accounting-core-owner-mismatch")
    else:
        result_ref, snapshot = task["result"], task["resultChangeSetEvidence"]
    result_raw = reader.read(root, result_ref["path"], ARTIFACT_BYTES)
    if artifact_identity(root, result_ref["path"], _json(result_raw)) != result_ref:
        _fail("accounting-core-result-mismatch")
    checked = validate_task_evidence_paths(root, manifest, state, task, result_ref,
                                         snapshot, [path])
    if not any(row["evidenceId"] == "EV216-ACCOUNTING-CORE" and row["validationStatus"] == "PASS"
               for row in checked["suppliedEvidence"]):
        _fail("accounting-core-receipt-unavailable")
    required = set(descriptor["validation"]["requirements"]["caseIds"])
    rows = [row for command in receipt["payload"]["commands"] for row in command["cases"]]
    if len({row["id"] for row in rows}) != len(rows) or {row["id"] for row in rows} != required or any(row["status"] != "PASS" for row in rows):
        _fail("accounting-core-witness-inventory-mismatch")
    return {"caseIds": sorted(required),
            "sourceComponents": [{"id": c["id"], "commitOid": c["commitOid"], "contentDigest": c["contentDigest"]}
                                 for c in receipt["subject"]["components"]]}


def _boundary_checks(profiles: dict, core: dict, required_ids: list[str]) -> list[dict]:
    """Map each frozen oracle to the predicates and witnesses actually checked."""
    if set(profiles) != EXPECTED_ADAPTERS:
        _fail("accounting-final-profile-inventory-mismatch")
    for item in profiles.values():
        payload = item["payload"]
        if (payload["modes"] != ["LIFECYCLE_ONLY"] or payload["claims"]
                or payload["completeFinancialRun"] is not False
                or any(r["state"] != "EXCLUDED" for r in payload["routes"])
                or any(o["usage"] is not None or o["usageStatus"] != "UNAVAILABLE"
                       for o in item["qualification"]["observations"])):
            _fail("accounting-final-source-only-boundary-mismatch")
    witnesses = {
        "inventory": ["exact-twelve-envelopes-and-frozen-catalog"],
        "version-mode-binding": ["closed-binding-source-and-candidate-joins", "binding-mutations"],
        "requested-guarantee-denial": ["exact-resolver-mutations-with-zero-dispatch", "ordinary-resolver-origin"],
        "failure-semantics": ["no-control-claim", "stronger-control-request-denied"],
        "usage-coverage": ["exact-role-inventory-excluded", "usage-unavailable-null", "complete-total-denied"],
        "closure-retention": ["complete-financial-run-false", "accounting.core.task-run-closeout", "accounting.core.ac13"],
        "source-case-applicability": ["exact-thirteen-case-hashes-and-reviewed-limitations"],
        "candidate-dispositions": ["exact-candidate-observation-source-links", "ordinary-qualification-origin"],
        "core-preservation": core["caseIds"],
    }
    ids = {"accounting.profile." + name for name in witnesses}
    if set(required_ids) != {"accounting.profile." + adapter for adapter in EXPECTED_ADAPTERS} | ids:
        _fail("accounting-final-case-inventory-mismatch")
    if not {"accounting.core.task-run-closeout", "accounting.core.ac13"} <= set(core["caseIds"]):
        _fail("accounting-final-closure-witness-missing")
    return [{"id": "accounting.profile." + name, "status": "PASS", "validatedPredicates": proof}
            for name, proof in witnesses.items()]


def _prepare_final_profiles(root: Path, manifest: Path, catalog: Path, profiles_root: Path, *,
                            state_path: str | None = None, run_id: str | None = None) -> tuple[dict, dict]:
    """One private validation snapshot; no PASS until the final fresh boundary."""
    checks = []
    reader = BoundedReader()
    try:
        manifest_path = manifest.absolute().relative_to(root).as_posix()
        if manifest_path != "tasks/release-2-16/plan.manifest.json":
            _fail("accounting-final-manifest-mismatch")
        catalog_check = validate_catalog(root, manifest, catalog, reader)
        adapters = [row["adapterId"] for row in catalog_check["entries"]]
        manifest_value = _json(reader.read(root, manifest_path, ARTIFACT_BYTES))
        frozen = _json(reader.read(root, "tasks/release-2-16/h04-adapter-profile-cases.json", ARTIFACT_BYTES))
        required_ids = [row["id"] for row in frozen["requiredCases"]]
        if len(required_ids) != 21 or len(set(required_ids)) != 21:
            _fail("accounting-final-case-inventory-mismatch")
        core = _check_current_core(root, manifest_value, reader, state_path=state_path, run_id=run_id)
        final = _read_reviewed_final_profile_snapshot(project_root=root, profiles_root=profiles_root,
                                                       adapter_ids=adapters, byte_limit=TASK_BYTES - reader.charged_bytes)
        for adapter, item in final["profiles"].items():
            _check_resolver_observations(item)
            checks.append({"id": "accounting.profile." + adapter, "status": "PASS",
                           "profileDigest": item["joins"]["profileDigest"], "nativeQualified": False})
        checks.extend(_boundary_checks(final["profiles"], core, required_ids))
        refs = {r["path"]: r for r in reader.snapshot_refs(root)}
        for ref in final["snapshotRefs"]:
            if ref["path"] in refs and refs[ref["path"]] != ref:
                _fail("accounting-final-snapshot-conflict")
            refs[ref["path"]] = ref
        if reader.charged_bytes + final["readBytes"] > TASK_BYTES:
            _fail("accounting-final-read-budget-exceeded")
        report = {"schemaVersion": "alk-accounting-final-validation.v1", "status": "PREPARED", "checks": checks,
                "blockers": [], "validatedProfileCount": 12, "acceptingReceipt": False,
                "dataCandidate": False, "typedReceiptRequired": True,
                "readBudgetChargedBytes": reader.charged_bytes + final["readBytes"],
                "inputRefs": [refs[path] for path in sorted(refs)], "sourceComponents": core["sourceComponents"],
                "ordinaryReviews": [list(row) for row in sorted({
                    (item["review"]["reviewId"], item["reviewRef"]["sha256"])
                    for item in final["profiles"].values()} | {
                    (item["resolverReceipt"]["reviewId"], item["resolver"]["receiptRef"]["sha256"])
                    for item in final["profiles"].values()})],
                "dispatchEntitlement": False, "modelCallsStarted": False, "releaseReady": False}
        return report, final
    finally:
        reader.close()


def _refresh_final_profile_inputs(root: Path, profiles_root: Path, report: dict, first: dict, *,
                                  extra_refs: list[dict] = (), extra_charged_bytes: int = 0) -> dict:
    """Re-enumerate profiles/source, then reopen all remaining inputs once.

    Overlapping profile inputs are verified from the fresh second snapshot;
    no stale cache crosses snapshots and every actual read remains charged.
    """
    charged = report["readBudgetChargedBytes"] + extra_charged_bytes
    if type(charged) is not int or not 0 < charged < TASK_BYTES:
        _fail("accounting-final-read-budget-exceeded")
    second = read_source_lifecycle_qualifications(
        root, profiles_root, list(first["profiles"]), final=True, byte_limit=TASK_BYTES - charged,
    )
    _require_matching_final_profile_snapshots(first, second)
    charged += second["readBytes"]
    refs = {}
    for ref in report["inputRefs"] + list(extra_refs):
        if ref["path"] in refs and refs[ref["path"]] != ref:
            _fail("accounting-final-snapshot-conflict")
        refs[ref["path"]] = ref
    fresh_refs = {ref["path"]: ref for ref in second["snapshotRefs"]}
    reader = BoundedReader(TASK_BYTES - charged)
    try:
        for path, ref in refs.items():
            if path in fresh_refs:
                if fresh_refs[path] != ref:
                    _fail("accounting-final-input-changed-after-validation")
            else:
                raw = reader.read(root, path, ARTIFACT_BYTES)
                if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                    _fail("accounting-final-input-changed-after-validation")
        return {**report, "status": "PASS", "dataCandidate": True,
                "readBudgetChargedBytes": charged + reader.charged_bytes,
                "inputRefs": [refs[path] for path in sorted(refs)]}
    finally:
        reader.close()


def _final_failure(checks: list[dict], exc: Exception) -> dict:
    return {"schemaVersion": "alk-accounting-final-validation.v1", "status": "FAIL", "checks": checks,
            "blockers": [{"code": getattr(exc, "code", "accounting-final-evidence-unavailable")}],
            "dataCandidate": False, "acceptingReceipt": False,
            "dispatchEntitlement": False, "modelCallsStarted": False, "releaseReady": False}


def validate_final_profiles(repo_root: Path, manifest: Path, catalog: Path, profiles_root: Path, *,
                            state_path: str | None = None, run_id: str | None = None) -> dict:
    """Standalone validation still requires two snapshots and all21 checks."""
    root = repo_root.absolute()
    manifest = manifest if manifest.is_absolute() else root / manifest
    catalog = catalog if catalog.is_absolute() else root / catalog
    profiles_root = profiles_root if profiles_root.is_absolute() else root / profiles_root
    report = None
    try:
        report, first = _prepare_final_profiles(root, manifest, catalog, profiles_root,
                                               state_path=state_path, run_id=run_id)
        return _refresh_final_profile_inputs(root, profiles_root, report, first)
    except (LifecycleError, OSError, ValueError, KeyError, TypeError, RecursionError, StopIteration) as exc:
        return _final_failure(report["checks"] if report else [], exc)


def _complete_payload(payload: dict, supplemental: dict | None, descriptor: dict) -> dict:
    """Compose existing observations; never invent or promote a case outcome."""
    combined = copy.deepcopy(payload)
    if supplemental is not None:
        if (supplemental.get("schemaVersion") != payload["schemaVersion"]
                or supplemental.get("platform") != payload["platform"]
                or not isinstance(supplemental.get("commands"), list)):
            _fail("accounting-final-supplemental-payload-mismatch")
        combined["commands"].extend(copy.deepcopy(supplemental["commands"]))
    commands = combined["commands"]
    ids = [c["commandDigest"] for c in commands]
    cases = [row for command in commands for row in command["cases"]]
    case_ids = [row["id"] for row in cases]
    required = descriptor["validation"]["requirements"]
    if (len(set(ids)) != len(ids) or set(ids) != set(required["commandDigests"])
            or len(set(case_ids)) != len(case_ids) or set(case_ids) != set(required["caseIds"])
            or any(c["status"] != "PASS" or c["exitCode"] != 0 for c in commands)
            or any(c["status"] != "PASS" for c in cases)):
        _fail("accounting-final-complete-payload-required")
    return combined


def _emit_prepared_final_receipt(root: Path, manifest_path: Path, report: dict, output: Path, *,
                       profiles_root: Path, first: dict,
                       state_path: str | None = None, run_id: str | None = None,
                       supplemental_path: str | None = None) -> dict:
    """Complete a private preparation; the workflow still performs acceptance."""
    if (report["status"] != "PREPARED" or len(report["checks"]) != 21
            or any(row["status"] != "PASS" for row in report["checks"])
            or not report.get("inputRefs") or not report.get("ordinaryReviews")):
        _fail("accounting-final-checks-not-passed")
    charged = report["readBudgetChargedBytes"]
    if type(charged) is not int or not 0 < charged < TASK_BYTES:
        _fail("accounting-final-read-budget-exceeded")
    root = root.absolute()
    reader = BoundedReader(TASK_BYTES - charged)
    try:
        manifest_relative = normalize_repo_path(manifest_path.relative_to(root).as_posix(), label="final manifest")
        if manifest_relative != "tasks/release-2-16/plan.manifest.json":
            _fail("accounting-final-manifest-mismatch")
        manifest = _json(reader.read(root, manifest_relative, ARTIFACT_BYTES))
        state = (_read_current_run_state(root, manifest, reader) if state_path is None and run_id is None
             else _read_current_run_state(root, manifest, reader, state_path=state_path, run_id=run_id))
        task, result_ref, snapshot = _prepared_task_result(root, state, reader)
        deadline = min(datetime.fromisoformat(v.replace("Z", "+00:00"))
                       for v in (task["attemptDeadlineAt"], state["runDeadlineAt"]))
        raw = reader.read(root, result_ref["path"], PROFILE_BYTES)
        result_raw_ref = {"path": result_ref["path"], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        descriptor = next(e for e in manifest["acceptance"]["evidence"] if e["id"] == "EV216-ACCOUNTING-ENFORCEMENT")
        subject = _expected_task_evidence_subject(root, state, task, result_ref, snapshot, descriptor["validation"])
        source_components = [{"id": c["id"], "commitOid": c["commitOid"], "contentDigest": c["contentDigest"]}
                             for c in subject["components"]]
        if source_components != report["sourceComponents"]:
            _fail("accounting-final-source-changed-after-validation")
        frozen = _json(reader.read(root, "tasks/release-2-16/h04-adapter-profile-cases.json", ARTIFACT_BYTES))
        ids = [row["id"] for row in report["checks"]]
        if len(set(ids)) != 21 or set(ids) != {row["id"] for row in frozen["requiredCases"]}:
            _fail("accounting-final-case-inventory-mismatch")
        output_relative = normalize_repo_path(output.relative_to(root).as_posix(), label="final evidence")
        if output_relative != descriptor["artifactPath"]:
            _fail("accounting-final-output-path-mismatch")
        contracts_path = "tasks/release-2-16/h04-artifact-contracts.json"
        contracts_raw = reader.read(root, contracts_path, ARTIFACT_BYTES)
        contract_refs = [ref for ref in report["inputRefs"] if ref["path"] == contracts_path]
        if (len(contract_refs) != 1 or contract_refs[0]["bytes"] != len(contracts_raw)
                or contract_refs[0]["sha256"] != hashlib.sha256(contracts_raw).hexdigest()):
            _fail("accounting-final-producer-contract-binding-mismatch")
        contracts = _json(contracts_raw)
        producers = [p for p in contracts["producers"] if p["id"] == "P-FINAL-VALIDATOR"]
        if len(producers) != 1:
            _fail("accounting-final-producer-unavailable")
        producer = producers[0]
        supplemental = None
        supplemental_refs = []
        if supplemental_path is not None:
            supplemental_path = normalize_repo_path(supplemental_path, label="supplemental observations")
            supplemental_raw = reader.read(root, supplemental_path, ARTIFACT_BYTES)
            supplemental = _json(supplemental_raw)
            supplemental_refs.append({"path": supplemental_path, "bytes": len(supplemental_raw),
                                      "sha256": hashlib.sha256(supplemental_raw).hexdigest()})
        # Membership is checked before any sidecar or final evidence is written.
        profile_payload = {"schemaVersion": "agent-command-observation.v1",
                           "platform": {"os": {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()],
                                        "architecture": platform.machine(), "pythonVersion": platform.python_version()},
                           "commands": [{"commandDigest": canonical_digest(producer["command"]), "status": "PASS", "exitCode": 0,
                                         "cases": [{"id": r["id"], "status": r["status"]} for r in report["checks"]]}]}
        complete = _complete_payload(profile_payload, supplemental, descriptor)
        verify_native_observations(
            root, complete, reader=reader, manifest=manifest, state=state, task=task,
            candidate_digest=first["profiles"]["codex"]["joins"]["alkCandidateDigest"],
        )
        for review_id, report_sha in report["ordinaryReviews"]:
            verified = verify_area_report(root, review_id=review_id)
            if (verified["reportSha256"] != report_sha or verified["nativeAllowed"] is not False
                    or verified["assurance"] != "PROCEDURAL_SAME_ACCOUNT"):
                _fail("accounting-final-review-changed-after-validation")
        # This is the second complete snapshot in the composed C21 command.
        # It also re-enumerates candidate sources to catch newly added files.
        report = _refresh_final_profile_inputs(
            root, profiles_root, report, first, extra_refs=reader.snapshot_refs(root),
            extra_charged_bytes=reader.charged_bytes,
        )
        if datetime.now(UTC) >= deadline:
            _fail("accounting-final-task-deadline-expired")
        report_path = Path(output_relative + ".observations.json")
        stderr_path = Path(output_relative + ".stderr.txt")
        write_json_create(root / report_path, report)
        (root / stderr_path).parent.mkdir(parents=True, exist_ok=True)
        with (root / stderr_path).open("xb") as stream:
            stream.write(b"")
        report_bytes = (root / report_path).read_bytes()
        report_ref = {"path": report_path.as_posix(), "sha256": hashlib.sha256(report_bytes).hexdigest(), "bytes": len(report_bytes)}
        payload = {"schemaVersion": "agent-command-observation.v1",
                   "platform": {"os": {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()],
                                "architecture": platform.machine(), "pythonVersion": platform.python_version()},
                   "commands": [{"commandDigest": canonical_digest(producer["command"]), "status": "PASS", "exitCode": 0,
                                 "stdout": report_ref, "stderr": {"path": stderr_path.as_posix(), "bytes": 0,
                                                                "sha256": hashlib.sha256(b"").hexdigest()},
                                 "cases": [{"id": row["id"], "status": "PASS", "evidence": report_ref} for row in report["checks"]]}]}
        payload = _complete_payload(payload, supplemental, descriptor)
        receipt = {"schemaVersion": "agent-evidence-receipt.v1", "evidenceId": "EV216-ACCOUNTING-ENFORCEMENT",
                   "subject": subject, "producer": {"actorId": "P-FINAL-VALIDATOR", "sessionId": "profile-final-validator",
                                                     "guarantee": "DECLARED", "attestation": None},
                   "payload": payload, "payloadDigest": canonical_digest(payload)}
        receipt["receiptDigest"] = canonical_digest(receipt)
        validate_evidence_receipt_shape(receipt)
        _validate_evidence_references(root, receipt, descriptor=descriptor["validation"])
        if datetime.now(UTC) >= deadline:
            _fail("accounting-final-task-deadline-expired")
        write_json_create(output, receipt)
        return receipt
    finally:
        reader.close()

def emit_final_receipt(root: Path, manifest_path: Path, output: Path, *,
                       catalog: Path, profiles_root: Path,
                       state_path: str | None = None, run_id: str | None = None,
                       supplemental_path: str | None = None) -> dict:
    """Validate and emit with one composed two-snapshot boundary.

    A caller-supplied validation report cannot substitute for preparation.
    Standalone validation remains available as a nonaccepting diagnostic.
    """
    root = root.absolute()
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    catalog = catalog if catalog.is_absolute() else root / catalog
    profiles_root = profiles_root if profiles_root.is_absolute() else root / profiles_root
    output = output if output.is_absolute() else root / output
    report, first = _prepare_final_profiles(root, manifest_path, catalog, profiles_root,
                                           state_path=state_path, run_id=run_id)
    return _emit_prepared_final_receipt(
        root, manifest_path, report, output, profiles_root=profiles_root, first=first,
        state_path=state_path, run_id=run_id, supplemental_path=supplemental_path,
    )


def validate_catalog(repo_root: Path, manifest: Path, catalog: Path,
                     reader: BoundedReader | None = None) -> dict[str, Any]:
    """Match the supplied catalog to the selected frozen expectation, byte sources too."""
    root = repo_root.absolute()
    reader = reader if reader is not None else BoundedReader()
    relative_manifest = manifest.absolute().relative_to(root).as_posix()
    _json(_read(root, relative_manifest, ARTIFACT_BYTES, reader))
    expectation_path = manifest.parent / "h04-adapter-profile-cases.json"
    frozen = _json(_read(root, expectation_path.absolute().relative_to(root).as_posix(), ARTIFACT_BYTES, reader))
    selected = _json(_read(root, catalog.absolute().relative_to(root).as_posix(), PROFILE_BYTES, reader))
    expected = frozen["expectedBindings"]
    if selected != expected or set(selected) != {"schemaVersion", "status", "entries"}:
        _fail("accounting-catalog-expectation-mismatch")
    if selected["schemaVersion"] != "alk-accounting-expectations.v2" or selected["status"] != "EXPECTED_NOT_OBSERVED":
        _fail("accounting-catalog-status-invalid")
    entries = selected["entries"]
    if len(entries) != 12 or {x["adapterId"] for x in entries} != EXPECTED_ADAPTERS:
        _fail("accounting-catalog-inventory-mismatch")
    sources: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for source in entry["sources"]:
            ref = source["artifact"]
            if ref["path"] in sources and sources[ref["path"]] != ref:
                _fail("accounting-source-conflict")
            raw = _read(root, ref["path"], ARTIFACT_BYTES, reader)
            if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                _fail("accounting-source-digest-mismatch")
            sources[ref["path"]] = ref
    return {"catalogDigest": canonical_digest(selected), "entries": entries, "verifiedSourceCount": len(sources)}


def _check_selected_profile(root: Path, entry: dict[str, Any], ceilings: list[dict[str, Any]],
                            reader: BoundedReader) -> dict[str, Any]:
    adapter = entry["adapterId"]
    raw = _read(root, f"{adapter}/profile.json", PROFILE_BYTES, reader)
    envelope = _json(raw)
    if set(envelope) != {"schemaVersion", "payload", "profileDigest", "qualificationRef", "resolverEvidenceRef"}:
        _fail("accounting-profile-envelope-invalid")
    if envelope["schemaVersion"] != "alk-accounting-profile.v1":
        _fail("accounting-profile-envelope-invalid")
    payload = envelope["payload"]
    checked = validate_profile_payload(payload)
    if (
        envelope["profileDigest"] != checked["profileDigest"]
        or payload["expectationId"] != entry["expectationId"]
        or payload["binding"]["adapterId"] != adapter
        or payload["binding"]["hostVersion"] != entry["target"]["version"]
    ):
        _fail("accounting-profile-binding-mismatch")
    expected_roles = {route: route.split(".")[0] for route in entry["roleInventory"]}
    if {r["routeId"]: r["role"] for r in payload["routes"]} != expected_roles:
        _fail("accounting-profile-route-inventory-mismatch")
    source_cases = {r["sourceCaseId"]: r["sourceCaseSha256"] for r in entry["sourceCaseRequirements"]}
    if {r["sourceCaseId"]: r["sourceCaseSha256"] for r in payload["sourceCaseDispositions"]} != source_cases:
        _fail("accounting-profile-source-case-mismatch")
    allowed = ceilings + [c for r in entry["candidateRequirements"] for c in r["claimCeilings"]]
    if any(not any(all(claim[k] == ceiling[k] for k in _CEILING_KEYS) for ceiling in allowed)
           for claim in payload["claims"]):
        _fail("accounting-profile-claim-exceeds-ceiling")
    graph = EvidenceGraph(root, reader)
    qualification = graph.document(envelope["qualificationRef"])
    resolver = graph.document(envelope["resolverEvidenceRef"])
    for ref in _refs(envelope):
        graph.verify(ref)
    for document in (qualification, resolver):
        if (document.get("profileDigest"), document.get("expectationDigest")) != (
            checked["profileDigest"], canonical_digest(entry)
        ):
            _fail("accounting-profile-evidence-join-mismatch")
    dispositions = qualification.get("candidateDispositions")
    candidates = {c["candidateId"] for c in entry["candidateRequirements"]}
    if (not isinstance(dispositions, list) or any(not isinstance(d, dict) for d in dispositions)
        or len(dispositions) != len(candidates)
        or {d.get("candidateId") for d in dispositions} != candidates):
        _fail("accounting-profile-candidate-inventory-mismatch")
    if any(d.get("disposition") not in {"QUALIFIED_SUPPORTED", "QUALIFIED_LIMITATION", "REVIEWED_EXCLUSION"}
           for d in dispositions):
        _fail("accounting-profile-candidate-unresolved")
    # Labels such as ACCEPTED, PASS or QUALIFIED_SUPPORTED above are input data.
    # Origin/provenance, runtime and exact pre-dispatch proof need independent review.
    return {"adapterId": adapter, "inputStatus": "STRUCTURE_VALID_ONLY",
            "profileDigest": checked["profileDigest"], "verifiedRefs": len(graph.verified),
            "verifiedBytes": graph.bytes_read + len(raw),
            "qualificationStatus": "UNAVAILABLE", "dispatchEntitlement": False}


def validate_profiles(repo_root: Path, manifest: Path, catalog: Path, profiles_root: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    catalog_digest = None
    sources = 0
    repo_root = repo_root.absolute()
    manifest = manifest if manifest.is_absolute() else repo_root / manifest
    catalog = catalog if catalog.is_absolute() else repo_root / catalog
    reader = BoundedReader()
    try:
        catalog_check = validate_catalog(repo_root, manifest, catalog, reader)
        catalog_digest = catalog_check["catalogDigest"]
        sources = catalog_check["verifiedSourceCount"]
        if profiles_root is not None:
            if profiles_root.is_symlink():
                _fail("accounting-evidence-root-symlink")
            rules_path = manifest.parent / "h04-artifact-contracts.json"
            rules = _json(_read(repo_root, rules_path.absolute().relative_to(repo_root).as_posix(), ARTIFACT_BYTES, reader))
            for entry in catalog_check["entries"]:
                try:
                    checked = _check_selected_profile(profiles_root, entry, rules["baseAlkClaimCeilings"], reader)
                    checks.append(checked)
                except (LifecycleError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                    code = getattr(exc, "code", "accounting-profile-input-unavailable")
                    blockers.append({"adapterId": entry["adapterId"], "code": code})
                    checks.append({"adapterId": entry["adapterId"], "inputStatus": "FAIL", "qualificationStatus": "UNAVAILABLE"})
    except (LifecycleError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        blockers.append({"code": getattr(exc, "code", "accounting-catalog-input-unavailable")})
    return {"schemaVersion": "alk-accounting-profile-preflight.v1",
            "status": "FAIL" if blockers else "STRUCTURE_VALID_ONLY", "catalogDigest": catalog_digest,
            "verifiedSourceCount": sources, "checks": checks, "blockers": blockers,
            "readBudgetChargedBytes": reader.charged_bytes,
            "qualificationRequired": True, "acceptingReceipt": False, "dispatchEntitlement": False,
            "modelCallsStarted": False, "hostCommandsStarted": False, "releaseReady": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--catalog", type=Path, default=Path("profiles/accounting-adapter-capabilities.v1.json"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--catalog-only", action="store_true")
    mode.add_argument("--profiles-root", type=Path)
    parser.add_argument("--preflight", action="store_true", help="keep selected-profile input-only diagnostics")
    parser.add_argument("--evidence", type=Path, required=True, help="Create-only diagnostic or DECLARED final command witness")
    parser.add_argument("--state-file", help="Explicit separately authorized ordinary runtime state")
    parser.add_argument("--run-id", help="Exact identity of the explicitly selected runtime")
    parser.add_argument("--supplemental-payload", help="Preserved observations for the remaining shared evidence cases")
    args = parser.parse_args()
    if (args.state_file is None) != (args.run_id is None):
        parser.error("--state-file and --run-id must be supplied together")
    if args.profiles_root is not None and not args.preflight:
        root = args.repo_root.absolute()
        manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
        output = args.evidence if args.evidence.is_absolute() else root / args.evidence
        try:
            receipt = emit_final_receipt(root, manifest, output, catalog=args.catalog, profiles_root=args.profiles_root,
                                         state_path=args.state_file, run_id=args.run_id,
                                         supplemental_path=args.supplemental_payload)
            print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
            return 0
        except (LifecycleError, OSError, ValueError, KeyError, TypeError, RecursionError, StopIteration) as exc:
            report = _final_failure([], exc)
        write_json_create(Path(str(output) + ".diagnostic.json"), report)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 2
    report = validate_profiles(args.repo_root, args.manifest, args.catalog, args.profiles_root)
    write_json_create(args.evidence, report)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    # Catalog-only success establishes only the declared inventory and saved bytes.
    # The release selector must not mistake valid input shape for qualification.
    return (0 if report["status"] == "STRUCTURE_VALID_ONLY" else 1) if args.catalog_only else 2


if __name__ == "__main__":
    raise SystemExit(main())
