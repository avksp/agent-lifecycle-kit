from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli, _write_state, write_json_create
except ImportError:
    from helpers import _run_cli, _write_state, write_json_create


class WorkflowRecoveryCommandTests(unittest.TestCase):
    def test_external_pause_and_resume_are_public_receipt_bound_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            code, payload = _run_cli(
                [
                    "workflow",
                    "external-pause",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "pause-cli",
                    "--expected-revision",
                    "1",
                    "--action-id",
                    "preview-deploy",
                    "--receipt",
                    "external/preview.json",
                    "--reason",
                    "wait for preview deployment",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")

            receipt = {
                "schemaVersion": "agent-external-action-receipt.v1",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "actionId": "preview-deploy",
                "status": "PASS",
                "evidenceIds": ["EV-PREVIEW"],
                "completedAt": "2026-08-24T00:00:00Z",
            }
            write_json_create(root / "external/preview.json", receipt)
            code, payload = _run_cli(
                [
                    "workflow",
                    "external-resume",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "resume-cli",
                    "--expected-revision",
                    "2",
                    "--receipt",
                    "external/preview.json",
                    "--reason",
                    "preview deployed",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "RUNNING")

    def test_final_audit_outcome_command_routes_blocked_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "FINAL_AUDIT"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = {
                "schemaVersion": "agent-final-candidate-audit.v1",
                "status": "FAIL",
                "semanticStatus": "BLOCKED",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "productionPromotionClaimed": False,
                "verifier": {"id": "final-auditor", "independent": True},
                "findings": [],
                "blocker": {
                    "externalAction": {
                        "actionId": "release-approval",
                        "expectedReceiptPath": "external/release-approval.json",
                    }
                },
            }
            write_json_create(root / "final/final-audit.json", audit)

            code, payload = _run_cli(
                [
                    "workflow",
                    "final-audit-outcome",
                    "--state",
                    str(state_path),
                    "--operation-id",
                    "final-outcome-cli",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--final-audit",
                    "final/final-audit.json",
                    "--verdict",
                    "BLOCKED",
                    "--reason",
                    "wait for external approval",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "WAITING_FOR_EXTERNAL_ACTION")
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")


class TechnicalReviewRecoveryTests(unittest.TestCase):
    def fixture(self, root, *, partial=False, exhausted=False):
        from datetime import UTC, datetime, timedelta

        from agent_lifecycle.contracts import write_json_create
        from agent_lifecycle.workflow import commit_task_result, migrate_workflow_state, start_task
        from agent_lifecycle.workflow.state import load_state, write_state_replace
        from tests.workflow.helpers import _result
        from tests.workflow.helpers import _write_state as workflow_state

        path = workflow_state(root, phase="RUNNING")
        state = load_state(path)
        state["budgets"].update({"maxTaskWallSeconds": 300, "maxReportedTokensPerTask": 17 if exhausted else 1000})
        state["runDeadlineAt"] = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        state["authorization"]["expiresAt"] = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        write_state_replace(path, state)
        migrate_workflow_state(path, operation_id="migrate", expected_revision=1, source_revision="source")
        start_task(
            path, task_id="WS-01", operation_id="start", expected_revision=2, source_revision="source", reason="unit"
        )
        state = load_state(path)
        result = _result(attempt=1)
        if partial:
            result["itemOutcomes"][0]["status"] = "INCOMPLETE"
            result["blocker"] = {
                "code": "partial",
                "reason": "valid partial result",
                "scope": "task",
                "recoveryRoute": "task-review",
                "taskId": "WS-01",
                "attempt": 1,
            }
        result_path = state["tasks"][0]["artifactPaths"]["result"].replace("{attempt}", "1")
        write_json_create(root / result_path, result)
        commit_task_result(
            path,
            task_id="WS-01",
            operation_id="result",
            expected_revision=3,
            source_revision="source",
            result_path=result_path,
            reason="unit candidate",
        )
        state = load_state(path)
        state["tasks"][0]["usageTotals"] = {"reportedTokens": 17, "toolCalls": 2, "iterations": 0}
        write_state_replace(path, state)
        return path, result_path

    def pause(self, path, code="review-response-missing"):
        result, payload = _run_cli(
            [
                "workflow",
                "block",
                "--state",
                str(path),
                "--operation-id",
                "interruption",
                "--expected-revision",
                "4",
                "--blocker-code",
                code,
                "--review-task",
                "WS-01",
                "--reason",
                "delivery failed",
            ]
        )
        self.assertEqual(result, 0, payload)

    def resume(self, path, *, revision=5):
        return _run_cli(
            [
                "workflow",
                "resolve",
                "--state",
                str(path),
                "--operation-id",
                "resume-review",
                "--expected-revision",
                str(revision),
                "--reason",
                "same-subject technical recovery",
            ]
        )

    def test_missing_truncated_and_partial_review_recover_without_new_attempt(self) -> None:
        from agent_lifecycle.workflow.state import load_state, write_state_replace

        for code, partial in (("review-response-missing", False), ("review-response-truncated", True)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, result_path = self.fixture(root, partial=partial)
                original, result_bytes = load_state(path), (root / result_path).read_bytes()
                self.pause(path, code)
                paused = load_state(path)
                self.assertEqual(paused["blocker"]["scope"], "run")
                self.assertNotIn("reviewer", paused["blocker"]["reviewSubject"])
                # A late declared usage increment is retained; a recovery never restores old counters.
                paused["tasks"][0]["usageTotals"]["reportedTokens"] = 18
                write_state_replace(path, paused)
                exit_code, payload = self.resume(path)
                self.assertEqual(exit_code, 0, payload)
                final = load_state(path)
                self.assertEqual(final["phase"], "RUNNING")
                self.assertEqual(final["tasks"][0]["status"], "VERIFYING")
                for key in ("attempt", "attemptHistory", "attemptDeadlineAt", "remediationFindingIds", "result"):
                    self.assertEqual(final["tasks"][0].get(key), original["tasks"][0].get(key))
                self.assertEqual(final["tasks"][0]["usageTotals"]["reportedTokens"], 18)
                self.assertEqual(final["runDeadlineAt"], original["runDeadlineAt"])
                self.assertEqual(final["planDigest"], original["planDigest"])
                self.assertEqual((root / result_path).read_bytes(), result_bytes)
                review = final["tasks"][0]["artifactPaths"]["review"].replace("{attempt}", "1")
                self.assertFalse((root / review).exists())
                before = path.read_bytes(), (root / "events.jsonl").read_bytes()
                self.assertNotEqual(self.resume(path, revision=6)[0], 0)
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_revocation_expiry_source_tampering_counter_reset_and_capacity_refuse(self) -> None:
        from datetime import UTC, datetime, timedelta

        from agent_lifecycle.workflow.state import load_state, write_state_replace

        for variant in (
            "revoked",
            "expired",
            "source",
            "result",
            "packet",
            "plan-revision",
            "usage-reset",
            "capacity",
            "revision",
        ):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, result_path = self.fixture(root, exhausted=variant == "capacity")
                self.pause(path)
                state = load_state(path)
                if variant == "revoked":
                    state["authorization"]["granted"] = False
                elif variant == "expired":
                    state["authorization"]["expiresAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
                elif variant == "source":
                    state["sourceRevision"] = "changed"
                elif variant == "result":
                    (root / result_path).write_bytes((root / result_path).read_bytes() + b" ")
                elif variant == "packet":
                    state["tasks"][0]["packet"]["sha256"] = "f" * 64
                elif variant == "plan-revision":
                    state["planRevision"] += 1
                elif variant == "usage-reset":
                    state["tasks"][0]["usageTotals"]["reportedTokens"] = 0
                write_state_replace(path, state)
                before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                self.assertNotEqual(self.resume(path, revision=4 if variant == "revision" else 5)[0], 0)
                self.assertEqual(
                    before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                )

    def test_expired_attempt_deadline_is_not_extended(self) -> None:
        from datetime import datetime, timedelta
        from unittest.mock import patch

        from agent_lifecycle.workflow.state import load_state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _ = self.fixture(root)
            self.pause(path)
            deadline = datetime.fromisoformat(load_state(path)["tasks"][0]["attemptDeadlineAt"].replace("Z", "+00:00"))
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            with patch("agent_lifecycle.workflow.run_transitions.datetime") as clock:
                clock.fromisoformat.side_effect = datetime.fromisoformat
                clock.now.return_value = deadline + timedelta(seconds=1)
                code, payload = self.resume(path)
            self.assertNotEqual(code, 0)
            self.assertEqual(payload["code"], "review-recovery-deadline-expired")
            self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_unknown_usage_is_not_zero_and_run_capacity_is_enforced(self) -> None:
        from agent_lifecycle.workflow.state import load_state, write_state_replace

        for variant, expected in (
            ("unknown", "review-recovery-budget-unavailable"),
            ("run-cap", "review-recovery-budget-exhausted"),
        ):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                path, _ = self.fixture(Path(tmp))
                state = load_state(path)
                if variant == "unknown":
                    state["tasks"][0]["usageTotals"].pop("reportedTokens")
                else:
                    state["budgets"]["maxReportedTokensPerRun"] = 17
                write_state_replace(path, state)
                self.pause(path)
                before = path.read_bytes(), (Path(tmp) / "events.jsonl").read_bytes()
                code, payload = self.resume(path)
                self.assertNotEqual(code, 0)
                self.assertEqual(payload["code"], expected)
                self.assertEqual((path.read_bytes(), (Path(tmp) / "events.jsonl").read_bytes()), before)

    def test_semantic_rework_cannot_be_relabelled_as_technical_interruption(self) -> None:
        from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
        from agent_lifecycle.workflow import block_run, rework_task
        from agent_lifecycle.workflow.state import load_state, write_state_replace
        from tests.workflow.helpers import _review

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, result_path = self.fixture(root)
            state = load_state(path)
            state["budgets"]["maxTaskAttempts"] = 2
            state["budgets"]["remediationMode"] = "ask"
            write_state_replace(path, state)
            result = read_json_object(root / result_path)
            review = _review(attempt=1, result_hash=canonical_digest(result), plan_digest=state["planDigest"])
            review["verdict"] = "REWORK"
            review["findings"] = [{"id": "F-SEMANTIC", "severity": "HIGH", "status": "open", "message": "repair"}]
            review_path = state["tasks"][0]["artifactPaths"]["review"].replace("{attempt}", "1")
            write_json_create(root / review_path, review)
            rework_task(
                path,
                task_id="WS-01",
                operation_id="semantic-rework",
                expected_revision=4,
                source_revision="source",
                review_path=review_path,
                finding_ids=["F-SEMANTIC"],
                reason="independent unit review requires repair",
            )
            before = path.read_bytes(), (root / "events.jsonl").read_bytes(), (root / review_path).read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                block_run(
                    path,
                    operation_id="relabel",
                    expected_revision=5,
                    blocker_code="review-response-missing",
                    review_task_id="WS-01",
                    reason="must not erase semantic finding",
                )
            self.assertEqual(caught.exception.code, "review-interruption-subject-invalid")
            self.assertEqual(
                (path.read_bytes(), (root / "events.jsonl").read_bytes(), (root / review_path).read_bytes()), before
            )
            self.assertEqual(load_state(path)["tasks"][0]["remediationFindingIds"], ["F-SEMANTIC"])


if __name__ == "__main__":
    unittest.main()
