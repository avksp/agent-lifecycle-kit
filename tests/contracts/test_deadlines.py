"""Original deadline invariants remain distinct from a closing permission."""

from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.deadline_schemas import (
    DURATION_RULE_V1,
    FIXED_DEADLINE_RULE_V1,
    FRESHNESS_RULE_V1,
    PERMISSION_RULE_V1,
    validate_duration_rule,
    validate_fixed_deadline_rule,
)
from agent_lifecycle.contracts.deadlines import (
    evaluate_original_duration,
    evaluate_original_freshness,
    evaluate_original_permission,
    evaluate_activation_deadline_binding,
    evaluate_original_freshness_binding,
    evaluate_late_result_applicability,
)
from agent_lifecycle.contracts.schemas import get_schema


def _permission(replacement: str = "RETAIN_ORIGINAL") -> dict:
    return {
        "kind": "EXECUTION_PERMISSION",
        "originalAuthorizationRef": {"path": "proof/original.json", "sha256": "a" * 64, "bytes": 12},
        "validFrom": "2026-09-23T01:00:00.000000Z",
        "expiresAt": "2026-09-23T02:00:00.000000Z",
        "replacement": replacement,
    }


def _duration(comparison: str = "LT") -> dict:
    return {
        "kind": "RUN_WALL_BUDGET", "originAt": "2026-09-23T01:00:00.000000Z",
        "limitSeconds": 3600, "originalDeadlineAt": "2026-09-23T02:00:00.000000Z",
        "replacement": "RETAIN_ORIGINAL", "comparison": comparison,
    }


def _freshness(age: int | None = 3600) -> dict:
    return {"kind": "EVIDENCE_FRESHNESS", "receiptSelector": "QUALIFIED_CURRENT_OPERATION_EVIDENCE_V1",
            "maxAgeSeconds": age, "replacement": "RETAIN_ORIGINAL"}


