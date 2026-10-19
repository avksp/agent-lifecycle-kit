"""Source-bound local input-fit witnesses; host qualification is separate."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.accounting.input_fit import (
    assess_local_input_fit,
    select_source_excerpts,
    validate_context_ref_index,
)
from agent_lifecycle.accounting.support_profiles import match_requested_claims, validate_profile_payload
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.resources import builtin_profile_path

CONTRACT = json.loads(Path("tasks/release-2-16/alk-input-fit-contract.json").read_text(encoding='utf-8'))
PROFILE = json.loads(builtin_profile_path("small-context-profile.v1.json").read_text(encoding='utf-8'))
HEX = "a" * 64


class InputFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = CONTRACT["sourceScope"]["orderedContextRefs"][0]
        source = self.root / self.path
        source.parent.mkdir(parents=True)
        self.data = ("é" + " source evidence " * 8).encode("utf-8")
        source.write_bytes(self.data)
        self.packet = {
            "schemaVersion": "agent-task-packet.v1",
            "plan": {"planDigest": HEX, "packageId": "release-2-16"},
            "task": {"id": "WS216-01", "plannedItems": []},
            "context": {"refs": CONTRACT["sourceScope"]["orderedContextRefs"]},
            "ownership": {},
            "specification": {},
            "validation": {},
            "acceptance": [],
        }
        self.summary = {key: [] for key in PROFILE["requiredSummaryFields"]}
        self.request = self._request(0, len(self.data))

    def _request(self, start: int, end: int) -> dict[str, object]:
        return {
            "path": self.path,
            "fileSha256": hashlib.sha256(self.data).hexdigest(),
            "startByte": start,
            "endByte": end,
            "selectedSha256": hashlib.sha256(self.data[start:end]).hexdigest(),
            "candidateDigest": HEX,
            "estimatorId": "canonical-json-bytes-div-4-ceil",
        }

    def _select(self, requests: list[dict[str, object]]):
        return select_source_excerpts(
            self.root,
            self.packet,
            CONTRACT,
            requests,
            run_id="run-1",
            attempt_id="attempt-1",
            manifest_sha256=HEX,
            candidate_digest=HEX,
            estimator_id="canonical-json-bytes-div-4-ceil",
        )

    def _binding(self) -> dict[str, object]:
        return {
            "runId": "run-1",
            "taskId": "WS216-01",
            "attemptId": "attempt-1",
            "planDigest": HEX,
            "manifestSha256": HEX,
            "candidateDigest": HEX,
            "estimatorId": "canonical-json-bytes-div-4-ceil",
        }

    def test_exact_source_selection_binds_bytes_and_lineage(self):
        selected = self._select([self.request])
        self.assertEqual(selected["status"], "SELECTED")
        self.assertEqual(selected["selected"][0]["text"], self.data.decode("utf-8"))
        self.assertEqual(selected["selected"][0]["selectedSha256"], self.request["selectedSha256"])
        self.assertEqual(selected["indexOnlyCount"], len(CONTRACT["sourceScope"]["orderedContextRefs"]))
        self.assertEqual(selected["taskId"], "WS216-01")

    def test_index_without_selection_remains_pending(self):
        self.assertEqual(validate_context_ref_index(self.packet, CONTRACT)["status"], "PENDING_SOURCE_SELECTION")
        self.assertEqual(self._select([])["status"], "PENDING_SOURCE_SELECTION")
        with self.assertRaises(LifecycleError):
            assess_local_input_fit(
                self.root,
                CONTRACT,
                PROFILE,
                self.packet,
                self.summary,
                self._select([]),
                role="worker",
                host_adapter_id="codex",
                host_version="0.155.1",
                host_mode="managedTask",
                estimator_id="canonical-json-bytes-div-4-ceil",
                instruction="do work",
                schema={},
                current_binding=self._binding(),
            )

    def test_stale_undeclared_traversal_and_utf8_boundary_refuse(self):
        mutations = (
            ("fileSha256", HEX),
            ("selectedSha256", HEX),
            ("path", "tasks/release-2-16/unknown.md"),
            ("path", "../outside.md"),
            ("endByte", 1),
            ("candidateDigest", "b" * 64),
            ("estimatorId", "wrong-estimator"),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                request = dict(self.request)
                request[key] = value
                with self.assertRaises(LifecycleError):
                    self._select([request])

    def test_excerpt_and_count_overflow_refuse_without_truncation(self):
        source = self.root / self.path
        self.data = b"x" * 2049
        source.write_bytes(self.data)
        with self.assertRaises(LifecycleError):
            self._select([self._request(0, 1025)])
        with self.assertRaises(LifecycleError):
            self._select([self._request(0, 512)] * 3)
        with self.assertRaises(LifecycleError):
            self._select([self._request(0, 1024), self._request(1024, 2049)])

    def test_wrong_ref_index_and_candidate_identity_refuse(self):
        self.packet["context"]["refs"] = list(reversed(self.packet["context"]["refs"]))
        with self.assertRaises(LifecycleError):
            self._select([self.request])
        self.packet["context"]["refs"] = CONTRACT["sourceScope"]["orderedContextRefs"]
        with self.assertRaises(LifecycleError):
            select_source_excerpts(
                self.root,
                self.packet,
                CONTRACT,
                [self.request],
                run_id="run-1",
                attempt_id="attempt-1",
                manifest_sha256=HEX,
                candidate_digest="wrong",
                estimator_id="canonical-json-bytes-div-4-ceil",
            )

    def test_local_fit_passes_only_alk_components_and_rejects_overflow(self):
        selected = self._select([self.request])
        arguments = dict(
            role="worker",
            host_adapter_id="codex",
            host_version="0.155.1",
            host_mode="managedTask",
            estimator_id="canonical-json-bytes-div-4-ceil",
            instruction="Implement the bounded task",
            schema={},
            current_binding=self._binding(),
        )
        fit = assess_local_input_fit(self.root, CONTRACT, PROFILE, self.packet, self.summary, selected, **arguments)
        self.assertEqual(fit["status"], "PASS_ALK_COMPONENTS_ONLY")
        self.assertEqual(fit["hostOwnedInput"], "UNAVAILABLE")
        self.assertEqual(fit["wholeCallUpperBound"], "UNAVAILABLE")
        self.assertFalse(fit["fullFinancial"])
        overflow = assess_local_input_fit(
            self.root,
            CONTRACT,
            PROFILE,
            self.packet,
            self.summary,
            selected,
            **{**arguments, "instruction": "x" * 3000},
        )
        self.assertEqual(overflow["status"], "REFUSE_OVERFLOW")
        self.assertIn("instruction-bytes", {check["id"] for check in overflow["checks"] if check["status"] == "FAIL"})
        with self.assertRaises(LifecycleError):
            assess_local_input_fit(
                self.root, CONTRACT, PROFILE, self.packet, self.summary, selected, **{**arguments, "window": "8k"}
            )

    def test_changed_source_or_dispatch_candidate_refuses_after_selection(self):
        selected = self._select([self.request])
        arguments = dict(
            role="worker",
            host_adapter_id="codex",
            host_version="0.155.1",
            host_mode="managedTask",
            estimator_id="canonical-json-bytes-div-4-ceil",
            instruction="bounded task",
            schema={},
            current_binding=self._binding(),
        )
        with self.assertRaises(LifecycleError):
            assess_local_input_fit(
                self.root,
                CONTRACT,
                PROFILE,
                self.packet,
                self.summary,
                selected,
                **{**arguments, "current_binding": {**self._binding(), "candidateDigest": "b" * 64}},
            )
        (self.root / self.path).write_bytes(self.data + b" changed")
        with self.assertRaises(LifecycleError):
            assess_local_input_fit(self.root, CONTRACT, PROFILE, self.packet, self.summary, selected, **arguments)

    def test_forged_receipt_cannot_expand_source_count_or_change_contract(self):
        selected = self._select([self.request])
        arguments = dict(
            role="worker",
            host_adapter_id="codex",
            host_version="0.155.1",
            host_mode="managedTask",
            estimator_id="canonical-json-bytes-div-4-ceil",
            instruction="bounded task",
            schema={},
            current_binding=self._binding(),
        )
        for change in (
            {"selected": selected["selected"] * 3, "selectedUtf8Bytes": selected["selectedUtf8Bytes"] * 3},
            {"contractDigest": "b" * 64},
        ):
            with self.subTest(change=change):
                forged = {**selected, **change}
                forged["receiptDigest"] = canonical_digest({k: v for k, v in forged.items() if k != "receiptDigest"})
                with self.assertRaises(LifecycleError):
                    assess_local_input_fit(self.root, CONTRACT, PROFILE, self.packet, self.summary, forged, **arguments)

    def test_canonical_context_can_include_index_only_metadata(self):
        extra = "tasks/release-2-16/ordinary-release-contract-r105.md"
        allowed = list(CONTRACT["sourceScope"]["orderedContextRefs"])
        self.packet["context"]["refs"] = [extra, *allowed]
        index = validate_context_ref_index(self.packet, CONTRACT)
        self.assertEqual(index["count"], len(allowed) + 1)
        self.assertEqual(index["status"], "PENDING_SOURCE_SELECTION")
        selected = self._select([self.request])
        self.assertEqual(selected["status"], "SELECTED")
        self.assertEqual(selected["indexOnlyCount"], len(allowed) + 1)
        self.assertEqual([entry["path"] for entry in selected["selected"]], [self.path])
        self.assertEqual(CONTRACT["sourceScope"]["orderedContextRefs"], allowed)
        fit = assess_local_input_fit(
            self.root, CONTRACT, PROFILE, self.packet, self.summary, selected,
            role="worker", host_adapter_id="codex", host_version="0.155.1",
            host_mode="managedTask", estimator_id="canonical-json-bytes-div-4-ceil",
            instruction="bounded task", schema={}, current_binding=self._binding(),
        )
        self.assertEqual(fit["status"], "PASS_ALK_COMPONENTS_ONLY")
        self.assertEqual(fit["hostOwnedInput"], "UNAVAILABLE")
        self.assertFalse(fit["fullFinancial"])

    def test_changed_index_only_refs_refuse_after_selection(self):
        allowed = list(CONTRACT["sourceScope"]["orderedContextRefs"])
        extra_a = "tasks/release-2-16/index-a.md"
        extra_b = "tasks/release-2-16/index-b.md"
        extra_c = "tasks/release-2-16/index-c.md"
        self.packet["context"]["refs"] = [extra_a, extra_b, *allowed]
        selected = self._select([self.request])
        changes = {
            "replace": [extra_a, extra_c, *allowed],
            "add": [extra_a, extra_b, extra_c, *allowed],
            "remove": [extra_a, *allowed],
            "reorder": [extra_b, extra_a, *allowed],
        }
        for change, refs in changes.items():
            with self.subTest(change=change):
                self.packet["context"]["refs"] = refs
                validate_context_ref_index(self.packet, CONTRACT)
                with self.assertRaises(LifecycleError) as raised:
                    assess_local_input_fit(
                        self.root, CONTRACT, PROFILE, self.packet, self.summary, selected,
                        role="worker", host_adapter_id="codex", host_version="0.155.1",
                        host_mode="managedTask", estimator_id="canonical-json-bytes-div-4-ceil",
                        instruction="bounded task", schema={}, current_binding=self._binding(),
                    )
                self.assertEqual(raised.exception.code, "source-selection-mismatch")

    def test_forged_context_index_digest_or_count_refuses(self):
        self.packet["context"]["refs"] = [
            "tasks/release-2-16/index-a.md", *CONTRACT["sourceScope"]["orderedContextRefs"]
        ]
        selected = self._select([self.request])
        changes = (
            {"contextRefIndexDigest": "b" * 64},
            {"contextRefIndexDigest": "malformed"},
            {"contextRefIndexDigest": None},
            {"indexOnlyCount": selected["indexOnlyCount"] + 1},
            {"indexOnlyCount": str(selected["indexOnlyCount"])},
            {"indexOnlyCount": float(selected["indexOnlyCount"])},
            {"indexOnlyCount": True},
            {"indexOnlyCount": None},
        )
        for change in changes:
            with self.subTest(change=change):
                forged = {**selected, **change}
                forged["receiptDigest"] = canonical_digest({
                    key: value for key, value in forged.items() if key != "receiptDigest"
                })
                with self.assertRaises(LifecycleError) as raised:
                    assess_local_input_fit(
                        self.root, CONTRACT, PROFILE, self.packet, self.summary, forged,
                        role="worker", host_adapter_id="codex", host_version="0.155.1",
                        host_mode="managedTask", estimator_id="canonical-json-bytes-div-4-ceil",
                        instruction="bounded task", schema={}, current_binding=self._binding(),
                    )
                self.assertEqual(raised.exception.code, "source-selection-mismatch")

    def test_index_only_metadata_never_authorizes_raw_source(self):
        extra = "tasks/release-2-16/ordinary-release-contract-r105.md"
        self.packet["context"]["refs"] = [extra, *CONTRACT["sourceScope"]["orderedContextRefs"]]
        path = self.root / extra
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.data)
        with self.assertRaises(LifecycleError) as raised:
            self._select([{**self.request, "path": extra}])
        self.assertEqual(raised.exception.code, "undeclared-source")

    def test_augmented_context_requires_every_allowed_ref_in_order(self):
        allowed = list(CONTRACT["sourceScope"]["orderedContextRefs"])
        extra = "tasks/release-2-16/ordinary-release-contract-r105.md"
        for changed in (allowed[1:], list(reversed(allowed))):
            with self.subTest(changed=changed):
                self.packet["context"]["refs"] = [extra, *changed]
                with self.assertRaises(LifecycleError) as raised:
                    self._select([self.request])
                self.assertEqual(raised.exception.code, "context-ref-index-mismatch")

    def test_augmented_context_rejects_duplicate_or_unsafe_index_refs(self):
        allowed = list(CONTRACT["sourceScope"]["orderedContextRefs"])
        extra = "tasks/release-2-16/ordinary-release-contract-r105.md"
        invalid = ([extra, extra, *allowed], [allowed[0], *allowed],
                   ["../outside.md", *allowed], ["/absolute.md", *allowed],
                   ["tasks//duplicate-separator.md", *allowed], [None, *allowed])
        for changed in invalid:
            with self.subTest(changed=changed):
                self.packet["context"]["refs"] = changed
                with self.assertRaises(LifecycleError) as raised:
                    self._select([self.request])
                self.assertEqual(raised.exception.code, "context-ref-index-mismatch")



class SupportProfileMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        roles = ("coordinator", "worker", "check", "auditor", "retry", "compaction", "closeout")
        proof = {"path": "source/proof.json", "sha256": HEX, "bytes": 1}
        self.payload = {
            "profileId": "fixture:codex-lifecycle",
            "revision": 1,
            "expectationId": "fixture:codex",
            "binding": {
                "adapterId": "codex",
                "hostVersion": "0.155.1",
                "executableSha256": None,
                "launchMode": "managedTask",
                "providerId": "NOT_CLAIMED",
                "transportId": "NOT_CLAIMED",
                "configurationSha256": None,
                "evidenceMode": "SOURCE_BOUND_LIMITATION",
            },
            "modes": ["LIFECYCLE_ONLY"],
            "claims": [],
            "routes": [
                {
                    "role": role,
                    "routeId": f"route-{role}",
                    "state": "EXCLUDED",
                    "claimIds": [],
                    "reason": "financial coverage unqualified",
                    "sourceIds": ["source-1"],
                }
                for role in roles
            ],
            "sources": [
                {
                    "sourceId": "source-1",
                    "kind": "OFFICIAL_DOCUMENTATION",
                    "origin": "fixture official document",
                    "artifact": proof,
                    "versionApplicability": "fixture version",
                }
            ],
            "sourceCaseDispositions": [
                {
                    "sourceCaseId": f"AC{i:02d}",
                    "sourceCaseSha256": HEX,
                    "claimIds": [],
                    "routeIds": ["route-worker"],
                    "disposition": "QUALIFIED_LIMITATION",
                    "reason": "fixture only; not accepted qualification",
                    "evidenceRefs": [proof],
                }
                for i in range(1, 14)
            ],
            "completeFinancialRun": False,
        }
        self.request = {
            "schemaVersion": "alk-accounting-capability-request.v1",
            "requestId": "request-1",
            "expectationDigest": HEX,
            "profileDigest": canonical_digest(self.payload),
            "planDigest": HEX,
            "alkCandidateDigest": HEX,
            "binding": dict(self.payload["binding"]),
            "operationId": "operation-1",
            "requestedModes": ["LIFECYCLE_ONLY"],
            "requiredClaims": [],
            "routeIds": ["route-worker"],
            "requestedUpperBound": None,
        }

    def _match(self, request=None, payload=None):
        return match_requested_claims(
            payload or self.payload,
            request or self.request,
            expectation_digest=HEX,
            plan_digest=HEX,
            candidate_digest=HEX,
        )

    def test_lifecycle_match_is_never_authority(self):
        self.assertEqual(validate_profile_payload(self.payload)["status"], "STRUCTURE_VALID_ONLY")
        match = self._match()
        self.assertEqual(match["status"], "MATCH_PENDING_EVIDENCE")
        self.assertFalse(match["dispatchEntitlement"])
        self.assertFalse(match["evidenceQualified"])

    def test_stronger_mode_and_wrong_binding_refuse(self):
        stronger = {**self.request, "requestedModes": ["OBSERVATION"]}
        self.assertEqual(self._match(stronger)["detail"], "UNSUPPORTED_GUARANTEE")
        wrong_host = {**self.request, "binding": {**self.request["binding"], "hostVersion": "0.156.0"}}
        self.assertEqual(self._match(wrong_host)["detail"], "BINDING_MISMATCH")

    def test_closed_shape_and_source_only_positive_claim_refuse(self):
        with self.assertRaises(LifecycleError):
            validate_profile_payload({**self.payload, "extra": True})
        with self.assertRaises(LifecycleError):
            validate_profile_payload({**self.payload, "modes": ["FULL_FINANCIAL"], "completeFinancialRun": True})
        with self.assertRaises(LifecycleError):
            validate_profile_payload({**self.payload, "modes": [{}]})
        with self.assertRaises(LifecycleError):
            validate_profile_payload(
                {
                    **self.payload,
                    "sourceCaseDispositions": [
                        *self.payload["sourceCaseDispositions"][:-1],
                        self.payload["sourceCaseDispositions"][0],
                    ],
                }
            )
        self.assertEqual(self._match({**self.request, "requestedModes": [{}]})["detail"], "INVALID_INPUT")

    def test_exact_claim_match_and_wrong_unit_or_fail_policy(self):
        payload = {
            **self.payload,
            "binding": {
                **self.payload["binding"],
                "evidenceMode": "RUNTIME_OBSERVED",
                "executableSha256": HEX,
                "configurationSha256": HEX,
                "providerId": "openai",
                "transportId": "cli",
            },
            "modes": ["ALK_INVOCATION_ADMISSION"],
        }
        routes = [dict(row) for row in payload["routes"]]
        routes[1] = {**routes[1], "state": "COVERED", "claimIds": ["claim-1"]}
        payload["routes"] = routes
        payload["claims"] = [
            {
                "claimId": "claim-1",
                "dimension": "CONTROL",
                "guarantee": "ALK_PRE_LAUNCH",
                "unitId": "alk-owned-invocations",
                "routeIds": ["route-worker"],
                "limitKind": "ADMISSION_ONLY",
                "boundMethodId": None,
                "failurePolicy": "FAIL_CLOSED",
                "sourceIds": ["source-1"],
            }
        ]
        needed = {
            "dimension": "CONTROL",
            "guarantee": "ALK_PRE_LAUNCH",
            "unitId": "alk-owned-invocations",
            "routeIds": ["route-worker"],
            "limitKind": "ADMISSION_ONLY",
            "boundMethodId": None,
            "requireFailClosed": True,
        }
        request = {
            **self.request,
            "binding": dict(payload["binding"]),
            "profileDigest": canonical_digest(payload),
            "requestedModes": ["ALK_INVOCATION_ADMISSION"],
            "requiredClaims": [needed],
        }
        self.assertEqual(self._match(request, payload)["matchedClaimIds"], ["claim-1"])
        self.assertFalse(self._match(request, payload)["dispatchEntitlement"])
        for change in (
            {"unitId": "reportedTokens"},
            {"guarantee": "HOST_SCOPED_LIMIT"},
            {"limitKind": "TASK_RUN_FINANCIAL"},
        ):
            with self.subTest(change=change):
                altered = {**request, "requiredClaims": [{**needed, **change}]}
                self.assertEqual(self._match(altered, payload)["status"], "MISMATCH")
        payload["claims"][0]["failurePolicy"] = "FAIL_OPEN"
        request["profileDigest"] = canonical_digest(payload)
        self.assertEqual(self._match(request, payload)["detail"], "UNSUPPORTED_GUARANTEE")


class FrozenAdapterProfileFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(Path("tests/accounting/fixtures/release_216_adapter_profiles.json").read_text(encoding='utf-8'))
        self.contract = json.loads(Path("tasks/release-2-16/h04-adapter-profile-cases.json").read_text(encoding='utf-8'))

    def test_all_twelve_local_profiles_pin_frozen_expectations_without_native_authority(self):
        self.assertEqual(self.fixture["assurance"], "SYNTHETIC_STRUCTURE_AND_REFUSAL_ONLY")
        self.assertIs(self.fixture["runtimeQualification"], False)
        self.assertIs(self.fixture["dispatchEntitlement"], False)
        for ref in self.fixture["contractRefs"]:
            raw = Path(ref["path"]).read_bytes()
            expected = (ref["sha256"], ref["bytes"])
            if ref["path"] == "tasks/release-2-16/h04-artifact-contracts.json":
                # Keep the historical fixture unchanged, while checking the
                # reviewed current frozen contract against its exact new pin.
                self.assertEqual(expected, (
                    "1118dd9c3b6e4bbfaf42265f8936bbdb8ff21177d03a56b5b72b61a87a1bf4ec", 42910
                ))
                expected = ("e54a9847e441b1d9253a8d1192d8f209a886f36bf953045dea99217ee9a9fd98", 43190)
            elif ref["path"] == "tasks/release-2-16/alk-input-fit-contract.json":
                self.assertEqual(expected, (
                    "b651e81f41f2feb4dfbdcd2b22dab67308273b3c4f746f83651391226c479e55", 119027
                ))
                expected = ("8f42383070b0103df4967797aaa34b2f2fb71ea2ebf9896ac6581c8f775ac531", 119260)
            self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), expected)
        expected = {e["adapterId"]: e for e in self.contract["expectedBindings"]["entries"]}
        profiles = self.fixture["profiles"]
        self.assertEqual(len(profiles), 12)
        self.assertEqual({p["binding"]["adapterId"] for p in profiles}, set(expected))
        for payload in profiles:
            with self.subTest(adapter=payload["binding"]["adapterId"]):
                e = expected[payload["binding"]["adapterId"]]
                self.assertEqual(payload["expectationId"], e["expectationId"])
                self.assertEqual(payload["binding"]["hostVersion"], e["target"]["version"])
                self.assertEqual(validate_profile_payload(payload)["status"], "STRUCTURE_VALID_ONLY")
                self.assertEqual({r["role"] for r in payload["routes"]},
                                 {"coordinator", "worker", "check", "auditor", "retry", "compaction", "closeout"})
                self.assertEqual({r["sourceCaseId"]: r["sourceCaseSha256"]
                                  for r in payload["sourceCaseDispositions"]}, self.contract["originalSourceCaseHashes"])
                self.assertTrue(all(r["disposition"] == "UNQUALIFIED" for r in payload["sourceCaseDispositions"]))
                self.assertFalse(payload["completeFinancialRun"])
                self.assertIsNone(payload["binding"]["executableSha256"])
                self.assertIsNone(payload["binding"]["configurationSha256"])

    def test_every_local_adapter_refuses_stronger_guarantees_and_changed_binding(self):
        for payload in self.fixture["profiles"]:
            request = {"schemaVersion": "alk-accounting-capability-request.v1", "requestId": "local-request",
                       "expectationDigest": HEX, "profileDigest": canonical_digest(payload), "planDigest": HEX,
                       "alkCandidateDigest": HEX, "binding": dict(payload["binding"]), "operationId": "local-op",
                       "requestedModes": ["LIFECYCLE_ONLY"], "requiredClaims": [],
                       "routeIds": [payload["routes"][0]["routeId"]], "requestedUpperBound": None}
            for mode in ("OBSERVATION", "ALK_INVOCATION_ADMISSION", "HOST_PARTIAL_CONTROL", "FULL_FINANCIAL"):
                with self.subTest(adapter=payload["binding"]["adapterId"], mode=mode):
                    out = match_requested_claims(payload, {**request, "requestedModes": [mode]},
                                                 expectation_digest=HEX, plan_digest=HEX, candidate_digest=HEX)
                    self.assertEqual(out["status"], "MISMATCH")
                    self.assertEqual(out["detail"], "UNSUPPORTED_GUARANTEE")
                    self.assertFalse(out["dispatchEntitlement"])
            request["binding"]["hostVersion"] += "-changed"
            out = match_requested_claims(payload, request, expectation_digest=HEX, plan_digest=HEX, candidate_digest=HEX)
            self.assertEqual(out["detail"], "BINDING_MISMATCH")
            self.assertFalse(out["dispatchEntitlement"])


if __name__ == "__main__":
    unittest.main()
