from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.freeze import build_plan_lock_v2, verify_plan_lock

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class PlanLockTests(unittest.TestCase):
    def test_v2_lock_binds_manifest_and_sorted_inventory(self) -> None:
        manifest = json.loads((FIXTURE / "plan.manifest.json").read_text(encoding="utf-8"))

        lock = build_plan_lock_v2(manifest, repository_root=ROOT)

        self.assertEqual(lock["schemaVersion"], "agent-plan-lock.v2")
        self.assertEqual(lock["manifestHash"], canonical_digest(manifest))
        self.assertEqual([item["path"] for item in lock["entries"]], sorted(manifest["planFiles"]))
        self.assertEqual(verify_plan_lock(manifest, lock)["lockSchemaVersion"], "agent-plan-lock.v2")

    def test_v1_lock_is_rejected_when_manifest_requires_v2(self) -> None:
        manifest = json.loads((FIXTURE / "plan.manifest.json").read_text(encoding="utf-8"))
        lock = {
            "schemaVersion": "agent-plan-lock.v1",
            "packageId": manifest["package"]["id"],
            "planRevision": manifest["planRevision"],
            "manifestHash": canonical_digest(manifest),
        }

        with self.assertRaisesRegex(Exception, "v2"):
            verify_plan_lock(manifest, lock)


if __name__ == "__main__":
    unittest.main()
