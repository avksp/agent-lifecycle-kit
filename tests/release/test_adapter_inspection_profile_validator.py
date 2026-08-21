from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol.inspection import CommandRun, inspect_adapter_descriptor
from agent_lifecycle.host_protocol.inspection_profile import validate_inspection_profile
from tools.release.validate_adapter_inspection_profiles import validate_profiles

ROOT = Path(__file__).resolve().parents[2]


class AdapterInspectionProfileValidatorTests(unittest.TestCase):
    def test_shipped_profiles_and_generic_boundary_pass(self) -> None:
        payload = validate_profiles(ROOT / "adapters", ROOT / "src/agent_lifecycle/host_protocol/inspection.py")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(len(payload["checks"]), 12)
        self.assertTrue(payload["inspectionBoundary"]["profileExtensible"])
        self.assertEqual(
            {item["adapterId"] for item in payload["checks"] if item["profileStatus"] == "UNSUPPORTED"},
            {"goose", "grok-build", "openinterpreter", "pi"},
        )

    def test_authority_bearing_profile_is_rejected(self) -> None:
        profile = {
            "schemaVersion": "agent-host-adapter-inspection-profile.v1",
            "adapterId": "codex",
            "host": "codex",
            "binary": "codex",
            "status": "SUPPORTED",
            "handler": "codex",
            "profileId": "codex-inspection",
            "productionPromotionClaimed": True,
            "modelCallsStarted": False,
        }
        validation = validate_inspection_profile(profile, adapter_id="codex", host="codex")
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("inspection-profile-authority-forbidden", {item["code"] for item in validation["blockers"]})

    def test_executable_profile_is_rejected_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/codex"
            adapter_root.mkdir(parents=True)
            (adapter_root / "inspection_profile.py").write_text(
                "import os\nPROFILE = os.environ\n",
                encoding="utf-8",
            )
            descriptor = json.loads((ROOT / "adapters/codex/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path = adapter_root / "adapter.descriptor.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                project_root=root,
            )
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("adapter-inspection-profile-not-literal", {item["code"] for item in payload["blockers"]})

    def test_temporary_profile_uses_existing_handler_without_dispatch_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/codex"
            adapter_root.mkdir(parents=True)
            descriptor = json.loads((ROOT / "adapters/codex/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path = adapter_root / "adapter.descriptor.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            shutil.copyfile(ROOT / "adapters/codex/inspection_profile.py", adapter_root / "inspection_profile.py")

            def runner(argv: list[str], timeout: float) -> CommandRun:
                del timeout
                return CommandRun(0, "codex-cli 0.147.0" if "--version" in argv else "--json --sandbox", "")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                project_root=root,
                command_runner=runner,
            )
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["capabilities"]["inspectionProfile"]["handler"], "codex")


if __name__ == "__main__":
    unittest.main()