class DeadlineContractTests(unittest.TestCase):
    @staticmethod
    def _activation_inputs():
        from tests.contracts.test_closing_window_schemas import _fixture
        fixture = _fixture(); request = fixture["request"]
        inventory = {"schemaVersion": "agent-closing-deadline-inventory.v1", "bindingId": "binding", "runId": "run",
                     "journalIdentity": "journal", "planDigest": request["scope"]["effectivePlanDigest"],
                     "sourceRevision": request["scope"]["sourceRevision"], "adoptionConfigurationDigest": "a" * 64,
                     "compiledControllerGatesDigest": "b" * 64, "runtimeRegistryDigest": "c" * 64,
                     "clockPolicy": "QUALIFIED_HOST_UTC_NONDECREASING",
                     "clockQualificationRef": {"path": "clock.json", "sha256": "d" * 64, "bytes": 10},
                     "inventoryQualificationRef": {"path": "inventory.json", "sha256": "e" * 64, "bytes": 10},
                     "coveredRoutes": ["ACTIVATE", "CONTINUE"],
                     "bindings": [{"bindingKey": key, "source": {"fixture": "UNQUALIFIED_LOCAL_PROJECTION"},
                                   "taskId": None, "phases": ["RUNNING"], "operations": [route],
                                   "rule": _freshness(), "validityEvidenceMode": "CURRENT_SQL_STATE"}
                                  for key, route in (("activate", "ACTIVATE"), ("continue", "CONTINUE"))]}
        request.update(deadlineInventoryDigest=canonical_digest(inventory), deadlineConsumerIds=["activate", "continue"])
        data = {"schemaVersion": "agent-closing-deadline-input.v1", "bindingId": "binding", "inventoryDigest": canonical_digest(inventory),
                "operationId": "activate-operation", "operationKind": "ACTIVATE", "taskId": "task", "phase": "RUNNING",
                "expectedWorkflowRevision": request["expectedWorkflowRevision"], "expectedAuthorityEpoch": 0,
                "closingWindowId": "window", "originalAuthorizationDigest": request["originalAuthorizationDigest"],
                "closingGrantDigest": canonical_digest(fixture["grant"]), "applicabilityAssessmentRefs": [], "currentReceiptObservations": []}
        clock = {"schemaVersion": "agent-workflow-clock-observation.v1", "journalIdentity": "journal", "processIdentity": "process",
                 "observedAt": fixture["observed_at"], "monotonicNanos": 10, "monotonicOriginId": "origin", "previousAcceptedUtc": None,
                 "clockQualificationDigest": "d" * 64}
        selected = {key: data[key] for key in ("bindingId", "closingWindowId", "operationId", "phase", "taskId", "expectedWorkflowRevision",
                                              "expectedAuthorityEpoch", "originalAuthorizationDigest", "closingGrantDigest")}
        selected.update({key: inventory[key] for key in ("sourceRevision", "planDigest", "adoptionConfigurationDigest", "compiledControllerGatesDigest",
                                                        "runtimeRegistryDigest", "journalIdentity")})
        selected.update(inventoryDigest=canonical_digest(inventory), deadlineInputDigest=canonical_digest(data),
                        originalDeadlineDigest=request["originalDeadlineDigest"], originalValidFrom=request["validFrom"], originalExpiresAt=request["expiresAt"],
                        grantValidFrom=fixture["grant"]["validFrom"], grantExpiresAt=fixture["grant"]["expiresAt"],
                        clockObservationDigest=canonical_digest(clock), clockQualificationDigest="d" * 64, clockProcessIdentity="process", clockOriginId="origin",
                        expectedCoveredRoutes=["ACTIVATE", "CONTINUE"], expectedApplicableConsumerIds=["activate"])
        return request, inventory, data, clock, selected

    def test_wr05_activation_deadline_binding_and_each_mismatch(self):
        args = self._activation_inputs(); saved = deepcopy(args)
        result = evaluate_activation_deadline_binding(*args)
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        self.assertTrue(all(result[key] is False for key in ("fullNestedWireValidated", "nativeClockQualified", "nativePermissionGranted",
                                                           "nativeActivationGranted", "dispatchAuthorized", "financialAdmission", "nonceConsumed")))
        for consumers in ([], ["activate"], ["activate", "continue", "extra"], ["activate", "activate"], ["continue", "activate"]):
            altered = deepcopy(args); altered[0]["deadlineConsumerIds"] = consumers
            with self.subTest(consumers=consumers), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
        changes = {"expectedAuthorityEpoch": 1, "expectedWorkflowRevision": True, "operationKind": "CLAIM", "operationId": "other",
                   "closingWindowId": "other", "phase": "FINAL_AUDIT", "taskId": "other", "closingGrantDigest": "f" * 64,
                   "inventoryDigest": "f" * 64, "originalAuthorizationDigest": "f" * 64}
        for key, value in changes.items():
            altered = deepcopy(args)
            if value == altered[2][key]: value = "e" * 64
            self.assertNotEqual(value, altered[2][key])
            altered[2][key] = value
            with self.subTest(input=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
        for key, value in (("journalIdentity", "other"), ("clockQualificationDigest", "f" * 64), ("monotonicNanos", True),
                           ("observedAt", "2026-02-30T01:30:00.000000Z"), ("processIdentity", "other"), ("monotonicOriginId", "other")):
            altered = deepcopy(args); altered[3][key] = value
            with self.subTest(clock=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
        for index, key, value in ((0, "originalDeadlineDigest", "f" * 64), (1, "runtimeRegistryDigest", "f" * 64),
                                  (4, "expectedAuthorityEpoch", True), (4, "clockObservationDigest", "f" * 64),
                                  (4, "expectedApplicableConsumerIds", []), (4, "expectedCoveredRoutes", ["ACTIVATE"])):
            altered = deepcopy(args); altered[index][key] = value
            with self.subTest(independent=index, key=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
        altered = deepcopy(args); altered[3]["observedAt"] = altered[0]["expiresAt"]
        altered[4]["clockObservationDigest"] = canonical_digest(altered[3])
        with self.assertRaises(LifecycleError):
            evaluate_activation_deadline_binding(*altered)
        # Re-pin only synthetic complete-document digests to reach the later independent identity joins.
        for key, value in changes.items():
            altered = deepcopy(args)
            if value == altered[2][key]: value = "e" * 64
            altered[2][key] = value; altered[4]["deadlineInputDigest"] = canonical_digest(altered[2])
            before = canonical_bytes(altered)
            with self.subTest(isolatedInput=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
            self.assertEqual(canonical_bytes(altered), before)
        for key in ("journalIdentity", "processIdentity", "monotonicOriginId", "clockQualificationDigest"):
            altered = deepcopy(args); altered[3][key] = "f" * 64 if key.endswith("Digest") else "other"
            altered[4]["clockObservationDigest"] = canonical_digest(altered[3]); before = canonical_bytes(altered)
            with self.subTest(isolatedClock=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
            self.assertEqual(canonical_bytes(altered), before)
        for mode in ([], {}, None, True):
            altered = deepcopy(args); altered[1]["bindings"][0]["validityEvidenceMode"] = mode
            altered[0]["deadlineInventoryDigest"] = altered[2]["inventoryDigest"] = altered[4]["inventoryDigest"] = canonical_digest(altered[1])
            altered[4]["deadlineInputDigest"] = canonical_digest(altered[2]); before = canonical_bytes(altered)
            with self.subTest(malformedMode=mode), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
            self.assertEqual(canonical_bytes(altered), before)
        for key, value in (("phases", ["FINAL_AUDIT"]), ("operations", ["CONTINUE"]), ("taskId", "other")):
            altered = deepcopy(args); altered[1]["bindings"][0][key] = value
            altered[0]["deadlineInventoryDigest"] = altered[2]["inventoryDigest"] = altered[4]["inventoryDigest"] = canonical_digest(altered[1])
            altered[4]["deadlineInputDigest"] = canonical_digest(altered[2])
            with self.subTest(isolatedApplicability=key), self.assertRaises(LifecycleError):
                evaluate_activation_deadline_binding(*altered)
        altered = deepcopy(args); del altered[4]["clockOriginId"]
        with self.assertRaises(LifecycleError):
            evaluate_activation_deadline_binding(*altered)
        self.assertEqual(args, saved)
        self.assertNotIn("clockObservation", args[2])
        self.assertNotIn("deadlineInputDigest", args[1])

    def test_local_original_freshness_and_each_independent_binding(self):
        rule = _freshness(3600)
        observation = {"bindingKey": "fresh", "requiredEvidenceBindingDigest": "a" * 64, "sourceBindingDigest": "b" * 64,
                       "producerOperationId": "producer", "consumerOperationId": "consumer", "producerGenerationDigest": "c" * 64,
                       "expectedWorkflowRevision": 2, "receiptRef": {"path": "r0.json", "sha256": "d" * 64, "bytes": 12},
                       "generatedAt": "2026-09-23T01:00:00.000000Z"}
        expected = {key: deepcopy(value) for key, value in observation.items() if key != "generatedAt"}
        expected.update(originalObservationDigest=canonical_digest(observation), originalRuleDigest=canonical_digest(rule))
        saved = canonical_bytes([rule, observation, expected])
        for now, disposition in (("2026-09-23T01:30:00.000000Z", "DATA_CANDIDATE"), ("2026-09-23T02:00:00.000000Z", "DATA_CANDIDATE"),
                                 ("2026-09-23T02:00:00.000001Z", "REFUSED"), ("2026-09-23T00:59:59.999999Z", "REFUSED")):
            result = evaluate_original_freshness_binding(rule, observation, now, expected)
            self.assertEqual(result["disposition"], disposition)
            self.assertIs(result["dataBindingMatched"], True)
            self.assertTrue(all(result[key] is False for key in ("nativeEvidenceBindingVerified", "nativePermissionGranted", "nativeClockQualified", "nativeActivationGranted", "dispatchAuthorized")))
        for key in expected:
            altered = deepcopy(expected)
            altered[key] = (3 if key == "expectedWorkflowRevision" else {"path": "other.json", "sha256": "e" * 64, "bytes": 12}
                            if key == "receiptRef" else "e" * 64 if key.endswith("Digest") else "other")
            with self.subTest(identity=key), self.assertRaises(LifecycleError):
                evaluate_original_freshness_binding(rule, observation, "2026-09-23T01:30:00.000000Z", altered)
        changes = [("observation", "generatedAt", "2026-09-23T01:29:00.000000Z"), ("rule", "maxAgeSeconds", 7200),
                   ("rule", "maxAgeSeconds", None), ("rule", "receiptSelector", "OTHER"), ("observation", "expectedWorkflowRevision", True)]
        for side, key, value in changes:
            r, o = deepcopy(rule), deepcopy(observation); (o if side == "observation" else r)[key] = value
            with self.subTest(substitution=key, value=value), self.assertRaises(LifecycleError):
                evaluate_original_freshness_binding(r, o, "2026-09-23T01:30:00.000000Z", expected)
        null_rule = _freshness(None); null_expected = {**expected, "originalRuleDigest": canonical_digest(null_rule)}
        self.assertEqual(evaluate_original_freshness_binding(null_rule, observation, "2026-09-24T01:30:00.000000Z", null_expected)["disposition"], "DATA_CANDIDATE")
        with self.assertRaises(LifecycleError):
            evaluate_original_freshness_binding(rule, observation, "2026-09-23T01:30:00.000000Z", null_expected)
        altered = deepcopy(expected); del altered["sourceBindingDigest"]
        with self.assertRaises(LifecycleError):
            evaluate_original_freshness_binding(rule, observation, "2026-09-23T01:30:00.000000Z", altered)
        self.assertEqual(canonical_bytes([rule, observation, expected]), saved)

    @staticmethod
    def _late_inputs():
        keys = ["subjectDigest", "sourceDigest", "configurationDigest", "oracleDigest", "producerDigest", "producerOperationId",
                "consumerOperationId", "producerGenerationDigest", "controllerGateDigest", "clockDigest", "workflowGenerationDigest", "accountingGenerationDigest"]
        identities = {key: "a" * 64 if key.endswith("Digest") else key for key in keys}
        original = {"evidenceRef": {"path": "late.json", "sha256": "b" * 64, "bytes": 20}, "body": {"result": "original"}, "verdict": "PASS",
                    "completedAt": "2026-09-23T01:59:00.000000Z", "deadlineAt": "2026-09-23T02:00:00.000000Z",
                    "generatedAt": "2026-09-23T01:00:00.000000Z", "maxAgeSeconds": 3600, "identities": identities,
                    "facts": {key: True for key in ("technicalValidity", "controllerGateMatched", "clockBindingMatched", "workflowGenerationMatched", "accountingGenerationMatched")},
                    "expenses": {"actualTokens": None, "reportedTokens": 100, "unknownTokens": None, "capConformance": None}}
        selected = {"identities": deepcopy(identities), "requireFullCost": False, "requireCapConformance": False}
        dependencies = [{"proofId": "proof-a", "original": {"helper": "c" * 64}, "current": {"helper": "c" * 64}, "missing": False, "bindingKeys": keys, "determinationKeys": [*original["facts"], "capConformance"]},
                        {"proofId": "proof-b", "original": {"helper": "d" * 64}, "current": {"helper": "d" * 64}, "missing": False, "bindingKeys": ["subjectDigest"], "determinationKeys": []}]
        return original, selected, dependencies

    def test_dd11_late_applicability_preserves_result_costs_and_only_affected_proofs(self):
        args = self._late_inputs(); saved = canonical_bytes(args)
        for at in ("2026-09-23T01:59:59.999999Z", "2026-09-23T02:00:00.000000Z", "2026-09-23T02:00:00.000001Z"):
            for verdict in ("PASS", "FAIL"):
                altered = deepcopy(args); altered[0].update(completedAt=at, verdict=verdict); altered[0]["expenses"]["reportedTokens"] = 500000
                result = evaluate_late_result_applicability(*altered)
                self.assertEqual((result["disposition"], result["affectedProofIds"]), ("REUSE", [])); self.assertEqual(result["original"], altered[0])
                self.assertTrue(all(result[key] is False for key in ("nativePermissionGranted", "nativeClockQualified", "dispatchAuthorized", "acceptanceGranted", "rerunDispatched")))
        for key in args[1]["identities"]:
            altered = deepcopy(args); altered[1]["identities"][key] = "e" * 64 if key.endswith("Digest") else "other"
            result = evaluate_late_result_applicability(*altered)
            self.assertEqual(result["disposition"], "RERUN_REQUIRED")
            self.assertEqual(result["affectedProofIds"], ["proof-a", "proof-b"] if key == "subjectDigest" else ["proof-a"])
            self.assertEqual(result["original"], altered[0])
        altered = deepcopy(args); altered[2][1]["current"]["helper"] = "e" * 64
        self.assertEqual(evaluate_late_result_applicability(*altered)["affectedProofIds"], ["proof-b"])
        altered = deepcopy(args); altered[2][1].update(missing=True, current={"helper": None})
        self.assertEqual(evaluate_late_result_applicability(*altered)["affectedProofIds"], ["proof-b"])
        for kind in ("binding", "fact", "cost", "cap", "dependency"):
            altered = deepcopy(args)
            if kind == "binding": altered[0]["identities"]["clockDigest"] = None
            elif kind == "fact": altered[0]["facts"]["workflowGenerationMatched"] = None
            elif kind == "cost": altered[1]["requireFullCost"] = True
            elif kind == "cap": altered[1]["requireCapConformance"] = True
            else: altered[2][1]["current"]["helper"] = None
            self.assertEqual(evaluate_late_result_applicability(*altered)["disposition"], "UNAVAILABLE")
        for fact in args[0]["facts"]:
            altered = deepcopy(args); altered[0]["facts"][fact] = False
            result = evaluate_late_result_applicability(*altered)
            self.assertEqual((result["disposition"], result["affectedProofIds"]), ("RERUN_REQUIRED", ["proof-a"]))
            self.assertEqual(result["original"], altered[0])
        for cap in (True, False):
            altered = deepcopy(args); altered[1]["requireCapConformance"] = True; altered[0]["expenses"]["capConformance"] = cap
            self.assertEqual(evaluate_late_result_applicability(*altered)["disposition"], "UNAVAILABLE")
            altered[0]["expenses"].update(actualTokens=100, unknownTokens=0)
            result = evaluate_late_result_applicability(*altered)
            self.assertEqual((result["disposition"], result["affectedProofIds"]), ("REUSE", []) if cap else ("RERUN_REQUIRED", ["proof-a"]))
            self.assertEqual(result["original"], altered[0])
        altered = deepcopy(args); altered[1]["identities"]["oracleDigest"] = "e" * 64
        for row in altered[2]: row["bindingKeys"] = [key for key in row["bindingKeys"] if key != "oracleDigest"]
        self.assertEqual(evaluate_late_result_applicability(*altered)["disposition"], "UNAVAILABLE")
        altered = deepcopy(args); altered[0]["facts"]["clockBindingMatched"] = False
        for row in altered[2]: row["determinationKeys"] = []
        self.assertEqual(evaluate_late_result_applicability(*altered)["disposition"], "UNAVAILABLE")
        for kind in ("duplicate", "boolean", "missingExpected"):
            altered = deepcopy(args)
            if kind == "duplicate": altered[2].append(deepcopy(altered[2][0]))
            elif kind == "boolean": altered[0]["expenses"]["reportedTokens"] = True
            else: del altered[1]["identities"]["controllerGateDigest"]
            with self.assertRaises(LifecycleError): evaluate_late_result_applicability(*altered)
        self.assertEqual(canonical_bytes(args), saved)

    def test_dd01_permission_interval_is_half_open_and_replacement_not_inferred(self) -> None:
        self.assertEqual(get_schema(PERMISSION_RULE_V1)["$id"], PERMISSION_RULE_V1)
        original = _permission()
        self.assertEqual(evaluate_original_permission(original, original["validFrom"])["disposition"], "DATA_CANDIDATE")
        self.assertEqual(evaluate_original_permission(original, original["expiresAt"])["disposition"], "REFUSED_OR_NATIVE_INTERSECTION_REQUIRED")
        replaced = _permission("SIGNED_CLOSING_PERMISSION_V1")
        result = evaluate_original_permission(replaced, "2026-09-23T01:30:00.000000Z")
        self.assertEqual(result["disposition"], "REFUSED_OR_NATIVE_INTERSECTION_REQUIRED")
        self.assertIs(result["nativeAuthorityGranted"], False)
        with self.assertRaises(LifecycleError):
            evaluate_original_permission(original, "2026-09-23T01:30:00Z")

    def test_dd02_dd14_duration_keeps_original_origin_and_comparator(self) -> None:
        self.assertEqual(get_schema(DURATION_RULE_V1)["$id"], DURATION_RULE_V1)
        rule = _duration()
        self.assertIs(validate_duration_rule(rule), rule)
        self.assertEqual(evaluate_original_duration(rule, rule["originalDeadlineAt"])["disposition"], "REFUSED")
        self.assertEqual(evaluate_original_duration(_duration("LTE"), rule["originalDeadlineAt"])["disposition"], "DATA_CANDIDATE")
        changed = {**rule, "originalDeadlineAt": "2026-09-23T03:00:00.000000Z"}
        with self.assertRaises(LifecycleError):
            validate_duration_rule(changed)
        with self.assertRaises(LifecycleError):
            validate_duration_rule({**rule, "limitSeconds": True})

    def test_dd04_original_evidence_age_is_inclusive_to_microsecond(self) -> None:
        self.assertEqual(get_schema(FRESHNESS_RULE_V1)["$id"], FRESHNESS_RULE_V1)
        rule = _freshness(3600)
        generated = "2026-09-23T01:00:00.000000Z"
        self.assertEqual(evaluate_original_freshness(rule, generated, "2026-09-23T02:00:00.000000Z")["disposition"], "DATA_CANDIDATE")
        self.assertEqual(evaluate_original_freshness(rule, generated, "2026-09-23T02:00:00.000001Z")["disposition"], "REFUSED")
        self.assertEqual(evaluate_original_freshness(rule, generated, "2026-09-23T00:59:59.999999Z")["disposition"], "REFUSED")
        self.assertEqual(evaluate_original_freshness(_freshness(None), generated, "2026-09-24T01:00:00.000000Z")["disposition"], "DATA_CANDIDATE")
        self.assertEqual(evaluate_original_freshness(_freshness(0), generated, generated)["disposition"], "DATA_CANDIDATE")
        self.assertEqual(evaluate_original_freshness(_freshness(0), generated, "2026-09-23T01:00:00.000001Z")["disposition"], "REFUSED")

    def test_dd05_fixed_native_limit_cannot_be_replaced_by_window(self) -> None:
        rule = {
            "kind": "WORKER_LEASE",
            "sourceDeadlineRef": {"path": "proof/lease.json", "sha256": "b" * 64, "bytes": 16},
            "deadlineAt": "2026-09-23T02:00:00.000000Z",
            "clockDomain": "QUALIFIED_UTC",
            "replacement": "RETAIN_ORIGINAL",
        }
        self.assertEqual(get_schema(FIXED_DEADLINE_RULE_V1)["$id"], FIXED_DEADLINE_RULE_V1)
        self.assertIs(validate_fixed_deadline_rule(rule), rule)
        for change in ({"replacement": "SIGNED_CLOSING_PERMISSION_V1"}, {"deadlineAt": None},
                       {"clockDomain": "UNKNOWN"}):
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_fixed_deadline_rule({**rule, **change})
