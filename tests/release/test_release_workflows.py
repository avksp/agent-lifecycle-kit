from __future__ import annotations

import itertools
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTION_USE_RE = re.compile(r"^\s*(?:-\s+)?uses:\s+[^@\s]+@([0-9a-f]{40})\s+#.*\bv\d")


class ReleaseWorkflowTests(unittest.TestCase):
    def test_test_matrices_include_python_3_14(self) -> None:
        for relative_path in [".github/workflows/ci.yml", ".github/workflows/matrix.yml"]:
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('"3.14"', workflow, relative_path)
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn('"3.14"', _job_block(ci, "foundation"))

    def test_complete_supported_runtime_and_quality_matrices(self) -> None:
        versions = ["3.11", "3.12", "3.13", "3.14", "3.15"]
        platforms = ["ubuntu-latest", "macos-latest", "windows-latest"]
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        matrix = (ROOT / ".github/workflows/matrix.yml").read_text(encoding="utf-8")
        for name, workflow in {
            "platform": _job_block(ci, "test"),
            "manual": matrix,
            "quality": _job_block(ci, "quality"),
            "foundation": _job_block(ci, "foundation"),
        }.items():
            found = re.search(r"python(?:-version)?: \[(.*?)\]", workflow)
            self.assertIsNotNone(found, name)
            actual = json.loads("[" + found.group(1) + "]")
            self.assertEqual(actual, versions, name)
            self.assertNotIn("continue-on-error", workflow, name)
            if name in ("platform", "manual"):
                operating_systems = re.search(r"os: \[(.*?)\]", workflow)
                self.assertIsNotNone(operating_systems)
                actual_platforms = [value.strip() for value in operating_systems.group(1).split(",")]
                self.assertEqual(actual_platforms, platforms, name)
                self.assertEqual(
                    set(itertools.product(actual_platforms, actual)), set(itertools.product(platforms, versions)), name
                )
                self.assertNotIn("exclude:", workflow, name)
                self.assertNotIn("include:", workflow, name)

    def test_each_full_family_keeps_its_own_discovery(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        platform = " ".join(_job_block(workflow, "test").split())
        foundation = " ".join(_job_block(workflow, "foundation").split())
        quality = " ".join(_job_block(workflow, "quality").split())
        self.assertIn("tools/ci/run_unittest.py --start tests --top . --pattern 'test*.py'", platform)
        self.assertIn("-m unittest discover -s tests/security -t . -v", platform)
        self.assertIn("tools/ci/run_unittest.py --start tests --top . --pattern 'test_*.py'", foundation)
        self.assertIn("tools/release/run_python_quality.py", quality)
        self.assertIn("--tests-root tests --test-top-level .", quality)
        self.assertNotIn("--qualified-coverage", quality)

    def test_reduced_contract_modules_keep_strict_type_guard(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        step = (
            _job_block(workflow, "quality")
            .split("- name: Check strict types in reduced contract modules\n", 1)[1]
            .split("\n      - name:", 1)[0]
        )
        self.assertIn('"$CELL_VENV_PYTHON" -m mypy --strict', step)
        for module in ("preparation_policy", "agent_plugin_qualification_schemas"):
            self.assertIn("src/agent_lifecycle/contracts/" + module + ".py", step)
        self.assertNotIn("ignore", step)

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
        self.assertEqual(
            {path.name for path in workflow_paths},
            {
                "ci-timing-control.yml",
                "ci.yml",
                "codeql.yml",
                "matrix.yml",
                "publish.yml",
                "release.yml",
            },
        )
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
        codeql_revisions = re.findall(r"github/codeql-action/(?:init|analyze)@([0-9a-f]{40})", codeql)
        self.assertEqual(len(codeql_revisions), 2)
        self.assertEqual(len(set(codeql_revisions)), 1)
        self.assertIn("package-ecosystem: github-actions", dependabot)
        self.assertIn("github/codeql-action/*", dependabot)
        self.assertIn("package-ecosystem: pip", dependabot)


def _job_block(workflow: str, job_id: str) -> str:
    match = re.search(rf"^  {re.escape(job_id)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", workflow, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"workflow job not found: {job_id}")
    return match.group(1)


if __name__ == "__main__":
    unittest.main()
