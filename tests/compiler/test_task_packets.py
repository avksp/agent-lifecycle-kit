from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.compiler import compile_task_packets  # noqa: E402
from agent_lifecycle.contracts import canonical_digest, write_json_create  # noqa: E402


class TaskPacketCompilerTests(unittest.TestCase):
    def test_compile_requires_frozen_lock_and_writes_idempotent_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                manifest = _write_bundle(Path(tmp))
                payload = compile_task_packets(manifest, write=True)
                repeat = compile_task_packets(manifest, write=True)
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(payload, repeat)
            self.assertEqual(payload["index"]["packetCount"], 1)
            self.assertEqual(payload["packets"][0]["task"]["id"], "WS-01")


def _write_bundle(root: Path) -> Path:
    manifest = _manifest()
    digest = canonical_digest(manifest)
    write_json_create(
        root / "plans/p/.agent-plan/p/plan.lock.json",
        {"schemaVersion": "agent-plan-lock.v1", "manifestHash": digest, "planRevision": 1},
    )
    path = root / "plans/p/plan.manifest.json"
    write_json_create(path, manifest)
    return path


def _manifest() -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "p",
            "artifactRoot": "plans/p",
            "planArtifactRoot": "plans/p/.agent-plan/p",
        },
        "specification": {"tier": "S1", "revision": 1, "artifact": "spec.json"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Compile",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src"],
                "plannedItems": [{"id": "REQ-1", "description": "Do it"}],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
                "artifactPaths": {
                    "result": "tasks/WS-01/attempt-{attempt}/task-result.json",
                    "review": "tasks/WS-01/attempt-{attempt}/task-review.json",
                },
            }
        ],
        "acceptanceCriteria": [{"id": "AC-1", "evidenceIds": ["EV-1"]}],
    }


if __name__ == "__main__":
    unittest.main()
