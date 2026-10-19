from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_implementation_audit_report
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, write_json_create
from agent_lifecycle.workflow import accept_task, commit_task_result, rework_task, start_task
from agent_lifecycle.workflow.reviews import validate_task_review
from agent_lifecycle.workflow.run import run_workflow_step


class TaskAcceptanceImplementationAuditGateTests(unittest.TestCase):
    def test_native_task_consumer_refuses_stronger_claims_before_committing(self) -> None:
        claims = [
            ({}, True),
            ({"reviewerProvenance": {"guarantee": "DECLARED", "attestation": None}}, True),
            ({"reviewerProvenance": {"guarantee": "ATTESTED", "attestation": None}}, False),
            ({"reviewerProvenance": {}}, False),
            ({"provenanceValidation": {"status": "PASS", "guarantee": "ATTESTED"}}, False),
        ]
        for claim, allowed in claims:
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=False)
                start_task(
                    bundle["statePath"],
                    task_id="WS-01",
                    operation_id="start",
                    expected_revision=1,
                    source_revision="source",
                    reason="unit consumer",
                )
                result_path, review_path = _write_result_review(root, bundle)
                commit_task_result(
                    bundle["statePath"],
                    task_id="WS-01",
                    operation_id="result",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="unit consumer result",
                )
                review = json.loads((root / review_path).read_text())
                review.update(claim)
                (root / review_path).write_bytes(canonical_bytes(review) + b"\n")
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                if allowed:
                    accept_task(
                        bundle["statePath"],
                        task_id="WS-01",
                        operation_id="accept",
                        expected_revision=3,
                        review_path=review_path,
                        reason="unit ordinary acceptance",
                    )
                    self.assertEqual(json.loads(bundle["statePath"].read_text())["tasks"][0]["status"], "ACCEPTED")
                else:
                    with self.assertRaises(LifecycleError) as caught:
                        accept_task(
                            bundle["statePath"],
                            task_id="WS-01",
                            operation_id="accept",
                            expected_revision=3,
                            review_path=review_path,
                            reason="unit unsupported claim refusal",
                        )
                    self.assertEqual(caught.exception.code, "review-provenance-invalid")
                    self.assertEqual(
                        before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    )

    def test_task_review_rejects_every_open_medium_plus_severity(self) -> None:
        state = {"runId": "run", "planDigest": "a" * 64}
        task = {
            "id": "WS-01",
            "attempt": 1,
            "result": {"sha256": "b" * 64},
            "packet": {"sha256": "c" * 64},
        }
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            review = {
                "schemaVersion": "agent-task-review.v2",
                "runId": "run",
                "taskId": "WS-01",
                "attempt": 1,
                "planDigest": "a" * 64,
                "resultHash": "b" * 64,
                "taskPacketHash": "c" * 64,
                "reviewer": {"independent": True},
                "verdict": "ACCEPTED",
                "findings": [{"id": severity, "status": "open", "severity": severity}],
            }
            with self.subTest(severity=severity), self.assertRaises(LifecycleError) as raised:
                validate_task_review(state, task, review)
            self.assertEqual(raised.exception.code, "task-review-open-findings")

    def test_task_acceptance_requires_accepted_implementation_audit_when_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            start_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    bundle["statePath"],
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "implementation-audit-required")
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )
            write_json_create(root / "work/WS-01/attempt-1/implementation-audit.json", report)

            payload = accept_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="accept-op",
                expected_revision=3,
                review_path=review_path,
                implementation_audit_path="work/WS-01/attempt-1/implementation-audit.json",
                reason="accepted",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            stored = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["implementationAuditReport"]["verdict"], "ACCEPTED")

    def test_managed_runner_blocks_when_verifying_task_lacks_required_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="STEP_REVIEW", task_status="VERIFYING", audit_required=True)

            receipt = run_workflow_step(
                state_path=bundle["statePath"],
                manifest_path=bundle["manifestPath"],
                operation_id="managed-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["nextAction"]["type"], "blocked")
            self.assertIn("implementation-audit-required", {item["code"] for item in receipt["blockers"]})

    def test_manifest_audit_policy_does_not_replace_independent_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            start_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle, reviewer_id="worker")
            commit_task_result(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    bundle["statePath"],
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="self review is not authority",
                )

            self.assertEqual(raised.exception.code, "task-review-self-certification")

    def test_task_rework_accepts_accepted_review_with_rework_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            state = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            state["budgets"] = {"remediationMode": "ask", "maxTaskAttempts": 2, "maxParallelTasks": 1}
            Path(bundle["statePath"]).write_text(json.dumps(state), encoding="utf-8")
            start_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
                changed_paths=[],
            )
            self.assertEqual(report["verdict"], "REWORK")
            finding_id = next(
                item["id"] for item in report["findings"] if item["code"] == "implementation-changed-paths-stale"
            )
            audit_path = "work/WS-01/attempt-1/implementation-audit.json"
            write_json_create(root / audit_path, report)

            payload = rework_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="rework-op",
                expected_revision=3,
                source_revision="source",
                review_path=review_path,
                implementation_audit_path=audit_path,
                finding_ids=[finding_id],
                reason="audit requested rework",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "REWORK")


