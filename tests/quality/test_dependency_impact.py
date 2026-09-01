from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.quality.dependency_impact import (
    build_module_dependency_report,
    graph_from_report,
    module_paths_from_report,
    transitive_dependents,
    validate_module_dependency_report,
)


class DependencyImpactTests(unittest.TestCase):
    def test_report_is_complete_and_transitive_dependents_are_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "middle.py").write_text("from agent_lifecycle.leaf import VALUE\n", encoding="utf-8")
            (root / "top.py").write_text("from agent_lifecycle import middle\n", encoding="utf-8")

            report = build_module_dependency_report(root, repository_root=Path(tmp))
            graph = graph_from_report(report)

            self.assertEqual(validate_module_dependency_report(report)["status"], "PASS")
            self.assertEqual(report["moduleCount"], 4)
            self.assertEqual(
                transitive_dependents(graph, {"agent_lifecycle.leaf"}),
                {"agent_lifecycle.leaf", "agent_lifecycle.middle", "agent_lifecycle.top"},
            )
            self.assertEqual(module_paths_from_report(report)["agent_lifecycle/leaf.py"], "agent_lifecycle.leaf")

    def test_tampered_or_incomplete_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            report = build_module_dependency_report(root, repository_root=Path(tmp))
            report["graphComplete"] = False

            validation = validate_module_dependency_report(report)

            self.assertEqual(validation["status"], "FAIL")
            with self.assertRaises(LifecycleError):
                graph_from_report(report)

    def test_absolute_source_identity_fails_closed_even_with_recomputed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_lifecycle"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            report = build_module_dependency_report(root, repository_root=Path(tmp))
            report["sourceFiles"][0]["path"] = (root / "__init__.py").as_posix()
            report["reportDigest"] = canonical_digest(
                {key: value for key, value in report.items() if key != "reportDigest"}
            )

            validation = validate_module_dependency_report(report)

            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("dependency-report-source-invalid", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
