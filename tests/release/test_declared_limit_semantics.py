"""A warning remains nonblocking; missing hard enforcement is detected."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.release.release_common import digest_value
from tools.release.validate_declared_limit_semantics import validate_limit_semantics

ROOT = Path(__file__).resolve().parents[2]


class DeclaredLimitSemanticsTests(unittest.TestCase):
    def report(self, *, hard_function=150):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "sample"
            package.mkdir()
            (package / "module.py").write_text("def f():\n    a = 1\n    b = 2\n    return a + b\n")
            evidence = Path(tmp) / "complexity.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(package),
                    "--target-file-lines",
                    "800",
                    "--hard-file-lines",
                    "1200",
                    "--target-function-lines",
                    "2",
                    "--hard-function-lines",
                    str(hard_function),
                    "--hard-symbols",
                    "80",
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            report = json.loads(evidence.read_text())
            self.assertEqual(result.returncode, 0 if hard_function >= 4 else 1, result.stderr)
            return report

    def test_function_target_warns_without_reporting_file_or_hard_failure(self) -> None:
        report = self.report()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["targetFileConformance"], "PASS")
        self.assertEqual(report["targetFunctionConformance"], "EXCEEDED")
        self.assertEqual(report["hardLimitConformance"], "PASS")
        self.assertEqual([row["code"] for row in report["warnings"]], ["architecture-function-target-exceeded"])
        self.assertEqual(validate_limit_semantics(report)["status"], "PASS")

    def test_correct_hard_failure_is_not_promoted_by_semantics_validation(self) -> None:
        report = self.report(hard_function=3)
        result = validate_limit_semantics(report)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["hardLimitConformance"], "FAIL")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["producerStatus"], "FAIL")
        self.assertFalse(result["productionPromotionClaimed"])

    def test_removed_warning_changed_classification_or_lost_hard_failure_refuse(self) -> None:
        warning, hard = self.report(), self.report(hard_function=3)
        variants = []
        missing_warning = deepcopy(warning)
        missing_warning["warnings"] = []
        variants.append(missing_warning)
        telemetry = deepcopy(warning)
        telemetry["limitSemantics"]["targetFunctionLines"] = "TELEMETRY"
        variants.append(telemetry)
        missing_hard = deepcopy(hard)
        missing_hard["blockers"] = []
        missing_hard["status"] = "PASS"
        missing_hard["hardLimitConformance"] = "PASS"
        variants.append(missing_hard)
        for report in variants:
            report["validationDigest"] = digest_value({k: v for k, v in report.items() if k != "validationDigest"})
            with self.subTest(report=report):
                self.assertEqual(validate_limit_semantics(report)["status"], "FAIL")
