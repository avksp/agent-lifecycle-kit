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

class CliContextCommandTests(unittest.TestCase):
    def test_context_profile_check_cli(self) -> None:
        code, payload = _run_cli([
            "context",
            "profile-check",
            "--profile",
            str(ROOT / "profiles/small-context-profile.v1.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-small-context-profile-validation.v1")
        self.assertEqual(payload["defaultWindow"], "8k")
        self.assertIn("4k-strict", payload["windows"])

    def test_context_check_overflow_returns_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, summary = _write_context_inputs(Path(tmp), oversized=True)
            code, payload = _run_cli([
                "context",
                "check",
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--task-packet",
                str(packet),
                "--summary",
                str(summary),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "context-overflow")
            self.assertEqual(payload["details"]["receipt"]["status"], "FAIL")

    def test_context_render_overflow_returns_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet, summary = _write_context_inputs(Path(tmp), oversized=True)
            code, payload = _run_cli([
                "context",
                "render",
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--task-packet",
                str(packet),
                "--summary",
                str(summary),
                "--target-window",
                "4k-strict",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "context-overflow")
            self.assertEqual(payload["details"]["receipt"]["status"], "FAIL")

    def test_task_compile_cli_writes_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_task_compile_bundle(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                code, payload = _run_cli(["task", "compile", "--manifest", str(manifest_path), "--write"])
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-task-packet-compile-result.v1")
            self.assertEqual(payload["index"]["packetCount"], 1)
            packet_path = root / "plans/p/workflow/task-packets/WS-01.task-packet.json"
            self.assertTrue(packet_path.exists())


if __name__ == "__main__":
    unittest.main()
