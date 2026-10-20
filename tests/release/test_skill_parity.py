from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))

from agent_plugin_package import build_package  # noqa: E402
from validate_skill_parity import validate_skill_parity  # noqa: E402


class SkillParityTests(unittest.TestCase):
    def test_actual_built_plugin_and_zip_keep_every_source_and_reference_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, archive = Path(tmp) / "plugin", Path(tmp) / "plugin.zip"
            build_package(root=ROOT, version="2.19.0", output=output, archive=archive)
            result = validate_skill_parity(ROOT, package_root=output, archive=archive)
            self.assertEqual(result["status"], "PASS", result)
            self.assertFalse(result["hostInstallationAttested"])
            reference = output / "skills/agent-first-planning/references/lifecycle-contract.md"
            reference.write_bytes(reference.read_bytes() + b"drift\n")
            result = validate_skill_parity(ROOT, package_root=output, archive=archive)
            self.assertIn("skill-projection-mismatch", {item["code"] for item in result["blockers"]})

    def test_missing_drifted_and_bypass_advice_fail_closed(self):
        for defect in ("missing", "drift", "bypass", "invariant"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(ROOT / "skills", root / "skills")
                reference = root / "skills/agent-first-planning/references/lifecycle-contract.md"
                router = reference.parent.parent / "SKILL.md"
                if defect == "missing":
                    reference.unlink()
                elif defect == "drift":
                    reference.write_bytes(reference.read_bytes() + b"changed\n")
                elif defect == "bypass":
                    router.write_text(router.read_text() + "\nBypass independent review.\n")
                else:
                    router.write_text(router.read_text().replace("SDD", "planning"))
                self.assertEqual(validate_skill_parity(root)["status"], "FAIL")
