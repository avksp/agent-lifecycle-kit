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

    def test_context_external_import_cli_writes_non_authoritative_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "memory.md"
            out = root / "external-context.json"
            source.write_text("Memory says auth retries need bounded evidence.", encoding="utf-8")

            code, payload = _run_cli([
                "context",
                "external-import",
                "--source",
                str(source),
                "--citation",
                "operator memory export",
                "--out",
                str(out),
            ])

            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertEqual(payload["schemaVersion"], "agent-external-context-import-receipt.v1")
            self.assertFalse(payload["sourceOfTruth"])
            self.assertFalse(payload["hints"][0]["proof"])

    def test_context_episode_retrieve_cli_accepts_external_context_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/result.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "taskId": "T-1"}), encoding="utf-8")
            source = root / "memory.md"
            source.write_text("Prior memory: retry work needs idempotency checks.", encoding="utf-8")
            receipt_path = root / "external-context.json"
            code, _receipt = _run_cli([
                "context",
                "external-import",
                "--source",
                str(source),
                "--out",
                str(receipt_path),
            ])
            self.assertEqual(code, 0)

            code, payload = _run_cli([
                "context",
                "episode-retrieve",
                "--project-root",
                str(root),
                "--artifact",
                "evidence/result.json",
                "--external-context",
                str(receipt_path),
                "--query",
                "retry",
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-episode-retrieval.v1")
            self.assertEqual(payload["externalContextHintCount"], 1)
            self.assertFalse(payload["externalContextPolicy"]["proof"])


if __name__ == "__main__":
    unittest.main()
