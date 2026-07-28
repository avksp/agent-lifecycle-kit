from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class LiveHostPromotionPlanValidatorTests(unittest.TestCase):
    def test_live_host_promotion_plan_validator_accepts_structural_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            evidence = out / "live-host-promotion-plan-validation.json"

            _run(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-live-host-promotion-plan-validation.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_host_promotion_plan_validator_rejects_missing_operation_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            plan = _load_json(plan_path)
            del plan["operationEvidenceRequirements"]["final-audit"]
            _write_json(plan_path, plan)
            evidence = out / "live-host-promotion-plan-validation.json"

            result = _run_no_check(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("invalid-operation-evidence-requirements", {item["code"] for item in payload["blockers"]})

    def test_live_host_promotion_plan_validator_requires_budget_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            plan = _load_json(plan_path)
            del plan["budgetPolicy"]["requiresPerInvocationAccountingReconciliation"]
            _write_json(plan_path, plan)
            evidence = out / "live-host-promotion-plan-validation.json"

            result = _run_no_check(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("invalid-live-host-budget-policy", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()
