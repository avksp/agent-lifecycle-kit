from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_cli_startup_boundary import validate_cli_startup_boundary


ROOT = Path(__file__).resolve().parents[2]


class CliStartupBoundaryValidatorTests(unittest.TestCase):
    def test_source_cli_version_boundary_passes(self) -> None:
        payload = validate_cli_startup_boundary(
            package_root=ROOT / "src/agent_lifecycle",
            policy_path=ROOT / "policy/performance-budgets.json",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["blockers"])


if __name__ == "__main__":
    unittest.main()
