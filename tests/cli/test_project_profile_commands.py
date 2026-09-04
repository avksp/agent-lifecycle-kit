from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main
from tests.cli.test_project_explain import _command as _explain_command
from tests.cli.test_project_explain import _write_bundle as _write_explain_bundle


def _run_cli(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, json.loads(output.getvalue())


class ProjectProfileCommandTests(unittest.TestCase):
    def test_init_writes_minimal_valid_json_without_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, receipt = _run_cli(["project", "profile", "init", "--project-root", str(root)])
            profile_path = root / ".alk/project-profile.json"
            profile_text = profile_path.read_text(encoding="utf-8")
            profile = json.loads(profile_text)

        self.assertEqual(code, 0)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(profile["schemaVersion"], "agent-project-workflow-profile.v1")
        self.assertNotIn("//", profile_text)

    def test_init_can_set_default_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, _receipt = _run_cli(["project", "profile", "init", "--project-root", str(root), "--adapter", "codex"])
            profile = json.loads((root / ".alk/project-profile.json").read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(profile["defaultAdapter"], "codex")

    def test_check_discovers_profile_and_returns_effective_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / ".alk/project-profile.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-project-workflow-profile.v1",
                        "profileId": "demo",
                        "defaultAdapter": "codex",
                        "defaultMode": "plan",
                        "defaultRisk": "S1",
                        "policies": {},
                        "stages": {},
                        "productionPromotionClaimed": False,
                    }
                ),
                encoding="utf-8",
            )
            code, effective = _run_cli(["project", "profile", "check", "--project-root", str(root)])

        self.assertEqual(code, 0)
        self.assertEqual(effective["schemaVersion"], "agent-effective-project-workflow-profile.v1")
        self.assertEqual(effective["defaultAdapter"], "codex")
        self.assertEqual(effective["defaultMode"], "plan")
        self.assertEqual(effective["defaultRisk"], "S1")

    def test_missing_profile_returns_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, error = _run_cli(["project", "profile", "check", "--project-root", directory])

        self.assertEqual(code, 2)
        self.assertEqual(error["code"], "project-profile-missing")
        self.assertIn("project profile init", error["details"]["initCommand"])

    def test_explain_projects_strategy_selection_without_model_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _write_explain_bundle(Path(directory))
            code, payload = _run_cli(_explain_command(paths))

        self.assertEqual(code, 0)
        self.assertEqual(payload["selection"]["requestedRisk"], "S1")
        self.assertEqual(payload["selection"]["winningSources"]["defaultRisk"], "preset")
        self.assertEqual(payload["selection"]["capabilityStatus"], "PASS")
        self.assertFalse(payload["modelCallsStarted"])


if __name__ == "__main__":
    unittest.main()
