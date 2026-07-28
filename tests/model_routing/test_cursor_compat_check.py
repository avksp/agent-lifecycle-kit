from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CursorCompatCheckTests(unittest.TestCase):
    def test_cursor_compat_check_accepts_fixture_and_redacts_evidence(self) -> None:
        # NEG-R04-02 Cursor Compatibility Evidence Missing Model Pin
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "cursor-compat.json"
            result = _run_cursor_compat(
                ROOT / "tasks/release-0-3/evidence/live-promotion-audit-cursor.json",
                ROOT / "tests/model_routing/fixtures/release-0-4/cursor-glm-compat.json",
                evidence,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-cursor-compat-evidence.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["source"]["kind"], "fixture")
            encoded = json.dumps(payload)
            self.assertNotIn("glm-5.2-max", encoded)
            self.assertNotIn("glm-5.2-high", encoded)

    def test_cursor_compat_check_rejects_critical_downshift(self) -> None:
        # NEG-R04-03 Critical Cursor Phase Downgraded
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "cursor-fixture.json"
            payload = json.loads((ROOT / "tests/model_routing/fixtures/release-0-4/cursor-glm-compat.json").read_text(encoding="utf-8"))
            payload["modelSelections"][0]["providerModel"] = "glm-5.2-high"
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            evidence = Path(tmp) / "cursor-compat.json"
            result = _run_cursor_compat(Path(tmp) / "missing-audit.json", fixture, evidence)
            self.assertEqual(result.returncode, 1)
            report = json.loads(evidence.read_text(encoding="utf-8"))
            failed = {check["name"] for check in report["checks"] if check["status"] == "FAIL"}
            self.assertIn("strong-reasoning-binding-matches-expected-family", failed)
            self.assertIn("critical-phases-use-strong-binding", failed)


def _run_cursor_compat(cursor_audit: Path, fixture: Path, evidence: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tests/model_routing/run_cursor_compat_check.py"),
            "--cursor-audit",
            str(cursor_audit),
            "--fixture",
            str(fixture),
            "--evidence",
            str(evidence),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
