from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.run_python_quality import _run_command, run_quality


class PythonQualityRunnerTests(unittest.TestCase):
    def test_runner_uses_bounded_command_and_accepts_diagnostic_exit(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "print('diagnostic')"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=1024,
            expected_exit_codes={0, 1},
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "diagnostic")
        self.assertFalse(result["timedOut"])
        self.assertFalse(result["outputLimited"])

    def test_runner_rejects_output_over_limit(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "print('x' * 4096)"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=128,
            expected_exit_codes={0},
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["outputLimited"])

    def test_runner_reports_invocation_failure_as_structured_result(self) -> None:
        result = _run_command(
            ["/path/that/does/not/exist"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=1024,
            expected_exit_codes={0},
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["returncode"])
        self.assertTrue(result["stderr"].strip())

    def test_failed_current_coverage_is_retained_and_next_run_cannot_reuse_it(self) -> None:
        policy = json.loads((Path(__file__).resolve().parents[2] / "policy/python-quality.json").read_text())
        policy["limits"]["maxWallSeconds"] = 30
        policy["limits"]["maxOutputBytes"] = 65536
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "src/agent_lifecycle"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (package / "example.py").write_text("value = 1\n")
            tests = root / "tests"
            tests.mkdir()
            (tests / "__init__.py").write_text("")
            test = tests / "test_case.py"
            test_source = (
                "import unittest\nfrom agent_lifecycle.example import value\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_value(self):\n        self.assertEqual(value, {expected})\n"
            )
            test.write_text(test_source.format(expected=2))
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(policy))
            arguments = dict(repository_root=root, policy_path=policy_path,
                             package_root=package, tests_root=tests, test_top_level=root,
                             base_sha="", work_root=root / "work")
            with patch.dict(os.environ, {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}):
                failed = run_quality(**arguments)
                self.assertEqual(failed["status"], "FAIL")
                coverage = next(row for row in failed["commands"] if row["id"] == "coverage")
                self.assertEqual(coverage["returncode"], 1)
                self.assertFalse(coverage["timedOut"])
                exported = root / failed["artifacts"]["coverage"]
                self.assertGreater(json.loads(exported.read_text())["totals"]["num_statements"], 0)
                self.assertTrue((root / failed["artifacts"]["coverageData"]).is_file())
                prior = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in failed["artifacts"].values()}
                test.write_text(test_source.format(expected=1))
                current = run_quality(**arguments)
            self.assertEqual(current["status"], "PASS", current["blockers"])
            self.assertNotEqual(current["runDirectory"], failed["runDirectory"])
            self.assertNotEqual(current["artifacts"]["coverageData"], failed["artifacts"]["coverageData"])
            self.assertTrue(all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                                for name, digest in prior.items()))
            format_command = next(row for row in current["commands"] if row["id"] == "ruff-format")
            self.assertEqual(format_command["argv"][-2:], ["--output-format", "json"])


if __name__ == "__main__":
    unittest.main()
