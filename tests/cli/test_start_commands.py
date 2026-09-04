from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.session_store import create_session
from agent_lifecycle.cli import main
from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.resources import builtin_profile_path

from .test_adapter_task_commands import _write_bundle

ROOT = Path(__file__).resolve().parents[2]


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

    def test_risk_flags_have_safe_defaults_and_bounded_choices(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(["start", "--adapter", "codex", "--text", "task"])
        explicit = parser.parse_args(["start", "--adapter", "codex", "--text", "task", "--risk", "S2"])

        self.assertEqual(parsed.risk, "auto")
        self.assertEqual(parsed.risk_policy, builtin_profile_path("risk-execution-policy.v1.json"))
        self.assertEqual(explicit.risk, "S2")
        with contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["start", "--adapter", "codex", "--text", "task", "--risk", "LOW"])

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

    def test_risk_profile_out_writes_the_exact_projected_profile(self) -> None:
        profile = {"schemaVersion": "agent-risk-execution-profile.v1", "profileDigest": "b" * 64}
        managed_receipt = {
            "schemaVersion": "agent-adapter-session-receipt.v1",
            "status": "READY",
            "blockers": [],
            "lifecycleCoverageClaimed": True,
            "hostLaunchStarted": False,
            "nextAction": {"riskExecutionProfile": profile, "riskProfileRequiredAtTaskStart": True},
            "receiptDigest": "a" * 64,
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run",
                return_value=managed_receipt,
            ),
        ):
            out = Path(tmp) / "risk-profile.json"
            code, payload, stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--mode",
                    "implement",
                    "--text",
                    json.dumps(_run_request()),
                    "--risk-profile-out",
                    str(out),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), profile)
            self.assertEqual(payload["delegate"]["riskExecutionProfile"], profile)

    def test_public_start_writes_the_same_managed_strategy_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root)
            descriptor = root / "adapters/codex/adapter.descriptor.json"
            descriptor.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "adapters/codex/adapter.descriptor.json", descriptor)
            shutil.copyfile(
                ROOT / "adapters/codex/capabilities.manifest.json",
                descriptor.with_name("capabilities.manifest.json"),
            )
            strategy_out = root / "work/execution-strategy.json"
            strategy_out.parent.mkdir()

            code, payload, stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--mode",
                    "implement",
                    "--file",
                    str(manifest),
                    "--descriptor",
                    str(descriptor),
                    "--state",
                    str(state),
                    "--lock",
                    str(manifest.with_name("plan.lock.json")),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "public-strategy-start",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--strategy-out",
                    str(strategy_out),
                    "--session-root",
                    str(root / "sessions"),
                    "--no-project-profile",
                ]
            )

            strategy = json.loads(strategy_out.read_text(encoding="utf-8"))
            self.assertEqual(code, 0, payload)
            self.assertEqual(stderr, "")
            self.assertTrue(strategy["authority"]["automaticAdoptionEligible"])
            self.assertEqual(payload["executionStrategy"]["strategyDigest"], strategy["strategyDigest"])
            self.assertFalse(payload["executionStrategy"]["modelCallsStarted"])

    def test_launch_profile_requires_launch_and_raw_implement_stays_blocked(self) -> None:
        profile_only = _run_cli(
            ["start", "--adapter", "codex", "--text", "task", "--host-launch-profile", ".alk/host-launch/codex.json"]
        )[1]
        planning = _run_cli(["start", "--adapter", "codex", "--text", "task", "--launch"])[1]
        implement = _run_cli(["start", "--adapter", "codex", "--mode", "implement", "--text", "task", "--launch"])[1]

        self.assertEqual(profile_only["blockers"][0]["code"], "start-launch-arguments-incomplete")
        self.assertEqual(planning["status"], "BLOCKED")
        self.assertIn("profileCommand", planning["blockers"][0])
        self.assertIn("preflightCommand", planning["blockers"][0])
        self.assertEqual(implement["blockers"][0]["code"], "start-implement-frozen-input-required")

    def test_implement_launch_delegates_only_after_ready_managed_projection(self) -> None:
        risk_profile = {"schemaVersion": "agent-risk-execution-profile.v1", "profileDigest": "b" * 64}
        task_receipt = {
            "schemaVersion": "agent-adapter-task-start-receipt.v1",
            "status": "READY",
            "action": "MANAGED_RUN",
            "executionStarted": True,
            "lifecycleCoverageClaimed": True,
            "reviewBlockers": [],
            "input": {"type": "FILE", "label": "request.json", "digest": "a" * 64, "byteCount": 10},
            "workflowBinding": {
                "state": "state.json",
                "manifest": "plan.manifest.json",
                "lock": "plan.lock.json",
                "task": "WS-01",
                "operationId": "start-run",
                "sourceRevision": "source",
            },
            "adapterSessionReceipt": {
                "sessionId": "session-1",
                "nextAction": {"riskExecutionProfile": risk_profile},
            },
        }
        launch_receipt = {
            "schemaVersion": "agent-managed-adapter-launch-receipt.v1",
            "status": "PASS",
            "hostLaunchStarted": True,
            "blockers": [],
            "receiptDigest": "c" * 64,
        }
        with (
            patch(
                "agent_lifecycle.adapter_sessions.unified_start.start_adapter_task",
                return_value=task_receipt,
            ),
            patch(
                "agent_lifecycle.adapter_sessions.unified_start.load_local_launch_profile",
                return_value=(Path(".alk/host-launch/codex.json"), {"adapterId": "codex"}, {"status": "PASS"}),
            ),
            patch(
                "agent_lifecycle.adapter_sessions.unified_start.launch_from_local_profile",
                return_value=launch_receipt,
            ) as launch,
        ):
            code, payload, stderr = _run_cli(
                [
                    "start",
                    "--adapter",
                    "codex",
                    "--mode",
                    "implement",
                    "--text",
                    json.dumps(_run_request()),
                    "--launch",
                    "--host-launch-profile",
                    ".alk/host-launch/codex.json",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["hostLaunchStarted"])
        self.assertEqual(payload["launchReceipt"]["status"], "PASS")
        launch.assert_called_once()


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
