from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class NegativeSuiteCoverageVerifierTests(unittest.TestCase):
    def test_negative_suite_coverage_verifier_requires_catalog_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = out / "catalog.md"
            tests_root = out / "tests"
            evidence = out / "evidence.json"
            catalog.write_text("## NEG-R03-01 One\n## NEG-R03-02 Two\n", encoding="utf-8")
            tests_root.mkdir()
            (tests_root / "test_negative.py").write_text(
                "# NEG-R03-01\n# NEG-R03-02\n",
                encoding="utf-8",
            )

            _run(
                "tools/release/verify_negative_suite_coverage.py",
                "--catalog",
                str(catalog),
                "--tests-root",
                str(tests_root),
                "--expected-range",
                "NEG-R03-01..NEG-R03-02",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(len(payload["coveredScenarios"]), 2)

    def test_negative_suite_coverage_verifier_accepts_release_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = out / "catalog.md"
            tests_root = out / "tests"
            evidence = out / "evidence.json"
            catalog.write_text("## NEG-R04-01 One\n## NEG-R04-02 Two\n", encoding="utf-8")
            tests_root.mkdir()
            (tests_root / "test_negative.py").write_text(
                "# NEG-R04-01\n# NEG-R04-02\n",
                encoding="utf-8",
            )

            _run(
                "tools/release/verify_negative_suite_coverage.py",
                "--catalog",
                str(catalog),
                "--tests-root",
                str(tests_root),
                "--expected-range",
                "NEG-R04-01..NEG-R04-02",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual([item["id"] for item in payload["coveredScenarios"]], ["NEG-R04-01", "NEG-R04-02"])

    def test_negative_suite_coverage_verifier_fails_for_missing_test_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = out / "catalog.md"
            tests_root = out / "tests"
            evidence = out / "evidence.json"
            catalog.write_text("## NEG-R03-01 One\n## NEG-R03-02 Two\n", encoding="utf-8")
            tests_root.mkdir()
            (tests_root / "test_negative.py").write_text("# NEG-R03-01\n", encoding="utf-8")

            result = _run_no_check(
                "tools/release/verify_negative_suite_coverage.py",
                "--catalog",
                str(catalog),
                "--tests-root",
                str(tests_root),
                "--expected-range",
                "NEG-R03-01..NEG-R03-02",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["missingScenarios"][0]["id"], "NEG-R03-02")


if __name__ == "__main__":
    unittest.main()
