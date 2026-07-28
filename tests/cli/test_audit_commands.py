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

class CliAuditCommandTests(unittest.TestCase):
    def test_audit_ownership_outputs_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "plan.manifest.json"
            manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "audit",
                    "ownership",
                    "--manifest",
                    str(manifest),
                    "--path",
                    "src/core.py",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-ownership-report.v1")
            self.assertEqual(payload["entries"][0]["owners"], ["WS-01"])


if __name__ == "__main__":
    unittest.main()
