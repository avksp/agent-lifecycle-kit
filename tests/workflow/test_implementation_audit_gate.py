"""Native typed evidence binding at the implementation audit boundary."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_final_implementation_audit, build_implementation_audit_report
from agent_lifecycle.changesets import capture_task_change_set
from agent_lifecycle.contracts import write_json_create
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, sha256_hex
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.evidence_receipt_schemas import classify_evidence_candidate
from agent_lifecycle.contracts.independent_evidence_schemas import build_independence_requirement
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_assignment, build_review_mesh_profile, validate_review_mesh_assignment,
)
from agent_lifecycle.workflow.artifacts import artifact_identity
from agent_lifecycle.workflow.finalization import _validate_final_implementation_audit
from agent_lifecycle.workflow.implementation_audit_gate import (
    _security_assignment_payload,
    _expected_task_evidence_subject,
    validate_final_task_evidence_reports,
    validate_task_evidence_paths,
    validate_task_implementation_audit_artifact,
)
from agent_lifecycle.workflow.reviews import _validate_commands, validate_task_result, validate_task_review
from tests.audit.test_implementation_audit import _write_bundle, _write_result_review


class ImplementationAuditEvidenceGateTests(unittest.TestCase):
    def test_exact_receipts_cover_each_id_and_current_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
            oracle = root / "oracle.txt"
            oracle.write_text("oracle\n", encoding="utf-8")
            subprocess.run(["git", "add", "oracle.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            output = root / "output.txt"
            output.write_bytes(b"observed\n")
            command_digest = canonical_digest("python3 -m unittest")
            descriptor = {
                "schemaVersion": "agent-expected-evidence.v1", "kind": "command-observation",
                "scope": "TASK", "components": [{"id": "alk", "repositoryPath": ".",
                    "configurationPaths": [], "oraclePaths": ["oracle.txt"], "buildArtifactPath": None}],
                "producerRequirement": "DECLARED", "requirements": {
                    "commandDigests": [command_digest], "caseIds": ["case-1"],
                },
            }
            manifest = {"validation": {"commands": ["python3 -m unittest"]}, "acceptance": {"evidence": [
                {"id": name, "artifactPath": f"{name}.json", "validation": descriptor}
                for name in ("EV-A", "EV-B")
            ]}}
            state = {"packageId": "package", "runId": "run", "planRevision": 42,
                     "planDigest": "b" * 64, "sourceRevision": "base"}
            task = {"id": "WS-01", "attempt": 1, "evidenceIds": ["EV-A", "EV-B"]}
            result_identity = {"sha256": "c" * 64}
            snapshot = {"snapshotHash": "d" * 64, "changedFiles": []}
            subject = _expected_task_evidence_subject(root, state, task, result_identity, snapshot, descriptor)
            ref = {"path": "output.txt", "sha256": sha256_hex(output.read_bytes()), "bytes": 9}
            receipt = {"schemaVersion": "agent-evidence-receipt.v1", "evidenceId": "EV-A",
                       "subject": subject, "producer": {"actorId": "worker", "sessionId": "session",
                       "guarantee": "DECLARED", "attestation": None},
                       "payload": {"schemaVersion": "agent-command-observation.v1",
                       "platform": {"os": "macos", "architecture": "arm64", "pythonVersion": "3.12"},
                       "commands": [{"commandDigest": command_digest, "status": "PASS", "exitCode": 0,
                                     "stdout": ref, "stderr": ref,
                                     "cases": [{"id": "case-1", "status": "PASS", "evidence": ref}]}]},
                       "payloadDigest": "", "receiptDigest": ""}
            for name in ("EV-A", "EV-B"):
                value = copy.deepcopy(receipt)
                value["evidenceId"] = name
                value["payloadDigest"] = canonical_digest(value["payload"])
                value["receiptDigest"] = canonical_digest({k: v for k, v in value.items() if k != "receiptDigest"})
                (root / f"{name}.json").write_bytes(canonical_bytes(value) + b"\n")
            one = validate_task_evidence_paths(root, manifest, state, task, result_identity, snapshot, ["EV-A.json"])
            self.assertEqual(one["missingEvidenceIds"], ["EV-B"])
            both = validate_task_evidence_paths(root, manifest, state, task, result_identity, snapshot,
                                                ["EV-A.json", "EV-B.json"])
            self.assertEqual(both["missingEvidenceIds"], [])
            self.assertEqual({x["evidenceId"] for x in both["suppliedEvidence"]}, {"EV-A", "EV-B"})
            reduced_plan = copy.deepcopy(manifest)
            reduced_plan["workstreams"] = [{"id": "WS-01", "evidenceIds": ["EV-A"]}]
            with self.assertRaises(LifecycleError):
                validate_task_evidence_paths(root, reduced_plan, state, task, result_identity, snapshot,
                                             ["EV-A.json", "EV-B.json"])
            with self.assertRaises(LifecycleError):
                validate_task_evidence_paths(root, manifest, state, task, result_identity, snapshot,
                                             ["EV-A.json", "EV-A.json"])
            output.write_bytes(b"changed\n")
            with self.assertRaises(LifecycleError):
                validate_task_evidence_paths(root, manifest, state, task, result_identity, snapshot,
                                             ["EV-A.json", "EV-B.json"])


class SemanticTypedEvidenceConsumerTests(unittest.TestCase):
    def _bundle(self, root: Path) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
        (root / "source.py").write_text("value = 1\n")
        subprocess.run(["git", "add", "source.py"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
        for name in ("configuration.json", "oracle.txt", "build.bin", "output.txt"):
            (root / name).write_bytes(b"original\n")
        command = "python3 -m unittest"
        descriptor = {"schemaVersion": "agent-expected-evidence.v1", "kind": "command-observation",
            "scope": "TASK", "components": [{"id": "alk", "repositoryPath": ".",
                "configurationPaths": ["configuration.json"], "oraclePaths": ["oracle.txt"],
                "buildArtifactPath": "build.bin"}], "producerRequirement": "DECLARED",
            "requirements": {"commandDigests": [canonical_digest(command)], "caseIds": ["case-1"]}}
        manifest = {"validation": {"commands": [command]}, "acceptance": {"evidence": [
            {"id": "EV-X", "artifactPath": "EV-X.json", "validation": descriptor}]}}
        state = {"packageId": "package", "runId": "run", "planRevision": 42,
                 "planDigest": "b" * 64, "sourceRevision": "frozen-baseline"}
        task = {"id": "WS-01", "attempt": 1, "evidenceIds": ["EV-X"]}
        identity, snapshot = {"sha256": "c" * 64}, {"snapshotHash": "d" * 64, "changedFiles": []}
        subject = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
        ref = {"path": "output.txt", "sha256": sha256_hex(b"original\n"), "bytes": 9}
        value = {"schemaVersion": "agent-evidence-receipt.v1", "evidenceId": "EV-X", "subject": subject,
            "producer": {"actorId": "worker", "sessionId": "fixture-session", "guarantee": "DECLARED", "attestation": None},
            "payload": {"schemaVersion": "agent-command-observation.v1", "platform": {
                "os": "macos", "architecture": "arm64", "pythonVersion": "3.12"}, "commands": [{
                "commandDigest": canonical_digest(command), "status": "PASS", "exitCode": 0,
                "stdout": ref, "stderr": ref, "cases": [{"id": "case-1", "status": "PASS", "evidence": ref}]}]}}
        return manifest, state, task, identity, snapshot, descriptor, value

    def _write_receipt(self, root: Path, value: dict) -> None:
        value["payloadDigest"] = canonical_digest(value["payload"])
        value["receiptDigest"] = canonical_digest({key: item for key, item in value.items() if key != "receiptDigest"})
        (root / "EV-X.json").write_bytes(canonical_bytes(value) + b"\n")

    def test_configuration_oracle_change_invalidates_receipt_without_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, state, task, identity, snapshot, descriptor, value = self._bundle(root)
            self._write_receipt(root, value)
            self.assertEqual(validate_task_evidence_paths(root, manifest, state, task, identity,
                snapshot, ["EV-X.json"])["missingEvidenceIds"], [])
            for name, dimension in (("configuration.json", "configurationDigest"), ("oracle.txt", "oracleDigest")):
                original = (root / name).read_bytes()
                (root / name).write_bytes(b"changed\n")
                current = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
                self.assertEqual(current["components"][0]["contentDigest"], value["subject"]["components"][0]["contentDigest"])
                self.assertNotEqual(current["components"][0][dimension], value["subject"]["components"][0][dimension])
                with self.subTest(dimension=dimension), self.assertRaises(LifecycleError):
                    validate_task_evidence_paths(root, manifest, state, task, identity, snapshot, ["EV-X.json"])
                (root / name).write_bytes(original)

    def test_composite_allows_actual_history_only_and_rejects_changed_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, state, task, identity, snapshot, descriptor, previous = self._bundle(root)
            self._write_receipt(root, previous)
            self.assertEqual(validate_task_evidence_paths(root, manifest, state, task, identity,
                snapshot, ["EV-X.json"])["missingEvidenceIds"], [])
            raw = (root / "EV-X.json").read_bytes()
            (root / "previous.json").write_bytes(raw)
            subprocess.run(["git", "commit", "--allow-empty", "-qm", "history only"], cwd=root, check=True)
            origin = copy.deepcopy(descriptor)
            descriptor.update(schemaVersion="agent-expected-evidence.v2", kind="composite-applicability",
                              requirements={"allowHistoryOnlyChange": True}, originValidation=origin)
            current = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
            self.assertNotEqual(previous["subject"]["components"][0]["commitOid"], current["components"][0]["commitOid"])
            value = {**copy.deepcopy(previous), "subject": current, "payload": {
                "schemaVersion": "agent-composite-applicability.v1", "previousReceipt": {
                    "path": "previous.json", "sha256": sha256_hex(raw), "bytes": len(raw)},
                "previousSubjectDigest": canonical_digest(previous["subject"]),
                "currentSubjectDigest": canonical_digest(current), "componentIds": ["alk"]}}
            self._write_receipt(root, value)
            self.assertEqual(validate_task_evidence_paths(root, manifest, state, task, identity,
                snapshot, ["EV-X.json"])["missingEvidenceIds"], [])
            for name in ("source.py", "build.bin", "configuration.json", "oracle.txt"):
                original = (root / name).read_bytes()
                (root / name).write_bytes(b"changed\n")
                altered = copy.deepcopy(value)
                altered["subject"] = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
                altered["payload"]["currentSubjectDigest"] = canonical_digest(altered["subject"])
                self._write_receipt(root, altered)
                with self.subTest(changed=name), self.assertRaises(LifecycleError):
                    validate_task_evidence_paths(root, manifest, state, task, identity, snapshot, ["EV-X.json"])
                (root / name).write_bytes(original)


    def test_composite_cannot_reuse_a_failed_previous_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, state, task, identity, snapshot, descriptor, previous = self._bundle(root)
            previous["payload"]["commands"][0].update(status="FAIL", exitCode=1)
            previous["payload"]["commands"][0]["cases"][0]["status"] = "FAIL"
            self._write_receipt(root, previous)
            raw = (root / "EV-X.json").read_bytes()
            (root / "previous.json").write_bytes(raw)
            origin = copy.deepcopy(descriptor)
            descriptor.update(schemaVersion="agent-expected-evidence.v2", kind="composite-applicability",
                              requirements={"allowHistoryOnlyChange": True}, originValidation=origin)
            current = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
            value = {**copy.deepcopy(previous), "subject": current, "payload": {
                "schemaVersion": "agent-composite-applicability.v1", "previousReceipt": {
                    "path": "previous.json", "sha256": sha256_hex(raw), "bytes": len(raw)},
                "previousSubjectDigest": canonical_digest(previous["subject"]),
                "currentSubjectDigest": canonical_digest(current), "componentIds": ["alk"]}}
            self._write_receipt(root, value)
            with self.assertRaises(LifecycleError):
                validate_task_evidence_paths(root, manifest, state, task, identity, snapshot, ["EV-X.json"])


class CompositeOriginConsumerTests(unittest.TestCase):
    # Reuse fixture construction without inheriting/re-running its test methods.
    _bundle = SemanticTypedEvidenceConsumerTests._bundle

    def _setup(self, root: Path, *, count: int = 2, asynchronous: bool = False,
               event: bool = False) -> tuple:
        manifest, state, task, identity, snapshot, descriptor, leaf = self._bundle(root)
        command = leaf["payload"]["commands"][0]
        ref = copy.deepcopy(command["stdout"])
        command["stdout"] = copy.deepcopy(ref)
        command["stderr"] = copy.deepcopy(ref)
        command["cases"][0]["evidence"] = copy.deepcopy(ref)
        if asynchronous:
            descriptor.update(kind="async-observation", requirements={
                "surfaceId": "surface", "readinessId": "ready", "boundary":
                {"kind": "event", "eventId": "finish"} if event else
                {"kind": "duration", "minimumMilliseconds": 10}})
            leaf["payload"] = {"schemaVersion": "agent-async-observation.v1",
                "surfaceId": "surface", "readinessId": "ready", "clockId": "monotonic",
                "readyAtMs": 0, "coverageStartMs": 0, "coverageEndMs": 10,
                "boundary": {"kind": "event", "eventId": "finish", "atMs": 10} if event else
                {"kind": "duration", "atMs": 10}, "violationCount": 0,
                "observationArtifact": copy.deepcopy(ref)}
        origin = copy.deepcopy(descriptor)
        descriptor.update(schemaVersion="agent-expected-evidence.v2", kind="composite-applicability",
                          requirements={"allowHistoryOnlyChange": True}, originValidation=origin)
        subprocess.run(["git", "commit", "--allow-empty", "-qm", "history only"], cwd=root, check=True)
        current = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
        self.assertNotEqual(leaf["subject"]["components"][0]["commitOid"], current["components"][0]["commitOid"])
        nodes = [leaf]
        for _ in range(count):
            nodes.append({"schemaVersion": "agent-evidence-receipt.v1", "evidenceId": "EV-X",
                "subject": copy.deepcopy(current), "producer": copy.deepcopy(leaf["producer"]),
                "payload": {"schemaVersion": "agent-composite-applicability.v1"}})
        return manifest, state, task, identity, snapshot, descriptor, nodes, ref

    def _persist(self, root: Path, nodes: list[dict], overrides: dict | None = None) -> None:
        overrides = overrides or {}
        previous_raw = b""
        for index, node in enumerate(nodes):
            if index:
                node["payload"].update(previousReceipt={"path": f"node-{index-1}.json",
                    "sha256": sha256_hex(previous_raw), "bytes": len(previous_raw)},
                    previousSubjectDigest=canonical_digest(nodes[index-1]["subject"]),
                    currentSubjectDigest=canonical_digest(node["subject"]),
                    componentIds=[item["id"] for item in node["subject"]["components"]])
                for field, value in overrides.get(index, {}).items():
                    if field == "previousReceipt": node["payload"][field].update(value)
                    else: node["payload"][field] = value
            node["payloadDigest"] = canonical_digest(node["payload"])
            node["receiptDigest"] = canonical_digest({key: item for key, item in node.items() if key != "receiptDigest"})
            previous_raw = canonical_bytes(node) + b"\n"
            (root / f"node-{index}.json").write_bytes(previous_raw)
        (root / "EV-X.json").write_bytes(previous_raw)

    def _record(self, root: Path, witness: str, status: str, *, code: str | None = None,
                dimension: str = "single", descriptor: dict) -> None:
        refs = []
        directory = os.environ.get("ALK_ORIGIN_WITNESS_DIR")
        if directory:
            target = Path(directory) / (witness + "--" + dimension)
            # Retain generated local Git history and every referenced raw fixture
            # before TemporaryDirectory cleanup; never reference deleted bytes.
            shutil.copytree(root, target, dirs_exist_ok=True)
            (target / "descriptor.json").write_bytes(canonical_bytes(descriptor))
            for path in sorted(target.iterdir()):
                if path.is_file():
                    raw = path.read_bytes()
                    refs.append({"path": str(path), "sha256": sha256_hex(raw), "bytes": len(raw)})
        self.originWitnessObservation = {"witness": witness, "dimension": dimension,
            "observedStatus": status, "observedExceptionCode": code,
            "fixtureArtifactRawRefs": refs}

    def _check(self, root: Path, setup: tuple, witness: str, *, code: str | None = None,
               unsupported: str | None = None, dimension: str = "single") -> None:
        manifest, state, task, identity, snapshot, descriptor, nodes, _ = setup
        if unsupported:
            subject = _expected_task_evidence_subject(root, state, task, identity, snapshot, descriptor)
            outcome = classify_evidence_candidate(nodes[-1], descriptor=descriptor,
                evidence_id="EV-X", expected_subject=subject)
            self._record(root, witness, outcome["status"], dimension=dimension, descriptor=descriptor)
            self.assertEqual(outcome["status"], "UNSUPPORTED")
            self.assertEqual(outcome["reason"], unsupported)
            self.assertFalse(outcome["acceptanceAuthority"])
        elif code:
            with self.assertRaises(LifecycleError) as caught:
                validate_task_evidence_paths(root, manifest, state, task, identity, snapshot, ["EV-X.json"])
            self._record(root, witness, "REFUSAL", code=caught.exception.code,
                         dimension=dimension, descriptor=descriptor)
            self.assertEqual(caught.exception.code, code)
        else:
            outcome = validate_task_evidence_paths(root, manifest, state, task, identity, snapshot, ["EV-X.json"])
            self.assertEqual(outcome["missingEvidenceIds"], [])
            candidate = classify_evidence_candidate(nodes[0], descriptor=descriptor["originValidation"],
                evidence_id="EV-X", expected_subject=nodes[0]["subject"])
            self._record(root, witness, candidate["status"], dimension=dimension, descriptor=descriptor)
            self.assertEqual(candidate["status"], "DATA_CANDIDATE")
            self.assertFalse(candidate["acceptanceAuthority"])

    def test_compatibility_witnesses(self) -> None:
        witness = "unbound_v1_composite"
        with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup = self._setup(root)
            setup[5].pop("originValidation")
            setup[5]["schemaVersion"] = "agent-expected-evidence.v1"
            self._persist(root, setup[6])
            self._check(root, setup, witness, unsupported="predecessor-expectations-unbound")
            with self.assertRaises(LifecycleError) as caught:
                validate_task_evidence_paths(root, *setup[:5], ["EV-X.json"])
            self.assertEqual(caught.exception.code, "evidence-provenance-unsupported")

    def test_command_witnesses(self) -> None:
        for witness in ("null_case_evidence", "absent_case", "substituted_case", "duplicate_case",
                        "wrong_command_digest", "failed_command", "origin_command_not_in_manifest",
                        "valid_command_history"):
            with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                setup = self._setup(root)
                manifest, _, _, _, _, _, nodes, _ = setup
                command = nodes[0]["payload"]["commands"][0]
                if witness == "null_case_evidence": command["cases"][0]["evidence"] = None
                elif witness == "absent_case": command["cases"] = []
                elif witness == "substituted_case": command["cases"][0]["id"] = "another-case"
                elif witness == "duplicate_case": command["cases"].append(copy.deepcopy(command["cases"][0]))
                elif witness == "wrong_command_digest": command["commandDigest"] = canonical_digest("different command")
                elif witness == "failed_command":
                    command.update(status="FAIL", exitCode=1)
                    command["cases"][0]["status"] = "FAIL"
                elif witness == "origin_command_not_in_manifest": manifest["validation"]["commands"] = []
                self._persist(root, nodes)
                code = None if witness == "valid_command_history" else (
                    "evidence-contract-invalid" if witness == "origin_command_not_in_manifest" else "evidence-receipt-invalid")
                self._check(root, setup, witness, code=code)

    def test_async_witnesses(self) -> None:
        witnesses = ["wrong_async_surface", "wrong_async_readiness", "wrong_async_event",
            "wrong_async_boundary_kind", "short_async_duration", "async_uncovered_readiness",
            "async_uncovered_boundary", "async_observed_violation"]
        for witness, event in [(name, name in {"wrong_async_event", "wrong_async_boundary_kind"}) for name in witnesses] + [
                ("valid_async_history", False), ("valid_async_history", True)]:
            with self.subTest(witness=witness, dimension="event" if event else "duration"), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                setup = self._setup(root, asynchronous=True, event=event)
                descriptor, nodes = setup[5:7]
                payload = nodes[0]["payload"]
                if witness == "wrong_async_surface": payload["surfaceId"] = "different-surface"
                elif witness == "wrong_async_readiness": payload["readinessId"] = "different-readiness"
                elif witness == "wrong_async_event": payload["boundary"]["eventId"] = "different-event"
                elif witness == "wrong_async_boundary_kind":
                    descriptor["originValidation"]["requirements"]["boundary"] = {"kind": "duration", "minimumMilliseconds": 10}
                elif witness == "short_async_duration":
                    payload["boundary"]["atMs"] = payload["coverageEndMs"] = 9
                elif witness == "async_uncovered_readiness": payload["coverageStartMs"] = 1
                elif witness == "async_uncovered_boundary": payload["coverageEndMs"] = 9
                elif witness == "async_observed_violation": payload["violationCount"] = 1
                self._persist(root, nodes)
                self._check(root, setup, witness, code=None if witness == "valid_async_history" else "evidence-receipt-invalid",
                            dimension="event" if event else "duration")

    def test_producer_witnesses(self) -> None:
        for witness, index in (("attested_outer", 2), ("attested_inherited_leaf", 0), ("attested_intermediate", 1)):
            with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                setup = self._setup(root)
                descriptor, nodes, ref = setup[5:]
                nodes[index]["producer"].update(guarantee="ATTESTED", attestation=copy.deepcopy(ref))
                if witness == "attested_outer":
                    descriptor["producerRequirement"] = descriptor["originValidation"]["producerRequirement"] = "ATTESTED"
                self._persist(root, nodes)
                self._check(root, setup, witness, code=None if witness == "attested_outer" else "evidence-provenance-unsupported",
                    unsupported="producer-attestation-unqualified" if witness == "attested_outer" else None)

    def test_chain_witnesses(self) -> None:
        component_fields = {"content_change": "contentDigest", "build_change": "buildDigest",
            "configuration_change": "configurationDigest", "oracle_change": "oracleDigest"}
        lineage_fields = {"plan_revision_change": "planRevision", "plan_digest_change": "planDigest",
            "run_change": "runId", "package_change": "packageId", "source_revision_change": "sourceRevision",
            "task_change": "taskId", "attempt_change": "attempt", "result_change": "resultDigest", "snapshot_change": "snapshotHash"}
        bindings = {"intermediate_component_ids": "componentIds", "intermediate_current_subject_digest": "currentSubjectDigest",
                    "intermediate_previous_subject_digest": "previousSubjectDigest"}
        references = ["previous_reference_sha", "previous_reference_bytes", "leaf_case_reference_sha",
            "leaf_case_reference_bytes", "leaf_stdout_reference_sha", "leaf_async_reference_sha"]
        witnesses = [*component_fields, *lineage_fields, "intermediate_evidence_id", *bindings, *references, "deep_leaf_violation"]
        for witness in witnesses:
            with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                setup = self._setup(root, count=3 if witness == "deep_leaf_violation" else 2,
                                    asynchronous=witness == "leaf_async_reference_sha")
                nodes = setup[6]
                overrides = {}
                code = "evidence-subject-mismatch"
                if witness in component_fields:
                    nodes[1]["subject"]["components"][0][component_fields[witness]] = "0" * 64
                elif witness in lineage_fields:
                    field = lineage_fields[witness]
                    subject = nodes[1]["subject"]
                    destination = subject["taskBindings"][0] if field in {"taskId", "attempt", "resultDigest", "snapshotHash"} else subject
                    old = destination[field]
                    destination[field] = old + 1 if type(old) is int else ("0" * 64 if field.endswith("Digest") or field == "snapshotHash" else "different")
                elif witness == "intermediate_evidence_id": nodes[1]["evidenceId"] = "EV-other"
                elif witness in bindings:
                    overrides[1] = {bindings[witness]: ["different"] if witness == "intermediate_component_ids" else "0" * 64}
                elif witness.startswith("previous_reference_"):
                    overrides[1] = {"previousReceipt": {"sha256": "0" * 64}} if witness.endswith("sha") else {"previousReceipt": {"bytes": 1}}
                    code = "evidence-artifact-invalid"
                elif witness.startswith("leaf_"):
                    payload = nodes[0]["payload"]
                    if witness == "leaf_async_reference_sha": ref = payload["observationArtifact"]
                    elif witness == "leaf_stdout_reference_sha": ref = payload["commands"][0]["stdout"]
                    else: ref = payload["commands"][0]["cases"][0]["evidence"]
                    if witness.endswith("bytes"): ref["bytes"] += 1
                    else: ref["sha256"] = "0" * 64
                    code = "evidence-artifact-invalid"
                elif witness == "deep_leaf_violation":
                    nodes[0]["payload"]["commands"][0]["cases"][0]["status"] = "FAIL"
                    code = "evidence-receipt-invalid"
                self._persist(root, nodes, overrides)
                self._check(root, setup, witness, code=code)

    def test_depth_witnesses(self) -> None:
        for count in (32, 33):
            witness = f"exactly_{count}_transitions"
            with self.subTest(witness=witness), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                setup = self._setup(root, count=count)
                self._persist(root, setup[6])
                self._check(root, setup, witness, code="evidence-artifact-invalid" if count == 33 else None)


class FinalTypedEvidenceConsumerTests(unittest.TestCase):
    def test_final_inventory_refuses_exact_errors_in_original_order(self) -> None:
        descriptor = {
            "schemaVersion": "agent-expected-evidence.v1", "kind": "command-observation",
            "scope": "TASK", "components": [{"id": "alk", "repositoryPath": ".",
                "configurationPaths": [], "oraclePaths": ["oracle.txt"], "buildArtifactPath": None}],
            "producerRequirement": "DECLARED", "requirements": {
                "commandDigests": [canonical_digest("python3 -m unittest")], "caseIds": ["case-1"],
            },
        }
        owner = {"id": "WS-01", "evidenceIds": ["EV-1"]}
        task = {**owner, "status": "ACCEPTED"}
        for owners, tasks, reports, message in (
            ([owner], [{**task, "id": "outside"}], None, "accepted task is outside frozen plan"),
            ([{**owner, "evidenceIds": None}], [task], None, "frozen task evidence inventory is invalid"),
            ([owner], [{**task, "evidenceIds": []}], None, "typed task evidence inventory changed"),
            ([owner], [task, task], None, "typed task evidence inventory changed"),
            ([{**owner, "evidenceIds": [1]}], [], None, "frozen evidence IDs are invalid"),
            ([owner], [], None, "required typed task is not accepted"),
            ([owner], [task], None, "final audit report inventory is incomplete"),
            ([owner], [task], [{}], "final audit report identity is invalid"),
            ([owner], [task], [], "typed accepted task report is missing"),
        ):
            manifest = {"status": "FROZEN", "workstreams": owners,
                        "acceptance": {"evidence": [{"id": "EV-1", "validation": descriptor}]}}
            state = {"planDigest": canonical_digest(manifest), "tasks": tasks}
            audit = {"reports": reports, "missingTaskIds": []}
            original = copy.deepcopy((manifest, state, audit))
            with self.subTest(message=message), self.assertRaises(LifecycleError) as caught:
                validate_final_task_evidence_reports(Path("unused.state.json"), state, audit, manifest=manifest)
            self.assertEqual(caught.exception.to_json(), {
                "schemaVersion": "agent-lifecycle-error.v1", "code": "evidence-contract-invalid",
                "message": message, "details": {},
            })
            self.assertEqual((manifest, state, audit), original)

    def test_final_acceptance_rechecks_exact_typed_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
            source = root / "src/example.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n")
            (root / "oracle.txt").write_text("oracle\n")
            (root / ".gitignore").write_text(
                "plans/\nrun.state.json\nwork/\noutput.txt\nEV-1.json\nfinal-audit.json\n"
            )
            subprocess.run(["git", "add", ".gitignore", "src/example.py", "oracle.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                                      capture_output=True, text=True).stdout.strip()
            bundle = _write_bundle(root, phase="FINAL_AUDIT", task_status="ACCEPTED")
            manifest_path, state_path = Path(bundle["manifestPath"]), Path(bundle["statePath"])
            manifest = json.loads(manifest_path.read_text())
            descriptor = {
                "schemaVersion": "agent-expected-evidence.v1", "kind": "command-observation",
                "scope": "TASK", "components": [{"id": "alk", "repositoryPath": ".",
                    "configurationPaths": [], "oraclePaths": ["oracle.txt"], "buildArtifactPath": None}],
                "producerRequirement": "DECLARED", "requirements": {
                    "commandDigests": [canonical_digest("python3 -m unittest")], "caseIds": ["case-1"],
                },
            }
            manifest["workstreams"][0]["evidenceIds"] = ["EV-1"]
            manifest["acceptance"] = {"evidence": [{"id": "EV-1", "artifactPath": "EV-1.json",
                                                   "validation": descriptor}]}
            manifest["validation"] = {"commands": ["python3 -m unittest"]}
            manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
            bundle["planDigest"] = canonical_digest(manifest)
            state = json.loads(state_path.read_text())
            state["planDigest"] = bundle["planDigest"]
            state["sourceRevision"] = revision
            state["tasks"][0]["evidenceIds"] = ["EV-1"]
            state_path.write_bytes(canonical_bytes(state) + b"\n")
            source.write_text("value = 2\n")
            freshness = capture_task_change_set(root, baseline=revision, write_paths=["src/example.py"])
            result_path, review_path = _write_result_review(root, bundle, source_revision=revision,
                                                            freshness=freshness)
            state = json.loads(state_path.read_text())
            result = json.loads((root / result_path).read_text())
            result_identity = artifact_identity(root, result_path, result)
            snapshot = validate_task_result(state, state["tasks"][0], result, result_identity,
                                            repository_root=root, require_freshness=True)
            subject = _expected_task_evidence_subject(root, state, state["tasks"][0], result_identity,
                                                      snapshot, descriptor)
            observed = root / "output.txt"
            observed.write_bytes(b"observed\n")
            ref = {"path": "output.txt", "sha256": sha256_hex(observed.read_bytes()), "bytes": 9}
            receipt = {
                "schemaVersion": "agent-evidence-receipt.v1", "evidenceId": "EV-1", "subject": subject,
                "producer": {"actorId": "worker", "sessionId": "session", "guarantee": "DECLARED",
                             "attestation": None},
                "payload": {"schemaVersion": "agent-command-observation.v1",
                            "platform": {"os": "macos", "architecture": "arm64", "pythonVersion": "3.12"},
                            "commands": [{"commandDigest": canonical_digest("python3 -m unittest"),
                                          "status": "PASS", "exitCode": 0, "stdout": ref, "stderr": ref,
                                          "cases": [{"id": "case-1", "status": "PASS", "evidence": ref}]}]},
            }
            receipt["payloadDigest"] = canonical_digest(receipt["payload"])
            receipt["receiptDigest"] = canonical_digest(receipt)
            write_json_create(root / "EV-1.json", receipt)
            report = build_implementation_audit_report(
                manifest_path=manifest_path, state_path=state_path, task_id="WS-01",
                result_path=result_path, review_path=review_path, evidence_paths=["EV-1.json"],
            )
            self.assertEqual(report["status"], "PASS", report["blockers"])
            report_path = "work/WS-01/attempt-1/implementation-audit.json"
            write_json_create(root / report_path, report)
            accepted = validate_task_implementation_audit_artifact(
                state_path, state, state["tasks"][0], report_path,
            )
            state["tasks"][0]["implementationAuditReport"] = accepted
            state_path.write_bytes(canonical_bytes(state) + b"\n")
            final = build_final_implementation_audit(
                manifest_path=manifest_path, state_path=state_path, report_paths=[report_path],
            )
            self.assertEqual(final["status"], "PASS", {
                "blockers": final["blockers"], "builderValidation": final["reports"][0]["validation"],
                "acceptedValidation": accepted["validation"],
            })
            write_json_create(root / "final-audit.json", final)
            self.assertEqual(_validate_final_implementation_audit(
                state_path, state, root, final_implementation_audit_path="final-audit.json",
            )["validation"]["status"], "PASS")
            observed.write_bytes(b"changed!\n")
            with self.assertRaises(LifecycleError):
                _validate_final_implementation_audit(
                    state_path, state, root, final_implementation_audit_path="final-audit.json",
                )

    def test_forged_pass_with_no_typed_task_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = {
                "schemaVersion": "agent-expected-evidence.v1", "kind": "command-observation",
                "scope": "TASK", "components": [{"id": "alk", "repositoryPath": ".",
                    "configurationPaths": [], "oraclePaths": ["oracle.txt"], "buildArtifactPath": None}],
                "producerRequirement": "DECLARED", "requirements": {
                    "commandDigests": [canonical_digest("python3 -m unittest")], "caseIds": ["case-1"],
                },
            }
            manifest = {
                "status": "FROZEN", "workstreams": [{"id": "WS-01", "evidenceIds": ["EV-1"]}],
                "acceptance": {"evidence": [{"id": "EV-1", "artifactPath": "receipt.json",
                                            "validation": descriptor}]},
                "validation": {"commands": ["python3 -m unittest"]},
            }
            (root / "plans").mkdir()
            write_json_create(root / "plans/manifest.json", manifest)
            state = {
                "runId": "run", "packageId": "package", "planRevision": 1,
                "planDigest": canonical_digest(manifest), "sourceRevision": "source",
                "packageRoot": ".", "manifestPath": "plans/manifest.json",
                "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1,
                           "evidenceIds": ["EV-1"], "required": True}],
            }
            audit = {
                "schemaVersion": "agent-final-implementation-audit.v1", "status": "PASS",
                "runId": "run", "packageId": "package", "planRevision": 1,
                "planDigest": state["planDigest"], "sourceRevision": "source",
                "auditor": {"id": "auditor", "surface": "test", "independent": True},
                "reports": [], "missingTaskIds": [], "findings": [], "blockers": [],
                "productionPromotionClaimed": False,
            }
            audit["auditDigest"] = canonical_digest(audit)
            write_json_create(root / "final-audit.json", audit)
            with self.assertRaises(LifecycleError) as rejected:
                _validate_final_implementation_audit(
                    root / "run.state.json", state, root,
                    final_implementation_audit_path="final-audit.json",
                )
            self.assertEqual(rejected.exception.code, "evidence-contract-invalid")
            state["tasks"] = []
            with self.assertRaises(LifecycleError) as omitted:
                _validate_final_implementation_audit(
                    root / "run.state.json", state, root,
                    final_implementation_audit_path="final-audit.json",
                )
            self.assertEqual(omitted.exception.code, "evidence-contract-invalid")


def _state_task() -> tuple[dict, dict]:
    return ({"runId": "current-run", "planDigest": "a" * 64, "sourceRevision": "b" * 40},
            {"id": "current-task", "attempt": 1, "result": {"sha256": "c" * 64}})


class ReviewerIdentityRegressionTests(unittest.TestCase):
    def _values(self) -> tuple[dict, dict, dict, dict]:
        state, task = _state_task()
        review = {"schemaVersion": "agent-task-review.v2", "reviewId": "review-one",
                  "runId": state["runId"], "taskId": task["id"], "attempt": task["attempt"],
                  "planDigest": state["planDigest"], "resultHash": task["result"]["sha256"],
                  "reviewer": {"id": "reviewer", "runId": "review-session", "independent": True},
                  "verdict": "ACCEPTED", "findings": []}
        return state, task, review, {"actor": "worker", "actorRunId": "worker-session"}

    def test_missing_or_invalid_reviewer_identity_is_refused(self) -> None:
        for field in ("id", "runId"):
            for value in (None, "", "   ", 1, True, [], {}):
                with self.subTest(field=field, value=value):
                    state, task, review, result = self._values()
                    review["reviewer"][field] = value
                    with self.assertRaises(LifecycleError):
                        validate_task_review(state, task, review, result=result)
            state, task, review, result = self._values()
            review["reviewer"].pop(field)
            with self.subTest(field=field, missing=True), self.assertRaises(LifecycleError):
                validate_task_review(state, task, review, result=result)

    def test_independent_identity_accepts_but_worker_aliases_refuse(self) -> None:
        state, task, review, result = self._values()
        validate_task_review(state, task, review, result=result)
        for field, value in (("id", result["actor"]), ("runId", result["actorRunId"])):
            bad = copy.deepcopy(review)
            bad["reviewer"][field] = value
            with self.subTest(field=field), self.assertRaises(LifecycleError):
                validate_task_review(state, task, bad, result=result)


class CommandObservationRegressionTests(unittest.TestCase):
    def _check(self, command: dict) -> None:
        state, task = _state_task()
        result = {"schemaVersion": "agent-task-result.v2", "runId": state["runId"],
                  "taskId": task["id"], "attempt": task["attempt"],
                  "planDigest": state["planDigest"], "sourceRevision": state["sourceRevision"],
                  "actor": "worker", "actorRunId": "worker-session",
                  "itemOutcomes": [{"plannedItemId": "item", "status": "COMPLETE"}], "commands": [command]}
        validate_task_result(state, task, result, {"sha256": "c" * 64})

    def test_unknown_and_malformed_observations_cannot_complete(self) -> None:
        for command in ({}, {"status": "UNKNOWN", "exitCode": None},
                        {"status": "PASS", "exitCode": "1"}, {"status": "PASS", "exitCode": "0"},
                        {"status": "PASS", "exitCode": False}, {"status": "PASS", "exitCode": None},
                        {"status": None, "exitCode": 0}, {"status": [], "exitCode": 0},
                        {"status": "SKIPPED", "exitCode": 0}, {"status": "NOT_RUN", "exitCode": 0},
                        {"status": "FAIL", "exitCode": 0}, {"status": "PASS", "exitCode": 1}):
            with self.subTest(command=command), self.assertRaises(LifecycleError):
                self._check(command)

    def test_actual_success_accepts_and_nonaccepting_history_is_preserved(self) -> None:
        for status in ("PASS", "PASSED"):
            self._check({"status": status, "exitCode": 0})
        result = {"commands": [{"status": "UNKNOWN", "exitCode": None},
                               {"status": "FAILED", "exitCode": 2}]}
        original = copy.deepcopy(result)
        _validate_commands(result, allow_failed=True)
        self.assertEqual(result, original)


class SecurityWrapperLineageRegressionTests(unittest.TestCase):
    def _packet(self, changes: dict | None = None, missing: str | None = None) -> tuple[dict, dict, dict]:
        state, task = _state_task()
        subject = {"runId": state["runId"], "taskId": task["id"], "attempt": task["attempt"],
                   "planDigest": state["planDigest"], "sourceRevision": state["sourceRevision"],
                   "reviewMeshBlockingOptIn": True}
        subject.update(changes or {})
        if missing:
            subject.pop(missing)
        assignment = build_review_mesh_assignment(
            profile=build_review_mesh_profile(), assignment_id="security-assignment", subject=subject,
            reviewer={"id": "reviewer", "producerClass": "independent-reviewer"},
            phase="task-review", blocking=True, evidence_ids=["security-evidence"],
            independence_requirement=build_independence_requirement(),
        )
        self.assertEqual(validate_review_mesh_assignment(assignment)["status"], "PASS")
        packet = {"schemaVersion": "agent-review-mesh-reviewer-packet.v1", "assignment": assignment,
                  "securityAnalysis": {"profileId": "security-analysis.v1",
                                       "independentVerificationRequired": True, "authorityClaimed": False},
                  "reviewerTask": {"hostOwnedExecution": True, "alkCoreLaunchAllowed": False,
                                   "promptAuthorityGranted": False}}
        packet["packetDigest"] = canonical_digest(packet)
        return state, task, packet

    def test_same_revision_wrong_original_lineage_is_refused(self) -> None:
        for field, value in (("runId", "other-run"), ("taskId", "other-task"), ("attempt", 2),
                             ("attempt", True), ("attempt", 1.0), ("planDigest", "d" * 64)):
            with self.subTest(field=field, value=value):
                state, task, packet = self._packet({field: value})
                with self.assertRaises(LifecycleError):
                    _security_assignment_payload(packet, state=state, task=task)
        for field in ("runId", "taskId", "attempt", "planDigest"):
            state, task, packet = self._packet(missing=field)
            with self.subTest(field=field, missing=True), self.assertRaises(LifecycleError):
                _security_assignment_payload(packet, state=state, task=task)

    def test_exact_original_lineage_preserves_security_assignment(self) -> None:
        state, task, packet = self._packet()
        assignment = _security_assignment_payload(packet, state=state, task=task)
        self.assertEqual({k: assignment[k] for k in ("runId", "taskId", "attempt", "planDigest")},
                         {k: packet["assignment"]["subject"][k] for k in ("runId", "taskId", "attempt", "planDigest")})
        self.assertEqual(assignment["assignmentDigest"], canonical_digest(
            {k: v for k, v in assignment.items() if k != "assignmentDigest"}))


if __name__ == "__main__":
    unittest.main()
