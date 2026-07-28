from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class TaskPacketContextVerifierTests(unittest.TestCase):
    def test_task_packet_context_verifier_compiles_and_checks_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = _write_context_manifest(out)
            summary = out / "summary.json"
            evidence = out / "context-fit.json"
            _write_json(
                summary,
                {
                    "acceptedEvidence": [],
                    "activeDecisions": ["Use compact context."],
                    "changedFiles": [],
                    "doNotDo": ["Do not truncate."],
                    "latestUserIntent": "Implement the task.",
                    "nextRequiredAction": "Run validation.",
                    "openBlockers": [],
                },
            )

            _run(
                "tools/release/verify_task_packet_context.py",
                "--manifest",
                str(manifest),
                "--profile",
                "profiles/small-context-profile.v1.json",
                "--summary",
                str(summary),
                "--out-dir",
                str(out / "packets"),
                "--target-windows",
                "4k-strict,8k",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual({item["window"] for item in payload["checks"]}, {"4k-strict", "8k"})


if __name__ == "__main__":
    unittest.main()