def _write_bundle(
    root: Path,
    *,
    phase: str,
    task_status: str,
    audit_required: bool,
) -> dict[str, Path | str]:
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package", "artifactRoot": "work"},
        "specification": {
            "tier": "S1",
            "requirements": [{"id": "REQ-FOUNDATION", "description": "Single-owner local audit fixture"}],
        },
        "acceptance": {
            "criteria": [
                {"id": "AC-FOUNDATION", "requirementIds": ["REQ-FOUNDATION"], "evidenceIds": ["EV-FOUNDATION"]}
            ],
        },
        "validation": {"commands": ["python -m unittest"], "extraEvidence": ["EV-FOUNDATION"]},
        "releaseImpact": "Non-release single-owner unit fixture.",
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "implementationAudit": {"required": audit_required, "finalRequired": False},
        "workstreams": [
            {
                "id": "WS-01",
                "owner": "worker",
                "dependsOn": [],
                "writes": ["src/example.py"],
            }
        ],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (manifest_path.parent / "plan.lock.json").write_text(
        json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
        encoding="utf-8",
    )
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
                "attempt": 0 if task_status == "READY" else 1,
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
            }
        ],
        "eventLog": "events.jsonl",
    }
    if task_status == "VERIFYING":
        state["tasks"][0]["result"] = {"path": "work/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10}
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"manifestPath": manifest_path, "statePath": state_path, "planDigest": digest}


def _write_result_review(
    root: Path,
    bundle: dict[str, Path | str],
    *,
    reviewer_id: str = "reviewer",
) -> tuple[str, str]:
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
        "itemOutcomes": [
            {
                "plannedItemId": "REQ-01",
                "status": "COMPLETE",
                "changedFiles": ["src/example.py"],
                "commandIds": ["unit"],
            }
        ],
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
        "reviewer": {"id": reviewer_id, "independent": True, "surface": "test", "runId": "review-run"},
        "reviewedAt": "2026-08-03T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [{"plannedItemId": "REQ-01", "verdict": "ACCEPTED", "findingIds": []}],
        "acceptanceChecks": [],
        "findings": [],
        "summary": "accepted",
    }
    review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / review_path, review)
    return result_path, review_path


