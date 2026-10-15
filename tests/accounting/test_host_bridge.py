"""Actual ALK refusal boundaries; synthetic profiles never qualify a host."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from agent_lifecycle.accounting.contracts import digest
from agent_lifecycle.accounting.host_bridge import (
    CAPABILITY_UNAVAILABLE,
    EvidenceGraph,
    read_accounting_input,
    read_source_lifecycle_qualification,
    read_source_lifecycle_qualifications,
    resolve_accounting_capability,
)
from agent_lifecycle.adapter_sessions.launch_execution import (
    resolve_qualified_accounting_capability,
    verify_final_source_accounting_profiles,
)
from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile
from agent_lifecycle.adapter_sessions.immutable_input import planning_invocation_context
from agent_lifecycle.adapter_sessions.planning_launch import run_planning_launch
from agent_lifecycle.contracts import LifecycleError, canonical_digest

ROOT = Path(__file__).resolve().parents[2]
HEX = "a" * 64


class EvidenceSchemaReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.dialect = "https://json-schema.org/draft/2020-12/schema"
        self.definitions = {"artifactRef": {"type": "object", "properties": {
            "path": {"type": "string"}, "bytes": {"type": "integer"},
            "sha256": {"type": "string"}}, "required": ["path", "bytes", "sha256"]}}

    def write(self, name, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        (self.root / name).write_bytes(raw)
        return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def test_standard_schema_is_source_metadata(self):
        schema = self.write("schema.json", {"$schema": self.dialect, "$defs": self.definitions})
        report = self.write("report.json", {"coveredFiles": [schema]})
        graph = EvidenceGraph(self.root, schema_refs=[schema])
        self.assertEqual(graph.document(report), {"coveredFiles": [schema]})
        self.assertEqual(set(graph.verified), {"report.json", "schema.json"})
        self.assertEqual(graph.documents["schema.json"]["$defs"], self.definitions)

    def test_mixed_contract_checks_live_refs_outside_schema(self):
        source = self.write("source.json", {"value": 1})
        contract = self.write("contract.json", {"schemaDialect": self.dialect,
            "$defs": self.definitions, "producerSource": source})
        report = self.write("report.json", {"coveredFiles": [contract]})
        graph = EvidenceGraph(self.root, schema_refs=[contract])
        graph.document(report)
        self.assertEqual(set(graph.verified), {"report.json", "contract.json", "source.json"})

    def test_mixed_contract_refuses_invalid_live_ref(self):
        invalid = {"path": {"type": "string"}, "bytes": 1, "sha256": HEX}
        contract = self.write("contract.json", {"schemaDialect": self.dialect,
            "$defs": self.definitions, "producerSource": invalid})
        with self.assertRaises(LifecycleError) as caught:
            EvidenceGraph(self.root, schema_refs=[contract]).document(contract)
        self.assertEqual(caught.exception.code, "accounting-reference-invalid")

    def test_data_markers_do_not_hide_invalid_refs_or_cycles(self):
        invalid = {"path": {"type": "string"}, "bytes": 1, "sha256": HEX}
        for index, markers in enumerate((
            {"$schema": self.dialect}, {"schemaDialect": self.dialect},
            {"$schema": self.dialect, "schemaDialect": self.dialect},
        )):
            with self.subTest(markers=markers, case="invalid"):
                data = self.write(f"invalid{index}.json", {
                    "payload": {**markers, "$defs": {"evidence": invalid}}})
                with self.assertRaises(LifecycleError) as caught:
                    EvidenceGraph(self.root).document(data)
                self.assertEqual(caught.exception.code, "accounting-reference-invalid")
            with self.subTest(markers=markers, case="cycle"):
                name = f"cycle{index}.json"
                cycle = {"path": name, "bytes": 0, "sha256": HEX}
                data = self.write(name, {"payload": {**markers, "$defs": {"evidence": cycle}}})
                with self.assertRaises(LifecycleError) as caught:
                    EvidenceGraph(self.root).document(data)
                self.assertEqual(caught.exception.code, "accounting-reference-cycle")

    def test_registered_metadata_keeps_depth_and_mixed_live_checks(self):
        nested = {"type": "object"}
        for _ in range(65):
            nested = {"not": nested}
        schema = self.write("deep.json", {"$schema": self.dialect, "$defs": {"deep": nested}})
        with self.assertRaises(LifecycleError) as caught:
            EvidenceGraph(self.root, schema_refs=[schema]).document(schema)
        self.assertEqual(caught.exception.code, "accounting-json-depth-exceeded")
        invalid = {"path": {"type": "string"}, "bytes": 1, "sha256": HEX}
        mixed = self.write("mixed.json", {"$schema": self.dialect, "schemaDialect": self.dialect,
            "$defs": self.definitions, "producerSource": invalid})
        with self.assertRaises(LifecycleError) as caught:
            EvidenceGraph(self.root, schema_refs=[mixed]).document(mixed)
        self.assertEqual(caught.exception.code, "accounting-reference-invalid")


class SourceQualificationConsumerTests(unittest.TestCase):
    """Synthetic content/provenance doubles are not accepted adapter evidence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.profiles = self.root / "work/profiles"
        frozen = ROOT / "tasks/release-2-16"
        catalog = json.loads((frozen / "h04-adapter-profile-cases.json").read_text())
        self.entry = copy.deepcopy(catalog["expectedBindings"]["entries"][0])
        self.manifest = {"status": "FROZEN", "syntheticUnitFixture": True}
        self.write(self.root, "tasks/release-2-16/plan.manifest.json", self.manifest)
        self.write(self.root, "tasks/release-2-16/h04-artifact-contracts.json",
                   json.loads((frozen / "h04-artifact-contracts.json").read_text()))
        source_bindings = []
        for index, source in enumerate(self.entry["sources"]):
            raw = ("synthetic archived source " + str(index)).encode()
            source["artifact"] = self.write(self.root, "archive/source" + str(index) + ".txt", raw)
            ref = self.write(self.profiles, source["artifact"]["path"], raw)
            source_bindings.append({"sourceId": source["sourceId"], "kind": "OFFICIAL_SOURCE",
                                    "origin": (source["origins"] or [source["artifact"]["path"]])[0], "artifact": ref,
                                    "versionApplicability": self.entry["target"]["version"]})
        catalog["expectedBindings"]["entries"] = [self.entry]
        self.write(self.root, "tasks/release-2-16/h04-adapter-profile-cases.json", catalog)
        pins = []
        for name in ("h04-artifact-contracts.json", "h04-adapter-profile-cases.json"):
            path = "tasks/release-2-16/" + name
            raw = (self.root / path).read_bytes()
            pins.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        self.write(self.root, "tasks/release-2-16/plan.lock.json", {"manifestHash": digest(self.manifest), "entries": pins})
        rows = [self.write(self.root, path, raw) for path, raw in (
            ("src/current.py", b"value = 1\n"),
            ("tools/release/validate_accounting_adapter_profiles.py", b"value = 2\n"))]
        binding = {"adapterId": "codex", "hostVersion": self.entry["target"]["version"],
                   "executableSha256": None, "configurationSha256": None,
                   "launchMode": "SOURCE_ONLY", "providerId": "NOT_CLAIMED", "transportId": "NOT_CLAIMED",
                   "evidenceMode": "SOURCE_BOUND_LIMITATION"}
        source_ids = [s["sourceId"] for s in source_bindings]
        ref = source_bindings[0]["artifact"]
        self.payload = {"profileId": "unit-codex", "revision": 1, "expectationId": self.entry["expectationId"],
                        "binding": binding, "modes": ["LIFECYCLE_ONLY"], "claims": [], "sources": source_bindings,
                        "routes": [{"routeId": rid, "role": rid.split(".")[0], "state": "EXCLUDED",
                                    "claimIds": [], "reason": "Synthetic documented limitation", "sourceIds": source_ids}
                                   for rid in self.entry["roleInventory"]],
                        "sourceCaseDispositions": [{"sourceCaseId": c["sourceCaseId"],
                                                    "sourceCaseSha256": c["sourceCaseSha256"], "claimIds": [],
                                                    "routeIds": ["worker"], "disposition": "QUALIFIED_LIMITATION",
                                                    "reason": "Synthetic limitation, never native PASS", "evidenceRefs": [ref]}
                                                   for c in self.entry["sourceCaseRequirements"]],
                        "completeFinancialRun": False}
        self.qualification = {"schemaVersion": "alk-accounting-qualification.v1", "profileDigest": digest(self.payload),
                              "expectationDigest": digest(self.entry), "planDigest": digest(self.manifest),
                              "alkCandidateDigest": digest(rows), "binding": binding,
                              "observations": [], "candidateDispositions": [], "reviewEvidenceRef": ref}
        for index, candidate in enumerate(self.entry["candidateRequirements"]):
            oid = "documented-" + str(index)
            self.qualification["observations"].append({
                "observationId": oid, "kind": "DOCUMENTED_LIMITATION", "claimIds": [],
                "routeIds": self.entry["roleInventory"], "sourceIds": candidate["sourceIds"],
                "recipeId": self.entry["qualificationRecipe"]["recipeId"], "actualBinding": binding,
                "rawEvidenceRefs": [ref], "observedResult": "Synthetic source-only limitation",
                "usage": None, "usageStatus": "UNAVAILABLE", "unitId": candidate["unitId"],
                "priorPermitRef": None, "reuseApplicabilityRef": None})
            self.qualification["candidateDispositions"].append({
                "candidateId": candidate["candidateId"], "claimIds": [], "disposition": "QUALIFIED_LIMITATION",
                "observationIds": [oid], "reason": "Synthetic source-only limitation"})
        self.save()
        self.request = {"schemaVersion": "alk-accounting-capability-request.v1", "requestId": "unit-request",
                        **{k: self.qualification[k] for k in ("profileDigest", "expectationDigest", "planDigest",
                                                            "alkCandidateDigest", "binding")},
                        "operationId": "unit-operation", "requestedModes": ["LIFECYCLE_ONLY"],
                        "requiredClaims": [], "routeIds": ["worker"], "requestedUpperBound": None}

    @staticmethod
    def write(root, path, value):
        raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def save(self):
        self.write(self.profiles, "codex/profile-payload.json", self.payload)
        subject = {"schemaVersion": "alk-accounting-qualification-subject.v1", "profileDigest": digest(self.payload),
                   "qualificationDigest": digest({k: v for k, v in self.qualification.items() if k != "reviewEvidenceRef"})}
        self.subject_ref = self.write(self.profiles, "codex/qualification-subject.json", subject)
        self.subject_ref["path"] = "work/profiles/codex/qualification-subject.json"
        self.write(self.profiles, self.subject_ref["path"], subject)
        self.report = {"reviewId": "unit-only", "verdict": "PASS", "coveredFiles": [self.subject_ref],
                       "planDigest": digest(self.manifest),
                       "lockSha256": hashlib.sha256((self.root / "tasks/release-2-16/plan.lock.json").read_bytes()).hexdigest(),
                       "coveredObligations": ["accounting.profile.codex"]}
        self.review_ref = self.write(self.profiles, "codex/review.json", self.report)
        self.qualification["reviewEvidenceRef"] = self.review_ref
        self.write(self.profiles, "codex/qualification.json", self.qualification)
        self.verified = {"report": self.report, "reportSha256": self.review_ref["sha256"],
                         "assignment": {"scopeId": "HOST_AND_TRANSPORT"},
                         "assurance": "PROCEDURAL_SAME_ACCOUNT", "nativeAllowed": False}

    def resolve(self):
        return resolve_qualified_accounting_capability(project_root=self.root, profiles_root=self.profiles,
                                                      adapter_id="codex", request=self.request)

    def test_synthetic_provenance_double_allows_only_lifecycle_capability(self):
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", return_value=self.verified) as verify:
            result = self.resolve()
        self.assertEqual(result["outcome"], "ALLOW_CAPABILITY")
        self.assertEqual(result["detail"], "MATCH")
        self.assertEqual(result["matchedClaimIds"], [])
        self.assertIs(result["dispatchEntitlement"], False)
        verify.assert_called_once_with(self.root, review_id="unit-only")
        contract = json.loads((ROOT / "tasks/release-2-16/h04-artifact-contracts.json").read_text())
        jsonschema.Draft202012Validator({"$defs": contract["$defs"], "$ref": "#/$defs/resolverResult"}).validate(result)

    def test_supplied_pass_without_real_publication_refuses(self):
        self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_source_content_and_current_candidate_mutations_refuse(self):
        for path in [self.entry["sources"][0]["artifact"]["path"], "src/current.py"]:
            target = self.root / path
            before = target.read_bytes()
            with self.subTest(path=path):
                target.write_bytes(before + b"changed")
                with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report") as verify:
                    self.assertEqual(self.resolve()["outcome"], "DENY")
                    verify.assert_not_called()
            target.write_bytes(before)

    def test_unresolved_or_duplicate_candidate_and_native_observation_refuse(self):
        before = copy.deepcopy(self.qualification)
        for mutation in ("missing", "duplicate", "native", "usage-zero"):
            with self.subTest(mutation=mutation):
                self.qualification = copy.deepcopy(before)
                if mutation == "missing":
                    self.qualification["candidateDispositions"].pop()
                elif mutation == "duplicate":
                    self.qualification["candidateDispositions"].append(self.qualification["candidateDispositions"][0])
                elif mutation == "native":
                    self.qualification["observations"][0]["kind"] = "NATIVE_POSITIVE"
                else:
                    self.qualification["observations"][0].update(usageStatus="AVAILABLE", usage=0)
                self.save()
                self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_all_original_cases_and_routes_are_required(self):
        for field in ("routes", "sourceCaseDispositions"):
            before = copy.deepcopy(self.payload[field])
            with self.subTest(field=field):
                self.payload[field].pop()
                self.save()
                self.assertEqual(self.resolve()["outcome"], "DENY")
            self.payload[field] = before

    def test_exact_review_origin_scope_and_subject_are_required(self):
        for mutation in ("sha", "scope", "subject", "obligation", "native", "assurance", "plan", "lock"):
            verified = copy.deepcopy(self.verified)
            with self.subTest(mutation=mutation):
                if mutation == "sha":
                    verified["reportSha256"] = HEX
                elif mutation == "scope":
                    verified["assignment"]["scopeId"] = "OTHER"
                elif mutation == "subject":
                    verified["report"]["coveredFiles"] = []
                elif mutation == "obligation":
                    verified["report"]["coveredObligations"] = []
                elif mutation == "native":
                    verified["nativeAllowed"] = True
                elif mutation == "plan":
                    verified["report"]["planDigest"] = HEX
                elif mutation == "lock":
                    verified["report"]["lockSha256"] = HEX
                else:
                    verified["assurance"] = "SUPPLIED_PASS"
                with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", return_value=verified):
                    self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_change_during_provenance_verification_refuses(self):
        def change(*_args, **_kwargs):
            (self.root / "src/current.py").write_bytes(b"value = 3\n")
            return self.verified
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=change):
            self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_contract_schema_drift_during_review_refuses_even_with_updated_local_lock(self):
        def change(*_args, **_kwargs):
            path = "tasks/release-2-16/h04-artifact-contracts.json"
            value = json.loads((self.root / path).read_bytes())
            value["$defs"]["qualification"]["description"] = "Changed without invalidating qualification shape"
            changed_ref = self.write(self.root, path, value)
            lock_path = "tasks/release-2-16/plan.lock.json"
            lock = json.loads((self.root / lock_path).read_bytes())
            lock["entries"] = [changed_ref if row["path"] == path else row for row in lock["entries"]]
            self.write(self.root, lock_path, lock)
            return self.verified
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=change):
            self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_actual_review_subject_formatting_drift_refuses_with_unchanged_archive_copy(self):
        def change(*_args, **_kwargs):
            path = self.profiles / "codex/qualification-subject.json"
            value = json.loads(path.read_bytes())
            path.write_text(json.dumps(value, indent=2))
            return self.verified
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=change):
            self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_request_drift_and_financial_upgrade_refuse_before_review(self):
        for field in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest", "requestedModes"):
            before = copy.deepcopy(self.request[field])
            with self.subTest(field=field):
                self.request[field] = ["FULL_FINANCIAL"] if field == "requestedModes" else HEX
                with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report") as verify:
                    result = self.resolve()
                    self.assertEqual(result["outcome"], "DENY")
                    self.assertIn(result["detail"], {"BINDING_MISMATCH", "UNSUPPORTED_GUARANTEE"})
                    verify.assert_not_called()
            self.request[field] = before

    def test_reader_uses_shared_budget_and_rejects_source_symlink(self):
        with self.assertRaises(LifecycleError):
            read_source_lifecycle_qualification(self.root, self.profiles, "codex", byte_limit=20)
        source = self.root / "src/current.py"
        source.unlink()
        source.symlink_to(self.root / "tasks/release-2-16/plan.manifest.json")
        self.assertEqual(self.resolve()["outcome"], "DENY")

    def test_batch_reader_rejects_duplicate_or_unresolved_final_profiles(self):
        with self.assertRaises(LifecycleError):
            read_source_lifecycle_qualifications(self.root, self.profiles, ["codex", "codex"])
        with self.assertRaises(LifecycleError):
            read_source_lifecycle_qualifications(self.root, self.profiles, ["codex"], final=True)
        batch = read_source_lifecycle_qualifications(self.root, self.profiles, ["codex"])
        self.assertEqual(batch["profiles"]["codex"]["payload"], self.payload)
        self.assertGreater(batch["readBytes"], 0)

    def make_final(self):
        """Real content reader, with only ordinary publication replaced by a double."""
        contracts = json.loads((self.root / "tasks/release-2-16/h04-artifact-contracts.json").read_bytes())
        command = next(p["command"] for p in contracts["producers"] if p["id"] == "P-EXACT-PROFILE-RESOLVER")
        result = {"schemaVersion": "alk-accounting-capability-result.v1", "requestDigest": digest(self.request),
                  "profileDigest": self.qualification["profileDigest"], "expectationDigest": self.qualification["expectationDigest"],
                  "outcome": "ALLOW_CAPABILITY", "reason": "CAPABILITY_MATCH", "detail": "MATCH",
                  "matchedClaimIds": [], "dispatchEntitlement": False}
        observation = {"caseId": "supported", "request": self.request, "result": result, "alkOwnedDispatchCount": 0}
        trace = {"schemaVersion": "alk-accounting-resolver-trace.v1", "profileDigest": digest(self.payload),
                 "commandDigest": digest(command), "observations": [observation]}
        trace_ref = self.write(self.profiles, "codex/trace.json", trace)
        resolver = {"schemaVersion": "alk-accounting-resolver-evidence.v1",
                    **{k: self.qualification[k] for k in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest")},
                    "commandDigest": digest(command), "observations": [{**observation, "rawTraceRef": trace_ref}]}
        subject = {"schemaVersion": "alk-accounting-resolver-subject.v1", "resolverDigest": digest(resolver)}
        subject_ref = self.write(self.profiles, "codex/resolver-subject.json", subject)
        subject_ref["path"] = "work/profiles/" + subject_ref["path"]
        self.write(self.profiles, subject_ref["path"], subject)
        covered_trace = {**trace_ref, "path": "work/profiles/" + trace_ref["path"]}
        self.write(self.profiles, covered_trace["path"], trace)
        report = {**self.report, "reviewId": "unit-resolver", "coveredFiles": [subject_ref, covered_trace],
                  "coveredObligations": ["accounting.profile.codex", "accounting.profile.requested-guarantee-denial"]}
        report_ref = self.write(self.profiles, "codex/resolver-review.json", report)
        resolver["receiptRef"] = report_ref
        resolver_ref = self.write(self.profiles, "codex/resolver-evidence.json", resolver)
        qualification_ref = self.write(self.profiles, "codex/qualification.json", self.qualification)
        self.write(self.profiles, "codex/profile.json", {"schemaVersion": "alk-accounting-profile.v1", "payload": self.payload,
                                                      "profileDigest": digest(self.payload), "qualificationRef": qualification_ref,
                                                      "resolverEvidenceRef": resolver_ref})
        self.final_reports = {"unit-only": self.verified,
                              "unit-resolver": {**self.verified, "report": report, "reportSha256": report_ref["sha256"]}}

    def final(self):
        return verify_final_source_accounting_profiles(project_root=self.root, profiles_root=self.profiles, adapter_ids=["codex"])

    def test_final_envelope_reads_actual_bytes_and_requires_both_review_origins(self):
        self.make_final()
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report",
                   side_effect=lambda _root, review_id: self.final_reports[review_id]) as verify:
            final = self.final()
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(final["profiles"]["codex"]["profile"]["payload"], self.payload)
        self.assertFalse(final["dispatchEntitlement"])
        self.assertIn("work/profiles/codex/profile.json", {r["path"] for r in final["snapshotRefs"]})
        with self.assertRaises(LifecycleError):
            self.final()  # Unmocked: supplied PASS labels never establish publication.

    def test_final_origin_cannot_omit_trace_or_change_bytes_during_review(self):
        self.make_final()
        original = copy.deepcopy(self.final_reports)
        self.final_reports["unit-resolver"]["report"]["coveredFiles"].pop()
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report",
                   side_effect=lambda _root, review_id: self.final_reports[review_id]), self.assertRaises(LifecycleError):
            self.final()
        self.final_reports = original
        def mutate(_root, review_id):
            if review_id == "unit-resolver":
                (self.profiles / "codex/trace.json").write_bytes(b"{}")
            return self.final_reports[review_id]
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=mutate), self.assertRaises(LifecycleError):
            self.final()

    def test_exact_artifact_mutations_are_denied_by_actual_staged_resolver(self):
        from tools.release.validate_accounting_adapter_profiles import (
            exact_qualification_mutations,
            exact_resolver_requests,
        )
        joins = {k: self.qualification[k] for k in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest", "binding")}
        requests = exact_resolver_requests(self.payload, joins)
        path = self.profiles / "codex/qualification.json"
        original = path.read_bytes()
        for case, replacement in exact_qualification_mutations(self.qualification, requests).items():
            with self.subTest(case=case):
                try:
                    if replacement is None:
                        path.unlink()
                    else:
                        self.write(self.profiles, "codex/qualification.json", replacement)
                    with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report") as verify:
                        observed = resolve_qualified_accounting_capability(project_root=self.root, profiles_root=self.profiles,
                                                                          adapter_id="codex", request=requests[case])
                    self.assertEqual(observed["outcome"], "DENY")
                    self.assertEqual(observed["detail"], "UNQUALIFIED_EVIDENCE")
                    self.assertFalse(observed["dispatchEntitlement"])
                    verify.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_final_snapshot_rejects_raw_format_drift_with_same_canonical_payload(self):
        self.make_final()
        def mutate(_root, review_id):
            if review_id == "unit-resolver":
                path = self.profiles / "codex/profile-payload.json"
                path.write_bytes(path.read_bytes() + b"\n")
            return self.final_reports[review_id]
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=mutate), self.assertRaises(LifecycleError):
            self.final()

    def test_final_snapshot_reenumerates_and_refuses_new_candidate_source(self):
        self.make_final()
        def mutate(_root, review_id):
            if review_id == "unit-resolver":
                self.write(self.root, "src/new_candidate.py", {"new": "source"})
            return self.final_reports[review_id]
        with patch("agent_lifecycle.adapter_sessions.launch_execution.verify_area_report", side_effect=mutate), \
                self.assertRaises(LifecycleError):
            self.final()


class AccountingDispatchRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = json.loads((ROOT / "tests/accounting/fixtures/release_216_adapter_profiles.json").read_text())
        payload = fixture["profiles"][0]
        ref = {"path": "proof.json", "sha256": HEX, "bytes": 1}
        self.profile = {"schemaVersion": "alk-accounting-profile.v1", "payload": payload,
                        "profileDigest": canonical_digest(payload), "qualificationRef": ref,
                        "resolverEvidenceRef": dict(ref)}
        self.request = {"schemaVersion": "alk-accounting-capability-request.v1", "requestId": "r1",
                        "profileDigest": self.profile["profileDigest"], "expectationDigest": HEX,
                        "planDigest": HEX, "alkCandidateDigest": HEX, "binding": copy.deepcopy(payload["binding"]),
                        "operationId": "op1", "requestedModes": ["LIFECYCLE_ONLY"], "requiredClaims": [],
                        "routeIds": [payload["routes"][1]["routeId"]], "requestedUpperBound": None}

    def resolve(self, request=None, profile=None):
        return resolve_accounting_capability(self.profile if profile is None else profile,
                                             self.request if request is None else request,
                                             expectation_digest=HEX, plan_digest=HEX, candidate_digest=HEX)

    def assert_refusal(self, result, detail):
        self.assertEqual(result["outcome"], "DENY")
        self.assertEqual(result["reason"], CAPABILITY_UNAVAILABLE)
        self.assertEqual(result["detail"], detail)
        self.assertEqual(result["matchedClaimIds"], [])
        self.assertIs(result["dispatchEntitlement"], False)

    def test_matching_fixture_is_unqualified_and_result_obeys_frozen_schema(self):
        result = self.resolve()
        self.assert_refusal(result, "UNQUALIFIED_EVIDENCE")
        contract = json.loads((ROOT / "tasks/release-2-16/h04-artifact-contracts.json").read_text())
        jsonschema.Draft202012Validator({"$defs": contract["$defs"], "$ref": "#/$defs/resolverResult"}).validate(result)
        self.assertEqual(result["requestDigest"], canonical_digest(self.request))
        self.assertEqual(result["profileDigest"], self.profile["profileDigest"])

    def test_each_requested_binding_mutation_refuses(self):
        for field in ("profileDigest", "expectationDigest", "planDigest", "alkCandidateDigest"):
            with self.subTest(field=field):
                request = copy.deepcopy(self.request)
                request[field] = "b" * 64
                self.assert_refusal(self.resolve(request), "BINDING_MISMATCH")
        request = copy.deepcopy(self.request)
        request["binding"]["hostVersion"] = "0.160.1"
        self.assert_refusal(self.resolve(request), "BINDING_MISMATCH")

    def test_stronger_modes_refuse_without_convenience_fallback(self):
        for mode in ("OBSERVATION", "ALK_INVOCATION_ADMISSION", "HOST_PARTIAL_CONTROL", "FULL_FINANCIAL"):
            with self.subTest(mode=mode):
                request = copy.deepcopy(self.request)
                request["requestedModes"] = [mode]
                self.assert_refusal(self.resolve(request), "UNSUPPORTED_GUARANTEE")

    def test_unknown_route_and_boolean_bound_refuse(self):
        request = copy.deepcopy(self.request)
        request["routeIds"] = ["unknown:worker"]
        self.assert_refusal(self.resolve(request), "UNCOVERED_ROUTE")
        request = copy.deepcopy(self.request)
        request["requestedUpperBound"] = True
        self.assert_refusal(self.resolve(request), "INVALID_INPUT")

    def test_positive_request_extra_excluded_or_unqualified_route_refuses(self):
        profile = copy.deepcopy(self.profile)
        payload = profile["payload"]
        worker, extra = payload["routes"][1], payload["routes"][2]
        payload["modes"] = ["ALK_INVOCATION_ADMISSION"]
        worker.update(state="COVERED", claimIds=["local-control"])
        payload["claims"] = [{"claimId": "local-control", "dimension": "CONTROL", "guarantee": "ALK_PRE_LAUNCH",
                              "unitId": "alk-owned-invocations", "routeIds": [worker["routeId"]],
                              "limitKind": "ADMISSION_ONLY", "boundMethodId": None, "failurePolicy": "FAIL_CLOSED",
                              "sourceIds": worker["sourceIds"]}]
        request = copy.deepcopy(self.request)
        request["requestedModes"] = ["ALK_INVOCATION_ADMISSION"]
        request["requiredClaims"] = [{"dimension": "CONTROL", "guarantee": "ALK_PRE_LAUNCH",
                                      "unitId": "alk-owned-invocations", "routeIds": [worker["routeId"]],
                                      "limitKind": "ADMISSION_ONLY", "boundMethodId": None, "requireFailClosed": True}]
        for state in ("EXCLUDED", "UNQUALIFIED"):
            with self.subTest(state=state):
                extra["state"] = state
                profile["profileDigest"] = canonical_digest(payload)
                request["profileDigest"] = profile["profileDigest"]
                request["routeIds"] = [worker["routeId"], extra["routeId"]]
                self.assert_refusal(self.resolve(request, profile), "UNCOVERED_ROUTE")
                request["routeIds"] = [worker["routeId"]]
                self.assert_refusal(self.resolve(request, profile), "UNQUALIFIED_EVIDENCE")

    def test_lifecycle_without_financial_claims_keeps_match00_exemption(self):
        for state in ("EXCLUDED", "UNQUALIFIED"):
            with self.subTest(state=state):
                profile = copy.deepcopy(self.profile)
                for route in profile["payload"]["routes"]:
                    route["state"] = state
                profile["profileDigest"] = canonical_digest(profile["payload"])
                request = copy.deepcopy(self.request)
                request["profileDigest"] = profile["profileDigest"]
                self.assert_refusal(self.resolve(request, profile), "UNQUALIFIED_EVIDENCE")

    def test_forged_pass_or_allow_object_cannot_be_a_profile(self):
        for flag in ("status", "outcome", "dispatchEntitlement"):
            profile = copy.deepcopy(self.profile)
            profile[flag] = "PASS"
            self.assert_refusal(self.resolve(profile=profile), "INVALID_INPUT")
        self.assert_refusal(self.resolve(profile={"outcome": "ALLOW_CAPABILITY"}), "INVALID_INPUT")

    def test_changed_payload_cannot_reuse_saved_digest(self):
        profile = copy.deepcopy(self.profile)
        profile["payload"]["revision"] += 1
        self.assert_refusal(self.resolve(profile=profile), "INVALID_INPUT")

    def test_duplicate_and_nonfinite_input_are_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'null', b'{'):
                path.write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(LifecycleError) as caught:
                    read_accounting_input(path)
                self.assertEqual(caught.exception.code, CAPABILITY_UNAVAILABLE)

    def test_symlink_and_oversized_request_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            target.write_bytes(b'{}')
            alias = root / "alias.json"
            alias.symlink_to(target)
            with self.assertRaises(LifecycleError):
                read_accounting_input(alias)
            target.write_bytes(b' ' * 262_145)
            with self.assertRaises(LifecycleError):
                read_accounting_input(target)

    def test_planning_refuses_request_and_replayed_allow_before_process(self):
        for request in (self.request, None, {"outcome": "ALLOW_CAPABILITY", "dispatchEntitlement": True}):
            with self.subTest(request=request), patch("agent_lifecycle.adapter_sessions.planning_launch.run_process") as run:
                launch_args = dict(
                    adapter_id="codex", session_id="s1", requested_mode="plan", task_text="private task",
                    input_source="text", argv=["never-run"], env={},
                    advisory={"accountingCapabilityRequest": request},
                )
                context = planning_invocation_context(
                    **launch_args, request=None, timeout_seconds=300, process_cwd=None,
                )
                result = run_planning_launch(**launch_args, immutable_input_context=context)
                run.assert_not_called()
                self.assertEqual(result["processCalls"], 0)
                self.assertFalse(result["hostLaunchStarted"])
                self.assertEqual(result["usageEvidence"]["inputTokens"], None)
                self.assertEqual(result["blockers"][0]["code"], CAPABILITY_UNAVAILABLE)
                self.assertNotIn("private task", json.dumps(result))

    def test_managed_gate_refuses_request_even_with_replayed_allow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".alk/host-launch/codex.json"
            path.parent.mkdir(parents=True)
            launch_profile = json.loads((ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles/valid.json").read_text())
            launch_profile["executable"] = sys.executable
            path.write_text(json.dumps(launch_profile))
            for value in (self.request, None, {"outcome": "ALLOW_CAPABILITY"}):
                with self.subTest(value=value), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as run:
                    result = launch_from_local_profile(
                        profile_path=path, project_root=root, operation="managedTask", explicit_launch=True,
                        state_path=root / "state.json", manifest_path=root / "manifest.json",
                        lock_path=root / "lock.json", task_id="task1", operation_id="op1", source_revision=HEX,
                        adapter_id="codex", risk_profile={"adapterId": "codex", "accountingCapabilityRequest": value},
                    )
                    run.assert_not_called()
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertFalse(result["hostLaunchStarted"])
                    self.assertEqual(result["blockers"], [{"code": CAPABILITY_UNAVAILABLE, "detail": "UNQUALIFIED_EVIDENCE"}])


if __name__ == "__main__":
    unittest.main()
