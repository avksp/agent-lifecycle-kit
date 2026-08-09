from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))

from validate_qualified_launch_profiles import validate_qualified_launch_profiles  # noqa: E402


class QualifiedLaunchProfileValidatorTests(unittest.TestCase):
    def test_repository_profiles_pass(self) -> None:
        payload = validate_qualified_launch_profiles(ROOT / "adapters")
        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertEqual({item["adapterId"] for item in payload["checks"]}, {"claude", "codex", "opencode"})
        self.assertFalse(payload["hostProcessesStarted"])
