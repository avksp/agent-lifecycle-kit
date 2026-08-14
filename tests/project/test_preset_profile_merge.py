from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.project.merge import build_effective_project_profile
from agent_lifecycle.project.presets import load_project_preset


def _profile() -> dict[str, object]:
    return {
        "schemaVersion": "agent-project-workflow-profile.v1",
        "profileId": "demo",
        "defaultAdapter": "codex",
        "defaultMode": "auto",
        "defaultRisk": "auto",
        "policies": {},
        "stages": {},
        "productionPromotionClaimed": False,
    }


class PresetProfileMergeTests(unittest.TestCase):
    def test_frozen_plan_risk_and_review_requirements_remain_authoritative(self) -> None:
        preset = load_project_preset("feature-implementation")
        plan = {
            "status": "FROZEN",
            "tierResolution": {"tier": "S2"},
            "reviewMeshRequired": True,
            "workstreams": [{"writes": ["src/example.py"]}],
            "requiredGates": ["implementation-audit"],
        }
        lock = {"manifestHash": canonical_digest(plan)}
        effective = build_effective_project_profile(_profile(), preset=preset, plan=plan, lock=lock)

        self.assertEqual(effective["defaultRisk"], "S2")
        self.assertEqual(effective["stages"]["implementation"]["risk"], "S2")
        self.assertEqual(effective["preset"]["presetId"], "feature-implementation")

        downgraded = {
            **_profile(),
            "stages": {"implementation": {"reviewMesh": "off"}},
        }
        with self.assertRaisesRegex(LifecycleError, "review mesh"):
            build_effective_project_profile(downgraded, preset=preset, plan=plan, lock=lock)


if __name__ == "__main__":
    unittest.main()
