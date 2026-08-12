from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle


class UnifiedStartProjectProfileTests(unittest.TestCase):
    def test_active_profile_wraps_existing_start_receipt(self) -> None:
        profile = {
            "schemaVersion": "agent-project-workflow-profile.v1",
            "profileId": "demo",
            "defaultAdapter": "codex",
            "defaultMode": "auto",
            "defaultRisk": "auto",
            "policies": {},
            "stages": {"research": {"modelClass": "standard-code", "maxAttempts": 2}},
        }

        receipt = start_lifecycle(adapter_id=None, task_text="Inspect this module", project_profile=profile)

        self.assertEqual(receipt["schemaVersion"], "agent-guided-action-receipt.v1")
        self.assertEqual(receipt["startReceipt"]["schemaVersion"], "agent-lifecycle-start-receipt.v1")
        self.assertEqual(receipt["effectiveProfile"]["stages"]["research"]["modelClass"], "standard-code")
        self.assertEqual(receipt["profileDigest"], receipt["effectiveProfile"]["effectiveProfileDigest"])
        self.assertEqual(receipt["startReceipt"]["projectProfileDigest"], receipt["profileDigest"])
        self.assertEqual(receipt["stageGuidance"]["stage"], "intake")
        self.assertEqual(receipt["nextAction"]["stage"], "intake")
        self.assertFalse(receipt["stageGuidance"]["guidance"]["guidanceExecutable"])

    def test_profile_without_default_adapter_returns_guided_blocker(self) -> None:
        profile = {
            "schemaVersion": "agent-project-workflow-profile.v1",
            "profileId": "empty",
            "defaultAdapter": None,
            "defaultMode": "auto",
            "defaultRisk": "auto",
            "policies": {},
            "stages": {},
        }

        receipt = start_lifecycle(adapter_id=None, task_text="Inspect this module", project_profile=profile)

        self.assertEqual(receipt["schemaVersion"], "agent-guided-action-receipt.v1")
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["startReceipt"]["blockers"][0]["code"], "start-adapter-required")
        self.assertEqual(receipt["stageGuidance"]["stage"], "intake")

    def test_guidance_is_project_metadata_only_in_guided_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guidance = root / "guidance" / "intake.md"
            guidance.parent.mkdir()
            guidance.write_text("Review the task boundary.", encoding="utf-8")
            profile = {
                "schemaVersion": "agent-project-workflow-profile.v1",
                "profileId": "guided",
                "defaultAdapter": "codex",
                "defaultMode": "auto",
                "defaultRisk": "auto",
                "policies": {},
                "stages": {"intake": {"guidanceRef": "guidance/intake.md"}},
            }

            receipt = start_lifecycle(
                adapter_id=None,
                task_text="Inspect this module",
                project_profile=profile,
                project_root=root,
            )

        self.assertTrue(receipt["stageGuidance"]["guidance"]["guidancePresent"])
        self.assertEqual(receipt["stageGuidance"]["guidance"]["guidanceBytes"], len("Review the task boundary."))
        self.assertNotIn("Review the task boundary.", str(receipt))
        self.assertFalse(receipt["stageGuidance"]["guidance"]["guidanceExecutable"])


if __name__ == "__main__":
    unittest.main()
