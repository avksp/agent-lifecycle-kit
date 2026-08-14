from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_project_workflow_presets import validate


class ProjectWorkflowPresetsValidatorTests(unittest.TestCase):
    def test_built_in_presets_pass_release_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate(Path(directory))

        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertEqual(result["presetCount"], 3)
        self.assertFalse(result["modelCallsStarted"])
        self.assertFalse(result["hostLaunchStarted"])


if __name__ == "__main__":
    unittest.main()
