from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_plan_package_integrity import validate_plan_package


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class PlanPackageIntegrityValidatorTests(unittest.TestCase):
    def test_validator_uses_tracked_v2_fixture(self) -> None:
        payload = validate_plan_package(
            repository_root=ROOT,
            package_root=PACKAGE,
            manifest_path=PACKAGE / "plan.manifest.json",
            lock_path=PACKAGE / "plan.lock.json",
            require_schema="agent-plan-lock.v2",
            reject_undeclared=True,
        )

        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        self.assertEqual(payload["schemaVersion"], "agent-plan-package-integrity-validation.v1")
        self.assertEqual(
            {item["id"] for item in payload["checks"]},
            {"lock-envelope", "declared-inventory", "filesystem-bytes-and-digests", "undeclared-top-level"},
        )


if __name__ == "__main__":
    unittest.main()
