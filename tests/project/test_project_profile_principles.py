from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.project.profile import validate_project_profile


class ProjectProfilePrinciplesTests(unittest.TestCase):
    def test_profile_accepts_a_digest_bound_reference(self) -> None:
        profile = {
            "schemaVersion": "agent-project-workflow-profile.v1",
            "profileId": "sample",
            "defaultAdapter": None,
            "defaultMode": "auto",
            "defaultRisk": "auto",
            "policies": {},
            "stages": {},
            "principles": {"path": "docs/project-principles.json", "digest": "a" * 64, "sourceOfTruth": False},
        }
        self.assertEqual(validate_project_profile(profile)["status"], "PASS")

    def test_profile_rejects_principles_as_authority(self) -> None:
        profile = {
            "schemaVersion": "agent-project-workflow-profile.v1",
            "profileId": "sample",
            "defaultAdapter": None,
            "defaultMode": "auto",
            "defaultRisk": "auto",
            "policies": {},
            "stages": {},
            "principles": {"path": "docs/project-principles.json", "digest": "a" * 64, "sourceOfTruth": True},
        }
        with self.assertRaises(LifecycleError):
            validate_project_profile(profile)


if __name__ == "__main__":
    unittest.main()
