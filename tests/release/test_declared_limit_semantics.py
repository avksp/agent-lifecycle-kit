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
from tools.release.validate_declared_limit_semantics import (
    LEGACY_LIMIT_SEMANTICS,
    LIMIT_SEMANTICS,
    validate_limit_semantics,
)

ROOT = Path(__file__).resolve().parents[2]


class DeclaredLimitSemanticsTests(unittest.TestCase):
    def report(self, *, hard_function=150, filename="module.py", length=4, cli_target=80, cli_hard=150, module=False):
        with tempfile.TemporaryDirectory() as tmp:
            # An ancestor called cli must not classify ordinary package files as CLI.
            package = Path(tmp) / "cli" / "sample"
            package.mkdir(parents=True)
            source = package / filename
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("def f():\n" + "    value = 1\n" * (length - 2) + "    return value\n")
            policy = json.loads((ROOT / "policy/architecture-limits.json").read_text())
            policy["limits"].update(cliTargetFunctionLines=cli_target, cliHardFunctionLines=cli_hard)
            policy_path = Path(tmp) / "policy.json"
            policy_path.write_text(json.dumps(policy))
            route = (
                ["-m", "tools.release.validate_architecture_complexity"]
                if module
                else [str(ROOT / "tools/release/validate_architecture_complexity.py")]
            )
            evidence = Path(tmp) / "complexity.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    *route,
                    "--policy",
                    str(policy_path),
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
            self.assertEqual(result.returncode, 0 if report["status"] == "PASS" else 1, result.stderr)
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

    def resign(self, report):
        report["validationDigest"] = digest_value({k: v for k, v in report.items() if k != "validationDigest"})
        return report

    def legacy(self, report):
        legacy = deepcopy(report)
        legacy["limits"] = {key: legacy["limits"][key] for key in LEGACY_LIMIT_SEMANTICS}
        legacy["limitSemantics"] = dict(LEGACY_LIMIT_SEMANTICS)
        for row in legacy["warnings"] + legacy["blockers"]:
            if "function" in row["code"]:
                row.pop("lines", None)
                if row["code"].startswith("architecture-hard-"):
                    row.pop("line", None)
        return self.resign(legacy)

    def test_legacy_five_limits_preserve_exact_warning_and_hard_shapes(self):
        for hard in (3, 150):
            with self.subTest(hard=hard):
                report = self.legacy(self.report(hard_function=hard))
                result = validate_limit_semantics(report)
                self.assertEqual("PASS", result["status"])
                self.assertEqual(report["status"], result["producerStatus"])
                self.assertEqual(LEGACY_LIMIT_SEMANTICS, result["limitSemantics"])
                # Current redundant metadata is not silently discarded in the legacy form.
                report["warnings"][0]["lines"] = 4
                self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])

    def test_distinct_cli_limits_and_package_scoped_classification(self):
        for filename in ("module.py", "cli/commands.py", "cli.py"):
            for length in (2, 3, 4, 5, 6):
                with self.subTest(filename=filename, length=length):
                    report = self.report(filename=filename, length=length, hard_function=3, cli_target=4, cli_hard=5)
                    cli = filename != "module.py"
                    warning = length > (4 if cli else 2)
                    hard = length > (5 if cli else 3)
                    self.assertEqual(LIMIT_SEMANTICS, report["limitSemantics"])
                    self.assertEqual(warning, bool(report["warnings"]))
                    self.assertEqual(hard, bool(report["blockers"]))
                    self.assertEqual("FAIL" if hard else "PASS", report["status"])
                    self.assertEqual("PASS", validate_limit_semantics(report)["status"])

    def test_limit_keys_values_and_classifications_are_strict_in_both_forms(self):
        current = self.report()
        for original in (current, self.legacy(current)):
            variants = []
            for key in original["limits"]:
                for value in (0, -1, True, 1.5, "80", None):
                    report = deepcopy(original)
                    report["limits"][key] = value
                    variants.append(report)
                report = deepcopy(original)
                report["limitSemantics"][key] = "TELEMETRY"
                variants.append(report)
                report = deepcopy(original)
                del report["limits"][key]
                variants.append(report)
            report = deepcopy(original)
            report["limits"]["unknownLimit"] = 10
            variants.append(report)
            report = deepcopy(original)
            report["limitSemantics"]["unknownLimit"] = "WARNING"
            variants.append(report)
            for report in variants:
                with self.subTest(limits=report["limits"], semantics=report["limitSemantics"]):
                    self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])

    def test_function_metadata_and_diagnostic_coverage_are_sourced_from_observations(self):
        current = self.report(hard_function=3)
        for original in (current, self.legacy(current)):
            for collection in ("warnings", "blockers"):
                for key in original[collection][0]:
                    for operation in ("remove", "forge"):
                        report = deepcopy(original)
                        row = report[collection][0]
                        if operation == "remove":
                            del row[key]
                        else:
                            row[key] = 99 if type(row[key]) is int else "forged"
                        with self.subTest(collection=collection, key=key, operation=operation):
                            self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])
                for operation in ("remove", "duplicate"):
                    report = deepcopy(original)
                    if operation == "remove":
                        report[collection].clear()
                    else:
                        report[collection].append(deepcopy(report[collection][0]))
                    self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])
            for key, value in (("line", 2), ("lines", 5), ("line", True), ("name", None)):
                report = deepcopy(original)
                report["functions"][0][key] = value
                self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])

    def test_cli_threshold_and_identity_drift_are_rejected(self):
        original = self.report(filename="cli/commands.py", length=6, hard_function=3, cli_target=4, cli_hard=5)
        variants = []
        for collection, key, value in (("warnings", "targetLines", 2), ("blockers", "maxLines", 3)):
            report = deepcopy(original)
            report[collection][0][key] = value
            variants.append(report)
        for path in ("outside.py", original["packageRoot"] + "/../outside.py"):
            report = deepcopy(original)
            report["functions"][0]["path"] = path
            variants.append(report)
        report = deepcopy(original)
        report["packageRoot"] = str(Path(original["packageRoot"]) / "cli")
        variants.append(report)
        for report in variants:
            self.assertEqual("FAIL", validate_limit_semantics(self.resign(report))["status"])

    def test_script_and_module_routes_preserve_semantic_status_for_correct_hard_fail(self):
        for module in (False, True):
            report = self.report(hard_function=3, module=module)
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "report.json"
                source.write_text(json.dumps(report))
                evidence = Path(tmp) / "semantics.json"
                route = (
                    ["-m", "tools.release.validate_declared_limit_semantics"]
                    if module
                    else [str(ROOT / "tools/release/validate_declared_limit_semantics.py")]
                )
                result = subprocess.run(
                    [sys.executable, "-B", *route, "--complexity-report", str(source), "--evidence", str(evidence)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(evidence.read_text())
                self.assertEqual("PASS", payload["status"])
                self.assertEqual("FAIL", payload["producerStatus"])
