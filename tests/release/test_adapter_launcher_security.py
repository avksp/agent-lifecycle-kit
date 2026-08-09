from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdapterLauncherSecurityValidatorTests(unittest.TestCase):
    def test_current_launcher_sources_pass_security_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "adapter-launcher-security.json"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    "src/agent_lifecycle/adapter_sessions",
                    "--paths",
                    "src/agent_lifecycle/cli/adapter.py",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["schemaVersion"], "agent-adapter-launcher-security-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["requiredInvariants"]["argvArrays"])
        self.assertFalse(payload["requiredInvariants"]["nativeConfigWrites"])

    def test_validator_rejects_shell_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad_launcher.py"
            evidence = root / "evidence.json"
            bad.write_text("subprocess.run(['echo'], shell=True)\\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("adapter-launcher-forbidden-snippet", {item["code"] for item in payload["blockers"]})

    def test_validator_rejects_generic_launcher_process_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "launcher.py"
            evidence = root / "evidence.json"
            bad.write_text("def launch_from_descriptor():\n    return run_process([])\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adapter-generic-launch-process-route", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()
