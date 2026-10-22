from __future__ import annotations

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.workflow.artifact_builders import (
    build_authored_artifact,
    create_artifact,
    inspect_artifact,
)
from tests.workflow.helpers import _write_state

ROOT = Path(__file__).resolve().parents[2]


class ArtifactBuilderTests(unittest.TestCase):
    def test_json_creation_is_canonical_exclusive_and_never_acceptance(self):
        value = {"z": 1, "a": "Пример"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            result = create_artifact(path, build_authored_artifact(value, kind="json"))
            self.assertEqual(path.read_bytes(), canonical_bytes(value) + b"\n")
            self.assertEqual(result["artifact"]["digest"], canonical_digest(value))
            self.assertFalse(result["nativeAcceptanceClaimed"])
            with self.assertRaises(FileExistsError):
                create_artifact(path, {"changed": True})
            self.assertEqual(path.read_bytes(), canonical_bytes(value) + b"\n")

    def test_concurrent_creation_has_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested/artifact.json"

            def write(index):
                try:
                    create_artifact(path, {"winner": index})
                    return True
                except FileExistsError:
                    return False
                except LifecycleError as error:
                    error.add_note(json.dumps({
                        "writer": index, "code": error.code,
                        "details": error.details,
                    }, sort_keys=True))
                    raise

            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(write, range(4)))
            self.assertEqual(sum(outcomes), 1)
            self.assertIn(json.loads(path.read_bytes())["winner"], range(4))

    def test_sensitive_input_is_refused_or_explicitly_advisory_redacted(self):
        original = {"authorityClaimed": False, "password": "secret-value"}
        with self.assertRaises(LifecycleError):
            build_authored_artifact(original, kind="json")
        result = build_authored_artifact(original, kind="json", redact_advisory=True)
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertEqual(original["password"], "secret-value")
        with self.assertRaises(LifecycleError):
            build_authored_artifact({"password": "secret-value"}, kind="json", redact_advisory=True)

    def test_inspection_redacts_limits_and_preserves_original_identity_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            raw = canonical_bytes({"password": "secret-value", "note": "я" * 1000})
            path.write_bytes(raw)
            result = inspect_artifact(path, max_display_bytes=256)
            self.assertTrue(result["displayRedacted"])
            self.assertTrue(result["displayTruncated"])
            self.assertLessEqual(len(result["display"].encode()), 256)
            self.assertNotIn("secret-value", result["display"])
            self.assertEqual(result["artifact"]["digest"], canonical_digest(json.loads(raw)))
            self.assertEqual(path.read_bytes(), raw)
            with self.assertRaises(LifecycleError):
                inspect_artifact(path, max_display_bytes=True)

    def test_evidence_builder_computes_digests_without_attesting_or_rewriting(self):
        value = json.loads((ROOT / "tests/audit/fixtures/release_216_evidence_contracts.json").read_bytes())["receipt"]
        value.pop("payloadDigest")
        value.pop("receiptDigest")
        result = build_authored_artifact(value, kind="evidence")
        self.assertEqual(result["payloadDigest"], canonical_digest(value["payload"]))
        self.assertEqual(
            result["receiptDigest"],
            canonical_digest({key: item for key, item in result.items() if key != "receiptDigest"}),
        )
        for mutation in ({"receiptDigest": "0" * 64}, {"extra": True}):
            with self.assertRaises(LifecycleError):
                build_authored_artifact({**value, **mutation}, kind="evidence")
        attested = copy.deepcopy(value)
        attested["producer"]["guarantee"] = "ATTESTED"
        with self.assertRaises(LifecycleError):
            build_authored_artifact(attested, kind="evidence")

    def test_task_builder_uses_existing_lineage_worker_and_item_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = json.loads(_write_state(root, phase="RUNNING").read_bytes())
            state.update(schemaVersion="agent-workflow-state.v4", operationLedger={})
            state["tasks"][0].update(status="RUNNING", attempt=1)
            value = {
                "actor": "/root/worker",
                "actorRunId": "worker-1",
                "itemOutcomes": [{"plannedItemId": "item-1", "status": "COMPLETE"}],
            }
            result = build_authored_artifact(
                value, kind="task-result", state=state, task_id="WS-01", repository_root=root
            )
            self.assertEqual(result["runId"], state["runId"])
            self.assertEqual(result["actor"], "/root/worker")
            self.assertEqual(result["taskPacketHash"], "1" * 64)
            self.assertNotIn("runId", value)
            for mutation in (
                {"runId": "other"},
                {"attempt": True},
                {"actor": ""},
                {"itemOutcomes": []},
                {"itemOutcomes": value["itemOutcomes"] * 2},
            ):
                with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                    build_authored_artifact(
                        {**value, **mutation}, kind="task-result", state=state, task_id="WS-01", repository_root=root
                    )
            incomplete = {
                **value,
                "itemOutcomes": [{"plannedItemId": "item-1", "status": "INCOMPLETE"}],
                "contractChangeRequest": {"reason": "Must revise the planned contract"},
            }
            result = build_authored_artifact(
                incomplete, kind="task-result", state=state, task_id="WS-01", repository_root=root
            )
            self.assertEqual(result["itemOutcomes"][0]["status"], "INCOMPLETE")
            self.assertEqual(result["contractChangeRequest"], incomplete["contractChangeRequest"])
