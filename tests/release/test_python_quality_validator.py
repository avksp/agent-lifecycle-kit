from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_python_quality import validate_quality


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(source_digest: str) -> dict:
    baseline = [{"path": "src/example.py", "code": "F401", "count": 0, "sourceDigest": source_digest}]
    return {
        "schemaVersion": "agent-python-quality-policy.v1",
        "revision": 1,
        "toolchain": {"ruff": "0.16.3", "mypy": "1.17.1", "coverage": "7.10.6"},
        "ruff": {
            "targetVersion": "py311",
            "lineLength": 120,
            "sourceRoots": ["src"],
            "firstParty": ["agent_lifecycle"],
            "correctnessSelectors": ["E4", "E7", "E9", "F", "B"],
            "migrationSelectors": ["I", "UP", "RUF", "SIM", "PTH", "ARG", "BLE"],
            "intentionalFindings": [],
            "correctnessBaseline": baseline,
            "migrationBaseline": [],
            "formatBaseline": [],
            "lineLengthBaseline": [],
        },
        "mypy": {"strictClean": [], "baseline": []},
        "coverage": {"minimumStatementLinePercent": 76.0, "baseline": {}},
        "limits": {"maxWallSeconds": 900, "maxOutputBytes": 16777216, "maxBaselineEntries": 20000},
        "productionPromotionClaimed": False,
    }


def _run_receipt() -> dict:
    return {
        "schemaVersion": "agent-python-quality-run.v1",
        "status": "PASS",
        "toolchain": {"ruff": "0.16.3", "mypy": "1.17.1", "coverage": "7.10.6"},
        "changedPaths": [],
        "commands": [
            {"id": "ruff-format", "status": "PASS", "returncode": 0, "timedOut": False, "outputLimited": False}
        ],
        "artifacts": {
            "ruffCorrectness": "work/raw/ruff-correctness.stdout.json",
            "ruffMigration": "work/raw/ruff-migration.stdout.json",
            "ruffFormat": "work/raw/ruff-format.stdout.txt",
            "ruffLineLength": "work/raw/ruff-line-length.stdout.json",
            "mypy": "work/raw/mypy.stdout.txt",
            "coverage": "work/raw/coverage.json",
        },
    }


