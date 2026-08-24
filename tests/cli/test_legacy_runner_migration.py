from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from .helpers import _run_cli
from agent_lifecycle.contracts import canonical_digest


class LegacyRunnerMigrationCliTests(unittest.TestCase):
    def test_explicit_conversion_is_read_only_and_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "runner-state.json"
            output = root / "archive" / "conversion.json"
            payload = _runner_state()
            source.write_text(json.dumps(payload), encoding="utf-8")
            before = source.read_bytes()

            code, result = _run_cli(
                [
                    "workflow",
                    "migrate-runner-artifact",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--expected-sha256",
                    _sha256(before),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["schemaVersion"], "agent-workflow-legacy-runner-conversion.v1")
            self.assertFalse(result["authorityClaimed"])
            self.assertFalse(result["stateWritten"])
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["source"]["sha256"], _sha256(before))

    def test_existing_output_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "runner-state.json"
            output = root / "conversion.json"
            source.write_text(json.dumps(_runner_state()), encoding="utf-8")
            output.write_text("original", encoding="utf-8")

            code, result = _run_cli(
                ["workflow", "migrate-runner-artifact", "--input", str(source), "--output", str(output)]
            )

            self.assertEqual(code, 2)
            self.assertEqual(result["code"], "legacy-conversion-output-exists")
            self.assertEqual(output.read_text(encoding="utf-8"), "original")


def _runner_state() -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "agent-runner-state.v1",
        "runnerRevision": 1,
        "status": "READY",
        "currentTaskId": "WS-01",
        "lineage": {"runId": "run-1", "packageId": "package", "sourceRevision": "source"},
        "policy": {},
        "counters": {},
        "history": [{"action": "initialize"}],
        "operations": {"init": {"action": "initialize"}},
    }
    payload["stateDigest"] = canonical_digest(payload)
    return payload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
