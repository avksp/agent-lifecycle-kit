from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest

try:
    from .helpers import ROOT, _run, _write_context_manifest, _write_json
except ImportError:
    from helpers import ROOT, _run, _write_context_manifest, _write_json


class TaskPacketContextVerifierTests(unittest.TestCase):
    def test_task_packet_context_verifier_compiles_and_checks_windows(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            out = Path(tmp)
            manifest = _write_context_manifest(out)
            value = json.loads(manifest.read_text(encoding="utf-8"))
            for key in ("artifactRoot", "planArtifactRoot"):
                value["package"][key] = Path(value["package"][key]).relative_to(ROOT).as_posix()
            _write_json(manifest, value)
            lock_path = out / "plan/plan.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["manifestHash"] = canonical_digest(value)
            _write_json(lock_path, lock)
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
