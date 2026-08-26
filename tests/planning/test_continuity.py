from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.context import build_context_checkpoint, restore_context_checkpoint, write_context_checkpoint
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.planning import (
    build_plan_snapshot,
    reconcile_plan_snapshot,
    render_plan_handoff,
    require_reconciliation_pass,
    require_repository_references_pass,
    validate_repository_references,
)


class PlanContinuityTests(unittest.TestCase):
    def test_repository_references_are_optional_for_single_repo_defaults(self) -> None:
        validation = validate_repository_references(_manifest(repository_references=[]))

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["referenceCount"], 0)
        self.assertEqual(validation["repositoryIds"], [])

    def test_repository_references_reject_absolute_paths_and_unscoped_writes(self) -> None:
        manifest = _manifest(
            repository_references=[
                {
                    "id": "external",
                    "repoId": "/tmp/repo",
                    "owner": "team-worker",
                    "access": "write-scoped",
                    "paths": [],
                }
            ]
        )

        validation = validate_repository_references(manifest)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("absolute-repository-reference", {item["code"] for item in validation["blockers"]})
        self.assertIn("write-reference-missing-paths", {item["code"] for item in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            require_repository_references_pass(validation)

    def test_repository_references_reject_non_object_entries_and_windows_paths(self) -> None:
        manifest = _manifest(
            repository_references=[
                "api-service",
                {
                    "id": "docs",
                    "repoId": "C:/work/repo",
                    "owner": "docs-reviewer",
                    "access": "read-only",
                    "paths": ["docs"],
                },
            ]
        )

        validation = validate_repository_references(manifest)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("invalid-repository-reference", {item["code"] for item in validation["blockers"]})
        self.assertIn("absolute-repository-reference", {item["code"] for item in validation["blockers"]})

    def test_frozen_snapshot_is_content_addressed_and_reconciles(self) -> None:
        manifest = _manifest()
        snapshot = build_plan_snapshot(manifest)
        reconciliation = reconcile_plan_snapshot(snapshot, manifest)

        self.assertEqual(snapshot["schemaVersion"], "agent-plan-snapshot.v1")
        self.assertTrue(snapshot["immutable"])
        self.assertEqual(reconciliation["classification"], "MATCH")
        self.assertEqual(require_reconciliation_pass(reconciliation)["status"], "PASS")

    def test_reconciliation_blocks_manifest_drift(self) -> None:
        manifest = _manifest()
        snapshot = build_plan_snapshot(manifest)
        drifted = _manifest()
        drifted["planRevision"] = 3

        reconciliation = reconcile_plan_snapshot(snapshot, drifted)

        self.assertEqual(reconciliation["status"], "FAIL")
        self.assertEqual(reconciliation["classification"], "REQUIRES_NEW_PLAN")
        self.assertIn("plan-snapshot-source-drift", {item["code"] for item in reconciliation["blockers"]})

    def test_handoff_is_compact_and_omits_extra_workstreams(self) -> None:
        manifest = _manifest()
        manifest["workstreams"].append(
            {"id": "WS-02", "title": "Follow-up", "owner": "reviewer", "writes": ["tests/team"]}
        )
        snapshot = build_plan_snapshot(manifest)

        handoff = render_plan_handoff(manifest, snapshot=snapshot, max_workstreams=1, target_tokens=4096)

        self.assertEqual(handoff["schemaVersion"], "agent-plan-handoff.v1")
        self.assertEqual(handoff["status"], "PASS")
        self.assertEqual(len(handoff["workstreams"]), 1)
        self.assertEqual(handoff["omitted"]["workstreamCount"], 1)
        self.assertLessEqual(handoff["estimatedTokens"], 4096)

    def test_four_sessions_resume_from_bounded_artifacts_without_model_state(self) -> None:
        manifest = _manifest()
        snapshot = build_plan_snapshot(manifest)
        handoff = render_plan_handoff(manifest, snapshot=snapshot, target_tokens=4096)
        phases = (
            ("planning", "work/release/plan-handoff.json"),
            ("implementation", "work/release/task-packet.json"),
            ("audit", "work/release/task-review.json"),
            ("acceptance", "work/release/final-audit.json"),
        )

        self.assertEqual(handoff["status"], "PASS")
        self.assertLessEqual(handoff["estimatedTokens"], 4096)
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_root = Path(tmp) / "checkpoints"
            for state_revision, (phase, artifact_path) in enumerate(phases, start=1):
                session_id = f"{phase}-session"
                state = {
                    "runId": "release-run-1",
                    "packageId": "team-plan",
                    "planRevision": 2,
                    "planDigest": "b" * 64,
                    "stateRevision": state_revision,
                    "sourceRevision": "a" * 40,
                }
                checkpoint = build_context_checkpoint(
                    session_id=session_id,
                    run_id=state["runId"],
                    adapter_id="no-model-fixture",
                    package_id=state["packageId"],
                    plan_revision=state["planRevision"],
                    plan_digest=state["planDigest"],
                    state_revision=state_revision,
                    source_revision=state["sourceRevision"],
                    capture_mode="MILESTONE",
                    reason=f"{phase}-handoff",
                    summary={
                        "latestUserIntent": "Complete the reviewed release without weakening gates.",
                        "acceptedDecisions": [f"{phase} uses current ALK artifacts"],
                        "openBlockers": [],
                        "nextRequiredAction": f"continue-{phase}",
                    },
                    referenced_artifacts=[{"path": artifact_path, "digest": f"{state_revision:x}" * 64}],
                    created_at=f"2026-08-26T00:00:0{state_revision}Z",
                    target_tokens=2048,
                )
                receipt = write_context_checkpoint(checkpoint, root=checkpoint_root)
                continuation = restore_context_checkpoint(
                    Path(receipt["path"]),
                    state=state,
                    session_id=session_id,
                    target_tokens=2048,
                )

                self.assertEqual(continuation["status"], "PASS")
                self.assertFalse(continuation["implementationAuthorized"])
                self.assertEqual(continuation["proofAuthority"], "none")
                self.assertEqual(continuation["referencedArtifacts"], checkpoint["referencedArtifacts"])
                serialized = repr(continuation)
                for forbidden in ("rawTranscript", "messages", "systemPrompt", "developerPrompt"):
                    self.assertNotIn(forbidden, serialized)


def _manifest(*, repository_references: list[dict] | None = None) -> dict:
    return {
        "status": "FROZEN",
        "planRevision": 2,
        "package": {"id": "team-plan"},
        "baseRevision": {"ref": "v1.0.0", "sha": "a" * 40},
        "repositoryReferences": repository_references
        if repository_references is not None
        else [
            {
                "id": "api",
                "repoId": "api-service",
                "owner": "api-worker",
                "access": "write-scoped",
                "paths": ["src/api", "tests/api"],
            },
            {
                "id": "docs",
                "repoId": "docs",
                "owner": "docs-reviewer",
                "access": "read-only",
                "paths": ["architecture"],
            },
        ],
        "specification": {
            "tier": "S2",
            "status": "FROZEN",
            "requirements": [{"id": "REQ-1", "description": "Coordinate repositories."}],
        },
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Reference validation",
                "owner": "api-worker",
                "dependsOn": [],
                "writes": ["src/team"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {
            "criteria": [
                {"id": "AC-1", "requirementIds": ["REQ-1"], "evidenceIds": ["EV-1"]},
            ],
            "evidence": [{"id": "EV-1", "description": "Tests."}],
        },
    }


if __name__ == "__main__":
    unittest.main()
