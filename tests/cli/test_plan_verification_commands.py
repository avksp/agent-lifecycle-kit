from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from tests.cli.helpers import _run_cli  # noqa: E402


class CliPlanVerificationTests(unittest.TestCase):
    def test_plan_verify_writes_bounded_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, acceptance_path = _write_inputs(root)
            out_path = root / "verification.json"

            code, payload = _run_cli([
                "plan", "verify", "--manifest", str(manifest_path), "--lock", str(lock_path),
                "--acceptance", str(acceptance_path), "--repository-root", str(root), "--out", str(out_path),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-verification-receipt.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["executedCommands"])
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8"))["verificationDigest"], payload["verificationDigest"])

    def test_plan_verify_returns_nonzero_for_missing_frozen_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, acceptance_path = _write_inputs(root)
            lock_path.unlink()
            out_path = root / "failed-verification.json"

            code, payload = _run_cli([
                "plan", "verify", "--manifest", str(manifest_path), "--acceptance", str(acceptance_path),
                "--repository-root", str(root), "--out", str(out_path),
            ])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "plan-verification-failed")
            receipt = payload["details"]["verification"]
            self.assertEqual(receipt["status"], "FAIL")
            self.assertIn("plan-lock-required", {item["code"] for item in receipt["blockers"]})
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8"))["status"], "FAIL")


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "cli-verification-fixture"},
        "specification": {"tier": "S1", "requirements": [{"id": "REQ-01", "description": "verify"}]},
        "releaseTarget": {"targetVersion": "1.0.0"},
        "acceptance": {"criteria": [{"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]}]},
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV-01"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }
    package = root / "plan"
    package.mkdir()
    manifest_path = package / "plan.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lock_path = package / "plan.lock.json"
    lock_path.write_text(json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": canonical_digest(manifest)}), encoding="utf-8")
    acceptance_path = package / "acceptance-criteria.md"
    acceptance_path.write_text("| ID | Requirements | Evidence | Statement |\n| --- | --- | --- | --- |\n| `AC-01` | `REQ-01` | `EV-01` | Verify. |\n", encoding="utf-8")
    return manifest_path, lock_path, acceptance_path


if __name__ == "__main__":
    unittest.main()
