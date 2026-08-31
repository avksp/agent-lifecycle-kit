from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from validate_no_model_calls import validate_no_model_calls  # noqa: E402


class NoModelCallScanTests(unittest.TestCase):
    def test_workflow_run_sources_do_not_import_model_clients(self) -> None:
        payload = validate_no_model_calls(
            [
                ROOT / "src/agent_lifecycle/workflow/run.py",
                ROOT / "src/agent_lifecycle/workflow/continuation.py",
                ROOT / "src/agent_lifecycle/workflow/continuation_batch.py",
                ROOT / "src/agent_lifecycle/workflow/managed_runner.py",
                ROOT / "src/agent_lifecycle/workflow/next_action.py",
            ]
        )

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertFalse(payload["modelCallsStarted"])
        self.assertFalse(payload["productionPromotionClaimed"])

    def test_model_client_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad_runner.py"
            source.write_text("import openai\n", encoding="utf-8")

            payload = validate_no_model_calls([source])

            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("model-or-network-import-detected", {item["code"] for item in payload["blockers"]})

    def test_cli_writes_evidence_and_nonzero_exit_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bad_runner.py"
            source.write_text("import requests\n", encoding="utf-8")
            evidence = root / "scan.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_RELEASE / "validate_no_model_calls.py"),
                    "--path",
                    str(source),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
