from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdapterInstallationMetadataValidatorTests(unittest.TestCase):
    def test_current_descriptors_pass_installation_metadata_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "installation-metadata.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_installation_metadata.py"),
                    "--descriptor-root",
                    "adapters",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["schemaVersion"], "agent-adapter-installation-metadata-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["adapterCount"], 12)
        self.assertFalse(payload["requiredInvariants"]["diagnosticsHostExecution"])
        self.assertFalse(Path(payload["catalog"]["path"]).is_absolute())

    def test_validator_rejects_shell_command_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_root = root / "adapters" / "codex"
            descriptor_root.mkdir(parents=True)
            source = ROOT / "adapters/codex/adapter.descriptor.json"
            target = descriptor_root / "adapter.descriptor.json"
            shutil.copyfile(source, target)
            descriptor = json.loads(target.read_text(encoding="utf-8"))
            descriptor["installation"]["commands"][0]["command"] = "codex plugin add"
            target.write_text(json.dumps(descriptor), encoding="utf-8")
            evidence = root / "evidence.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_installation_metadata.py"),
                    "--descriptor-root",
                    str(root / "adapters"),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("adapter-installation-facts-invalid", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()
