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

from validate_review_mesh_host_boundary import validate_paths  # noqa: E402


class ReviewMeshHostBoundaryValidatorTests(unittest.TestCase):
    def test_current_review_mesh_sources_pass(self) -> None:
        payload = validate_paths(
            [
                ROOT / "src/agent_lifecycle/review_mesh/assignments.py",
                ROOT / "src/agent_lifecycle/review_mesh/results.py",
                ROOT / "src/agent_lifecycle/review_mesh/synthesis.py",
                ROOT / "src/agent_lifecycle/review_mesh/quorum.py",
            ]
        )

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertFalse(payload["productionPromotionClaimed"])

    def test_validator_rejects_hidden_launch_and_prompt_authority_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad_review_mesh.py"
            bad.write_text("from os import system\nmessage = 'bypass review'\n", encoding="utf-8")

            payload = validate_paths([bad])

        codes = {item["code"] for item in payload["blockers"]}
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("review-mesh-hidden-launch-from-import", codes)
        self.assertIn("review-mesh-prompt-authority-marker", codes)

    def test_cli_writes_evidence_and_returns_nonzero_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad_review_mesh.py"
            evidence = root / "host-boundary.json"
            bad.write_text("import subprocess\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_RELEASE / "validate_review_mesh_host_boundary.py"),
                    "--path",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
