from __future__ import annotations

import unittest

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.project.merge import build_effective_project_profile


def _profile() -> dict[str, object]:
    return {
        "schemaVersion": "agent-project-workflow-profile.v1",
        "profileId": "effective-configuration",
        "defaultAdapter": "codex",
        "defaultMode": "auto",
        "defaultRisk": "auto",
        "policies": {},
        "stages": {"audit": {"reviewMesh": "implementation-audit-panel"}},
        "productionPromotionClaimed": False,
    }


class EffectiveConfigurationTests(unittest.TestCase):
    def test_plan_constraint_is_explained_without_replacing_profile(self) -> None:
        plan = {
            "status": "FROZEN",
            "tierResolution": {"tier": "S2"},
            "reviewMeshRequired": True,
            "threadBridge": {
                "mode": "read-only",
                "operations": {
                    "read": {"enabled": True, "scope": "explicit-target", "approval": "none", "blocking": "required"},
                    "list": {"enabled": False, "scope": "project", "approval": "none", "blocking": "non-blocking"},
                    "send": {"enabled": False, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
                    "create": {"enabled": False, "scope": "project", "approval": "operator", "blocking": "required"},
                },
                "phaseRules": {},
                "limits": {"maxImportedBytes": 4096, "maxImportedTokens": 512},
            },
        }
        effective = build_effective_project_profile(
            _profile(), plan=plan, lock={"manifestHash": canonical_digest(plan)}
        )

        fields = {item["field"]: item for item in effective["fieldProvenance"]}
        self.assertEqual(effective["defaultRisk"], "S2")
        self.assertEqual(fields["defaultRisk"]["winningSource"], "plan")
        self.assertEqual(fields["threadBridge"]["winningSource"], "plan")
        self.assertEqual(fields["stages.audit.reviewMesh"]["winningSource"], "profile")


if __name__ == "__main__":
    unittest.main()
