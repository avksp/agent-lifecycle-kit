from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LifecycleControlGuidanceTests(unittest.TestCase):
    def test_orchestrator_explains_levels_and_preserves_plan_authority(self) -> None:
        text = (ROOT / "skills/agent-workflow-orchestrator/SKILL.md").read_text(encoding="utf-8")
        self._assert_control_terms(text)
        self.assertIn("frozen plan and lock", text)
        self.assertIn("host-owned pre-action boundary", text)
        self.assertIn("prompt, skill or fixture", text)

    def test_implementation_audit_checks_adapter_control_evidence(self) -> None:
        text = (ROOT / "skills/audit-plan-implementation/SKILL.md").read_text(encoding="utf-8")
        self._assert_control_terms(text)
        self.assertIn("a prompt or skill", text)
        self.assertIn("pre-action", text)
        self.assertIn("stale receipt", text)

    @staticmethod
    def _assert_control_terms(text: str) -> None:
        for term in ("GUIDANCE_ONLY", "OBSERVED", "ENFORCED", "NO_RECOMMENDATION"):
            if term not in text:
                raise AssertionError(f"missing lifecycle-control term: {term}")


if __name__ == "__main__":
    unittest.main()
