from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main


def _run_cli(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, json.loads(output.getvalue())


class StartProjectProfileTests(unittest.TestCase):
    def test_start_discovers_profile_and_returns_guided_receipt_without_adapter_flag(self) -> None:
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
                        "defaultMode": "auto",
                        "defaultRisk": "auto",
                        "policies": {},
                        "stages": {},
                        "productionPromotionClaimed": False,
                    }
                ),
                encoding="utf-8",
            )
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, receipt = _run_cli(["start", "--text", "Inspect the cache"])
            finally:
                os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(receipt["schemaVersion"], "agent-guided-action-receipt.v1")
        self.assertEqual(receipt["startReceipt"]["adapterId"], "codex")
        self.assertEqual(receipt["effectiveProfile"]["profileId"], "demo")
        self.assertEqual(receipt["nextAction"]["type"], "DRAFT_INTAKE")
        self.assertFalse(receipt["modelCallsStarted"])

    def test_explicit_adapter_overrides_profile_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / ".alk/project-profile.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-project-workflow-profile.v1",
                        "profileId": "demo",
                        "defaultAdapter": "claude",
                        "defaultMode": "auto",
                        "defaultRisk": "auto",
                        "policies": {},
                        "stages": {},
                        "productionPromotionClaimed": False,
                    }
                ),
                encoding="utf-8",
            )
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, receipt = _run_cli(["start", "--adapter", "qwen-code", "--text", "Inspect the cache"])
            finally:
                os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(receipt["startReceipt"]["adapterId"], "qwen-code")

    def test_no_project_profile_preserves_legacy_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                code, receipt = _run_cli(
                    ["start", "--no-project-profile", "--adapter", "codex", "--text", "Inspect the cache"]
                )
            finally:
                os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(receipt["schemaVersion"], "agent-lifecycle-start-receipt.v1")
        self.assertNotIn("effectiveProfile", receipt)


if __name__ == "__main__":
    unittest.main()
