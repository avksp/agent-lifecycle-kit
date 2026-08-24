from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from validate_removed_runner_surface import validate_removed_runner_surface  # noqa: E402


class RemovedRunnerSurfaceTests(unittest.TestCase):
    def test_current_surface_passes(self) -> None:
        result = validate_removed_runner_surface(
            package_root=ROOT / "src/agent_lifecycle",
            docs_root=ROOT / "docs",
        )

        self.assertEqual(result["schemaVersion"], "agent-removed-runner-surface-validation.v1")
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertFalse(result["productionPromotionClaimed"])

    def test_active_parser_mutation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src/agent_lifecycle"
            docs = root / "docs"
            shutil.copytree(ROOT / "src/agent_lifecycle", package)
            shutil.copytree(ROOT / "docs", docs)
            parser = package / "cli/parsers.py"
            parser.write_text(parser.read_text(encoding="utf-8") + '\nsubparsers.add_parser("runner")\n', encoding="utf-8")

            result = validate_removed_runner_surface(package_root=package, docs_root=docs)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("removed-runner-surface-active-reference", {item["code"] for item in result["blockers"]})

    def test_active_documentation_mutation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src/agent_lifecycle"
            docs = root / "docs"
            shutil.copytree(ROOT / "src/agent_lifecycle", package)
            shutil.copytree(ROOT / "docs", docs)
            cli = docs / "reference/cli.md"
            cli.write_text(cli.read_text(encoding="utf-8") + "\nagent-lifecycle runner start\n", encoding="utf-8")

            result = validate_removed_runner_surface(package_root=package, docs_root=docs)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("removed-runner-command-documented-as-active", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
