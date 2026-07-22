from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.audit import build_ownership_report  # noqa: E402


class OwnershipTests(unittest.TestCase):
    def test_report_classifies_workstream_lead_plan_and_unowned_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                manifest = Path("plan.manifest.json")
                manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
                report = build_ownership_report(
                    manifest,
                    [
                        "plan.manifest.json",
                        "src/package/core.py",
                        "runtime/state.json",
                        "plan/files/spec.json",
                        "README.extra.md",
                        "LICENSE",
                    ],
                    base="main",
                )
            finally:
                os.chdir(previous_cwd)
            by_path = {entry["path"]: entry for entry in report["entries"]}
            self.assertEqual(by_path["plan.manifest.json"]["category"], "plan-authority")
            self.assertEqual(by_path["src/package/core.py"]["owners"], ["WS-01"])
            self.assertEqual(by_path["runtime/state.json"]["category"], "lead-owned")
            self.assertEqual(by_path["plan/files/spec.json"]["category"], "plan-authority")
            self.assertEqual(by_path["README.extra.md"]["category"], "unowned")
            self.assertEqual(by_path["LICENSE"]["category"], "forbidden")


def _manifest() -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "sample",
            "planArtifactRoot": "plan/files",
        },
        "leadOwned": [{"path": "runtime", "reason": "controller artifacts"}],
        "readOnly": ["LICENSE", "plan/files"],
        "forbiddenWrites": ["LICENSE", "plan/files"],
        "workstreams": [
            {
                "id": "WS-01",
                "writes": ["src/package"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
