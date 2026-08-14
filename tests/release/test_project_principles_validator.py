from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_project_principles import validate


class ProjectPrinciplesReleaseValidatorTests(unittest.TestCase):
    def test_validator_passes_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate(Path(directory))
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["modelCallsStarted"])
        self.assertFalse(result["hostLaunchStarted"])


if __name__ == "__main__":
    unittest.main()
