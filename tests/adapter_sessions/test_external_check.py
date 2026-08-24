from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions.external_check import (
    load_external_check_profile,
    run_external_check,
)
from agent_lifecycle.contracts import LifecycleError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/quality/fixtures/external-checks"


class ExternalCheckAdapterTests(unittest.TestCase):
    def test_missing_executable_is_unavailable_without_starting_a_process(self) -> None:
        runner = Mock()
        result = run_external_check(
            project_root=ROOT,
            profile_path=FIXTURES / "missing-executable.v1.json",
            plan_digest="1" * 64,
            plan_lock_digest="2" * 64,
            operation_id="missing-tool-op",
            check_id="import-boundaries",
            process_runner=runner,
        )

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertFalse(result["audit"]["blockingEligible"])
        runner.assert_not_called()

    def test_profile_rejects_command_string_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            profile = json.loads((FIXTURES / "missing-executable.v1.json").read_text(encoding="utf-8"))
            profile["argv"] = ["alk-no-such-external-check && touch owned"]
            path.write_text(json.dumps(profile), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                load_external_check_profile(path)

        self.assertEqual(raised.exception.code, "external-check-profile-invalid")

    def test_process_result_is_bound_to_current_source_and_plan(self) -> None:
        profile = json.loads((FIXTURES / "json-check.v1.json").read_text(encoding="utf-8"))
        profile["executable"] = sys.executable
        profile["argv"] = [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'status': 'PASS', 'findings': []}))",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "json.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            with patch.dict("os.environ", {"PATH": os.environ.get("PATH", "")}, clear=True):
                result = run_external_check(
                    project_root=ROOT,
                    profile_path=path,
                    plan_digest="3" * 64,
                    plan_lock_digest="4" * 64,
                    operation_id="clean-tool-op",
                    check_id="import-boundaries",
                )

        self.assertEqual(result["result"]["planDigest"], "3" * 64)
        self.assertEqual(result["result"]["planLockDigest"], "4" * 64)
        self.assertEqual(result["result"]["sourceSnapshot"], result["descriptor"]["sourceSnapshot"])
        self.assertNotIn("stdout", result["result"])

    def test_source_drift_after_process_is_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "pyproject.toml"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=ALK", "-c", "user.email=alk@example.invalid", "commit", "-qm", "base"],
                cwd=root,
                check=True,
            )
            profile = json.loads((FIXTURES / "json-check.v1.json").read_text(encoding="utf-8"))
            profile["executable"] = sys.executable
            profile["argv"] = [sys.executable, "-c", "print('{}')"]
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            def runner(*_args: object, **_kwargs: object) -> dict[str, object]:
                (root / "generated.py").write_text("changed = True\n", encoding="utf-8")
                return {
                    "status": "PASS",
                    "processStarted": True,
                    "timedOut": False,
                    "outputLimitExceeded": False,
                    "cleanup": {"status": "PASS"},
                    "exitCode": 0,
                    "stdout": "{}",
                    "stderr": "",
                }

            result = run_external_check(
                project_root=root,
                profile_path=profile_path,
                plan_digest="5" * 64,
                plan_lock_digest="6" * 64,
                operation_id="drift-op",
                check_id="import-boundaries",
                process_runner=runner,
            )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn({"code": "external-check-source-drift"}, result["result"]["blockers"])
        self.assertFalse(result["audit"]["blockingEligible"])


if __name__ == "__main__":
    unittest.main()
