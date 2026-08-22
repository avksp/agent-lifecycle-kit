from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_adapter_lifecycle_control import validate_adapter_lifecycle_control

ROOT = Path(__file__).resolve().parents[2]


class AdapterLifecycleControlValidatorTests(unittest.TestCase):
    def test_shipped_claude_candidate_is_safe_and_non_promoting(self) -> None:
        result = validate_adapter_lifecycle_control(
            adapter_root=ROOT / "adapters",
            policy_path=ROOT / "policy/adapter-lifecycle-control.json",
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["fixtureQualificationStatus"], "NO_RECOMMENDATION")
        self.assertFalse(result["productionPromotionClaimed"])

    def test_validator_rejects_candidate_enforcement_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude = root / "claude"
            claude.mkdir()
            template = json.loads(
                (ROOT / "adapters/claude/lifecycle-control.template.json").read_text(encoding="utf-8")
            )
            template["operations"]["file-edit"]["qualifiedLevel"] = "ENFORCED"
            (claude / "lifecycle-control.template.json").write_text(json.dumps(template), encoding="utf-8")
            result = validate_adapter_lifecycle_control(
                adapter_root=root,
                policy_path=ROOT / "policy/adapter-lifecycle-control.json",
            )

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("candidate-template-enforced-overclaim", {item["code"] for item in result["blockers"]})

    def test_validator_returns_failure_for_non_object_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude = root / "claude"
            claude.mkdir()
            (claude / "lifecycle-control.template.json").write_text(
                (ROOT / "adapters/claude/lifecycle-control.template.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            policy = root / "policy.json"
            policy.write_text("[]", encoding="utf-8")

            result = validate_adapter_lifecycle_control(adapter_root=root, policy_path=policy)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("control-policy-read-failed", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
