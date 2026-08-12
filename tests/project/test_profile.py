from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.project.profile import (
    PROJECT_PROFILE_RELATIVE_PATH,
    load_project_profile,
    normalize_project_profile,
    validate_project_profile,
)


def _profile(**changes: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "schemaVersion": "agent-project-workflow-profile.v1",
        "profileId": "project-default",
        "defaultAdapter": "codex",
        "defaultMode": "auto",
        "defaultRisk": "auto",
        "policies": {
            "routingProfile": "profiles/routing.json",
            "hostModelProfile": ".alk/host-model.json",
        },
        "stages": {
            "planning": {"mode": "plan", "modelClass": "standard-code", "maxAttempts": 2},
            "audit": {"reviewMesh": "implementation-audit-panel", "minReviewers": 2},
        },
    }
    profile.update(changes)
    return profile


class ProjectProfileTests(unittest.TestCase):
    def test_valid_profile_is_normalized_without_mutating_input(self) -> None:
        profile = _profile()
        normalized = normalize_project_profile(profile)

        self.assertEqual(normalized["schemaVersion"], "agent-project-workflow-profile.v1")
        self.assertEqual(validate_project_profile(profile)["status"], "PASS")
        self.assertIsNot(normalized, profile)
        self.assertNotIn("productionPromotionClaimed", profile)
        self.assertFalse(normalized["productionPromotionClaimed"])

    def test_unknown_stage_and_alias_are_rejected(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "canonical"):
            validate_project_profile(_profile(stages={"implementation-review": {}}))

    def test_sensitive_and_provider_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "sensitive"):
            validate_project_profile(_profile(apiKey="secret"))

        with self.assertRaisesRegex(LifecycleError, "sensitive"):
            validate_project_profile(_profile(stages={"research": {"providerModel": "vendor/model"}}))

    def test_unsafe_references_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            validate_project_profile(_profile(policies={"routingProfile": "/tmp/routing.json"}))
        with self.assertRaises(LifecycleError):
            validate_project_profile(_profile(stages={"planning": {"guidanceRef": "../instructions.md"}}))

    def test_profile_file_is_bounded_and_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / PROJECT_PROFILE_RELATIVE_PATH
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(_profile()), encoding="utf-8")

            loaded = load_project_profile(profile_path, project_root=root)

            self.assertEqual(loaded["profileId"], "project-default")

    def test_symlinked_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / f"alk-profile-outside-{root.name}.md"
            outside.write_text("guidance", encoding="utf-8")
            try:
                (root / "guidance").mkdir()
                (root / "guidance/out.md").symlink_to(outside)
                with self.assertRaises(LifecycleError):
                    validate_project_profile(
                        _profile(stages={"planning": {"guidanceRef": "guidance/out.md"}}),
                        project_root=root,
                    )
            finally:
                outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
