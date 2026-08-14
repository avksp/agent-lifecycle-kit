from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.project.presets import (
    build_preset_profile_draft,
    list_project_presets,
    load_project_preset,
    merge_preset_defaults,
    render_project_preset,
    validate_project_preset,
)


class ProjectPresetTests(unittest.TestCase):
    def test_all_built_in_presets_validate_with_documented_matrix(self) -> None:
        result = list_project_presets()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([item["presetId"] for item in result["presets"]], ["quick-change", "research-review", "feature-implementation"])
        self.assertEqual(result["presets"][1]["reviewMesh"], "parallel-research-synthesis")
        self.assertEqual(result["presets"][2]["implementationAuthority"], "requires-frozen-plan")

    def test_research_preset_excludes_implementation(self) -> None:
        preset = load_project_preset("research-review")
        profile = build_preset_profile_draft(preset)

        self.assertEqual(validate_project_preset(preset)["status"], "PASS")
        self.assertNotIn("implementation", profile["stages"])
        self.assertEqual(profile["defaultRisk"], "S1")

    def test_sensitive_and_quality_floor_fields_are_rejected(self) -> None:
        preset = load_project_preset("quick-change")
        unsafe = copy.deepcopy(preset)
        unsafe["provider"] = "vendor"
        unsafe["presetDigest"] = canonical_digest({key: value for key, value in unsafe.items() if key != "presetDigest"})
        self.assertEqual(validate_project_preset(unsafe)["status"], "FAIL")

        quality = copy.deepcopy(preset)
        quality["qualityFloor"] = "strict"
        quality["presetDigest"] = canonical_digest({key: value for key, value in quality.items() if key != "presetDigest"})
        self.assertEqual(validate_project_preset(quality)["status"], "FAIL")

    def test_explicit_profile_values_override_preset_defaults(self) -> None:
        preset = load_project_preset("feature-implementation")
        profile = {
            "schemaVersion": "agent-project-workflow-profile.v1",
            "profileId": "existing",
            "defaultAdapter": "codex",
            "defaultMode": "plan",
            "defaultRisk": "S1",
            "policies": {},
            "stages": {"planning": {"maxAttempts": 1}},
            "productionPromotionClaimed": False,
        }
        merged = merge_preset_defaults(profile, preset)

        self.assertEqual(merged["defaultMode"], "plan")
        self.assertEqual(merged["defaultRisk"], "S1")
        self.assertEqual(merged["stages"]["planning"]["maxAttempts"], 1)
        self.assertEqual(merged["stages"]["implementation"]["maxAttempts"], 3)

    def test_render_requires_contained_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = render_project_preset(
                "quick-change",
                output_path=root / ".alk" / "project-profile.json",
                project_root=root,
            )
            self.assertEqual(receipt["status"], "PASS")
            self.assertTrue((root / ".alk/project-profile.json").is_file())
            with self.assertRaises(LifecycleError):
                render_project_preset(
                    "quick-change",
                    output_path=root.parent / "outside.json",
                    project_root=root,
                )

    def test_project_files_cannot_shadow_built_in_preset_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preset_dir = root / "profiles/project-workflow-presets"
            preset_dir.mkdir(parents=True)
            preset_dir.joinpath("quick-change.v1.json").write_text(
                '{"presetId":"quick-change","defaultRisk":"S2"}',
                encoding="utf-8",
            )
            preset = load_project_preset("quick-change", project_root=root)
            self.assertEqual(preset["defaultRisk"], "S0")


if __name__ == "__main__":
    unittest.main()
