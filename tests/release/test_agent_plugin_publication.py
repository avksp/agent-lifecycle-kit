from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginPublicationTests(unittest.TestCase):
    def test_release_candidate_builds_version_bound_package(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("tools/release/build_agent_plugin.py", workflow)
        self.assertIn("tools/release/validate_agent_plugin.py", workflow)
        self.assertIn('print(tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])', workflow)
        self.assertIn("release/candidate/agent-lifecycle-kit-agent-plugin-v${VERSION}.zip", workflow)
        self.assertIn('"$EVIDENCE_DIR"/agent-plugin.json', workflow)

    def test_published_workflow_uses_immutable_tag_and_separate_permissions(self) -> None:
        workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
        publish_job = _job_block(workflow, "publish")
        plugin_job = _job_block(workflow, "agent-plugin")

        self.assertIn("ref: ${{ github.event.release.tag_name }}", publish_job)
        self.assertIn("validate_publication_adoption.py", publish_job)
        self.assertNotIn("contents: write", publish_job)
        self.assertIn("contents: write", plugin_job)
        self.assertIn("GH_TOKEN: ${{ github.token }}", plugin_job)
        self.assertIn("github.event.release.tag_name", plugin_job)
        self.assertIn("gh release upload \"$RELEASE_TAG\" \"$ARCHIVE\"", plugin_job)
        self.assertIn('re.fullmatch(r"v[0-9]+\\.[0-9]+\\.[0-9]+", tag)', plugin_job)
        self.assertNotIn("id-token: write", plugin_job)

    def test_release_inventory_tracks_pinned_agent_plugins_schema(self) -> None:
        release_common = (ROOT / "tools/release/release_common.py").read_text(encoding="utf-8")

        self.assertIn('"schemas/agent-plugins"', release_common)


def _job_block(workflow: str, job_id: str) -> str:
    match = re.search(rf"^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", workflow, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"workflow job not found: {job_id}")
    return match.group(0)


if __name__ == "__main__":
    unittest.main()
