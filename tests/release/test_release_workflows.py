from __future__ import annotations

import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTION_USE_RE = re.compile(r"^\s*(?:-\s+)?uses:\s+[^@\s]+@([0-9a-f]{40})\s+#.*\bv\d")


class ReleaseWorkflowTests(unittest.TestCase):
    def test_test_matrices_include_python_3_14(self) -> None:
        for relative_path in [
            ".github/workflows/ci.yml",
            ".github/workflows/matrix.yml",
            ".github/workflows/neutrality.yml",
        ]:
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('"3.14"', workflow, relative_path)

    def test_release_and_publication_use_python_3_14_packaging_smoke(self) -> None:
        for relative_path in [
            ".github/workflows/release.yml",
            ".github/workflows/publish.yml",
        ]:
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('python-version: "3.14"', workflow, relative_path)
            self.assertIn("tests/package/run_packaging_smoke.py", workflow, relative_path)
            self.assertIn("--python python", workflow, relative_path)

    def test_ci_and_release_use_tracked_release_neutrality_scope(self) -> None:
        for relative_path in [".github/workflows/ci.yml", ".github/workflows/release.yml"]:
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("neutrality scan --scope tracked-release", workflow, relative_path)
            self.assertNotIn("neutrality scan --scope current-tree-complete", workflow, relative_path)

    def test_all_actions_are_sha_pinned_and_checkout_credentials_are_disabled(self) -> None:
        workflow_paths = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual({path.name for path in workflow_paths}, {
            "ci.yml",
            "codeql.yml",
            "matrix.yml",
            "neutrality.yml",
            "publish.yml",
            "release.yml",
        })
        for path in workflow_paths:
            lines = path.read_text(encoding="utf-8").splitlines()
            action_lines = [line for line in lines if "uses:" in line]
            self.assertTrue(action_lines, path.name)
            for line in action_lines:
                self.assertRegex(line, ACTION_USE_RE, path.name)
            checkout_indexes = [index for index, line in enumerate(lines) if "uses: actions/checkout@" in line]
            for index in checkout_indexes:
                nearby = "\n".join(lines[index : index + 10])
                self.assertIn("persist-credentials: false", nearby, path.name)

    def test_privileged_publication_validates_tag_ancestry(self) -> None:
        publish = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(publish.count("validate_release_ref.py"), 2)
        self.assertIn("origin/main", publish)

    def test_codeql_and_dependabot_are_declared(self) -> None:
        codeql = (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
        dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("github/codeql-action/init@", codeql)
        self.assertIn("github/codeql-action/analyze@", codeql)
        self.assertIn("package-ecosystem: github-actions", dependabot)
        self.assertIn("package-ecosystem: pip", dependabot)


if __name__ == "__main__":
    unittest.main()
