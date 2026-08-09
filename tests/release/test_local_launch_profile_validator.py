from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LocalLaunchProfileValidatorTests(unittest.TestCase):
    def test_release_validator_covers_positive_and_negative_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/release/validate_local_launch_profiles.py",
                    "--fixtures",
                    "tests/adapter_sessions/fixtures/local_launch_profiles",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["fixtureCount"], 5)
        self.assertFalse(payload["hostLaunchStarted"])


if __name__ == "__main__":
    unittest.main()
