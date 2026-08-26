from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES
from agent_lifecycle.metrics import build_phase_resource_measurement

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class PhaseResourceCommandTests(unittest.TestCase):
    def test_cli_matches_builder_bytes_and_digest(self) -> None:
        source = {
            "schemaVersion": "agent-phase-resource-input.v1",
            "phases": [_phase("planning", "PLANNING"), _phase("audit", "AUDIT")],
            "lineage": {"runId": "release-2-6"},
            "sourceArtifacts": [],
        }
        expected = build_phase_resource_measurement(
            source["phases"],
            lineage=source["lineage"],
            source_artifacts=source["sourceArtifacts"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "phases-input.json"
            output_path = root / "phases.json"
            input_path.write_text(json.dumps(source), encoding="utf-8")

            code, receipt = _run_cli(
                ["metrics", "phase-resources", "--input", str(input_path), "--out", str(output_path)]
            )
            output_bytes = output_path.read_bytes()

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output_bytes), expected)
        self.assertEqual(receipt["measurementDigest"], expected["measurementDigest"])
        self.assertEqual(receipt["outputBytes"], len(output_bytes))
        self.assertEqual(receipt["validation"]["status"], "PASS")

    def test_cli_rejects_input_above_shared_json_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "oversized.json"
            input_path.write_bytes(b'{"padding":"' + b"x" * MAX_JSON_INPUT_BYTES + b'"}')

            code, payload = _run_cli(
                ["metrics", "phase-resources", "--input", str(input_path), "--out", str(root / "out.json")]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "json-input-too-large")


def _phase(phase_id: str, phase_kind: str) -> dict[str, object]:
    return {
        "phaseId": phase_id,
        "phaseKind": phase_kind,
        "tokens": {"input": 10, "output": 5, "total": 15},
        "steps": 2,
        "resources": {"toolCalls": 2},
        "durationMs": 100,
        "receiptDigests": [],
    }


if __name__ == "__main__":
    unittest.main()
