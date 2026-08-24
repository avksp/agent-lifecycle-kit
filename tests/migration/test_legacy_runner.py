from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.migration.legacy_runner import convert_legacy_runner_artifact


class LegacyRunnerConversionTests(unittest.TestCase):
    def test_supported_policy_is_converted_without_mutating_source(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "runner-artifacts" / "runner-policy.v1.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "policy.json"
            output = root / "archive" / "policy-conversion.json"
            source.write_bytes(fixture.read_bytes())
            before = source.read_bytes()

            result = convert_legacy_runner_artifact(source, output)

            self.assertEqual(result["source"]["schemaVersion"], "agent-runner-policy.v1")
            self.assertEqual(result["source"]["bytes"], len(before))
            self.assertFalse(result["authorityClaimed"])
            self.assertFalse(result["stateWritten"])
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["conversionDigest"], result["conversionDigest"])

    def test_stale_embedded_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "state.json"
            payload = {
                "schemaVersion": "agent-runner-state.v1",
                "runnerRevision": 1,
                "status": "READY",
                "currentTaskId": "WS-01",
                "lineage": {},
                "policy": {},
                "counters": {},
                "history": [{}],
                "operations": {},
                "stateDigest": "0" * 64,
            }
            source.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                convert_legacy_runner_artifact(source, root / "out.json")
            self.assertEqual(raised.exception.code, "legacy-artifact-digest-mismatch")

    def test_oversized_input_is_rejected_before_json_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "large.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaises(LifecycleError) as raised:
                convert_legacy_runner_artifact(source, root / "out.json", max_input_bytes=1)
            self.assertEqual(raised.exception.code, "legacy-artifact-too-large")

    @unittest.skipIf(os.name == "nt", "symlink creation requires elevated Windows privileges")
    def test_symlink_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "policy.json"
            target.write_text("{}", encoding="utf-8")
            source = root / "link.json"
            source.symlink_to(target)
            with self.assertRaises(LifecycleError) as raised:
                convert_legacy_runner_artifact(source, root / "out.json")
            self.assertEqual(raised.exception.code, "legacy-artifact-symlink")


if __name__ == "__main__":
    unittest.main()
