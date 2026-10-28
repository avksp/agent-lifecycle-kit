"""Renewal fixtures use synthetic identities, never release reviewers."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.audit import build_implementation_audit_report
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, write_json_create
from agent_lifecycle.contracts.workflow_authorization_schemas import (
    WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT,
    authorization_renewal_bindings,
)
from agent_lifecycle.workflow import (
    apply_final_audit_outcome,
    apply_task_review_outcome,
    authorize_execution,
    commit_task_result,
    finalize_run,
    renew_execution_authorization,
    start_execution,
    start_task,
)
from agent_lifecycle.workflow.initialization import migrate_workflow_state
from agent_lifecycle.workflow.operation_kernel import load_for_update, observe_workflow_writes
from agent_lifecycle.workflow.state import load_state
from tests.workflow.helpers import _final_audit
from tests.workflow.test_task_acceptance_audit_gate import _write_bundle, _write_result_review


class FixtureTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2000, 1, 1, tzinfo=UTC).astimezone(tz or UTC)


def save(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


def seal(value):
    body = {key: item for key, item in value.items() if key != "receiptDigest"}
    return {**body, "receiptDigest": canonical_digest(body)}


def build_fixture(root, version="v4"):
    """Actually consume an initial grant under a historical fixture clock."""
    bundle = _write_bundle(root, phase="AWAITING_AUTHORIZATION", task_status="READY", audit_required=True)
    path = bundle["statePath"]
    state = json.loads(path.read_bytes())
    state.update(
        schemaVersion="agent-workflow-state.v4",
        stateRevision=1,
        packageRoot=".",
        startMode="approval-required",
        operationLedger={},
        blocker=None,
        authorization={"required": True, "granted": False},
        budgets={"maxTaskAttempts": 2, "remediationMode": "ask", "maxParallelTasks": 1},
        runStartedAt="2000-01-01T00:00:00Z",
        runDeadlineAt="2001-01-01T00:00:00Z",
        expenses={"inputTokens": None, "outputTokens": None, "usd": None, "unknownHolds": ["fixture-hold"]},
    )
    save(path, state)
    previous = seal(
        {
            "schemaVersion": "agent-workflow-authorization-receipt.v1",
            "status": "PASS",
            "decision": "ALLOW",
            **{
                key: state[key]
                for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision", "stateRevision")
            },
            "authorizationId": "fixture-old",
            "authorizedBy": "fixture-only-operator",
            "issuedAt": "1999-12-31T00:00:00Z",
            "expiresAt": "2001-01-01T00:00:00Z",
        }
    )
    write_json_create(root / "old-authorization.json", previous)
    with (
        patch("agent_lifecycle.contracts.workflow_authorization_schemas.datetime", FixtureTime),
        patch("agent_lifecycle.workflow.state.datetime", FixtureTime),
    ):
        authorize_execution(
            path,
            operation_id="fixture-authorize",
            expected_revision=1,
            source_revision="source",
            receipt_path="old-authorization.json",
            reason="historical fixture-only grant",
        )
        start_execution(
            path, operation_id="fixture-run-start", expected_revision=2, source_revision="source", reason="fixture"
        )
        start_task(
            path,
            task_id="WS-01",
            operation_id="fixture-task-start",
            expected_revision=3,
            source_revision="source",
            reason="fixture",
        )
        result, review = _write_result_review(root, bundle, reviewer_id="fixture-only-reviewer")
        commit_task_result(
            path,
            task_id="WS-01",
            operation_id="fixture-result",
            expected_revision=4,
            source_revision="source",
            result_path=result,
            reason="fixture",
        )
    state = load_state(path)
    state["tasks"][0].update(attemptStartedAt="2000-01-01T00:00:00Z", attemptDeadlineAt="2001-01-01T00:00:00Z")
    state["priorSnapshots"] = [
        {
            "runId": "run",
            "packageId": "package",
            "planRevision": 0,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "tasks": [],
            "financialRole": "HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING",
        }
    ]
    save(path, state)
    audit = build_implementation_audit_report(
        manifest_path=bundle["manifestPath"],
        state_path=path,
        task_id="WS-01",
        result_path=result,
        review_path=review,
        auditor_id="fixture-only-auditor",
    )
    if audit["status"] != "PASS" or audit["verdict"] != "ACCEPTED":
        raise AssertionError(audit)
    audit_path = "work/WS-01/attempt-1/implementation-audit.json"
    write_json_create(root / audit_path, audit)
    if version == "v5":
        migrate_workflow_state(
            path,
            operation_id="fixture-migrate",
            expected_revision=state["stateRevision"],
            source_revision="source",
            target_schema="agent-workflow-state.v5",
        )
    return path, review, audit_path


def renewal(state, *, number=1):
    return seal(
        {
            "schemaVersion": WORKFLOW_AUTHORIZATION_RENEWAL_RECEIPT,
            "status": "PASS",
            "decision": "ALLOW",
            **authorization_renewal_bindings(state),
            "authorizationId": f"fixture-renewal-{number}",
            "authorizedBy": "fixture-only-operator",
            "issuedAt": "2026-01-01T00:00:00Z",
            "expiresAt": f"209{number}-01-01T00:00:00Z",
            "purpose": "RENEW_SAME_RUN_AUTHORIZATION",
            "reason": "fixture-only same-run authorization",
        }
    )


def renew(path, receipt="renewal.json", operation="renew", expected=None):
    return renew_execution_authorization(
        path,
        operation_id=operation,
        expected_revision=expected or load_state(path)["stateRevision"],
        source_revision="source",
        receipt_path=receipt,
        reason="fixture-only renewal",
    )


def apply_review(path, review, audit):
    return apply_task_review_outcome(
        path,
        task_id="WS-01",
        operation_id="fixture-review-apply",
        expected_revision=load_state(path)["stateRevision"],
        source_revision="source",
        review_path=review,
        implementation_audit_path=audit,
        reason="fixture-only acceptance",
    )


def close_fixture(root, path, review, audit):
    before = load_state(path)
    apply_review(path, review, audit)
    accepted = load_state(path)
    final = _final_audit()
    final.update(
        runId="run",
        packageId="package",
        sourceRevision="source",
        planDigest=accepted["planDigest"],
        verifier={"id": "fixture-only-final-auditor", "independent": True},
    )
    final["completionSignal"].update(
        planDigest=accepted["planDigest"], verifier={"id": "fixture-only-final-auditor", "independent": True}
    )
    write_json_create(root / "final-audit.json", final)
    apply_final_audit_outcome(
        path,
        operation_id="fixture-final-outcome",
        expected_revision=accepted["stateRevision"],
        source_revision="source",
        final_audit_path="final-audit.json",
        verdict="ACCEPTED",
        reason="fixture-only",
    )
    payload = finalize_run(
        path,
        operation_id="fixture-finalize",
        expected_revision=load_state(path)["stateRevision"],
        source_revision="source",
        final_audit_path="final-audit.json",
        proof_path="final-proof.json",
        reason="fixture-only",
    )
    return {
        "phase": payload["phase"],
        "originalAttemptClocks": {key: before["tasks"][0][key] for key in ("attemptStartedAt", "attemptDeadlineAt")},
        "ordinaryAcceptanceRemovedLiveAttemptClocks": all(
            key not in accepted["tasks"][0] for key in ("attemptStartedAt", "attemptDeadlineAt")
        ),
    }


class RenewalWorkflowTests(unittest.TestCase):
    def test_expired_refusal_exact_renewal_and_ordinary_closeout_v4_v5(self):
        for version in ("v4", "v5"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, review, audit = build_fixture(root, version)
                before = load_state(path)
                state_bytes, event_bytes = path.read_bytes(), (root / "events.jsonl").read_bytes()
                old_receipt = (root / "old-authorization.json").read_bytes()
                with self.assertRaises(LifecycleError) as caught:
                    apply_review(path, review, audit)
                self.assertEqual(caught.exception.code, "authorization-expired")
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), (state_bytes, event_bytes))
                write_json_create(root / "renewal.json", renewal(before))
                observed = []
                with observe_workflow_writes(path, observed.append):
                    renew(path)
                after = load_state(path)
                for key in set(before) - {
                    "authorization",
                    "stateRevision",
                    "updatedAt",
                    "operationLedger",
                    "lastReason",
                }:
                    self.assertEqual(after[key], before[key], key)
                self.assertEqual(after["stateRevision"], before["stateRevision"] + 1)
                self.assertEqual(observed[-1][path.resolve()], path.read_bytes())
                self.assertEqual((root / "old-authorization.json").read_bytes(), old_receipt)
                result = close_fixture(root, path, review, audit)
                self.assertEqual(result["phase"], "COMPLETE")
                self.assertTrue(result["ordinaryAcceptanceRemovedLiveAttemptClocks"])

    def test_repeated_fresh_grants_preserve_chain_and_final_audit_renewal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, review, audit = build_fixture(root, "v5")
            for number in (1, 2):
                write_json_create(root / f"renewal-{number}.json", renewal(load_state(path), number=number))
                renew(path, f"renewal-{number}.json", f"renew-{number}")
            events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
            chain = [event["payload"] for event in events if event["eventType"] == "execution-authorization-renewed"]
            self.assertEqual(chain[0]["authorizationReceipt"], chain[1]["previousAuthorizationReceipt"])
            apply_review(path, review, audit)
            before = load_state(path)
            self.assertEqual(before["phase"], "FINAL_AUDIT")
            write_json_create(root / "renewal-3.json", renewal(before, number=3))
            renew(path, "renewal-3.json", "renew-3")
            self.assertEqual(load_state(path)["tasks"], before["tasks"])
            self.assertEqual(load_state(path)["phase"], "FINAL_AUDIT")

    def test_stale_replayed_foreign_and_widening_refuse_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root)
            before = load_state(path)
            variants = [
                {"stateRevision": 1},
                {"runId": "foreign"},
                {"packageId": "foreign"},
                {"planRevision": 2},
                {"sourceRevision": "foreign"},
                {"planDigest": "0" * 64},
                {"budgetsDigest": "0" * 64},
                {"originalClocksDigest": "0" * 64},
                {"taskSubjectDigest": "0" * 64},
                {"previousExpiresAt": "2002-01-01T00:00:00Z"},
                {"authorizationId": "fixture-old"},
                {"issuedAt": "2099-01-01T00:00:00Z"},
                {"expiresAt": "2001-01-01T00:00:00Z"},
                {"budgets": {"maxTaskAttempts": 999}},
                {"runDeadlineAt": "2099-01-01T00:00:00Z"},
            ]
            for index, change in enumerate(variants):
                with self.subTest(change=change):
                    write_json_create(root / f"bad-{index}.json", seal({**renewal(before), **change}))
                    bytes_before = path.read_bytes(), (root / "events.jsonl").read_bytes()
                    with self.assertRaises(LifecycleError):
                        renew(path, f"bad-{index}.json")
                    self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), bytes_before)
            write_json_create(root / "renewal.json", renewal(before))
            renew(path)
            for operation, expected in (("renew", None), ("other", before["stateRevision"]), ("other", None)):
                with self.subTest(operation=operation, expected=expected), self.assertRaises(LifecycleError):
                    renew(path, operation=operation, expected=expected)

    def test_missing_revoked_legacy_phase_and_history_refuse(self):
        changes = [
            lambda s: s.pop("authorization"),
            lambda s: s["authorization"].update(granted=False),
            lambda s: s["authorization"].update(revoked=True),
            lambda s: s["authorization"].pop("authorizationReceipt"),
            lambda s: s["authorization"].pop("expiresAt"),
            lambda s: s.update(phase="READY"),
            lambda s: s.update(phase="COMPLETE"),
            lambda s: s.update(startMode="plan-only"),
            lambda s: s["tasks"][0].pop("result"),
        ]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, _, _ = build_fixture(root)
                state = load_state(path)
                receipt = renewal(state)
                change(state)
                save(path, state)
                write_json_create(root / "renewal.json", receipt)
                before = path.read_bytes(), (root / "events.jsonl").read_bytes()
                with self.assertRaises(LifecycleError):
                    renew(path)
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root, "v5")
            write_json_create(root / "renewal.json", renewal(load_state(path)))
            snapshot = load_state(path)["priorSnapshots"][0]
            (root / "run.state.json.storage" / snapshot["path"]).unlink()
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError):
                renew(path)
            self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_consumed_receipt_identity_and_v5_operation_capacity_refuse(self):
        for mode in ("receipt", "capacity"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, _, _ = build_fixture(root, "v5")
                state = load_state(path)
                if mode == "capacity":
                    for number in range(2048 - len(state["operationLedger"])):
                        state["operationLedger"][f"fixture-old-op-{number}"] = {
                            "stateRevision": 1,
                            "eventType": "fixture-old",
                            "recordedAt": "2000-01-01T00:00:00Z",
                        }
                    save(path, state)
                else:
                    (root / "old-authorization.json").write_bytes((root / "old-authorization.json").read_bytes() + b" ")
                write_json_create(root / "renewal.json", renewal(state))
                before = path.read_bytes(), (root / "events.jsonl").read_bytes()
                with self.assertRaises(LifecycleError):
                    renew(path)
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    def test_prepublication_capacity_and_after_event_split_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root)
            state = load_state(path)
            # Readable v4 input whose larger renewal authority crosses the exact bound.
            state["padding"] = ""
            state["padding"] = "x" * (1_048_500 - len(canonical_bytes(state)))
            save(path, state)
            write_json_create(root / "renewal.json", renewal(state))
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                renew(path)
            self.assertIn(caught.exception.code, {"json-input-too-large", "workflow-storage-capacity-exceeded"})
            self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _, _ = build_fixture(root, "v5")
            write_json_create(root / "renewal.json", renewal(load_state(path)))
            before = path.read_bytes()
            with (
                patch(
                    "agent_lifecycle.workflow.operation_kernel.write_state_replace",
                    side_effect=OSError("fixture fault"),
                ),
                self.assertRaises(OSError),
            ):
                renew(path)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(LifecycleError) as caught:
                load_for_update(
                    path,
                    operation_id="retry",
                    expected_revision=load_state(path)["stateRevision"],
                    authorization_required=False,
                )
            self.assertEqual(caught.exception.code, "workflow-split-brain")
