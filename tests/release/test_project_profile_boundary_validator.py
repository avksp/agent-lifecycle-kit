from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_project_profile_boundary import validate_boundary


ROOT = Path(__file__).resolve().parents[2]


class ProjectProfileBoundaryValidatorTests(unittest.TestCase):
    def test_repository_profile_boundary_passes(self) -> None:
        payload = validate_boundary(
            ROOT / "src/agent_lifecycle",
            profile_path=ROOT / "src/agent_lifecycle/project/profile.py",
            merge_path=ROOT / "src/agent_lifecycle/project/merge.py",
            start_path=ROOT / "src/agent_lifecycle/adapter_sessions/unified_start.py",
            strategy_path=ROOT / "src/agent_lifecycle/policy/execution_strategy.py",
        )

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertGreater(len(payload["checkedFiles"]), 20)
        self.assertFalse(payload["modelCallsStarted"])
        self.assertFalse(payload["sourceWritesStarted"])

    def test_complete_package_scan_detects_unsafe_unlisted_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent_lifecycle"
            project = root / "project"
            contracts = root / "contracts"
            project.mkdir(parents=True)
            contracts.mkdir()
            (project / "profile.py").write_text("from pathlib import Path\n", encoding="utf-8")
            (project / "merge.py").write_text("from pathlib import Path\n", encoding="utf-8")
            (contracts / "unsafe.py").write_text(
                "from agent_lifecycle.project.profile import load_project_profile\n",
                encoding="utf-8",
            )
            (project / "unsafe.py").write_text("import openai\n", encoding="utf-8")

            payload = validate_boundary(
                root,
                profile_path=project / "profile.py",
                merge_path=project / "merge.py",
                start_path=project / "profile.py",
                strategy_path=project / "merge.py",
            )

            self.assertEqual(payload["status"], "FAIL")
            self.assertTrue(any(item["code"] == "project-profile-model-network-import" for item in payload["blockers"]))
            self.assertTrue(any(item["code"] == "project-profile-import-direction" for item in payload["blockers"]))

    def test_project_layer_rejects_provider_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent_lifecycle"
            project = root / "project"
            project.mkdir(parents=True)
            unsafe = project / "profile.py"
            unsafe.write_text("import openai\n", encoding="utf-8")
            merge = project / "merge.py"
            merge.write_text("from pathlib import Path\n", encoding="utf-8")

            payload = validate_boundary(
                root,
                profile_path=unsafe,
                merge_path=merge,
                start_path=unsafe,
                strategy_path=merge,
            )

            self.assertEqual(payload["status"], "FAIL")
            self.assertTrue(any(item["code"] == "project-profile-model-network-import" for item in payload["blockers"]))


if __name__ == "__main__":
    unittest.main()
