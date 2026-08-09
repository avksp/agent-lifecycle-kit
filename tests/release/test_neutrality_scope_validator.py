from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NeutralityScopeValidatorTests(unittest.TestCase):
    def test_current_scope_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "scope.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_neutrality_scopes.py"),
                    "--policy",
                    "policy/neutrality.policy.json",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["scope"], "tracked-release")
        self.assertEqual(payload["blockers"], [])


if __name__ == "__main__":
    unittest.main()
