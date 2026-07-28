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

class CliSpecificationPlanCommandTests(unittest.TestCase):
    def test_specification_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specification.json"
            path.write_text(
                json.dumps({
                    "tier": "S1",
                    "status": "FROZEN",
                    "requirements": [{"id": "REQ-1", "required": True}],
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli(["specification", "check", "--specification", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-specification-validation.v1")
            self.assertEqual(payload["requirementCount"], 1)

    def test_plan_check_cli_validates_manifest_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "plan.manifest.json"
            manifest = _manifest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            lock_path = root / "plan.lock.json"
            lock_path.write_text(
                json.dumps({
                    "schemaVersion": "agent-plan-lock.v1",
                    "planRevision": manifest["planRevision"],
                    "manifestHash": canonical_digest(manifest),
                }),
                encoding="utf-8",
            )
            code, payload = _run_cli([
                "plan",
                "check",
                "--manifest",
                str(manifest_path),
                "--lock",
                str(lock_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-check.v1")
            self.assertEqual(payload["manifest"]["schemaVersion"], "agent-plan-validation.v1")
            self.assertEqual(payload["lock"]["schemaVersion"], "agent-plan-lock-verification.v1")


if __name__ == "__main__":
    unittest.main()
