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
        self.assertIn("architecture-file-target-exceeded", codes)
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


if __name__ == "__main__":
    unittest.main()
