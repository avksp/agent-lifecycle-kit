from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class WorkflowLineageTests(unittest.TestCase):
    def test_check_lineage_compares_shared_release_and_workflow_identity(self) -> None:
        manifest = _plan_manifest(include_dependent=True)
        digest = canonical_digest(manifest)
        state = {
            "packageId": "package",
            "planRevision": 2,
            "planDigest": digest,
            "tasks": [
                {"id": "WS-01", "required": True},
                {"id": "WS-02", "required": True},
            ],
        }
        packet_index = {"packageId": "package", "manifestDigest": digest}
        final_audit = {"planRevision": 2, "planDigest": digest}
        final_proof = {"packageId": "package", "planRevision": 2, "planDigest": digest}
        release_inventory = {"packageId": "package", "planRevision": 2, "planDigest": digest}
        lock = {"packageId": "package", "planRevision": 2, "manifestHash": digest}

        payload = check_lineage(
            manifest,
            state=state,
            task_packet_index=packet_index,
            final_audit=final_audit,
            final_proof=final_proof,
            release_inventory=release_inventory,
            lock=lock,
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(all(item["status"] == "PASS" for item in payload["lineageChecks"]))

    def test_check_lineage_fails_for_required_task_and_digest_drift(self) -> None:
        manifest = _plan_manifest(include_dependent=True)
        state = {
            "packageId": "package",
            "planRevision": 2,
            "planDigest": "9" * 64,
            "tasks": [{"id": "WS-01", "required": True}],
        }

        payload = check_lineage(manifest, state=state)

        failed = {item["id"] for item in payload["lineageChecks"] if item["status"] == "FAIL"}
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("state.planDigest", failed)
        self.assertIn("requiredTaskSet", failed)


if __name__ == "__main__":
    unittest.main()
