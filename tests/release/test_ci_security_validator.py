from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"

import sys

sys.path.insert(0, str(TOOLS_RELEASE))

from validate_ci_security import validate_ci_security  # noqa: E402


class CiSecurityValidatorTests(unittest.TestCase):
    def test_current_ci_and_test_loader_pass(self) -> None:
        result = validate_ci_security(workflow_root=ROOT / ".github/workflows", tests_root=ROOT / "tests", repository_root=ROOT)

        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertEqual(result["loader"]["loaderErrors"], [])
        self.assertGreaterEqual(result["loader"]["discoveredCaseCount"], result["loader"]["expectedCaseCount"])
        self.assertEqual(result["testInventory"]["topLevelFunctionCount"], 0)
        self.assertTrue(all(item["status"] == "PASS" for item in result["mutationChecks"]))

    def test_missing_action_pin_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow_root = Path(tmp) / "workflows"
            workflow_root.mkdir()
            workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
            mutated_workflow = re.sub(
                r"(?m)^(\s*-\s+uses:\s*actions/checkout)@[^\s#]+",
                r"\1@v5",
                workflow,
                count=1,
            )
            (workflow_root / "ci.yml").write_text(mutated_workflow, encoding="utf-8")
            result = validate_ci_security(workflow_root=workflow_root, tests_root=ROOT / "tests", repository_root=ROOT)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("action-reference-not-immutable", {item["code"] for item in result["blockers"]})

    def test_mixed_codeql_action_revisions_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow_root = Path(tmp) / "workflows"
            workflow_root.mkdir()
            workflow = (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
            mutated_workflow = re.sub(
                r"(?m)^(\s*-\s+uses:\s+github/codeql-action/analyze)@[0-9a-f]{40}",
                rf"\1@{'0' * 40}",
                workflow,
                count=1,
            )
            (workflow_root / "codeql.yml").write_text(mutated_workflow, encoding="utf-8")
            result = validate_ci_security(workflow_root=workflow_root, tests_root=ROOT / "tests", repository_root=ROOT)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("codeql-action-revision-mismatch", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
