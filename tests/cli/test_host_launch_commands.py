from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli import main

ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURE = ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles/valid.json"


class HostLaunchCommandTests(unittest.TestCase):
    def test_qualification_check_missing_evidence_refuses_without_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            request.write_text('{"schemaVersion":"alk-accounting-capability-request.v1"}')
            output = root / "result.json"
            with _working_directory(root), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as process:
                code, payload, _stderr = _run_cli([
                    "host-launch", "qualification-check", "--profiles-root", "work/profiles",
                    "--adapter", "codex", "--request", str(request), "--out", str(output)])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE")
            self.assertEqual(json.loads(output.read_bytes())["outcome"], "DENY")
            process.assert_not_called()

    def test_accounting_request_refuses_before_profile_or_version_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "accounting.json"
            request.write_text('{"outcome":"ALLOW_CAPABILITY","dispatchEntitlement":true}')
            with _working_directory(root), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as process:
                code, payload, _stderr = _run_cli([
                    "host-launch", "preflight", "--profile", "missing.json",
                    "--accounting-request", str(request),
                ])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE")
            process.assert_not_called()

    def test_accounting_check_refuses_and_saves_create_only_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, request, output = root / "profile.json", root / "request.json", root / "output.json"
            profile.write_text('{"status":"PASS"}')
            request.write_text('{"outcome":"ALLOW_CAPABILITY"}')
            args = ["host-launch", "accounting-check", "--profile", str(profile), "--request", str(request),
                    "--expectation-digest", "a" * 64, "--plan-digest", "a" * 64,
                    "--candidate-digest", "a" * 64, "--out", str(output)]
            with _working_directory(root), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as process:
                code, payload, _stderr = _run_cli(args)
                saved = output.read_bytes()
                code2, _payload2, _stderr2 = _run_cli(args)
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "ADAPTER_BUDGET_CAPABILITY_UNAVAILABLE")
            self.assertEqual(json.loads(saved)["outcome"], "DENY")
            self.assertEqual(code2, 2)
            self.assertEqual(output.read_bytes(), saved)
            process.assert_not_called()

    def test_inspect_makes_zero_process_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _write_profile(root)
            with _working_directory(root), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as run_process:
                code, payload, stderr = _run_cli(["host-launch", "inspect", "--profile", str(profile.relative_to(root))])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schemaVersion"], "agent-local-host-launch-profile-receipt.v1")
        self.assertEqual(payload["operation"], "INSPECT")
        self.assertEqual(payload["processCalls"], 0)
        self.assertFalse(payload["hostLaunchStarted"])
        run_process.assert_not_called()

    def test_preflight_makes_one_bounded_redacted_probe(self) -> None:
        process_result = {
            "status": "PASS",
            "exitCode": 0,
            "timedOut": False,
            "stdoutTail": "codex 1.2 API_KEY=secret /Us" "ers/operator/private",
            "stdoutRedacted": False,
            "stderrTail": "",
            "stderrRedacted": False,
            "blockers": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _write_profile(root)
            with _working_directory(root), patch(
                "agent_lifecycle.adapter_sessions.launcher.run_process",
                return_value=process_result,
            ) as run_process:
                code, payload, stderr = _run_cli(["host-launch", "preflight", "--profile", str(profile.relative_to(root))])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["operation"], "PREFLIGHT")
        self.assertEqual(payload["processCalls"], 1)
        self.assertTrue(payload["probeReceipt"]["stdout"]["redacted"])
        self.assertNotIn("secret", payload["probeReceipt"]["stdout"]["tail"])
        run_process.assert_called_once()
        self.assertLessEqual(run_process.call_args.kwargs["timeout_seconds"], 10.0)

    def test_invalid_profile_is_structured_error_without_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _write_profile(root, fixture="shell-command.json")
            with _working_directory(root), patch("agent_lifecycle.adapter_sessions.launcher.run_process") as run_process:
                code, payload, _stderr = _run_cli(["host-launch", "preflight", "--profile", str(profile.relative_to(root))])

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "local-launch-profile-invalid")
        run_process.assert_not_called()


def _write_profile(root: Path, *, fixture: str = "valid.json") -> Path:
    profile = root / ".alk/host-launch/codex.json"
    profile.parent.mkdir(parents=True)
    source = ROOT / "tests/adapter_sessions/fixtures/local_launch_profiles" / fixture
    payload = json.loads(source.read_text(encoding="utf-8"))
    if fixture == "valid.json":
        payload["executable"] = sys.executable
    profile.write_text(json.dumps(payload), encoding="utf-8")
    return profile


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_cli(args: list[str]) -> tuple[int, dict, str]:
    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(args)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
