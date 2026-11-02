"""Canonical decision preparation on synthetic, nonproduction authorities."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from agent_lifecycle.cli.plan_lock_commands import prepare_freeze_candidate
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
from agent_lifecycle.workflow import adopt_plan, start_execution, start_task
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from tests.cli.helpers import _run_cli
from tests.cli.test_artifact_authoring_commands import _write_draft
from tests.workflow.test_research_preflight import _declaration, _record, _seal


def _research_draft(root: Path, *, pretty_record: bool = False) -> tuple[Path, dict]:
    path, manifest = _write_draft(root)
    manifest["author"] = {"id": "fixture-author", "runId": "fixture-author-run"}
    manifest["baseRevision"] = {"ref": "fixture", "sha": "f" * 40}
    manifest["packageIntegrity"].update(inventorySource="planFiles", undeclaredTopLevelFiles="reject")
    manifest["specification"]["source"] = "plan/acceptance-criteria.md"
    manifest["planReview"] = {
        "required": True,
        "report": "plan/plan-review.json",
        "reviewedRevision": manifest["planRevision"],
        "verdict": "PENDING",
    }
    workstream = manifest["workstreams"][0]
    workstream.update(
        owner="worker",
        title="Research fixture",
        reviewer="fixture-reviewer",
        plannedItems=["REQ-01"],
        acceptanceIds=["AC-01"],
        contextRefs=["plan/acceptance-criteria.md"],
    )
    _, _, policy = _declaration("S1")
    policy["inputs"][0].update(
        path="acceptance-criteria.md",
        sha256=hashlib.sha256((root / "plan/acceptance-criteria.md").read_bytes()).hexdigest(),
    )
    workstream["decisionResearch"] = policy
    manifest["planFiles"] = sorted([*manifest["planFiles"], "plan/decision.json"])
    _seal(manifest, workstream)
    record = _record(policy)
    raw = json.dumps(record, indent=2).encode() + b"\n" if pretty_record else canonical_bytes(record) + b"\n"
    (root / "plan/decision.json").write_bytes(raw)
    policy["record"]["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_bytes(canonical_bytes(manifest) + b"\n")
    return path, manifest


def _prepare(root: Path, path: Path) -> tuple[Path, dict]:
    result = prepare_freeze_candidate(
        manifest_path=path.relative_to(root).as_posix(),
        output_path="candidates/research",
        repository_root=root,
    )
    candidate = root / result["candidateManifest"]
    return candidate, json.loads(candidate.read_bytes())


def _adopt_reviewed_fixture(root: Path, path: Path, manifest: dict) -> Path:
    """Real writers; reviewer declarations are explicitly UNIT_ONLY fixtures."""
    review = {
        "schemaVersion": "agent-plan-review.v1",
        "reviewId": "SYNTHETIC-UNIT-ONLY-REVIEW",
        "packageId": manifest["package"]["id"],
        "planRevision": manifest["planRevision"],
        "reviewedPlanHash": canonical_digest(manifest),
        "reviewer": {
            "id": "fixture-reviewer",
            "runId": "fixture-reviewer-run",
            "surface": "unit-fixture",
            "independent": True,
        },
        "fullReview": True,
        "verdict": "READY_TO_FREEZE",
        "findings": [],
    }
    review_raw = canonical_bytes(review) + b"\n"
    review_path = manifest["planReview"]["report"]
    (root / review_path).write_bytes(review_raw)
    lock = build_reviewed_plan_lock_v2(
        manifest,
        review,
        review_path=review_path,
        review_sha256=hashlib.sha256(review_raw).hexdigest(),
        repository_root=root,
    )
    (path.parent / "plan.lock.json").write_bytes(canonical_bytes(lock) + b"\n")
    with chdir(root):
        code, payload = _run_cli(["task", "compile", "--manifest", str(path), "--write"])
    if code != 0:
        raise AssertionError(payload)
    state = root / "run.state.json"
    initialize_workflow_state(state, run_id="synthetic-research", package_id=manifest["package"]["id"])
    adopt_plan(
        state,
        manifest_path=path,
        operation_id="fixture-adopt",
        expected_revision=1,
        source_revision="f" * 40,
        reset_tasks=True,
        start_mode="auto-after-freeze",
        authorized_by="UNIT_ONLY_FIXTURE",
    )
    start_execution(
        state,
        operation_id="fixture-run",
        expected_revision=2,
        source_revision="f" * 40,
        reason="synthetic fixture",
    )
    return state


class DecisionResearchFreezeTests(unittest.TestCase):
    def test_real_prepare_lock_v4_adoption_and_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path, original = _research_draft(root)
            before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
            candidate_path, candidate = _prepare(root, path)
            workstream = candidate["workstreams"][0]
            policy = workstream["decisionResearch"]
            self.assertEqual(workstream["contextRefs"], ["candidates/research/acceptance-criteria.md"])
            self.assertEqual(policy, original["workstreams"][0]["decisionResearch"])
            for item in [*policy["inputs"], policy["record"]]:
                self.assertEqual(
                    hashlib.sha256((candidate_path.parent / item["path"]).read_bytes()).hexdigest(),
                    item["sha256"],
                )
            self.assertEqual(before, {p.name: p.read_bytes() for p in path.parent.iterdir()})
            self.assertFalse((candidate_path.parent / "plan-review.json").exists())
            self.assertFalse((candidate_path.parent / "plan.lock.json").exists())
            state = _adopt_reviewed_fixture(root, candidate_path, candidate)
            start_task(
                state,
                task_id="WS-01",
                operation_id="fixture-task",
                expected_revision=3,
                source_revision="f" * 40,
                reason="synthetic fixture",
            )
            current = json.loads(state.read_bytes())
            self.assertEqual(current["schemaVersion"], "agent-workflow-state.v4")
            self.assertEqual(current["tasks"][0]["status"], "RUNNING")

    def test_legacy_opt_out_references_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path, manifest = _write_draft(root)
            manifest["workstreams"][0]["contextRefs"] = ["plan/acceptance-criteria.md"]
            path.write_bytes(canonical_bytes(manifest) + b"\n")
            _, candidate = _prepare(root, path)
            self.assertEqual(candidate["workstreams"], manifest["workstreams"])
            self.assertNotIn("decisionResearch", candidate["workstreams"][0])

    def test_changed_json_bytes_remain_stale_without_hash_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path, _ = _research_draft(root, pretty_record=True)
            candidate_path, candidate = _prepare(root, path)
            state = _adopt_reviewed_fixture(root, candidate_path, candidate)
            before = state.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                start_task(
                    state,
                    task_id="WS-01",
                    operation_id="fixture-stale",
                    expected_revision=3,
                    source_revision="f" * 40,
                    reason="synthetic fixture",
                )
            self.assertEqual(caught.exception.code, "decision-research-input-stale")
            self.assertEqual((state.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_invalid_research_still_leaves_no_candidate_authority(self) -> None:
        for mode in ("scope", "partial"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                path, manifest = _research_draft(root)
                if mode == "scope":
                    manifest["workstreams"][0]["decisionResearch"]["scope"] = "LIVE_WORKSPACE"
                else:
                    manifest["workstreams"][0]["decisionResearch"] = None
                path.write_bytes(canonical_bytes(manifest) + b"\n")
                before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
                with self.assertRaises(LifecycleError):
                    _prepare(root, path)
                self.assertFalse((root / "candidates").exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in path.parent.iterdir()})


if __name__ == "__main__":
    unittest.main()
