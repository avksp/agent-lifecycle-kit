"""Native disposable authority paths; no release or live execution qualification."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.workflow_state_authority import read_workflow_authority
from agent_lifecycle.contracts.workflow_storage import (
    iter_historical_snapshots,
    persist_storage,
    prepare_storage,
    task_evidence,
)
from agent_lifecycle.workflow.initialization import migrate_workflow_state
from agent_lifecycle.workflow.plan_adoption import _build_tasks, _replace_plan_state
from tests.contracts.test_review_remedy_authority import authority, required_state
from tests.review_mesh.test_remediation import config
from tests.workflow.test_state_storage import state_fixture


class ReviewRemedyWorkflowAuthorityTests(unittest.TestCase):
    def test_v6_compaction_read_and_history_never_demote(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = state_fixture()
            state.update(
                schemaVersion="agent-workflow-state.v6",
                reviewMesh=config(),
                reviewRemedyAuthority=authority(),
                stateRevision=1,
                phase="RUNNING",
                eventLog="events.jsonl",
            )
            for task in state["tasks"]:
                task["reviewMesh"] = deepcopy(state["reviewMesh"])
            state["priorSnapshots"][0].update(reviewMesh=config(), reviewRemedyAuthority=authority())
            prepared = prepare_storage(state, storage_root="state.json.storage")
            self.assertEqual(prepared.state["schemaVersion"], "agent-workflow-state.v6")
            persist_storage(root, prepared)
            path = root / "state.json"
            path.write_bytes(canonical_bytes(prepared.state) + b"\n")
            loaded = read_workflow_authority(path)
            self.assertEqual(loaded["reviewRemedyAuthority"], authority())
            snapshots = list(iter_historical_snapshots(root, loaded))
            self.assertEqual(snapshots[0]["reviewRemedyAuthority"], authority())
            historical = snapshots[0]["tasks"][0]
            original = state["priorSnapshots"][0]["tasks"][0]
            for field in ("ownershipReceipt", "resultChangeSetEvidence"):
                self.assertEqual(task_evidence(root, loaded, historical, field), original[field])
            self.assertEqual(historical["result"], original["result"])
            self.assertEqual(prepare_storage(loaded).state["schemaVersion"], "agent-workflow-state.v6")

    def test_required_policy_is_materialized_and_override_erasure_refuses(self):
        manifest = {
            "reviewMesh": config(),
            "reviewRemedyAuthority": authority(),
            "package": {"artifactRoot": "work"},
            "workstreams": [{"id": "T", "writes": ["src"], "reviewer": "reviewer"}],
        }
        tasks = _build_tasks(manifest, {})
        self.assertEqual(tasks[0]["reviewMesh"], config())
        manifest["workstreams"][0]["reviewMesh"] = {"required": False}
        with self.assertRaises(LifecycleError):
            _build_tasks(manifest, {})

    def test_required_migration_downgrade_and_unrestricted_target_refuse_before_commit(self):
        state = required_state()
        state["sourceRevision"] = "source"
        with (
            patch("agent_lifecycle.workflow.initialization.load_for_update", return_value=state),
            patch("agent_lifecycle.workflow.initialization.commit_state") as commit,
        ):
            for target in [
                "agent-workflow-state.v3",
                "agent-workflow-state.v4",
                "agent-workflow-state.v5",
                "agent-workflow-state.v6",
            ]:
                with self.assertRaises(LifecycleError):
                    migrate_workflow_state.__wrapped__(
                        Path("absent.json"),
                        operation_id="migration",
                        expected_revision=1,
                        source_revision="source",
                        target_schema=target,
                    )
            commit.assert_not_called()

    def test_v4_adoption_promotion_preserves_clocks_and_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = required_state()
            state["schemaVersion"] = "agent-workflow-state.v4"
            state.pop("storage")
            state.pop("reviewRemedyAuthority")
            state.pop("reviewMesh")
            state.update(runStartedAt="2026-11-10T09:36:14Z", packageRoot=".", priorSnapshots=[])
            manifest = {
                "reviewMesh": config(),
                "reviewRemedyAuthority": authority(),
                "orchestration": {},
                "planReview": {"report": "review.json"},
                "package": {"planArtifactRoot": "plans"},
            }
            with patch("agent_lifecycle.workflow.plan_adoption._last_plan_review", return_value={}):
                _replace_plan_state(
                    state,
                    state_path=root / "state.json",
                    manifest_path=root / "plans/plan.manifest.json",
                    manifest=manifest,
                    digest="d" * 64,
                    revision=2,
                    root=root,
                    source_revision="s",
                    start_mode="approval-required",
                    authorized_by=None,
                    packet_set={},
                    tasks=[],
                )
            self.assertEqual(state["schemaVersion"], "agent-workflow-state.v6")
            self.assertEqual(state["runStartedAt"], "2026-11-10T09:36:14Z")
            self.assertFalse(state["authorization"]["granted"])
