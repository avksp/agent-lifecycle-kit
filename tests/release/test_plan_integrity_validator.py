from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_plan_integrity import validate_plan_integrity


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class PlanIntegrityValidatorTests(unittest.TestCase):
    def test_tracked_fixture_and_negative_mutations_pass(self) -> None:
        payload = validate_plan_integrity(
            repository_root=ROOT,
            package_root=PACKAGE,
            manifest_path=PACKAGE / "plan.manifest.json",
            acceptance_path=PACKAGE / "plan.md",
            lock_path=PACKAGE / "plan.lock.json",
        )

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertTrue(payload["cleanCloneFixtures"])
        self.assertEqual({item["status"] for item in payload["checks"]}, {"PASS"})
        self.assertEqual(payload["schemaVersion"], "agent-plan-integrity-regression-validation.v1")


if __name__ == "__main__":
    unittest.main()
