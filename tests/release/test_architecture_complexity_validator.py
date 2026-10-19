from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ArchitectureComplexityValidatorTests(unittest.TestCase):
    def test_validator_reports_file_function_and_symbol_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "agent_lifecycle"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            lines = ["def oversized():"] + ["    value = 1"] * 6 + ["    return value"]
            lines.extend(f"def symbol_{index}():\n    return {index}" for index in range(4))
            (package / "large.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
            evidence = Path(tmp) / "complexity.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(package),
                    "--target-file-lines",
                    "5",
                    "--hard-file-lines",
                    "100",
                    "--target-function-lines",
                    "3",
                    "--hard-function-lines",
                    "5",
                    "--hard-symbols",
                    "2",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("architecture-file-target-exceeded", {row["code"] for row in payload["warnings"]})
        self.assertEqual(payload["targetFileConformance"], "EXCEEDED")
        self.assertIn("architecture-hard-function-limit-exceeded", codes)
        self.assertIn("architecture-hard-symbol-limit-exceeded", codes)

    def test_validator_passes_small_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "agent_lifecycle"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "small.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            evidence = Path(tmp) / "complexity.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_architecture_complexity.py"),
                    "--package-root",
                    str(package),
                    "--target-file-lines",
                    "800",
                    "--hard-file-lines",
                    "1200",
                    "--target-function-lines",
                    "80",
                    "--hard-function-lines",
                    "150",
                    "--hard-symbols",
                    "120",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blockers"], [])

    def test_target_is_reported_and_hard_boundaries_still_refuse(self) -> None:
        cases = [
            ("file-800", "# line\n" * 800, 0, False, None),
            ("file-801", "# line\n" * 801, 0, True, None),
            ("file-1200", "# line\n" * 1200, 0, True, None),
            ("file-1201", "# line\n" * 1201, 1, True, "architecture-hard-file-limit-exceeded"),
            ("function-150", "def f():\n" + "    value = 1\n" * 148 + "    return value\n", 0, False, None),
            (
                "function-151",
                "def f():\n" + "    value = 1\n" * 149 + "    return value\n",
                1,
                False,
                "architecture-hard-function-limit-exceeded",
            ),
            ("symbols-80", "".join(f"def f{i}():\n    return {i}\n" for i in range(80)), 0, False, None),
            (
                "symbols-81",
                "".join(f"def f{i}():\n    return {i}\n" for i in range(81)),
                1,
                False,
                "architecture-hard-symbol-limit-exceeded",
            ),
        ]
        for label, source, exit_code, warning, code in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                package = Path(tmp) / "agent_lifecycle"
                package.mkdir()
                (package / "__init__.py").write_text("", encoding="utf-8")
                (package / "fixture.py").write_text(source, encoding="utf-8")
                evidence = Path(tmp) / "complexity.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools/release/validate_architecture_complexity.py"),
                        "--package-root",
                        str(package),
                        "--target-file-lines",
                        "800",
                        "--hard-file-lines",
                        "1200",
                        "--target-function-lines",
                        "80",
                        "--hard-function-lines",
                        "150",
                        "--hard-symbols",
                        "80",
                        "--evidence",
                        str(evidence),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                payload = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual(
                    any(row["code"] == "architecture-file-target-exceeded" for row in payload["warnings"]), warning
                )
                self.assertEqual(
                    any(row["code"] == "architecture-function-target-exceeded" for row in payload["warnings"]),
                    label.startswith("function-"),
                )
                self.assertEqual(payload["targetFileConformance"], "EXCEEDED" if warning else "PASS")
                self.assertEqual(payload["hardLimitConformance"], "FAIL" if code else "PASS")
                self.assertEqual(payload["status"], "FAIL" if code else "PASS")
                self.assertEqual([row["code"] for row in payload["blockers"]], [code] if code else [])


if __name__ == "__main__":
    unittest.main()
