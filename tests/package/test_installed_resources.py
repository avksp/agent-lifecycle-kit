from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.resources import builtin_profile_path

ROOT = Path(__file__).resolve().parents[2]


class InstalledResourceTests(unittest.TestCase):
    def test_built_in_profiles_are_loaded_from_package_data(self) -> None:
        expected = {
            "lifecycle-baselines.v1.json",
            "model-routing-profile.v1.json",
            "risk-execution-policy.v1.json",
            "small-context-profile.v1.json",
        }
        for name in expected:
            path = builtin_profile_path(name)
            self.assertTrue(path.is_file(), name)
            self.assertEqual(path.parent, ROOT / "src/agent_lifecycle/data/profiles")
            self.assertEqual(
                path.read_bytes(),
                (ROOT / "profiles" / name).read_bytes(),
            )

    def test_cwd_cannot_shadow_built_in_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shadow = root / "profiles/project-workflow-presets/quick-change.v1.json"
            shadow.parent.mkdir(parents=True)
            shadow.write_text(json.dumps({"presetId": "quick-change", "defaultRisk": "S2"}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from agent_lifecycle.project.presets import load_project_preset; "
                        "print(load_project_preset('quick-change')['defaultRisk'])"
                    ),
                ],
                cwd=root,
                env={"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "S0")

    def test_missing_built_in_resource_is_structured(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            builtin_profile_path("does-not-exist.v1.json")
        self.assertEqual(raised.exception.code, "built-in-resource-missing")


if __name__ == "__main__":
    unittest.main()
