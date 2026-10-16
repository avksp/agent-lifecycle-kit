"""Typed evidence cannot become acceptance from a shape or producer claim."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.evidence_receipt_schemas import (
    ASYNC_V1,
    COMMAND_V1,
    COMPOSITE_V1,
    EXPECTED_V1,
    EXPECTED_V2,
    RECEIPT_V1,
    classify_evidence_candidate,
    load_evidence_receipt_bytes,
    validate_evidence_receipt_shape,
    validate_expected_evidence,
)
from agent_lifecycle.contracts.schemas import get_schema

FIXTURE = Path(__file__).resolve().parents[1] / "audit/fixtures/release_216_evidence_contracts.json"
MANIFEST = Path(__file__).resolve().parents[2] / "tasks/release-2-16/plan.manifest.json"


def _bind(receipt: dict) -> dict:
    value = copy.deepcopy(receipt)
    value["payloadDigest"] = canonical_digest(value["payload"])
    value["receiptDigest"] = canonical_digest({key: item for key, item in value.items() if key != "receiptDigest"})
    return value


class EvidenceReceiptSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["authority"], "SYNTHETIC_SHAPE_ONLY")
        self.assertFalse(fixture["nativeAcceptance"])
        self.descriptor = fixture["descriptor"]
        self.receipt = fixture["receipt"]

    def test_closed_synthetic_receipt_is_only_a_data_candidate(self) -> None:
        for schema_id in (EXPECTED_V1, RECEIPT_V1, COMMAND_V1, COMPOSITE_V1, ASYNC_V1):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)
        self.assertEqual(validate_expected_evidence(self.descriptor), self.descriptor)
        self.assertEqual(validate_evidence_receipt_shape(self.receipt), self.receipt)
        self.assertEqual(load_evidence_receipt_bytes(canonical_bytes(self.receipt)), self.receipt)
        result = classify_evidence_candidate(
            self.receipt, descriptor=self.descriptor, evidence_id=self.receipt["evidenceId"],
            expected_subject=self.receipt["subject"],
        )
        self.assertEqual(result["status"], "DATA_CANDIDATE")
        self.assertFalse(result["acceptanceAuthority"])

    def test_closed_bounds_types_and_unsupported_payload_kind(self) -> None:
        mutations = (
            ("boolean attempt", lambda value: value["subject"]["taskBindings"][0].update(attempt=True)),
            ("oversized reference", lambda value: value["payload"]["commands"][0]["stdout"].update(bytes=8_388_609)),
            ("oversized case id", lambda value: value["payload"]["commands"][0]["cases"][0].update(id="x" * 129)),
            ("float exit code", lambda value: value["payload"]["commands"][0].update(exitCode=0.0)),
            ("unsupported kind", lambda value: value["payload"].update(schemaVersion="agent-unknown-observation.v1")),
        )
        for name, mutate in mutations:
            value = copy.deepcopy(self.receipt)
            mutate(value)
            with self.subTest(case=name), self.assertRaises(LifecycleError):
                validate_evidence_receipt_shape(_bind(value))

    def _async_receipt(self, root: Path, *, end_ms: int, violations: int = 0) -> tuple[dict, dict]:
        observation = canonical_bytes({"readyAtMs": 0, "coverageEndMs": end_ms, "violationCount": violations})
        (root / "observation.json").write_bytes(observation)
        value = copy.deepcopy(self.receipt)
        value["payload"] = {
            "schemaVersion": ASYNC_V1, "surfaceId": "local-event-listener", "readinessId": "listener-ready",
            "clockId": "test-monotonic", "readyAtMs": 0, "coverageStartMs": 0, "coverageEndMs": end_ms,
            "boundary": {"kind": "duration", "atMs": end_ms}, "violationCount": violations,
            "observationArtifact": {"path": "observation.json", "sha256": hashlib.sha256(observation).hexdigest(),
                                    "bytes": len(observation)},
        }
        descriptor = copy.deepcopy(self.descriptor)
        descriptor.update(kind="async-observation", requirements={
            "surfaceId": "local-event-listener", "readinessId": "listener-ready",
            "boundary": {"kind": "duration", "minimumMilliseconds": 20},
        })
        return _bind(value), descriptor

    def test_async_readiness_and_coverage_use_observed_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic_ns()
            absent_violation = threading.Event()
            self.assertFalse(absent_violation.wait(0.03))
            elapsed = (time.monotonic_ns() - started) // 1_000_000
            self.assertGreaterEqual(elapsed, 20)
            value, descriptor = self._async_receipt(Path(directory), end_ms=elapsed)
            candidate = classify_evidence_candidate(value, descriptor=descriptor,
                evidence_id=value["evidenceId"], expected_subject=value["subject"])
            self.assertEqual(candidate["status"], "DATA_CANDIDATE")
            self.assertFalse(candidate["acceptanceAuthority"])
            mutations = (
                ("wrong readiness", lambda payload: payload.update(readinessId="not-ready")),
                ("wrong surface", lambda payload: payload.update(surfaceId="other-surface")),
                ("uncovered readiness", lambda payload: payload.update(coverageStartMs=1)),
                ("truncated coverage", lambda payload: payload.update(coverageEndMs=elapsed - 1)),
                ("insufficient duration", lambda payload: payload["boundary"].update(atMs=19)),
            )
            for name, mutate in mutations:
                altered = copy.deepcopy(value)
                mutate(altered["payload"])
                with self.subTest(case=name), self.assertRaises(LifecycleError):
                    classify_evidence_candidate(_bind(altered), descriptor=descriptor,
                        evidence_id=altered["evidenceId"], expected_subject=altered["subject"])

    def test_async_seeded_delayed_violation_cannot_back_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            violation = threading.Event()
            started = time.monotonic_ns()
            timer = threading.Timer(0.01, violation.set)
            self.addCleanup(timer.cancel)
            timer.start()
            self.assertTrue(violation.wait(1), "seeded violation must actually be observed")
            timer.join(1)
            self.assertFalse(timer.is_alive())
            detected = (time.monotonic_ns() - started) // 1_000_000
            self.assertGreater(detected, 0, "violation must arrive after readiness")
            time.sleep(0.02)
            elapsed = (time.monotonic_ns() - started) // 1_000_000
            value, descriptor = self._async_receipt(Path(directory), end_ms=elapsed,
                                                   violations=int(violation.is_set()))
            self.assertEqual(value["payload"]["violationCount"], 1)
            validate_evidence_receipt_shape(value)
            with self.assertRaisesRegex(LifecycleError, "observed violation"):
                classify_evidence_candidate(value, descriptor=descriptor,
                    evidence_id=value["evidenceId"], expected_subject=value["subject"])

    def test_frozen_release_descriptors_use_the_published_closed_contract(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        published_ids = {
            "EV216-SCHEMA",
            "EV216-BINDING",
            "EV216-RECEIPT",
            "EV216-PROVENANCE",
            "EV216-IMPORT",
            "EV216-PUBLICATION",
            "EV216-ACCOUNTING-CORE",
            "EV216-ACCOUNTING-ENFORCEMENT",
            "EV216-FINALIZATION-RECOVERY",
            "EV216-CLOSING-WINDOW",
            "EV216-CLOSING-POLICY",
            "EV216-WORKFLOW-STORE",
            "EV216-WORKFLOW-AUTHORITY",
            "EV216-CLOSING-RESOURCES",
            "EV216-DEADLINE-CONTRACT",
            "EV216-SOURCE-USAGE",
        }
        entries = manifest["acceptance"]["evidence"]
        published = [entry for entry in entries if entry["id"] in published_ids]
        self.assertEqual(len(published), 16)
        self.assertEqual({entry["id"] for entry in published}, published_ids)
        internal = [entry for entry in entries if entry["id"] not in published_ids]
        self.assertLessEqual(len(internal), 1)
        for entry in internal:
            self.assertEqual(entry["id"], "EV216-NATIVE-RENEWAL")
        for entry in entries:
            with self.subTest(evidence_id=entry["id"]):
                self.assertIn("validation", entry)
                validate_expected_evidence(entry["validation"])

    def test_descriptor_rejects_unsorted_and_unexpected_requirements(self) -> None:
        value = copy.deepcopy(self.descriptor)
        value["components"][0]["oraclePaths"] = ["z.py", "a.py"]
        with self.assertRaises(LifecycleError):
            validate_expected_evidence(value)
        value = copy.deepcopy(self.descriptor)
        value["requirements"]["unknown"] = True
        with self.assertRaises(LifecycleError):
            validate_expected_evidence(value)
        value = copy.deepcopy(self.descriptor)
        value["components"][0]["configurationPaths"] = ["../escape"]
        with self.assertRaises(LifecycleError):
            validate_expected_evidence(value)
        value = copy.deepcopy(self.descriptor)
        value["kind"] = []
        with self.assertRaises(LifecycleError):
            validate_expected_evidence(value)

    def test_receipt_rejects_digest_duplicate_member_and_false_success(self) -> None:
        value = copy.deepcopy(self.receipt)
        value["payload"]["commands"][0]["exitCode"] = None
        value = _bind(value)
        with self.assertRaises(LifecycleError):
            validate_evidence_receipt_shape(value)
        value = copy.deepcopy(self.receipt)
        value["payloadDigest"] = "0" * 64
        with self.assertRaises(LifecycleError):
            validate_evidence_receipt_shape(value)
        value = copy.deepcopy(self.receipt)
        value["extra"] = True
        with self.assertRaises(LifecycleError):
            validate_evidence_receipt_shape(value)
        value = copy.deepcopy(self.receipt)
        value["producer"]["guarantee"] = []
        with self.assertRaises(LifecycleError):
            validate_evidence_receipt_shape(value)
        raw = canonical_bytes(self.receipt).replace(b'{"evidenceId":', b'{"evidenceId":"duplicate","evidenceId":', 1)
        with self.assertRaises(LifecycleError):
            load_evidence_receipt_bytes(raw)

    def test_independent_expectation_and_required_case_are_enforced(self) -> None:
        subject = copy.deepcopy(self.receipt["subject"])
        subject["taskBindings"][0]["attempt"] = 2
        with self.assertRaises(LifecycleError):
            classify_evidence_candidate(self.receipt, descriptor=self.descriptor,
                                        evidence_id=self.receipt["evidenceId"], expected_subject=subject)
        value = copy.deepcopy(self.receipt)
        value["payload"]["commands"][0]["cases"][0]["status"] = "SKIPPED"
        with self.assertRaises(LifecycleError):
            classify_evidence_candidate(_bind(value), descriptor=self.descriptor,
                                        evidence_id=value["evidenceId"], expected_subject=value["subject"])
        value = copy.deepcopy(self.receipt)
        value["producer"]["guarantee"] = "ATTESTED"
        value["producer"]["attestation"] = value["payload"]["commands"][0]["stdout"]
        value = _bind(value)
        result = classify_evidence_candidate(value, descriptor=self.descriptor,
                                             evidence_id=value["evidenceId"], expected_subject=value["subject"])
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertFalse(result["acceptanceAuthority"])


class CompositeOriginSchemaTests(unittest.TestCase):
    def _descriptor(self, *, asynchronous: bool = False) -> dict:
        origin = copy.deepcopy(json.loads(FIXTURE.read_bytes())["descriptor"])
        if asynchronous:
            origin.update(kind="async-observation", requirements={
                "surfaceId": "surface", "readinessId": "ready",
                "boundary": {"kind": "duration", "minimumMilliseconds": 10}})
        value = copy.deepcopy(origin)
        value.update(schemaVersion=EXPECTED_V2, kind="composite-applicability",
                     requirements={"allowHistoryOnlyChange": True}, originValidation=origin)
        return value

    def _sized(self, size: int, *, v1: bool = False) -> dict:
        value = self._descriptor()
        if v1:
            value = value["originValidation"]
        components = [value["components"]] if v1 else [value["components"], value["originValidation"]["components"]]
        paths = [f"p{i:04}_" for i in range(64)]
        for items in components:
            items[0]["configurationPaths"] = list(paths)
        factor = len(components)
        for index in range(64):
            count = min(1018, (size - len(canonical_bytes(value))) // factor)
            for items in components:
                items[0]["configurationPaths"][index] += "x" * count
        remainder = size - len(canonical_bytes(value))
        requirements = value["requirements"] if v1 else value["originValidation"]["requirements"]
        requirements["caseIds"][0] += "x" * remainder
        self.assertEqual(len(canonical_bytes(value)), size)
        return value

    def _record(self, witness: str, value: dict, status: str, code: str | None = None,
                *, dimension: str = "single") -> None:
        raw = canonical_bytes(value)
        refs = []
        directory = os.environ.get("ALK_ORIGIN_WITNESS_DIR")
        if directory:
            target = Path(directory) / (witness + "--" + dimension) / "descriptor.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            refs.append({"path": str(target), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        self.originWitnessObservation = {"witness": witness, "dimension": dimension,
            "observedStatus": status, "observedExceptionCode": code,
            "fixtureArtifactRawRefs": refs}

    def test_schema_witnesses(self) -> None:
        self.assertEqual(get_schema(EXPECTED_V2)["$id"], EXPECTED_V2)
        mutations = [
            "missing_origin", "origin_not_object", "v2_extra_field", "v2_wrong_kind",
            "v2_kind_not_string", "v2_scope_not_string", "v2_components_not_list",
            "v2_producer_not_string", "v2_requirement_not_object", "v2_history_integer",
            "v2_history_false", "v2_extra_requirement", "v2_child_forbidden",
            "v1_composite_child_forbidden", "origin_scope_mismatch", "origin_component_mismatch",
            "origin_producer_mismatch", "origin_extra_field", "origin_bad_digest",
            "origin_empty_components", "origin_65_components", "origin_duplicate_components",
            "origin_65_configuration_paths", "origin_65_oracle_paths", "origin_duplicate_paths",
            "origin_unsorted_paths", "origin_oversize_id", "origin_oversize_path",
            "origin_empty_commands", "origin_65_commands", "origin_duplicate_commands",
            "origin_empty_case_ids", "origin_1025_case_ids", "origin_duplicate_case_ids",
            "origin_oversize_case_id", "origin_boolean_duration", "origin_zero_duration",
            "origin_uint_overflow", "origin_bad_boundary", "v2_bytes_65537", "v1_origin_bytes_65537",
        ]
        for witness in mutations:
            with self.subTest(witness=witness):
                value = self._descriptor(asynchronous=witness in {
                    "origin_boolean_duration", "origin_zero_duration", "origin_uint_overflow", "origin_bad_boundary"})
                origin = value["originValidation"]
                if witness == "missing_origin": del value["originValidation"]
                elif witness == "origin_not_object": value["originValidation"] = []
                elif witness == "v2_extra_field": value["unknown"] = True
                elif witness == "v2_wrong_kind": value["kind"] = "command-observation"
                elif witness == "v2_kind_not_string": value["kind"] = []
                elif witness == "v2_scope_not_string": value["scope"] = True
                elif witness == "v2_components_not_list": value["components"] = {}
                elif witness == "v2_producer_not_string": value["producerRequirement"] = True
                elif witness == "v2_requirement_not_object": value["requirements"] = []
                elif witness == "v2_history_integer": value["requirements"]["allowHistoryOnlyChange"] = 1
                elif witness == "v2_history_false": value["requirements"]["allowHistoryOnlyChange"] = False
                elif witness == "v2_extra_requirement": value["requirements"]["unknown"] = True
                elif witness == "v2_child_forbidden": value["originValidation"] = self._descriptor()
                elif witness == "v1_composite_child_forbidden":
                    origin.update(kind="composite-applicability", requirements={"allowHistoryOnlyChange": True})
                elif witness == "origin_scope_mismatch": origin["scope"] = "FINAL"
                elif witness == "origin_component_mismatch": origin["components"][0]["repositoryPath"] = "different"
                elif witness == "origin_producer_mismatch": origin["producerRequirement"] = "ATTESTED"
                elif witness == "origin_extra_field": origin["unknown"] = True
                elif witness == "origin_bad_digest": origin["requirements"]["commandDigests"] = ["bad"]
                elif witness == "origin_empty_components": origin["components"] = []
                elif witness == "origin_65_components":
                    origin["components"] = [{**copy.deepcopy(origin["components"][0]), "id": f"c{i:03}"} for i in range(65)]
                elif witness == "origin_duplicate_components": origin["components"].append(copy.deepcopy(origin["components"][0]))
                elif witness == "origin_65_configuration_paths": origin["components"][0]["configurationPaths"] = [f"p{i:03}" for i in range(65)]
                elif witness == "origin_65_oracle_paths": origin["components"][0]["oraclePaths"] = [f"p{i:03}" for i in range(65)]
                elif witness == "origin_duplicate_paths": origin["components"][0]["configurationPaths"] = ["same", "same"]
                elif witness == "origin_unsorted_paths": origin["components"][0]["oraclePaths"] = ["z", "a"]
                elif witness == "origin_oversize_id": origin["components"][0]["id"] = "x" * 129
                elif witness == "origin_oversize_path": origin["components"][0]["configurationPaths"] = ["x" * 1025]
                elif witness == "origin_empty_commands": origin["requirements"]["commandDigests"] = []
                elif witness == "origin_65_commands": origin["requirements"]["commandDigests"] = [f"{i:064x}" for i in range(65)]
                elif witness == "origin_duplicate_commands": origin["requirements"]["commandDigests"] *= 2
                elif witness == "origin_empty_case_ids": origin["requirements"]["caseIds"] = []
                elif witness == "origin_1025_case_ids": origin["requirements"]["caseIds"] = [f"c{i}" for i in range(1025)]
                elif witness == "origin_duplicate_case_ids": origin["requirements"]["caseIds"] *= 2
                elif witness == "origin_oversize_case_id": origin["requirements"]["caseIds"] = ["x" * 129]
                elif witness == "origin_boolean_duration": origin["requirements"]["boundary"]["minimumMilliseconds"] = True
                elif witness == "origin_zero_duration": origin["requirements"]["boundary"]["minimumMilliseconds"] = 0
                elif witness == "origin_uint_overflow": origin["requirements"]["boundary"]["minimumMilliseconds"] = 9_007_199_254_740_992
                elif witness == "origin_bad_boundary": origin["requirements"]["boundary"]["kind"] = "unknown"
                elif witness == "v2_bytes_65537": value = self._sized(65_537)
                elif witness == "v1_origin_bytes_65537": value = self._sized(65_537, v1=True)
                if witness.startswith("origin_") and witness not in {
                    "origin_not_object", "origin_scope_mismatch", "origin_component_mismatch", "origin_producer_mismatch"}:
                    value["components"] = copy.deepcopy(origin["components"])
                with self.assertRaises(LifecycleError) as caught:
                    validate_expected_evidence(value)
                self._record(witness, value, "REFUSAL", caught.exception.code)
                self.assertEqual(caught.exception.code, "evidence-receipt-invalid")
        positive = [("valid_command_descriptor", self._descriptor()),
                    ("valid_async_descriptor", self._descriptor(asynchronous=True)),
                    ("v2_bytes_65536", self._sized(65_536)),
                    ("v1_origin_bytes_65536", self._sized(65_536, v1=True))]
        for witness, value in positive:
            with self.subTest(witness=witness):
                self.assertEqual(validate_expected_evidence(value), value)
                self._record(witness, value, "VALID_DESCRIPTOR")
        for dimension in ("components64", "commandDigests64", "caseIds1024", "configurationPaths64",
                          "oraclePaths64", "idBytes128", "pathBytes1024"):
            witness = "origin_cardinality_limits"
            with self.subTest(witness=witness, dimension=dimension):
                value = self._descriptor()
                origin = value["originValidation"]
                if dimension == "components64":
                    origin["components"] = [{**copy.deepcopy(origin["components"][0]), "id": f"c{i:03}"} for i in range(64)]
                elif dimension == "commandDigests64": origin["requirements"]["commandDigests"] = [f"{i:064x}" for i in range(64)]
                elif dimension == "caseIds1024": origin["requirements"]["caseIds"] = [f"c{i}" for i in range(1024)]
                elif dimension == "configurationPaths64": origin["components"][0]["configurationPaths"] = [f"p{i:03}" for i in range(64)]
                elif dimension == "oraclePaths64": origin["components"][0]["oraclePaths"] = [f"p{i:03}" for i in range(64)]
                elif dimension == "idBytes128": origin["components"][0]["id"] = "x" * 128
                elif dimension == "pathBytes1024": origin["components"][0]["configurationPaths"] = ["x" * 1024]
                value["components"] = copy.deepcopy(origin["components"])
                self.assertEqual(validate_expected_evidence(value), value)
                self._record(witness, value, "VALID_DESCRIPTOR", dimension=dimension)


if __name__ == "__main__":
    unittest.main()