class PythonQualityValidatorTests(unittest.TestCase):
    def _coverage_result(self, totals: dict, *, modern: bool = True, cli: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            for name in ("ruff-correctness.stdout.json", "ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n", encoding="utf-8")
            (raw / "ruff-format.stdout.txt").write_text("1 file already formatted\n", encoding="utf-8")
            (raw / "mypy.stdout.txt").write_text("Success: no issues found\n", encoding="utf-8")
            (raw / "coverage.json").write_text(json.dumps({"totals": totals}), encoding="utf-8")
            policy = _policy(_digest(source))
            if modern:
                policy["revision"] = 5
                policy["coverage"]["minimumCombinedPercent"] = 76.0
            policy_path, run_path = root / "policy.json", root / "run.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            run_path.write_text(json.dumps(_run_receipt()), encoding="utf-8")
            if not cli:
                return validate_quality(
                    repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
                )
            script = Path(__file__).resolve().parents[2] / "tools/release/validate_python_quality.py"
            output = root / "validation.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--policy",
                    str(policy_path),
                    "--run-receipt",
                    str(run_path),
                    "--work-root",
                    str(root / "work"),
                    "--evidence",
                    str(output),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(completed.stdout), value)
            self.assertEqual(completed.returncode, 0 if value["status"] == "PASS" else 1)
            return value

    def test_modern_coverage_requires_both_line_and_combined_floors_via_actual_cli(self) -> None:
        cases = [
            (
                {
                    "num_statements": 100,
                    "covered_lines": 90,
                    "missing_lines": 10,
                    "num_branches": 100,
                    "covered_branches": 50,
                    "missing_branches": 50,
                    "percent_covered": 70.0,
                },
                "combinedPercent",
            ),
            (
                {
                    "num_statements": 100,
                    "covered_lines": 60,
                    "missing_lines": 40,
                    "num_branches": 100,
                    "covered_branches": 100,
                    "missing_branches": 0,
                    "percent_covered": 80.0,
                },
                "statementLinePercent",
            ),
        ]
        for totals, failed_metric in cases:
            with self.subTest(failed_metric=failed_metric):
                value = self._coverage_result(totals, cli=True)
                self.assertEqual("FAIL", value["status"])
                self.assertEqual([failed_metric], [x["metric"] for x in value["blockers"]])
                legacy = self._coverage_result(totals, modern=False)
                self.assertEqual("PASS" if totals["percent_covered"] >= 76 else "FAIL", legacy["status"])
                self.assertEqual("legacy-aggregate-alias", legacy["summary"]["coverage"]["interpretation"])

    def test_modern_coverage_accepts_boundary_and_reports_three_metrics(self) -> None:
        totals = {
            "num_statements": 100,
            "covered_lines": 76,
            "missing_lines": 24,
            "num_branches": 100,
            "covered_branches": 76,
            "missing_branches": 24,
            "percent_covered": 76.0,
        }
        result = self._coverage_result(totals, cli=True)
        self.assertEqual("PASS", result["status"], result)
        self.assertEqual(
            {
                "statementLinePercent": 76.0,
                "branchPercent": 76.0,
                "combinedPercent": 76.0,
                "interpretation": "explicit-combined-and-lines",
            },
            result["summary"]["coverage"],
        )

    def test_modern_coverage_missing_inconsistent_and_nonfinite_counts_refuse(self) -> None:
        valid = {
            "num_statements": 100,
            "covered_lines": 90,
            "missing_lines": 10,
            "num_branches": 20,
            "covered_branches": 10,
            "missing_branches": 10,
            "percent_covered": 83.33333333333333,
        }
        mutations = [
            lambda t: t.pop("covered_lines"),
            lambda t: t.update(covered_lines=91),
            lambda t: t.update(missing_branches=11),
            lambda t: t.update(num_branches=-1),
            lambda t: t.update(covered_lines=True),
            lambda t: t.update(num_statements=100.0),
            lambda t: t.update(num_partial_branches=21),
            lambda t: t.update(num_partial_branches=False),
            lambda t: t.update(percent_covered=99),
            lambda t: t.update(percent_covered="83.33"),
            lambda t: t.update(percent_statements_covered=85),
            lambda t: t.update(percent_branches_covered=90),
        ]
        for invalid in (float("nan"), float("inf"), float("-inf"), False, -1, 101, 10**400):
            mutations.append(lambda t, v=invalid: t.update(percent_covered=v))
            mutations.append(lambda t, v=invalid: t.update(covered_branches=v))
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                totals = copy.deepcopy(valid)
                mutate(totals)
                result = self._coverage_result(totals)
                self.assertEqual("FAIL", result["status"])
                self.assertEqual(["coverage-artifact-invalid"], [x["code"] for x in result["blockers"]])

    def test_modern_coverage_zero_denominators_are_explicit_and_legacy_receipts_still_work(self) -> None:
        zero = {
            "num_statements": 0,
            "covered_lines": 0,
            "missing_lines": 0,
            "num_branches": 0,
            "covered_branches": 0,
            "missing_branches": 0,
            "percent_covered": 100.0,
        }
        result = self._coverage_result(zero)
        self.assertEqual("PASS", result["status"], result)
        self.assertTrue(
            all(value == 100.0 for key, value in result["summary"]["coverage"].items() if key.endswith("Percent"))
        )
        zero.update(num_statements=10, covered_lines=8, missing_lines=2, percent_covered=80.0)
        result = self._coverage_result(zero)
        self.assertEqual("PASS", result["status"], result)
        self.assertEqual(100.0, result["summary"]["coverage"]["branchPercent"])
        self.assertEqual("PASS", self._coverage_result({"percent_covered": 80.0}, modern=False)["status"])
        self.assertEqual("FAIL", self._coverage_result({"percent_covered": 80.0})["status"])

    def test_coverage_policy_rejects_unknown_keys_invalid_floors_and_weakened_modern_floor(self) -> None:
        from tools.release.validate_python_quality import _validate_policy

        legacy = _policy("0" * 64)
        self.assertEqual([], _validate_policy(legacy))
        for key, invalid in (
            ("minimumStatementLinePercent", float("nan")),
            ("minimumCombinedPercent", 75.99),
            ("minimumCombinedPercent", float("inf")),
            ("minimumCombinedPercent", True),
            ("minimumCombinedPercent", "76"),
            ("minimumCombinedPercent", 10**400),
            ("extra", 76),
        ):
            with self.subTest(key=key, kind=type(invalid).__name__):
                policy = copy.deepcopy(legacy)
                policy["coverage"]["minimumCombinedPercent"] = 76.0
                policy["coverage"][key] = invalid
                self.assertIn("quality-coverage-policy-invalid", {x["code"] for x in _validate_policy(policy)})

    def test_current_coverage_tool_export_is_accepted_by_actual_validator_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "example.py"
            program.write_text(
                "def pick(flag):\n    if flag:\n        return 1\n    return 2\npick(True)\npick(False)\n",
                encoding="utf-8",
            )
            commands = [
                [sys.executable, "-m", "coverage", "run", "--branch", "--source", str(root), str(program)],
                [sys.executable, "-m", "coverage", "json", "-o", "export.json"],
            ]
            for command in commands:
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
            totals = json.loads((root / "export.json").read_text(encoding="utf-8"))["totals"]
            self.assertGreater(totals["num_statements"], 0)
            self.assertGreater(totals["num_branches"], 0)
            result = self._coverage_result(totals, cli=True)
            self.assertEqual("PASS", result["status"], result)
            self.assertEqual(100.0, result["summary"]["coverage"]["combinedPercent"])

    def test_format_json_legacy_exit_join_and_invalid_output_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            for name in ("ruff-correctness.stdout.json", "ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n")
            (raw / "mypy.stdout.txt").write_text("Success: no issues found\n")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}))
            policy = _policy(_digest(source))
            policy["ruff"]["formatBaseline"] = [
                {"path": "src/example.py", "code": "FORMAT", "count": 1, "sourceDigest": _digest(source)}
            ]
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(policy))
            run_path = root / "run.json"
            finding = {"filename": str(source), "code": "unformatted"}
            cases = (
                ("[]", 0, None),
                (json.dumps([finding]), 1, None),
                ("1 file already formatted\n", 0, None),
                ("Would reformat: src/example.py\n1 file would be reformatted\n", 1, None),
                (
                    "Would reformat: src/example.py\n2 files would be reformatted\n",
                    1,
                    "quality-format-artifact-invalid",
                ),
                ("Would reformat: src/example.py\n", 1, "quality-format-artifact-invalid"),
                ("Would reformat: src/example.py\n1 file already formatted\n", 1, "quality-format-artifact-invalid"),
                ("1 file already formatted\n1 file already formatted\n", 0, "quality-format-artifact-invalid"),
                ("[]", 1, "quality-format-exit-findings-mismatch"),
                (json.dumps([finding]), 0, "quality-format-exit-findings-mismatch"),
                ("new unrecognized display\n", 0, "quality-format-artifact-invalid"),
                ("[", 1, "quality-format-artifact-invalid"),
                (json.dumps({"diagnostics": []}), 0, "quality-format-artifact-invalid"),
                (json.dumps([{**finding, "code": "unknown"}]), 1, "quality-format-artifact-invalid"),
                (json.dumps([{**finding, "filename": "src/../../outside.py"}]), 1, "quality-format-artifact-invalid"),
                (json.dumps([finding, finding]), 1, "quality-format-artifact-invalid"),
            )
            for text, code, expected in cases:
                with self.subTest(output=text, exit=code):
                    (raw / "ruff-format.stdout.txt").write_text(text)
                    run = _run_receipt()
                    run["commands"][0]["returncode"] = code
                    run_path.write_text(json.dumps(run))
                    result = validate_quality(
                        repository_root=root,
                        policy_path=policy_path,
                        run_receipt_path=run_path,
                        work_root=root / "work",
                    )
                    if expected is None:
                        self.assertEqual(result["status"], "PASS", result["blockers"])
                    else:
                        self.assertEqual(result["status"], "FAIL")
                        self.assertIn(expected, {row["code"] for row in result["blockers"]})
            # A declared fresh invocation cannot select older invocation output.
            current = root / "work/run-current"
            current.mkdir()
            (raw / "ruff-format.stdout.txt").write_text("[]")
            run = _run_receipt()
            run["runDirectory"] = "work/run-current"
            run["artifacts"]["coverageData"] = "work/run-current/coverage.data"
            run_path.write_text(json.dumps(run))
            result = validate_quality(
                repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("quality-artifact-outside-current-run", {row["code"] for row in result["blockers"]})

    def test_validator_accepts_bound_clean_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            for name in ("ruff-correctness.stdout.json", "ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n", encoding="utf-8")
            (raw / "ruff-format.stdout.txt").write_text("1 file already formatted\n", encoding="utf-8")
            (raw / "mypy.stdout.txt").write_text("Success: no issues found\n", encoding="utf-8")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}), encoding="utf-8")
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(_policy(_digest(source))), encoding="utf-8")
            run_path = root / "run.json"
            run_path.write_text(json.dumps(_run_receipt()), encoding="utf-8")

            result = validate_quality(
                repository_root=root,
                policy_path=policy_path,
                run_receipt_path=run_path,
                work_root=root / "work",
            )

            self.assertEqual(result["status"], "PASS", result["blockers"])

    def test_validator_rejects_new_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n", encoding="utf-8")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            (raw / "ruff-correctness.stdout.json").write_text(
                json.dumps([{"filename": "src/example.py", "code": "F821"}]), encoding="utf-8"
            )
            for name in ("ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n", encoding="utf-8")
            (raw / "ruff-format.stdout.txt").write_text("", encoding="utf-8")
            (raw / "mypy.stdout.txt").write_text("", encoding="utf-8")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}), encoding="utf-8")
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(_policy(_digest(source))), encoding="utf-8")
            run_path = root / "run.json"
            run_path.write_text(json.dumps(_run_receipt()), encoding="utf-8")

            result = validate_quality(
                repository_root=root,
                policy_path=policy_path,
                run_receipt_path=run_path,
                work_root=root / "work",
            )

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("new-quality-finding", {item["code"] for item in result["blockers"]})

    def test_empty_mypy_baseline_refuses_a_new_error_even_on_unchanged_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/example.py"
            source.parent.mkdir()
            source.write_text("value = 1\n")
            raw = root / "work/raw"
            raw.mkdir(parents=True)
            for name in ("ruff-correctness.stdout.json", "ruff-migration.stdout.json", "ruff-line-length.stdout.json"):
                (raw / name).write_text("[]\n")
            (raw / "ruff-format.stdout.txt").write_text("1 file already formatted\n")
            (raw / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}))
            (raw / "mypy.stdout.txt").write_text("src/example.py:1: error: Incompatible types [assignment]\n")
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(_policy(_digest(source))))
            run_path = root / "run.json"
            run_path.write_text(json.dumps(_run_receipt()))
            result = validate_quality(
                repository_root=root, policy_path=policy_path, run_receipt_path=run_path, work_root=root / "work"
            )
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(
                any(row["code"] == "new-quality-finding" and row["kind"] == "mypy" for row in result["blockers"])
            )


if __name__ == "__main__":
    unittest.main()
