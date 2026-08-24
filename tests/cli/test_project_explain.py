from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[2]


def _run_cli(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, json.loads(output.getvalue())


class ProjectExplainCommandTests(unittest.TestCase):
    def test_explain_reports_lineage_and_field_enforceability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_bundle(root)
            code, payload = _run_cli(_command(paths))

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["descriptorLineage"]["status"], "PASS")
        self.assertEqual(payload["capabilityLineage"]["status"], "PASS")
        fields = {item["field"]: item for item in payload["fields"]}
        self.assertEqual(fields["defaultRisk"]["winningSource"], "preset")
        self.assertEqual(fields["defaultRisk"]["enforceability"], "GUIDANCE_ONLY")

    def test_stale_capability_is_unavailable_without_changing_selected_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_bundle(root)
            capability_path = Path(paths["capability"])
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
            capability["descriptorDigest"] = "0" * 64
            capability_path.write_text(json.dumps(capability), encoding="utf-8")

            code, payload = _run_cli(_command(paths))

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["capabilityLineage"]["status"], "UNAVAILABLE")
        self.assertEqual(payload["effectiveProfile"]["defaultRisk"], "S1")
        self.assertTrue(all(item["enforceability"] == "UNAVAILABLE" for item in payload["fields"]))

    def test_command_risk_downgrade_is_rejected_by_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = _write_bundle(root)
            argv = [*_command(paths), "--risk", "S0"]
            code, payload = _run_cli(argv)

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "risk-tier-downgrade")


def _command(paths: dict[str, str]) -> list[str]:
    return [
        "project",
        "profile",
        "explain",
        "--project-root",
        paths["root"],
        "--profile",
        paths["profile"],
        "--preset",
        "feature-implementation",
        "--manifest",
        paths["manifest"],
        "--lock",
        paths["lock"],
        "--descriptor",
        paths["descriptor"],
        "--capability-manifest",
        paths["capability"],
    ]


def _write_bundle(root: Path) -> dict[str, str]:
    profile_path = root / ".alk/project-profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-project-workflow-profile.v1",
                "profileId": "explain-test",
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
    manifest = {"status": "FROZEN", "tierResolution": {"tier": "S1"}, "workstreams": []}
    manifest_path = root / "plan.manifest.json"
    lock_path = root / "plan.lock.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lock_path.write_text(json.dumps({"manifestHash": canonical_digest(manifest)}), encoding="utf-8")
    adapter_root = root / "adapters/claude"
    adapter_root.mkdir(parents=True)
    descriptor_path = adapter_root / "adapter.descriptor.json"
    capability_path = adapter_root / "capabilities.manifest.json"
    shutil.copyfile(ROOT / "adapters/claude/adapter.descriptor.json", descriptor_path)
    shutil.copyfile(ROOT / "adapters/claude/capabilities.manifest.json", capability_path)
    return {
        "root": str(root),
        "profile": str(profile_path),
        "manifest": str(manifest_path),
        "lock": str(lock_path),
        "descriptor": str(descriptor_path),
        "capability": str(capability_path),
    }


if __name__ == "__main__":
    unittest.main()
