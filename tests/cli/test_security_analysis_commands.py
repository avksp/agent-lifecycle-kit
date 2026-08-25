from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.cli.helpers import _run_cli


class SecurityAnalysisCliTests(unittest.TestCase):
    def test_security_profile_command_is_optional(self) -> None:
        code, payload = _run_cli(["quality", "security-profile"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["profileId"], "security-analysis")
        self.assertFalse(payload["enabledByDefault"])

    def test_security_findings_import_command_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.json"
            path.write_text(
                json.dumps(
                    {
                        "sourceRevision": "source-1",
                        "findings": [{"id": "SEC-1", "title": "issue", "severity": "LOW", "path": "src/a.py"}],
                    }
                ),
                encoding="utf-8",
            )
            code, payload = _run_cli(
                ["import", "security-findings", "--source", str(path), "--expected-source-revision", "source-1"]
            )
        self.assertEqual(code, 0)
        self.assertFalse(payload["trusted"])
        self.assertFalse(payload["authorityClaimed"])
        self.assertEqual(payload["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
