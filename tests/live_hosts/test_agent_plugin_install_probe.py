from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.host_protocol.agent_plugin_qualification import run_agent_plugin_qualification_probe


ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "agent-first-planning",
    "agent-plan-to-workers",
    "agent-workflow-orchestrator",
    "audit-agent-plan",
    "audit-plan-implementation",
    "bug-forensics",
    "issue-to-spec",
)


class AgentPluginInstallProbeTests(unittest.TestCase):
    def test_probe_is_bounded_and_does_not_store_host_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            project = root / "project"
            for tree in (package, project):
                tree.mkdir(parents=True)
                if tree == package:
                    (tree / "plugin.json").write_text('{"name":"agent-lifecycle-kit","version":"1.68.0"}', encoding="utf-8")
                else:
                    (tree / ".codex-plugin").mkdir(parents=True)
                    (tree / ".codex-plugin/plugin.json").write_text('{"name":"agent-lifecycle-kit","version":"1.68.0"}', encoding="utf-8")
                (tree / "skills").mkdir()
                for skill in SKILLS:
                    (tree / "skills" / skill).mkdir()
                    (tree / "skills" / skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            profile = read_json_object(ROOT / "adapters/codex/agent_plugin_profile.json")

            def runner(argv: list[str], timeout: float) -> dict[str, object]:
                self.assertEqual(timeout, 10)
                return {"status": "PASS", "exitCode": 0, "timedOut": False, "stdout": "codex 1.68.0\nsecret-output\n", "stderr": "", "blockers": []}

            receipt = run_agent_plugin_qualification_probe(
                package_root=package,
                project_root=project,
                profile=profile,
                command_runner=runner,
            )
            self.assertEqual(receipt["status"], "QUALIFIED")
            self.assertFalse(receipt["rawOutputStored"])
            self.assertNotIn("secret-output", str(receipt))


if __name__ == "__main__":
    unittest.main()
