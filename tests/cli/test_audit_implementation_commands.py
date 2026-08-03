from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, write_json_create

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class CliImplementationAuditTests(unittest.TestCase):
    def test_audit_implementation_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle)
            out_path = root / "work/WS-01/attempt-1/implementation-audit.json"

            code, payload = _run_cli(
                [
                    "audit",
                    "implementation",
                    "--manifest",
                    str(bundle["manifestPath"]),
                    "--state",
                    str(bundle["statePath"]),
                    "--task",
                    "WS-01",
                    "--result",
                    result_path,
                    "--review",
                    review_path,
                    "--expected-revision",
                    "1",
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-implementation-audit-report.v1")
            self.assertEqual(payload["status"], "PASS")
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["reportDigest"], payload["reportDigest"])

    def test_audit_final_implementation_writes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="FINAL_AUDIT", task_status="ACCEPTED")
            result_path, review_path = _write_result_review(root, bundle)
            report_out = root / "work/WS-01/attempt-1/implementation-audit.json"
            _run_cli(
                [
                    "audit",
                    "implementation",
                    "--manifest",
                    str(bundle["manifestPath"]),
                    "--state",
                    str(bundle["statePath"]),
                    "--task",
                    "WS-01",
                    "--result",
                    result_path,
                    "--review",
                    review_path,
                    "--out",
                    str(report_out),
                ]
            )
            final_out = root / "final/final-implementation-audit.json"

            code, payload = _run_cli(
                [
                    "audit",
                    "final-implementation",
                    "--manifest",
                    str(bundle["manifestPath"]),
                    "--state",
                    str(bundle["statePath"]),
                    "--report",
                    "work/WS-01/attempt-1/implementation-audit.json",
                    "--out",
                    str(final_out),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-final-implementation-audit.v1")
            self.assertEqual(payload["status"], "PASS")
            saved = json.loads(final_out.read_text(encoding="utf-8"))
            self.assertEqual(saved["auditDigest"], payload["auditDigest"])


def _write_bundle(
    root: Path,
    *,
    phase: str = "STEP_REVIEW",
    task_status: str = "VERIFYING",
) -> dict[str, Path | str]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"]}],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": []}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": digest,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": phase,
        "manifestPath": "plans/package/plan.manifest.json",
        "authorization": {"required": False, "granted": True},
        "tasks": [
            {
                "id": "WS-01",
                "status": task_status,
                "attempt": 1,
                "dependsOn": [],
                "required": True,
                "writes": ["src/example.py"],
                "acceptanceIds": [],
                "evidenceIds": [],
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
                "packet": {"sha256": "1" * 64},
                "result": {"path": "work/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10},
                "review": {
                    "path": "work/WS-01/attempt-1/task-review.json",
                    "sha256": "3" * 64,
                    "bytes": 10,
                    "verdict": "ACCEPTED",
                },
            }
        ],
        "eventLog": "events.jsonl",
    }
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"manifestPath": manifest_path, "statePath": state_path, "planDigest": digest}


def _write_result_review(root: Path, bundle: dict[str, Path | str]) -> tuple[str, str]:
    result = {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": bundle["planDigest"],
        "sourceRevision": "source",
        "actor": "worker",
        "actorRunId": "worker-run",
        "surface": "test",
        "taskPacketHash": "1" * 64,
        "traceDigest": "4" * 64,
        "changedFiles": ["src/example.py"],
        "changeSet": {
            "provider": "git-worktree-v1",
            "baselineRef": "main",
            "baselineSha": "source",
            "fileSetHash": "5" * 64,
            "diffHash": "6" * 64,
            "snapshotHash": "7" * 64,
        },
        "commands": [{"id": "unit", "status": "PASS", "exitCode": 0}],
        "itemOutcomes": [{"plannedItemId": "REQ-01", "status": "COMPLETE", "changedFiles": ["src/example.py"]}],
        "summary": "done",
        "assumptions": [],
        "blocker": None,
        "contractChangeRequest": None,
    }
    result_path = "work/WS-01/attempt-1/task-result.json"
    write_json_create(root / result_path, result)
    result_digest = canonical_digest(result)
    review = {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": bundle["planDigest"],
        "resultHash": result_digest,
        "taskPacketHash": "1" * 64,
        "traceDigest": "4" * 64,
        "reviewer": {"id": "reviewer", "independent": True, "surface": "test", "runId": "review-run"},
        "reviewedAt": "2026-08-03T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [{"plannedItemId": "REQ-01", "verdict": "ACCEPTED", "findingIds": []}],
        "acceptanceChecks": [],
        "findings": [],
        "summary": "accepted",
    }
    review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / review_path, review)
    state_path = Path(bundle["statePath"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"][0]["result"]["sha256"] = result_digest
    state["tasks"][0]["result"]["bytes"] = len(json.dumps(result).encode("utf-8"))
    state["tasks"][0]["review"]["sha256"] = canonical_digest(review)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return result_path, review_path


if __name__ == "__main__":
    unittest.main()
