from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.run_python_quality import _run_command, run_quality
from tools.release.validate_python_quality import validate_quality


class PythonQualityRunnerTests(unittest.TestCase):
    def test_selected_tool_strict_types_cover_supported_platforms(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        policy = json.loads((repository / "policy/python-quality.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            for platform in ("win32", "linux", "darwin"):
                with self.subTest(platform=platform):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "mypy",
                            "--strict",
                            "--platform",
                            platform,
                            *policy["tooling"]["paths"],
                            "--cache-dir",
                            str(Path(directory) / platform),
                        ],
                        cwd=repository,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

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
        policy.pop("tooling")
        policy["mypy"]["strictClean"] = []
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
            arguments = dict(
                repository_root=root,
                policy_path=policy_path,
                package_root=package,
                tests_root=tests,
                test_top_level=root,
                base_sha="",
                work_root=root / "work",
            )
            with patch.dict(os.environ, {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}):
                failed = run_quality(**arguments)
                self.assertEqual(failed["status"], "FAIL")
                coverage = next(row for row in failed["commands"] if row["id"] == "coverage")
                self.assertEqual(coverage["returncode"], 1)
                self.assertFalse(coverage["timedOut"])
                exported = root / failed["artifacts"]["coverage"]
                self.assertGreater(json.loads(exported.read_text())["totals"]["num_statements"], 0)
                self.assertTrue((root / failed["artifacts"]["coverageData"]).is_file())
                prior = {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in failed["artifacts"].values()
                }
                test.write_text(test_source.format(expected=1))
                current = run_quality(**arguments)
            self.assertEqual(current["status"], "PASS", current["blockers"])
            self.assertNotEqual(current["runDirectory"], failed["runDirectory"])
            self.assertNotEqual(current["artifacts"]["coverageData"], failed["artifacts"]["coverageData"])
            self.assertTrue(
                all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in prior.items())
            )
            format_command = next(row for row in current["commands"] if row["id"] == "ruff-format")
            self.assertEqual(format_command["argv"][-2:], ["--output-format", "json"])

    def test_selected_tool_gate_rejects_real_lint_type_format_and_source_drift(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        policy = json.loads((repository / "policy/python-quality.json").read_text())
        # A tiny runtime isolates the selected tool gate. Production floors and
        # runtime baselines are untouched; these fixture sources have no debt.
        for name in ("correctnessBaseline", "migrationBaseline", "formatBaseline", "lineLengthBaseline"):
            policy["ruff"][name] = []
        policy["mypy"]["strictClean"] = ["src/agent_lifecycle/__init__.py"]
        policy["coverage"] = {"minimumStatementLinePercent": 76, "baseline": {}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for relative in (
                *policy["tooling"]["paths"],
                "tools/release/run_python_quality.py",
                "tools/release/release_common.py",
                "pyproject.toml",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repository / relative, target)
            package = root / "src/agent_lifecycle"
            package.mkdir(parents=True)
            # Real CLIs use the canonical writer outside the tiny checked runtime.
            (package / "__init__.py").write_text(
                "__path__.append(\n    " + repr(str(repository)) + "\n    '/src/agent_lifecycle'\n)\nvalue = 1\n"
            )
            subprocess.run(
                [sys.executable, "-m", "ruff", "format", str(package / "__init__.py")],
                capture_output=True,
                check=True,
                timeout=15,
            )
            tests = root / "tests"
            tests.mkdir()
            (tests / "__init__.py").write_text("")
            (tests / "test_case.py").write_text(
                "import unittest\nfrom agent_lifecycle import value\n"
                "class Example(unittest.TestCase):\n"
                "    def test_value(self):\n        self.assertEqual(value, 1)\n"
            )
            policy_path, run_path = root / "policy.json", root / "run.json"
            policy_path.write_text(json.dumps(policy))

            def execute(package_argument: str | None = None) -> tuple[dict, dict]:
                with patch.dict(os.environ, {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(repository / "tools/release/run_python_quality.py"),
                            "--policy",
                            "policy.json",
                            "--package-root",
                            package_argument or str(package),
                            "--tests-root",
                            "tests",
                            "--test-top-level",
                            ".",
                            "--base-sha",
                            "",
                            "--work-root",
                            "work",
                            "--evidence",
                            "run.json",
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    self.assertTrue(completed.stdout.strip(), completed.stderr)
                    run = json.loads(completed.stdout)
                    self.assertEqual(completed.returncode, 0 if run["status"] == "PASS" else 1, completed.stderr)
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(repository / "tools/release/validate_python_quality.py"),
                            "--policy",
                            "policy.json",
                            "--run-receipt",
                            "run.json",
                            "--work-root",
                            "work",
                            "--evidence",
                            "validation.json",
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    self.assertTrue(completed.stdout.strip(), completed.stderr)
                    checked = json.loads(completed.stdout)
                    self.assertEqual(completed.returncode, 0 if checked["status"] == "PASS" else 1, completed.stderr)
                return run, checked

            control, checked = execute()
            self.assertEqual(checked["status"], "PASS", checked["blockers"])
            print(
                json.dumps(
                    {
                        "case": "selected-tool-unchanged-control",
                        "status": checked["status"],
                        "sourceInventory": control["sourceInventory"],
                        "commands": control["commands"],
                    }
                )
            )
            relative, checked = execute("src/agent_lifecycle")
            print(
                json.dumps(
                    {
                        "case": "relative-cli-control",
                        "status": checked["status"],
                        "blockers": checked["blockers"],
                        "commands": relative["commands"],
                    }
                )
            )
            self.assertEqual(checked["status"], "PASS", checked["blockers"])
            self.assertEqual(relative["sourceInventory"], control["sourceInventory"])
            for selected in policy["tooling"]["paths"]:
                self.assertIn(selected, control["sourceInventory"])
                for identifier in ("ruff-correctness", "ruff-migration", "ruff-format", "mypy-strict"):
                    command = next(row for row in control["commands"] if row["id"] == identifier)
                    self.assertIn(selected, command["argv"])
            selected = root / policy["tooling"]["paths"][0]
            original = selected.read_text()
            seeds = {
                "lint": ("\n\nunused_import_probe = undefined_quality_probe\n", "new-quality-finding"),
                "type": ('\n\ntyped_quality_probe: int = "wrong"\n', "quality-strict-command-failed"),
                "format": ("\n\nformat_quality_probe=[1,2,3]\n", "new-quality-finding"),
            }
            for label, (seed, expected) in seeds.items():
                with self.subTest(seed=label):
                    selected.write_text(original + seed)
                    run, checked = execute()
                    self.assertEqual(checked["status"], "FAIL", checked)
                    self.assertIn(expected, {row["code"] for row in checked["blockers"]})
                    print(
                        json.dumps(
                            {
                                "case": label,
                                "status": checked["status"],
                                "blockers": checked["blockers"],
                                "commands": run["commands"],
                            }
                        )
                    )
                    selected.write_text(original)
            # Reuse real passing outputs, then change otherwise clean source.
            run_path.write_text(json.dumps(control))
            selected.write_text(original + "\n# clean source changed after the run\n")
            checked = validate_quality(
                repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
            )
            self.assertEqual(checked["status"], "FAIL")
            self.assertIn("quality-source-inventory-drift", {row["code"] for row in checked["blockers"]})
            print(json.dumps({"case": "source-drift", "status": checked["status"], "blockers": checked["blockers"]}))
            selected.write_text(original)
            checked = validate_quality(
                repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
            )
            self.assertEqual(checked["status"], "PASS", checked["blockers"])
            # An omitted selected argv cannot reuse the same successful results.
            command = next(row for row in control["commands"] if row["id"] == "ruff-correctness")
            command["argv"].remove(policy["tooling"]["paths"][0])
            run_path.write_text(json.dumps(control))
            checked = validate_quality(
                repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
            )
            self.assertIn("quality-command-scope-mismatch", {row["code"] for row in checked["blockers"]})


if __name__ == "__main__":
    unittest.main()
