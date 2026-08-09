from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.session_store import create_session
from agent_lifecycle.cli import main
from agent_lifecycle.cli.parsers import build_parser


class StartCommandTests(unittest.TestCase):
    def test_text_defaults_to_auto_and_returns_json_receipt(self) -> None:
        code, payload, stderr = _run_cli(["start", "--adapter", "codex", "--text", "Research the cache design"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-start-receipt.v1")
        self.assertEqual(payload["requestedMode"], "auto")
        self.assertEqual(payload["status"], "REVIEW_REQUIRED")
        self.assertFalse(payload["executionStarted"])

    def test_canonical_and_alias_task_flags_share_the_same_destinations(self) -> None:
        parser = build_parser()
        canonical_file = parser.parse_args(["start", "--adapter", "codex", "--file", "task.md"])
        alias_file = parser.parse_args(["start", "--adapter", "codex", "--task-file", "task.md"])
        canonical_text = parser.parse_args(["start", "--adapter", "codex", "--text", "task"])
        alias_text = parser.parse_args(["start", "--adapter", "codex", "--task-text", "task"])

        self.assertEqual(canonical_file.task_file, alias_file.task_file)
        self.assertEqual(canonical_text.task_text, alias_text.task_text)

    def test_parser_requires_adapter_and_exactly_one_action(self) -> None:
        parser = build_parser()
        cases = (
            ["start", "--text", "task"],
            ["start", "--adapter", "codex"],
            ["start", "--adapter", "codex", "--text", "task", "--resume", "session"],
            ["start", "--adapter", "codex", "--file", "task.md", "--text", "task"],
        )
        for argv in cases:
            with self.subTest(argv=argv), contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(argv)

    def test_research_mode_is_non_executing(self) -> None:
        code, payload, _stderr = _run_cli(
            ["start", "--adapter", "codex", "--mode", "research", "--task-text", "Inspect this module"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["requestedMode"], "research")
        self.assertEqual(payload["status"], "REVIEW_REQUIRED")
        self.assertFalse(payload["executionStarted"])

    def test_implement_mode_delegates_only_complete_structured_request(self) -> None:
        managed_receipt = {
            "schemaVersion": "agent-adapter-session-receipt.v1",
            "status": "READY",
            "blockers": [],
            "lifecycleCoverageClaimed": True,
            "hostLaunchStarted": False,
            "receiptDigest": "a" * 64,
        }
        with patch(
            "agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run",
            return_value=managed_receipt,
        ) as managed_run:
            code, payload, stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--mode",
                    "implement",
                    "--text",
                    json.dumps(_run_request()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["action"], "MANAGED_RUN")
        self.assertTrue(payload["executionStarted"])
        managed_run.assert_called_once()

    def test_resume_missing_session_returns_blocked_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, payload, _stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--resume",
                    "missing",
                    "--session-root",
                    tmp,
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["blockers"][0]["code"], "start-resume-session-missing")

    def test_resume_with_implement_mode_is_rejected_by_the_domain_guard(self) -> None:
        code, payload, _stderr = _run_cli(
            [
                "start",
                "--adapter",
                "codex",
                "--resume",
                "session",
                "--mode",
                "implement",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["blockers"][0]["code"], "start-resume-mode-invalid")
        self.assertFalse(payload["executionStarted"])

    def test_resume_persisted_unbound_session_is_unmanaged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = create_session(
                adapter_id="codex",
                mode="INTERACTIVE",
                status="WAITING_FOR_TASK",
                launch_profile={"status": "WRAPPER_ONLY"},
                session_root=root,
            )
            code, payload, _stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--resume",
                    session["sessionId"],
                    "--session-root",
                    str(root),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "UNMANAGED")
        self.assertFalse(payload["lifecycleCoverageClaimed"])

    def test_out_writes_the_same_receipt_and_unknown_args_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "start.json"
            code, payload, _stderr = _run_cli(
                ["start", "--adapter", "codex", "--text", "Draft a plan", "--out", str(out)]
            )
            written = json.loads(out.read_text(encoding="utf-8"))
        unknown_code, unknown, _stderr = _run_cli(
            ["start", "--adapter", "codex", "--text", "Draft a plan", "--unknown"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(written, payload)
        self.assertEqual(unknown_code, 2)
        self.assertEqual(unknown["code"], "start-argument-unknown")


def _run_cli(args: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def _run_request() -> dict[str, object]:
    return {
        "schemaVersion": "agent-adapter-task-run-request.v1",
        "adapterId": "codex",
        "state": "state.json",
        "manifest": "tasks/release/plan.manifest.json",
        "lock": "tasks/release/plan.lock.json",
        "task": "WS-01",
        "operationId": "start-run",
        "expectedRevision": 1,
        "sourceRevision": "source",
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()
