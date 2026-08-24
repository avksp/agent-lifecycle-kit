from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_package_resources import validate_package_resources


class PackageResourceValidatorTests(unittest.TestCase):
    def test_canonical_profile_copies_pass_and_legacy_presets_are_absent(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = validate_package_resources(
            pyproject_path=root / "pyproject.toml",
            source_root=root / "profiles",
            package_root=root / "src/agent_lifecycle/data/profiles",
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resourceCount"], 10)
        self.assertEqual(result["blockers"], [])

    def test_drift_and_legacy_data_file_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "profiles"
            package = root / "src/agent_lifecycle/data/profiles"
            for relative in (
                "lifecycle-baselines.v1.json",
                "model-routing-profile.v1.json",
                "risk-execution-policy.v1.json",
                "small-context-profile.v1.json",
                "project-workflow-presets/feature-implementation.v1.json",
                "project-workflow-presets/quick-change.v1.json",
                "project-workflow-presets/research-review.v1.json",
                "external-checks/import-boundaries.v1.json",
                "external-checks/module-dependencies.v1.json",
                "external-checks/declared-dependencies.v1.json",
            ):
                source_path = source / relative
                package_path = package / relative
                source_path.parent.mkdir(parents=True, exist_ok=True)
                package_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text("{}\n", encoding="utf-8")
                package_path.write_text('{"drift":true}\n', encoding="utf-8")
            (root / "src/agent_lifecycle/resources.py").parent.mkdir(parents=True, exist_ok=True)
            (root / "src/agent_lifecycle/resources.py").write_text(
                "import importlib.resources\n# agent_lifecycle.data\n", encoding="utf-8"
            )
            (root / "pyproject.toml").write_text(
                "[tool.setuptools.package-data]\n"
                'agent_lifecycle = ["data/profiles/**/*.json"]\n'
                "[tool.setuptools.data-files]\n"
                'legacy = ["profiles/project-workflow-presets/quick-change.v1.json"]\n',
                encoding="utf-8",
            )

            result = validate_package_resources(
                pyproject_path=root / "pyproject.toml",
                source_root=source,
                package_root=package,
            )

        self.assertEqual(result["status"], "FAIL")
        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("resource-content-drift", codes)
        self.assertIn("legacy-preset-data-files", codes)

    def test_evidence_is_json_serializable(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = validate_package_resources(
            pyproject_path=root / "pyproject.toml",
            source_root=root / "profiles",
            package_root=root / "src/agent_lifecycle/data/profiles",
        )
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
