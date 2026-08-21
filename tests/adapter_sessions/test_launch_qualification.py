from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile

ROOT = Path(__file__).resolve().parents[2]


class LaunchQualificationTests(unittest.TestCase):
    def test_preflight_writes_bound_receipt_for_exact_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = load_shipped_launch_profile("codex", repository_root=ROOT)
            profile["executable"] = sys.executable
            path = root / ".alk/host-launch/codex.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(profile), encoding="utf-8")
            result = {
                "status": "PASS", "exitCode": 0, "timedOut": False,
                "stdoutTail": "codex-cli 0.147.0", "stderrTail": "",
                "stdoutRedacted": False, "stderrRedacted": False, "blockers": [],
            }
            with patch("agent_lifecycle.adapter_sessions.launcher.run_process", return_value=result) as run_process:
                receipt = launch_from_local_profile(profile_path=path, operation="preflight", project_root=root, process_env={"PATH": "/bin", "HOME": "/tmp"})
            qualification = receipt["qualificationReceipt"]
            stored_exists = (root / ".alk/host-launch/codex-0.147.0.qualification.json").is_file()
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(qualification["status"], "PASS")
        self.assertEqual(qualification["executableIdentity"]["status"], "PASS")
        self.assertEqual(receipt["hostIdentity"]["executableContentSha256"], qualification["executableIdentity"]["executableContentSha256"])
        self.assertTrue(stored_exists)
        run_process.assert_called_once()

    def test_preflight_fails_closed_for_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = load_shipped_launch_profile("codex", repository_root=ROOT)
            profile["executable"] = sys.executable
            path = root / ".alk/host-launch/codex.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(profile), encoding="utf-8")
            result = {
                "status": "PASS", "exitCode": 0, "timedOut": False,
                "stdoutTail": "codex-cli 0.148.0", "stderrTail": "",
                "stdoutRedacted": False, "stderrRedacted": False, "blockers": [],
            }
            with patch("agent_lifecycle.adapter_sessions.launcher.run_process", return_value=result):
                receipt = launch_from_local_profile(profile_path=path, operation="preflight", project_root=root, process_env={"PATH": "/bin", "HOME": "/tmp"})
        self.assertEqual(receipt["status"], "FAIL")
        self.assertIn("qualified-launch-version-mismatch", {item["code"] for item in receipt["blockers"]})


if __name__ == "__main__":
    unittest.main()
