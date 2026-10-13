"""Offline profile input checks; fixtures never qualify an installed host."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import jsonschema
import tools.release.validate_accounting_adapter_profiles as profile_validator
from tools.release.validate_accounting_adapter_profiles import (
    BoundedReader,
    EvidenceGraph,
    _boundary_checks,
    _check_current_core,
    _check_resolver_observations,
    _read_current_run_state,
    emit_final_receipt,
    exact_qualification_mutations,
    exact_resolver_requests,
    validate_final_profiles,
    validate_profiles,
)

from agent_lifecycle.accounting.support_profiles import match_requested_claims
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.evidence_receipt_schemas import validate_evidence_receipt_shape

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "profiles/accounting-adapter-capabilities.v1.json"


class AccountingAdapterProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.manifest = self.root / "tasks/release-2-16/plan.manifest.json"
        self.catalog_path = self.root / "profiles/accounting-adapter-capabilities.v1.json"
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        self.catalog = json.loads(CATALOG.read_text())
        # Replace archived bytes only inside this disposable structural fixture.
        for entry in self.catalog["entries"]:
            for source in entry["sources"]:
                raw = json.dumps({"fixtureSourceId": source["sourceId"]}).encode()
                path = "saved/" + hashlib.sha256(raw).hexdigest() + ".json"
                self._put(self.root / path, raw)
                source["artifact"] = self._ref(path, raw)
        self._put(self.manifest, b"{}")
        self._json(self.manifest.parent / "h04-adapter-profile-cases.json", {"expectedBindings": self.catalog})
        self._json(self.manifest.parent / "h04-artifact-contracts.json", {"baseAlkClaimCeilings": []})
        self._json(self.catalog_path, self.catalog)

    @staticmethod
    def _put(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    @staticmethod
    def _ref(path: str, raw: bytes) -> dict:
        return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def _json(self, path: Path, value: dict) -> dict:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self._put(path, raw)
        return self._ref(path.relative_to(self.evidence_root).as_posix(), raw) if path.is_relative_to(self.evidence_root) else {}

    def _report(self, profiles: bool = False) -> dict:
        return validate_profiles(self.root, self.manifest, self.catalog_path, self.evidence_root if profiles else None)

    def _profile(self) -> tuple[dict, dict]:
        entry = self.catalog["entries"][0]
        adapter = entry["adapterId"]
        raw_ref = self._json(self.evidence_root / "raw.json", {"fixture": True})
        original = json.loads((REPO / "tests/accounting/fixtures/release_216_adapter_profiles.json").read_text())
        payload = copy.deepcopy(next(x for x in original["profiles"] if x["binding"]["adapterId"] == adapter))
        payload["expectationId"] = entry["expectationId"]
        payload["binding"]["hostVersion"] = entry["target"]["version"]
        payload["routes"] = [
            {"role": route.split(".")[0], "routeId": route, "state": "EXCLUDED", "claimIds": [],
             "sourceIds": ["synthetic-source"], "reason": "Synthetic input, no runtime qualification"}
            for route in entry["roleInventory"]
        ]
        payload["sources"] = [{"sourceId": "synthetic-source", "kind": "ALK_TEST", "origin": "fixture",
                               "artifact": raw_ref, "versionApplicability": "synthetic"}]
        for case in payload["sourceCaseDispositions"]:
            case["evidenceRefs"] = [raw_ref]
            case["routeIds"] = [entry["roleInventory"][0]]
        qualification = {"profileDigest": canonical_digest(payload), "expectationDigest": canonical_digest(entry),
                         "candidateDispositions": [
                             {"candidateId": c["candidateId"], "disposition": "REVIEWED_EXCLUSION"}
                             for c in entry["candidateRequirements"]
                         ], "verdict": "ACCEPTED", "status": "PASS"}
        qualifier_ref = self._json(self.evidence_root / f"{adapter}/qualification.json", qualification)
        resolver_ref = self._json(self.evidence_root / f"{adapter}/resolver-evidence.json",
                                  {"profileDigest": canonical_digest(payload), "expectationDigest": canonical_digest(entry),
                                   "status": "PASS", "dispatchEntitlement": True})
        profile = {"schemaVersion": "alk-accounting-profile.v1", "payload": payload,
                   "profileDigest": canonical_digest(payload), "qualificationRef": qualifier_ref,
                   "resolverEvidenceRef": resolver_ref}
        self._json(self.evidence_root / f"{adapter}/profile.json", profile)
        return profile, entry

    def test_exact_catalog_preserves_all_candidates_without_promotion(self) -> None:
        report = self._report()
        self.assertEqual(report["status"], "STRUCTURE_VALID_ONLY")
        self.assertEqual(len(self.catalog["entries"]), 12)
        self.assertGreater(report["verifiedSourceCount"], 12)
        self.assertFalse(report["acceptingReceipt"])
        self.assertFalse(report["dispatchEntitlement"])

    def test_catalog_tamper_duplicate_and_unknown_adapter_refuse(self) -> None:
        for mutate in (lambda c: c["entries"].pop(),
                       lambda c: c["entries"].append(copy.deepcopy(c["entries"][0])),
                       lambda c: c["entries"][0].update(adapterId="unknown"),
                       lambda c: c.update(status="QUALIFIED_SUPPORTED")):
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(self.catalog)
                mutate(changed)
                self._json(self.catalog_path, changed)
                self.assertEqual(self._report()["status"], "FAIL")

    def test_modified_saved_source_fails(self) -> None:
        ref = self.catalog["entries"][0]["sources"][0]["artifact"]
        (self.root / ref["path"]).write_bytes(b"replaced")
        self.assertEqual(self._report()["blockers"][0]["code"], "accounting-source-digest-mismatch")

    def test_missing_profiles_cannot_complete_release_validation(self) -> None:
        report = self._report(True)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(report["checks"]), 12)
        self.assertTrue(all(x["qualificationStatus"] == "UNAVAILABLE" for x in report["checks"]))
        self.assertFalse(report["releaseReady"])

    def test_supplied_positive_labels_never_become_qualification(self) -> None:
        self._profile()
        selected = self._report(True)["checks"][0]
        self.assertEqual(selected["inputStatus"], "STRUCTURE_VALID_ONLY")
        self.assertEqual(selected["qualificationStatus"], "UNAVAILABLE")
        self.assertFalse(selected["dispatchEntitlement"])

    def test_final_validator_refuses_synthetic_labels_without_frozen_core_and_reviews(self):
        self._profile()
        report = validate_final_profiles(self.root, self.manifest, self.catalog_path, self.evidence_root)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["acceptingReceipt"])
        self.assertFalse(report["dataCandidate"])

    def test_exact_resolver_matrix_checks_all_mutations_trace_and_dispatch(self):
        profile, _entry = self._profile()
        payload = profile["payload"]
        joins = {"profileDigest": profile["profileDigest"], "expectationDigest": "a" * 64,
                 "planDigest": "b" * 64, "alkCandidateDigest": "c" * 64, "binding": payload["binding"]}
        requests = exact_resolver_requests(payload, joins)
        contracts = json.loads((REPO / "tasks/release-2-16/h04-artifact-contracts.json").read_bytes())
        request_schema = {"$defs": contracts["$defs"], "$ref": "#/$defs/resolverRequest"}
        self.assertEqual(len(requests), 29)
        for case_id, request in requests.items():
            with self.subTest(request_schema_case=case_id):
                jsonschema.Draft202012Validator(request_schema).validate(request)
        qualification = {"alkCandidateDigest": joins["alkCandidateDigest"],
                         "reviewEvidenceRef": {"path": "review.json", "bytes": 1, "sha256": "f" * 64}}
        observations = []
        for case_id, request in requests.items():
            matched = match_requested_claims(payload, request, expectation_digest=joins["expectationDigest"],
                                             plan_digest=joins["planDigest"], candidate_digest=joins["alkCandidateDigest"])
            allowed = case_id == "supported"
            marker = canonical_digest({"invalidInput": True})
            self.assertTrue(case_id.startswith("artifact.") or allowed or matched["status"] == "MISMATCH")
            result = {"schemaVersion": "alk-accounting-capability-result.v1", "requestDigest": canonical_digest(request),
                      "profileDigest": marker if case_id.startswith("artifact.") else joins["profileDigest"],
                      "expectationDigest": marker if case_id.startswith("artifact.") else joins["expectationDigest"],
                      "outcome": "ALLOW_CAPABILITY" if allowed else "DENY",
                      "reason": "CAPABILITY_MATCH" if allowed else "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE",
                      "detail": "MATCH" if allowed else "UNQUALIFIED_EVIDENCE" if case_id.startswith("artifact.") else matched["detail"],
                      "matchedClaimIds": [], "dispatchEntitlement": False}
            observations.append({"caseId": case_id, "request": request, "result": result,
                                 "rawTraceRef": {"path": "trace.json", "bytes": 1, "sha256": "d" * 64},
                                 "alkOwnedDispatchCount": 0})
        trace = {"schemaVersion": "alk-accounting-resolver-trace.v1", "profileDigest": joins["profileDigest"],
                 "commandDigest": "e" * 64, "observations": [{k: v for k, v in row.items() if k != "rawTraceRef"} for row in observations],
                 "qualificationMutations": {case: {"originalQualificationDigest": canonical_digest(qualification),
                                                  "replacementJson": None if value is None else json.dumps(
                                                      value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}
                                            for case, value in exact_qualification_mutations(qualification, requests).items()}}
        item = {"payload": payload, "qualification": qualification, "joins": joins,
                "resolver": {"observations": observations, "commandDigest": "e" * 64},
                "resolverTraces": {"trace.json": trace}}
        _check_resolver_observations(item)
        self.assertIn("binding.evidenceMode", requests)
        for mutation in ("missing", "dispatch", "forged-result", "trace", "mutation-input", "unqualified-identity"):
            changed = copy.deepcopy(item)
            if mutation == "missing":
                changed["resolver"]["observations"].pop()
            elif mutation == "dispatch":
                changed["resolver"]["observations"][0]["alkOwnedDispatchCount"] = 1
            elif mutation == "forged-result":
                changed["resolver"]["observations"][1]["result"]["outcome"] = "ALLOW_CAPABILITY"
            elif mutation == "trace":
                changed["resolverTraces"]["trace.json"]["observations"].pop()
            elif mutation == "unqualified-identity":
                row = next(r for r in changed["resolver"]["observations"] if r["caseId"] == "artifact.missing")
                row["result"]["profileDigest"] = joins["profileDigest"]
                raw_row = next(r for r in changed["resolverTraces"]["trace.json"]["observations"]
                               if r["caseId"] == "artifact.missing")
                raw_row["result"]["profileDigest"] = joins["profileDigest"]
            else:
                changed["resolverTraces"]["trace.json"]["qualificationMutations"]["artifact.stale"]["replacementJson"] = "{}"
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError) as caught:
                _check_resolver_observations(changed)
            if mutation == "unqualified-identity":
                self.assertEqual(caught.exception.code, "accounting-exact-resolver-result-mismatch")

    def test_boundary_cases_require_explicit_limitation_and_closure_witnesses(self):
        profile, _entry = self._profile()
        adapters = {entry["adapterId"] for entry in self.catalog["entries"]}
        profiles = {adapter: {"payload": copy.deepcopy(profile["payload"]),
                              "qualification": {"observations": [{"usageStatus": "UNAVAILABLE", "usage": None}]}}
                    for adapter in adapters}
        frozen = json.loads((REPO / "tasks/release-2-16/h04-adapter-profile-cases.json").read_bytes())
        ids = [row["id"] for row in frozen["requiredCases"]]
        core = {"caseIds": ["accounting.core.task-run-closeout", "accounting.core.ac13"]}
        rows = _boundary_checks(profiles, core, ids)
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["validatedPredicates"] for row in rows))
        for mutation in ("financial", "zero-usage", "missing-core", "missing-profile", "unknown-oracle"):
            changed, changed_core, changed_ids = copy.deepcopy(profiles), copy.deepcopy(core), list(ids)
            if mutation == "financial":
                changed["codex"]["payload"]["completeFinancialRun"] = True
            elif mutation == "zero-usage":
                changed["codex"]["qualification"]["observations"][0]["usage"] = 0
            elif mutation == "missing-core":
                changed_core["caseIds"].pop()
            elif mutation == "missing-profile":
                changed.pop("codex")
            else:
                changed_ids[-1] = "invented"
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                _boundary_checks(changed, changed_core, changed_ids)

    def emitter_fixture(self):
        """Shape-only fixture; Git source and actual publication remain explicit doubles."""
        frozen = json.loads((REPO / "tasks/release-2-16/h04-adapter-profile-cases.json").read_bytes())
        self._json(self.manifest.parent / "h04-adapter-profile-cases.json", frozen)
        contracts = json.loads((REPO / "tasks/release-2-16/h04-artifact-contracts.json").read_bytes())
        self._json(self.manifest.parent / "h04-artifact-contracts.json", contracts)
        output = self.root / "work/ev216-accounting-enforcement.json"
        manifest = {"orchestration": {"stateFile": "work/state.json"}, "acceptance": {"evidence": [{
            "id": "EV216-ACCOUNTING-ENFORCEMENT", "artifactPath": output.relative_to(self.root).as_posix(), "validation": {}}]}}
        manifest["acceptance"]["evidence"][0]["validation"] = {"requirements": {
            "caseIds": [r["id"] for r in frozen["requiredCases"]],
            "commandDigests": [canonical_digest(next(p for p in contracts["producers"] if p["id"] == "P-FINAL-VALIDATOR")["command"])]}}
        self._json(self.manifest, manifest)
        task = {"id": "WS216-02", "status": "RUNNING", "attempt": 1, "attemptDeadlineAt": "2999-01-01T00:00:00Z",
                "writes": ["src/"], "artifactPaths": {"result": "work/result-{attempt}.json"}}
        state = {"planDigest": canonical_digest(manifest), "runId": "synthetic-run", "sourceRevision": "base",
                 "runDeadlineAt": "2999-01-01T00:00:00Z", "tasks": [task]}
        self._json(self.root / "work/state.json", state)
        snapshot = {"changedFiles": [], "provider": "git-worktree-v2", "baselineSha": "e" * 40,
                    "fileSetHash": "a" * 64, "diffHash": "b" * 64, "snapshotHash": "c" * 64}
        result = {"planDigest": state["planDigest"], "runId": state["runId"], "taskId": task["id"], "attempt": 1,
                  "changedFiles": [], "changeSet": {"schemaVersion": "agent-task-change-set-claim.v1",
                                                     **{key: value for key, value in snapshot.items() if key != "changedFiles"}}}
        self._put(self.root / "work/result-1.json", canonical_bytes(result) + b"\n")
        subject = copy.deepcopy(json.loads((REPO / "tests/audit/fixtures/release_216_evidence_contracts.json").read_bytes())["receipt"]["subject"])
        subject.update(planDigest=state["planDigest"])
        subject["taskBindings"][0].update(taskId=task["id"], snapshotHash=snapshot["snapshotHash"])
        refs = [self._ref(path, (self.root / path).read_bytes()) for path in (
            "tasks/release-2-16/plan.manifest.json", "tasks/release-2-16/h04-artifact-contracts.json",
            "tasks/release-2-16/h04-adapter-profile-cases.json", "work/state.json")]
        report = {"status": "PASS", "checks": [{"id": r["id"], "status": "PASS"} for r in frozen["requiredCases"]],
                  "inputRefs": refs, "ordinaryReviews": [["shape-only", "d" * 64]], "readBudgetChargedBytes": 100,
                  "sourceComponents": [{k: c[k] for k in ("id", "commitOid", "contentDigest")} for c in subject["components"]]}
        verified = {"reportSha256": "d" * 64, "assurance": "PROCEDURAL_SAME_ACCOUNT", "nativeAllowed": False}
        return output, report, snapshot, subject, verified

    def test_declared_emitter_checks_shape_exact_case_inventory_and_current_inputs(self):
        module = "tools.release.validate_accounting_adapter_profiles"
        for mutation in ("none", "snapshot", "input", "origin", "subject", "path", "duplicate-case", "deadline",
                         "late", "contract-change", "changed-result", "budget", "noncanonical-result", "run-deadline",
                         "producer-aba", "missing-contract-ref", "duplicate-contract-ref"):
            # Each branch gets new output paths; rejected branches must write none.
            output, report, snapshot, subject, verified = self.emitter_fixture()
            contracts_path = self.manifest.parent / "h04-artifact-contracts.json"
            original_contracts_raw = contracts_path.read_bytes()
            if mutation == "none":
                output.parent.mkdir(exist_ok=True)
                for existing in output.parent.glob(output.name + "*"):
                    existing.unlink()
            elif mutation == "snapshot":
                snapshot["diffHash"] = "0" * 64
            elif mutation == "input":
                (self.manifest.parent / "h04-artifact-contracts.json").write_bytes(b"{}")
            elif mutation == "origin":
                verified["reportSha256"] = "0" * 64
            elif mutation == "subject":
                subject["components"][0]["contentDigest"] = "0" * 64
            elif mutation == "path":
                output = output.parent / "other.json"
            elif mutation == "duplicate-case":
                report["checks"][-1] = report["checks"][0]
            elif mutation in {"deadline", "run-deadline"}:
                state = json.loads((self.root / "work/state.json").read_bytes())
                if mutation == "deadline":
                    state["tasks"][0]["attemptDeadlineAt"] = "2000-01-01T00:00:00Z"
                else:
                    state["runDeadlineAt"] = "2000-01-01T00:00:00Z"
                self._json(self.root / "work/state.json", state)
            elif mutation == "budget":
                total = sum(r["bytes"] for r in report["inputRefs"]) + (self.root / "work/result-1.json").stat().st_size
                report["readBudgetChargedBytes"] = 25_165_824 - 2 * total + 1
            elif mutation == "noncanonical-result":
                result_path = self.root / "work/result-1.json"
                result_path.write_text(json.dumps(json.loads(result_path.read_bytes()), indent=2))
            elif mutation == "producer-aba":
                contracts = json.loads(original_contracts_raw)
                producer = next(p for p in contracts["producers"] if p["id"] == "P-FINAL-VALIDATOR")
                producer["command"] += " --unvalidated-producer"
                self._json(contracts_path, contracts)
            elif mutation == "missing-contract-ref":
                report["inputRefs"] = [r for r in report["inputRefs"] if not r["path"].endswith("h04-artifact-contracts.json")]
            elif mutation == "duplicate-contract-ref":
                report["inputRefs"].append(next(r for r in report["inputRefs"] if r["path"].endswith("h04-artifact-contracts.json")))
            def make_subject(_root, _state, _task, identity, *_args, subject=subject):
                subject["taskBindings"][0]["resultDigest"] = identity["sha256"]
                return subject
            def verify(*_args, mutation=mutation, verified=verified, original_contracts_raw=original_contracts_raw,
                       contracts_path=contracts_path, **_kwargs):
                if mutation == "contract-change":
                    path = self.manifest.parent / "h04-artifact-contracts.json"
                    value = json.loads(path.read_bytes())
                    value["changedAfterProducerSelection"] = True
                    self._json(path, value)
                elif mutation == "changed-result":
                    path = self.root / "work/result-1.json"
                    value = json.loads(path.read_bytes())
                    value["changedDuringOriginVerification"] = True
                    self._put(path, canonical_bytes(value) + b"\n")
                elif mutation == "producer-aba":
                    self._put(contracts_path, original_contracts_raw)
                return verified
            with self.subTest(mutation=mutation), patch(module + ".capture_task_change_set", return_value=snapshot), \
                    patch(module + "._expected_task_evidence_subject", side_effect=make_subject), \
                    patch(module + ".verify_area_report", side_effect=verify) as origin, \
                    patch(module + "._validate_evidence_references"), patch(module + ".datetime") as clock:
                clock.fromisoformat.side_effect = datetime.fromisoformat
                clock.now.return_value = datetime(2026, 1, 1, tzinfo=UTC)
                if mutation == "late":
                    clock.now.side_effect = [datetime(2026, 1, 1, tzinfo=UTC), datetime(3000, 1, 1, tzinfo=UTC)]
                if mutation == "none":
                    receipt = emit_final_receipt(self.root, self.manifest, report, output)
                    self.assertEqual(validate_evidence_receipt_shape(receipt), receipt)
                    self.assertEqual(receipt["producer"]["guarantee"], "DECLARED")
                    self.assertEqual(len(receipt["payload"]["commands"][0]["cases"]), 21)
                    self.assertEqual(receipt["subject"]["taskBindings"][0]["resultDigest"],
                                     canonical_digest(json.loads((self.root / "work/result-1.json").read_bytes())))
                    for existing in output.parent.glob(output.name + "*"):
                        existing.unlink()
                else:
                    with self.assertRaises((LifecycleError, KeyError)):
                        emit_final_receipt(self.root, self.manifest, report, output)
                    self.assertFalse(output.exists())
                    if mutation in {"producer-aba", "missing-contract-ref", "duplicate-contract-ref"}:
                        origin.assert_not_called()

    def ordinary_route_fixture(self):
        dispatch_path = "tasks/release-2-16/ordinary-release-dispatch-r89.json"
        contract_path = "tasks/release-2-16/ordinary-release-contract-r89.md"
        manifest = {"planRevision": 89, "planFiles": [dispatch_path, contract_path],
                    "runtimePolicy": {"remainingWorkR88": {
                        "dispatchContract": dispatch_path, "contract": contract_path}},
                    "budgets": {"stateFile": "work/current-state.json", "eventLog": "work/current-events.jsonl"},
                    "orchestration": {"stateFile": "work/absent-old-state.json"}}
        dispatch = {"schemaVersion": "alk-ordinary-release-dispatch.v1", "revision": 89,
                    "contractPath": contract_path, **manifest["budgets"],
                    "workspace": str(self.root), "runId": "current-run"}
        self._json(self.root / dispatch_path, dispatch)
        self._put(self.root / contract_path, b"Selected ordinary release contract.\n")
        lock = {"schemaVersion": "agent-plan-lock.v2", "manifestHash": canonical_digest(manifest),
                "planRevision": 89, "entries": [self._ref(path, (self.root / path).read_bytes())
                                               for path in (dispatch_path, contract_path)]}
        self._json(self.manifest.parent / "plan.lock.json", lock)
        state = {"planDigest": canonical_digest(manifest), "planRevision": 89, "runId": "current-run"}
        self._json(self.root / manifest["budgets"]["stateFile"], state)
        return manifest, dispatch, lock, state

    def test_legacy_route_rejects_explicit_selectors_and_preserves_default(self):
        manifest = {"orchestration": {"stateFile": "work/legacy-state.json"}}
        state = {"runId": "legacy-run"}
        self._json(self.root / "work/legacy-state.json", state)
        with closing(BoundedReader()) as reader:
            self.assertEqual(_read_current_run_state(self.root, manifest, reader), state)
            self.assertEqual({ref["path"] for ref in reader.snapshot_refs(self.root)},
                             {"work/legacy-state.json"})
        for state_path, run_id, expected_code in (
                ("work/selected-state.json", "selected-run",
                 "accounting-current-runtime-selector-unsupported"),
                ("work/selected-state.json", None,
                 "accounting-current-runtime-selector-incomplete"),
                (None, "selected-run", "accounting-current-runtime-selector-incomplete")):
            with self.subTest(state_path=state_path, run_id=run_id), closing(BoundedReader()) as reader:
                with self.assertRaises(LifecycleError) as raised:
                    _read_current_run_state(self.root, manifest, reader,
                                            state_path=state_path, run_id=run_id)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertFalse(reader.snapshot_refs(self.root))

    def test_frozen_ordinary_route_reads_current_state_without_old_state_alias(self):
        manifest, _, _, state = self.ordinary_route_fixture()
        with closing(BoundedReader()) as reader:
            self.assertEqual(_read_current_run_state(self.root, manifest, reader), state)
            paths = {ref["path"] for ref in reader.snapshot_refs(self.root)}
        self.assertIn("work/current-state.json", paths)
        self.assertNotIn("work/absent-old-state.json", paths)
        self.assertFalse((self.root / "work/absent-old-state.json").exists())

    def test_selected_ordinary_route_refuses_changed_frozen_dispatch_or_contract(self):
        for path_kind in ("dispatchContract", "contract"):
            with self.subTest(path_kind=path_kind):
                manifest, _, _, _ = self.ordinary_route_fixture()
                path = manifest["runtimePolicy"]["remainingWorkR88"][path_kind]
                self._put(self.root / path, (self.root / path).read_bytes() + b" ")
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError) as raised:
                    _read_current_run_state(self.root, manifest, reader)
                self.assertEqual(raised.exception.code, "accounting-current-route-artifact-mismatch")

    def test_selected_ordinary_route_never_falls_back_on_binding_or_lock_mismatch(self):
        for route in ({}, None, {"dispatchContract": None}, {"dispatchContract": 1, "contract": "x"}):
            with self.subTest(route=route):
                manifest, _, _, _ = self.ordinary_route_fixture()
                manifest["runtimePolicy"]["remainingWorkR88"] = route
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError) as raised:
                    _read_current_run_state(self.root, manifest, reader)
                self.assertEqual(raised.exception.code, "accounting-current-route-binding-mismatch")
        for field, value in (("revision", 88), ("stateFile", "work/old-state.json"),
                             ("eventLog", "work/old-events.jsonl"), ("workspace", "/wrong-root"),
                             ("contractPath", "tasks/release-2-16/wrong-contract.md"),
                             ("schemaVersion", "unknown-route")):
            with self.subTest(field=field):
                manifest, dispatch, lock, _ = self.ordinary_route_fixture()
                dispatch[field] = value
                path = manifest["runtimePolicy"]["remainingWorkR88"]["dispatchContract"]
                self._json(self.root / path, dispatch)
                lock["entries"][0] = self._ref(path, (self.root / path).read_bytes())
                self._json(self.manifest.parent / "plan.lock.json", lock)
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError) as raised:
                    _read_current_run_state(self.root, manifest, reader)
                self.assertEqual(raised.exception.code, "accounting-current-route-binding-mismatch")
        manifest, _, lock, _ = self.ordinary_route_fixture()
        lock["manifestHash"] = "0" * 64
        self._json(self.manifest.parent / "plan.lock.json", lock)
        with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError) as raised:
            _read_current_run_state(self.root, manifest, reader)
        self.assertEqual(raised.exception.code, "accounting-current-route-lock-mismatch")

    def test_selected_ordinary_route_refuses_other_run_or_plan(self):
        for field, value in (("runId", "old-run"), ("planRevision", 88), ("planDigest", "0" * 64)):
            with self.subTest(field=field):
                manifest, _, _, state = self.ordinary_route_fixture()
                state[field] = value
                self._json(self.root / manifest["budgets"]["stateFile"], state)
                with closing(BoundedReader()) as reader, self.assertRaises(LifecycleError) as raised:
                    _read_current_run_state(self.root, manifest, reader)
                self.assertEqual(raised.exception.code, "accounting-current-route-state-mismatch")

    def test_core_result_uses_existing_canonical_workflow_identity(self):
        frozen_manifest = json.loads((REPO / "tasks/release-2-16/plan.manifest.json").read_bytes())
        descriptor = next(e for e in frozen_manifest["acceptance"]["evidence"] if e["id"] == "EV216-ACCOUNTING-CORE")
        manifest = {"orchestration": {"stateFile": "work/state.json"}, "acceptance": {"evidence": [descriptor]}}
        manifest["workstreams"] = [{"id": "WS216-04", "evidenceIds": [descriptor["id"]]}]
        result = {"syntheticCanonicalIdentityFixture": True}
        raw = canonical_bytes(result) + b"\n"
        self._put(self.root / "work/core-result.json", raw)
        ref = {"path": "work/core-result.json", "bytes": len(raw), "sha256": canonical_digest(result)}
        self.assertNotEqual(ref["sha256"], hashlib.sha256(raw).hexdigest())
        task = {"id": "WS216-04", "status": "ACCEPTED", "result": ref, "resultChangeSetEvidence": {}}
        state = {"planDigest": canonical_digest(manifest), "tasks": [task]}
        self._json(self.root / "work/state.json", state)
        receipt = copy.deepcopy(json.loads((REPO / "tests/audit/fixtures/release_216_evidence_contracts.json").read_bytes())["receipt"])
        receipt["evidenceId"] = descriptor["id"]
        receipt["payload"]["commands"][0]["cases"] = [
            {"id": case_id, "status": "PASS", "evidence": self._ref("synthetic-proof.txt", b"x")}
            for case_id in descriptor["validation"]["requirements"]["caseIds"]]
        receipt["payloadDigest"] = canonical_digest(receipt["payload"])
        receipt["receiptDigest"] = canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"})
        self._json(self.root / descriptor["artifactPath"], receipt)
        accepted_double = {"suppliedEvidence": [{"evidenceId": descriptor["id"], "validationStatus": "PASS"}]}
        with patch("tools.release.validate_accounting_adapter_profiles.validate_task_evidence_paths", return_value=accepted_double):
            reader = BoundedReader()
            self.addCleanup(reader.close)
            self.assertEqual(len(_check_current_core(self.root, manifest, reader)["caseIds"]), 27)
            task["result"]["sha256"] = hashlib.sha256(raw).hexdigest()
            self._json(self.root / "work/state.json", state)
            reader = BoundedReader()
            self.addCleanup(reader.close)
            with self.assertRaises(LifecycleError):
                _check_current_core(self.root, manifest, reader)

    def test_explicit_runtime_selector_preserves_old_state_and_refuses_wrong_join(self):
        manifest, _, _, old = self.ordinary_route_fixture()
        selected = {**old, "runId": "separately-approved-run"}
        self._json(self.root / "work/selected-state.json", selected)
        original = (self.root / "work/current-state.json").read_bytes()
        with closing(BoundedReader()) as reader:
            actual = _read_current_run_state(self.root, manifest, reader,
                                            state_path="work/selected-state.json", run_id=selected["runId"])
            self.assertEqual(actual, selected)
            self.assertNotIn("work/current-state.json", {r["path"] for r in reader.snapshot_refs(self.root)})
        self.assertEqual((self.root / "work/current-state.json").read_bytes(), original)
        for path, run in [("work/selected-state.json", "wrong"), ("../outside.json", selected["runId"]),
                          ("work/selected-state.json", None)]:
            with self.subTest(path=path, run=run), closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
                _read_current_run_state(self.root, manifest, reader, state_path=path, run_id=run)

    def test_current_owner_core_uses_prepared_result_without_accepting_task(self):
        _output, _report, snapshot, _subject, _verified = self.emitter_fixture()
        frozen = json.loads((REPO / "tasks/release-2-16/plan.manifest.json").read_bytes())
        descriptor = next(e for e in frozen["acceptance"]["evidence"] if e["id"] == "EV216-ACCOUNTING-CORE")
        manifest = json.loads(self.manifest.read_bytes())
        manifest["acceptance"]["evidence"] = [descriptor]
        manifest["workstreams"] = [{"id": "WS216-02", "evidenceIds": [descriptor["id"]]}, {"id": "WS216-03", "evidenceIds": []}]
        state = json.loads((self.root / "work/state.json").read_bytes())
        state["planDigest"] = canonical_digest(manifest)
        result_path = self.root / "work/result-1.json"
        result = json.loads(result_path.read_bytes()); result["planDigest"] = state["planDigest"]
        self._json(self.manifest, manifest); self._json(self.root / "work/state.json", state)
        self._put(result_path, canonical_bytes(result) + b"\n")
        receipt = copy.deepcopy(json.loads((REPO / "tests/audit/fixtures/release_216_evidence_contracts.json").read_bytes())["receipt"])
        receipt["evidenceId"] = descriptor["id"]
        receipt["payload"]["commands"][0]["cases"] = [
            {"id": c, "status": "PASS", "evidence": self._ref("synthetic-proof.txt", b"x")}
            for c in descriptor["validation"]["requirements"]["caseIds"]]
        receipt["payloadDigest"] = canonical_digest(receipt["payload"])
        receipt["receiptDigest"] = canonical_digest({k: v for k, v in receipt.items() if k != "receiptDigest"})
        self._json(self.root / descriptor["artifactPath"], receipt)
        module = "tools.release.validate_accounting_adapter_profiles"
        accepted = {"suppliedEvidence": [{"evidenceId": descriptor["id"], "validationStatus": "PASS"}]}
        with patch(module + ".capture_task_change_set", return_value=snapshot), \
                patch(module + ".validate_task_evidence_paths", return_value=accepted) as check, closing(BoundedReader()) as reader:
            self.assertEqual(len(_check_current_core(self.root, manifest, reader)["caseIds"]), 27)
            self.assertEqual(check.call_args.args[4]["sha256"], canonical_digest(result))
        self.assertEqual(json.loads((self.root / "work/state.json").read_bytes())["tasks"][0]["status"], "RUNNING")
        result["runId"] = "other-run"; self._put(result_path, canonical_bytes(result) + b"\n")
        with patch(module + ".capture_task_change_set", return_value=snapshot), closing(BoundedReader()) as reader, self.assertRaises(LifecycleError):
            _check_current_core(self.root, manifest, reader)

    def test_shared_payload_requires_all_85_cases_and_five_commands(self):
        manifest = json.loads((REPO / "tasks/release-2-16/plan.manifest.json").read_bytes())
        descriptor = next(e for e in manifest["acceptance"]["evidence"] if e["id"] == "EV216-ACCOUNTING-ENFORCEMENT")
        required = descriptor["validation"]["requirements"]
        commands = [{"commandDigest": d, "status": "PASS", "exitCode": 0, "cases": []} for d in required["commandDigests"]]
        for i, cid in enumerate(required["caseIds"]): commands[i % len(commands)]["cases"].append({"id": cid, "status": "PASS"})
        base = {"schemaVersion": "agent-command-observation.v1", "platform": {"os": "macos"}, "commands": commands[:1]}
        extra = {**base, "commands": commands[1:]}
        combined = profile_validator._complete_payload(base, extra, descriptor)
        self.assertEqual(sum(len(c["cases"]) for c in combined["commands"]), 85)
        self.assertEqual(len(combined["commands"]), 5)
        for mutation in [None, {**extra, "commands": commands[1:-1]}, {**extra, "commands": commands},
                         {**extra, "platform": {"os": "linux"}}]:
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                profile_validator._complete_payload(base, mutation, descriptor)

    def test_wrong_profile_binding_and_join_refuse(self) -> None:
        profile, entry = self._profile()
        path = self.evidence_root / f"{entry['adapterId']}/profile.json"
        profile["payload"]["binding"]["hostVersion"] = "different"
        profile["profileDigest"] = canonical_digest(profile["payload"])
        self._json(path, profile)
        report = self._report(True)
        self.assertEqual(report["checks"][0]["inputStatus"], "FAIL")
        self.assertEqual(report["blockers"][0]["code"], "accounting-profile-binding-mismatch")
        profile, entry = self._profile()
        profile["qualificationRef"] = self._json(self.evidence_root / "wrong.json",
                                                {"profileDigest": "0" * 64, "expectationDigest": canonical_digest(entry)})
        self._json(path, profile)
        self.assertEqual(self._report(True)["blockers"][0]["code"], "accounting-profile-evidence-join-mismatch")

    def test_graph_escape_symlink_digest_and_boolean_size_refuse(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_bytes(b"private")
        (self.evidence_root / "link.txt").symlink_to(outside)
        for ref in [self._ref("../outside.txt", b"private"), self._ref(str(outside), b"private"),
                    self._ref("link.txt", b"private"),
                    {"path": "missing.txt", "sha256": "0" * 64, "bytes": True}]:
            with self.subTest(ref=ref), self.assertRaises(LifecycleError):
                EvidenceGraph(self.evidence_root).verify(ref)
        good = self._json(self.evidence_root / "raw.json", {"source": True})
        good["sha256"] = "0" * 64
        with self.assertRaises(LifecycleError):
            EvidenceGraph(self.evidence_root).verify(good)

    def test_reference_count_and_duplicate_json_keys_refuse(self) -> None:
        graph = EvidenceGraph(self.evidence_root)
        for i in range(64):
            graph.verify(self._json(self.evidence_root / f"{i}.json", {"i": i}))
        with self.assertRaises(LifecycleError):
            graph.verify(self._json(self.evidence_root / "overflow.json", {"overflow": True}))
        raw = b'{"verdict":"BLOCKED","verdict":"ACCEPTED"}'
        self._put(self.evidence_root / "duplicate.json", raw)
        with self.assertRaises(LifecycleError):
            EvidenceGraph(self.evidence_root).verify(self._ref("duplicate.json", raw))

    def test_cli_catalog_success_and_release_selector_nonzero(self) -> None:
        script = REPO / "tools/release/validate_accounting_adapter_profiles.py"
        for mode, code in [(["--catalog-only"], 0), (["--profiles-root", str(self.evidence_root), "--preflight"], 2),
                           (["--profiles-root", str(self.evidence_root)], 2)]:
            with self.subTest(mode=mode):
                out = self.root / f"diagnostic-{code}-{'preflight' if '--preflight' in mode else 'final'}.json"
                run = subprocess.run([sys.executable, str(script), "--repo-root", str(self.root),
                                      "--manifest", str(self.manifest), "--catalog", str(self.catalog_path),
                                      "--evidence", str(out), *mode], cwd=REPO, capture_output=True, text=True, check=False)
                self.assertEqual(run.returncode, code, run.stderr)
                if "--profiles-root" in mode and "--preflight" not in mode:
                    self.assertFalse(out.exists())
                    diagnostic = Path(str(out) + ".diagnostic.json")
                    self.assertFalse(json.loads(diagnostic.read_text())["dataCandidate"])
                else:
                    diagnostic = out
                self.assertFalse(json.loads(diagnostic.read_text())["acceptingReceipt"])

    def test_directory_swap_cannot_redirect_held_parent_leaf(self) -> None:
        original = b"inside"
        self._put(self.evidence_root / "nested/leaf.txt", original)
        outside = self.root / "outside"
        self._put(outside / "leaf.txt", b"outside")
        real_open = os.open
        swapped = False

        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "leaf.txt" and not swapped:
                (self.evidence_root / "nested").rename(self.evidence_root / "held")
                (self.evidence_root / "nested").symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        supported = os.supports_dir_fd | {swapping_open}
        with patch.object(os, "supports_dir_fd", supported), patch.object(os, "open", swapping_open):
            raw = BoundedReader().read(self.evidence_root, "nested/leaf.txt", 100)
        self.assertTrue(swapped)
        self.assertEqual(raw, original)

    def test_document_interpretation_uses_verified_snapshot_after_replacement(self) -> None:
        ref = self._json(self.evidence_root / "qualification.json", {"profileDigest": "original"})
        graph = EvidenceGraph(self.evidence_root)
        graph.verify(ref)
        self._json(self.evidence_root / "qualification.json", {"profileDigest": "replacement"})
        self.assertEqual(graph.document(ref)["profileDigest"], "original")

    def test_known_json_with_other_extension_still_traverses_refs(self) -> None:
        child = self._ref("../outside.json", b"{}")
        ref = self._json(self.evidence_root / "qualification.json.txt", {"rawEvidenceRef": child})
        graph = EvidenceGraph(self.evidence_root)
        with self.assertRaises(LifecycleError):
            graph.document(ref)

    def test_shared_budget_retains_failed_read_and_caches_duplicate(self) -> None:
        raw = b"123456"
        self._put(self.evidence_root / "first.txt", raw)
        self._put(self.evidence_root / "second.txt", raw)
        reader = BoundedReader(10)
        wrong = self._ref("first.txt", raw)
        wrong["sha256"] = "0" * 64
        with self.assertRaises(LifecycleError):
            EvidenceGraph(self.evidence_root, reader).verify(wrong)
        self.assertEqual(reader.charged_bytes, 6)
        EvidenceGraph(self.evidence_root, reader).verify(self._ref("first.txt", raw))
        self.assertEqual(reader.charged_bytes, 6)
        with self.assertRaises(LifecycleError):
            EvidenceGraph(self.evidence_root, reader).verify(self._ref("second.txt", raw))
        self.assertEqual(reader.charged_bytes, 6)
        self.assertNotIn((str(self.evidence_root.resolve()), "second.txt"), reader.cache)

    def test_cached_subtree_depth_is_checked_from_deeper_root(self) -> None:
        refs = [self._json(self.evidence_root / "depth-0.json", {"leaf": True})]
        for i in range(1, 10):
            refs.append(self._json(self.evidence_root / f"depth-{i}.json", {"child": refs[-1]}))
        graph = EvidenceGraph(self.evidence_root)
        graph.verify(refs[2])
        graph.verify(refs[8])
        with self.assertRaises(LifecycleError):
            graph.verify(refs[9])

    def test_swapped_route_roles_refuse_even_with_same_role_inventory(self) -> None:
        profile, entry = self._profile()
        routes = profile["payload"]["routes"]
        worker = next(r for r in routes if r["role"] == "worker")
        checker = next(r for r in routes if r["role"] == "check")
        worker["role"], checker["role"] = checker["role"], worker["role"]
        profile["profileDigest"] = canonical_digest(profile["payload"])
        self._json(self.evidence_root / f"{entry['adapterId']}/profile.json", profile)
        self.assertEqual(self._report(True)["blockers"][0]["code"], "accounting-profile-route-inventory-mismatch")

    def test_null_and_scalar_candidate_dispositions_fail_with_diagnostic(self) -> None:
        for value in (None, 42, "invalid", False):
            with self.subTest(value=value):
                profile, entry = self._profile()
                path = self.evidence_root / f"{entry['adapterId']}/qualification.json"
                qualification = json.loads(path.read_text())
                qualification["candidateDispositions"][0] = value
                profile["qualificationRef"] = self._json(path, qualification)
                self._json(self.evidence_root / f"{entry['adapterId']}/profile.json", profile)
                self.assertEqual(self._report(True)["blockers"][0]["code"], "accounting-profile-candidate-inventory-mismatch")

    def test_nonstandard_json_constants_refuse(self) -> None:
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(constant=constant):
                raw = b'{"value":' + constant + b'}'
                self._put(self.evidence_root / "invalid.json", raw)
                with self.assertRaises(LifecycleError):
                    EvidenceGraph(self.evidence_root).verify(self._ref("invalid.json", raw))

    def test_root_replacement_after_initial_check_refuses_outside_read(self) -> None:
        graph = EvidenceGraph(self.evidence_root)
        raw = b"outside"
        outside = self.root / "outside-root"
        self._put(outside / "value.txt", raw)
        self.evidence_root.rename(self.root / "original-root")
        self.evidence_root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            graph.verify(self._ref("value.txt", raw))
        self.assertEqual(graph.reader.charged_bytes, 0)

    def test_opaque_document_uses_pinned_bytes_after_root_rebinding(self) -> None:
        original = self._json(self.evidence_root / "resolver.txt", {"bound": "original"})
        graph = EvidenceGraph(self.evidence_root)
        graph.verify(original)
        self.evidence_root.rename(self.root / "held-root")
        outside = self.root / "replacement-root"
        self._json(outside / "resolver.txt", {"bound": "replacement"})
        self.evidence_root.symlink_to(outside, target_is_directory=True)
        self.assertEqual(graph.document(original), {"bound": "original"})
        # A new path still uses the held original root rather than resolving the
        # replacement, and an opaque document never needs a second read.
        (self.root / "held-root/new.txt").write_bytes(b"inside")
        (outside / "new.txt").write_bytes(b"outside")
        graph.verify(self._ref("new.txt", b"inside"))
        self.assertEqual(graph.raw_bytes["new.txt"], b"inside")

    def test_growth_during_read_cannot_consume_more_than_reserved_bytes(self) -> None:
        path = self.evidence_root / "growing.txt"
        path.write_bytes(b"before")
        real_fdopen = os.fdopen
        consumed = []
        buffer_modes = []

        class GrowDuringRead:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def fileno(self):
                return self.stream.fileno()

            def read(self, size):
                with path.open("ab") as writer:
                    writer.write(b"x" * 16_384)
                raw = self.stream.read(size)
                underlying = getattr(self.stream, "raw", self.stream)
                consumed.append(underlying.tell())
                return raw

        def growing_fdopen(*args, **kwargs):
            buffer_modes.append(kwargs.get("buffering"))
            return GrowDuringRead(real_fdopen(*args, **kwargs))

        reader = BoundedReader(6)
        with patch.object(os, "fdopen", growing_fdopen), self.assertRaises(LifecycleError):
            reader.read(self.evidence_root, "growing.txt", 100_000)
        self.assertEqual(buffer_modes, [0])
        self.assertEqual(consumed, [6])
        self.assertEqual(reader.charged_bytes, 6)

    def test_failed_json_graph_cannot_pass_repeated_verification(self) -> None:
        for raw in (b'{"value":NaN}', b'[]', b'{"unfinished":'):
            with self.subTest(raw=raw):
                self._put(self.evidence_root / "refused.json", raw)
                ref = self._ref("refused.json", raw)
                graph = EvidenceGraph(self.evidence_root)
                with self.assertRaises(LifecycleError):
                    graph.verify(ref)
                charged = graph.reader.charged_bytes
                with self.assertRaises(LifecycleError):
                    graph.verify(ref)
                self.assertEqual(graph.reader.charged_bytes, charged)


if __name__ == "__main__":
    unittest.main()
