from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DigestAuthorityRunnerTests(unittest.TestCase):
    def test_digest_authority_runner_rejects_divergent_canonicalizer(self) -> None:
        # NEG-R03-20 Digest Authority Drift
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "digest-authority.json"

            subprocess.run(
                [
                    sys.executable,
                    "tests/contracts/run_digest_authority_check.py",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            checks = {item["id"]: item for item in payload["checks"]}
            self.assertEqual(checks["divergent-canonicalizer-rejected"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
