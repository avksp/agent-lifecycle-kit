from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.1"
PLUGIN_NAME = "agent-lifecycle-kit"
SKILL_NAMES = {
    "agent-first-planning",
    "audit-agent-plan",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-plan-implementation",
}

PROJECT_MARKERS = (
    "board" + "-app",
    "board" + "2.0",
    "Dot" + "Space",
    "/Vol" + "umes/",
    "/Us" + "ers/",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


class PublicationManifestTests(unittest.TestCase):
    def test_root_plugin_manifests_use_shared_skills_and_release_license(self) -> None:
        manifest_paths = (
            ROOT / ".codex-plugin" / "plugin.json",
            ROOT / ".claude-plugin" / "plugin.json",
            ROOT / ".cursor-plugin" / "plugin.json",
        )
        for path in manifest_paths:
            manifest = load_json(path)
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertEqual(manifest["name"], PLUGIN_NAME)
                self.assertEqual(manifest["version"], VERSION)
                self.assertEqual(manifest["license"], "Apache-2.0")
                self.assertEqual(manifest["skills"], "./skills")
                self.assertTrue((ROOT / "skills").is_dir())
                self.assertEqual(manifest["interface"]["displayName"], "Agent Lifecycle Kit")

    def test_codex_publication_manifest_is_marketplace_ready(self) -> None:
        manifest = load_json(ROOT / ".codex-plugin" / "plugin.json")
        interface = manifest["interface"]
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
            "capabilities",
            "defaultPrompt",
        ):
            self.assertIn(field, interface)
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))

        marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
        self.assertEqual(marketplace["name"], PLUGIN_NAME)
        [entry] = marketplace["plugins"]
        self.assertEqual(entry["name"], PLUGIN_NAME)
        self.assertEqual(entry["source"]["source"], "url")
        self.assertEqual(entry["source"]["url"], "https://github.com/avksp/agent-lifecycle-kit.git")
        self.assertEqual(entry["source"]["ref"], f"v{VERSION}")
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Productivity")

    def test_claude_marketplace_points_to_tagged_github_source(self) -> None:
        marketplace = load_json(ROOT / ".claude-plugin" / "marketplace.json")
        self.assertEqual(marketplace["name"], PLUGIN_NAME)
        [entry] = marketplace["plugins"]
        self.assertEqual(entry["name"], PLUGIN_NAME)
        self.assertEqual(entry["source"]["source"], "github")
        self.assertEqual(entry["source"]["repo"], "avksp/agent-lifecycle-kit")
        self.assertEqual(entry["source"]["ref"], f"v{VERSION}")
        self.assertEqual(entry["license"], "Apache-2.0")

    def test_cursor_marketplace_can_resolve_root_plugin(self) -> None:
        marketplace = load_json(ROOT / ".cursor-plugin" / "marketplace.json")
        self.assertEqual(marketplace["name"], PLUGIN_NAME)
        [entry] = marketplace["plugins"]
        self.assertEqual(entry["name"], PLUGIN_NAME)
        self.assertEqual(entry["source"], ".")
        self.assertTrue((ROOT / ".cursor-plugin" / "plugin.json").is_file())
        self.assertEqual(entry["license"], "Apache-2.0")

    def test_hermes_skills_index_covers_all_lifecycle_skills(self) -> None:
        index = load_json(ROOT / "skills.sh.json")
        listed = {
            skill
            for grouping in index["groupings"]
            for skill in grouping.get("skills", [])
        }
        self.assertEqual(listed, SKILL_NAMES)
        self.assertEqual({path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}, SKILL_NAMES)

    def test_opencode_root_config_points_to_existing_adapter(self) -> None:
        manifest = load_json(ROOT / "opencode.json")
        self.assertEqual(manifest["plugin"], ["./adapters/opencode/plugins/agent-lifecycle-kit.js"])
        for raw_path in manifest["plugin"]:
            self.assertTrue((ROOT / raw_path).is_file())

    def test_release_payload_roots_include_publication_artifacts(self) -> None:
        release_common = runpy.run_path(str(ROOT / "tools" / "release" / "release_common.py"))
        payload_roots = set(release_common["PAYLOAD_ROOTS"])
        self.assertTrue(
            {
                ".agents/plugins",
                ".claude-plugin",
                ".codex-plugin",
                ".cursor-plugin",
                "opencode.json",
                "skills.sh.json",
            }.issubset(payload_roots)
        )

    def test_publication_files_are_project_neutral(self) -> None:
        roots = [
            ROOT / ".agents",
            ROOT / ".claude-plugin",
            ROOT / ".codex-plugin",
            ROOT / ".cursor-plugin",
            ROOT / "opencode.json",
            ROOT / "skills.sh.json",
        ]
        for root in roots:
            paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
            for path in paths:
                text = path.read_text(encoding="utf-8")
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    for marker in PROJECT_MARKERS:
                        self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