class CrossAttemptItemOutcomeTests(unittest.TestCase):
    def archived_fixture(self, root, *, authorized=False):
        from agent_lifecycle.workflow.artifacts import artifact_identity
        from tests.workflow.helpers import _review

        state, task, current = self.fixture(root)
        previous = {
            "id": task["id"],
            "attempt": 1,
            "packet": task["packet"],
            "attemptHistory": [],
            "result": task["attemptHistory"][0]["result"],
            "status": "VERIFYING",
        }
        snapshot = {
            "runId": "run",
            "planRevision": 1,
            "planDigest": state["planDigest"],
            "sourceRevision": "source",
            "tasks": [previous],
        }
        task["attemptHistory"] = []
        state["priorSnapshots"] = [snapshot]
        state["planRevision"] = 2
        state["planDigest"] = current["planDigest"] = "9" * 64
        current["itemOutcomes"][0]["plannedItemId"] = "NEW-SCOPE"
        if authorized:
            review = _review(attempt=1, result_hash=previous["result"]["sha256"])
            review["verdict"] = "CONTRACT_CHANGE"
            request = {
                "reason": "independently reviewed replacement scope",
                "excludedPlannedItemIds": ["REQ-FOUNDATION"],
            }
            review["contractChangeRequest"] = request
            write_json_create(root / "scope-review.json", review)
            previous.update(
                status="CONTRACT_CHANGE",
                review=artifact_identity(root, "scope-review.json", review),
                contractChangeRequest={**request, "scope": "plan", "recoveryRoute": "adopt-plan", "taskId": task["id"]},
            )
        return state, task, current, previous

    def test_plan_adoption_cannot_hide_unfinished_ids_in_archived_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, task, current, _ = self.archived_fixture(root)
            with self.assertRaises(LifecycleError) as caught:
                self.validate(root, state, task, current)
            self.assertEqual(caught.exception.code, "task-result-unresolved-item-omitted")
            current["contractChangeRequest"] = {"reason": "worker cannot authorize omission"}
            with self.assertRaises(LifecycleError) as caught:
                self.validate(root, state, task, current, nonaccepting=True)
            self.assertEqual(caught.exception.code, "task-result-unresolved-item-omitted")
            current.pop("contractChangeRequest")
            current["itemOutcomes"][0]["plannedItemId"] = "REQ-FOUNDATION"
            self.validate(root, state, task, current)

    def test_exact_independent_contract_change_accounts_for_excluded_archived_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, task, current, _ = self.archived_fixture(root, authorized=True)
            prior = (root / "prior.json").read_bytes()
            self.validate(root, state, task, current)
            self.assertEqual((root / "prior.json").read_bytes(), prior)

    def test_exclusion_cannot_be_replayed_substituted_or_self_authorized(self) -> None:
        from agent_lifecycle.contracts import read_json_object
        from agent_lifecycle.workflow.artifacts import artifact_identity

        for variant in ("unreviewed-status", "same-revision", "substituted-ids", "changed-review", "self-review"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state, task, current, previous = self.archived_fixture(root, authorized=True)
                if variant == "unreviewed-status":
                    previous["status"] = "VERIFYING"
                elif variant == "same-revision":
                    state["planRevision"] = 1
                elif variant == "substituted-ids":
                    previous["contractChangeRequest"]["excludedPlannedItemIds"] = ["OTHER"]
                elif variant == "changed-review":
                    (root / "scope-review.json").write_bytes((root / "scope-review.json").read_bytes() + b" ")
                else:
                    review = read_json_object(root / "scope-review.json")
                    review["reviewer"]["id"] = "worker"
                    (root / "scope-review.json").write_bytes(canonical_bytes(review) + b"\n")
                    previous["review"] = artifact_identity(root, "scope-review.json", review)
                with self.assertRaises(LifecycleError):
                    self.validate(root, state, task, current)

    def fixture(self, root):
        from agent_lifecycle.workflow.artifacts import artifact_identity
        from tests.workflow.helpers import _result

        prior = _result(attempt=1)
        prior["itemOutcomes"][0]["status"] = "DEFERRED"
        prior["blocker"] = {
            "code": "unavailable",
            "reason": "dependency unavailable",
            "scope": "task",
            "recoveryRoute": "task-review",
            "taskId": "WS-01",
            "attempt": 1,
        }
        write_json_create(root / "prior.json", prior)
        current = _result(attempt=2)
        current["commands"] = [
            {"id": "verification", "command": ["python", "-m", "unittest"], "status": "PASS", "exitCode": 0}
        ]
        current["itemOutcomes"][0]["commandIds"] = ["verification"]
        state = {
            "schemaVersion": "agent-workflow-state.v4",
            "runId": "run",
            "planDigest": "0" * 64,
            "sourceRevision": "source",
        }
        task = {
            "id": "WS-01",
            "attempt": 2,
            "packet": {"sha256": "1" * 64},
            "attemptHistory": [{"attempt": 1, "result": artifact_identity(root, "prior.json", prior)}],
        }
        return state, task, current

    def validate(self, root, state, task, result, *, nonaccepting=False):
        from agent_lifecycle.workflow.reviews import validate_task_result

        return validate_task_result(
            state,
            task,
            result,
            {"sha256": canonical_digest(result)},
            repository_root=root,
            allow_non_accepting_outcome=nonaccepting,
        )

    def test_prior_deferred_item_must_resolve_with_selected_passing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, task, result = self.fixture(root)
            before = (root / "prior.json").read_bytes()
            self.validate(root, state, task, result)
            self.assertEqual((root / "prior.json").read_bytes(), before)
            result["itemOutcomes"][0]["commandIds"] = []
            with self.assertRaises(LifecycleError) as caught:
                self.validate(root, state, task, result)
            self.assertEqual(caught.exception.code, "task-result-item-resolution-unproven")

    def test_omitted_identity_unauthorized_deferral_and_duplicate_ids_refuse(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, task, original = self.fixture(root)
            for variant in ("omit", "defer", "duplicate"):
                result = deepcopy(original)
                if variant == "omit":
                    result["itemOutcomes"][0]["plannedItemId"] = "replacement"
                elif variant == "defer":
                    result["itemOutcomes"][0]["status"] = "DEFERRED"
                else:
                    result["itemOutcomes"].append(deepcopy(result["itemOutcomes"][0]))
                with self.subTest(variant=variant), self.assertRaises(LifecycleError):
                    self.validate(root, state, task, result)

    def test_deferred_remains_nonaccepting_and_tampered_history_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, task, result = self.fixture(root)
            result["itemOutcomes"][0]["status"] = "DEFERRED"
            result["blocker"] = {
                "code": "still-unavailable",
                "reason": "still pending",
                "scope": "task",
                "recoveryRoute": "task-review",
                "taskId": "WS-01",
                "attempt": 2,
            }
            self.validate(root, state, task, result, nonaccepting=True)
            (root / "prior.json").write_bytes((root / "prior.json").read_bytes() + b" ")
            with self.assertRaises(LifecycleError):
                self.validate(root, state, task, result, nonaccepting=True)


if __name__ == "__main__":
    unittest.main()
