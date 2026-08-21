from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CliDispatchBoundaryValidatorTests(unittest.TestCase):
    def test_current_root_dispatcher_passes_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "dispatch-boundary.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_cli_dispatch_boundary.py"),
                    "--path",
                    "src/agent_lifecycle/cli/dispatch.py",
                    "--max-lines",
                    "800",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertLessEqual(payload["actualLines"], 800)
        self.assertEqual(len(payload["routedDelegates"]), 6)

    def test_validator_rejects_oversized_dispatcher_without_delegates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "dispatch.py"
            path.write_text("def _dispatch_domain():\n    pass\n" + ("# filler\n" * 5), encoding="utf-8")
            evidence = root / "dispatch-boundary.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_cli_dispatch_boundary.py"),
                    "--path",
                    str(path),
                    "--max-lines",
                    "2",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("cli-dispatch-line-limit-exceeded", codes)
        self.assertIn("cli-dispatch-delegate-import-missing", codes)
        self.assertIn("cli-dispatch-domain-handler-retained", codes)

    def test_current_observability_dispatcher_uses_specialized_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "observability-boundary.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_cli_dispatch_boundary.py"),
                    "--path",
                    "src/agent_lifecycle/cli/dispatch_observability.py",
                    "--max-lines",
                    "800",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["role"], "observability")
        self.assertEqual(payload["requiredDelegates"], {})
