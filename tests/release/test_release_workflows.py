from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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


if __name__ == "__main__":
    unittest.main()
