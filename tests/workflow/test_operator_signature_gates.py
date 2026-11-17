"""Real native authorization/finalization, never a private-key host qualification."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.workflow import authorize_execution, finalize_run, renew_execution_authorization
from tests.contracts.test_operator_signature import (
    NEGATIVE_CASES,
    envelope,
    inventory,
    negative_case,
    state,
)
from tests.workflow.helpers import _final_audit
from tests.workflow.test_authorization import _receipt
from tests.workflow.test_authorization_renewal import renewal


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def native_fixture(root, kind, case=None, mode="required"):
    value = state(mode, phase="FINAL_AUDIT" if kind == "accept" else "AWAITING_AUTHORIZATION")
    if kind == "accept":
        value["authorization"] = {"required": False, "granted": True}
        value["finalAuditOutcome"] = {"verdict": "ACCEPTED"}
        subject = _final_audit()
        subject["planDigest"] = value["planDigest"]
        subject["completionSignal"]["planDigest"] = value["planDigest"]
    else:
        subject = _receipt(value)
    name = "final-audit.json" if kind == "accept" else "authorization.json"
    args = {"operation_id": "operation", "subject": subject}
    signed = envelope(value, kind, **args)
    if case is not None:
        value, signed = negative_case(value, kind, case, **args)
    path = root / "run.state.json"
    write(path, value)
    write(root / name, subject)
    if signed is not None:
        write(root / (name + ".operator-signature.json"), signed)
    return path, name


def invoke(path, kind, name):
    common = {
        "operation_id": "operation",
        "expected_revision": 1,
        "source_revision": "source",
        "reason": "Synthetic signature fixture",
    }
    if kind == "accept":
        return finalize_run(path, final_audit_path=name, proof_path="proof.json", **common)
    return authorize_execution(path, receipt_path=name, **common)


class OperatorSignatureNativeTests(unittest.TestCase):
    def test_renewal_needs_fresh_signature_and_keeps_previous_authority_history(self):
        for case in (None, *NEGATIVE_CASES):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, name = native_fixture(root, "authorize")
                initial = json.loads((root / name).read_bytes())
                initial.update(issuedAt="2026-01-01T00:00:00Z", expiresAt="2030-01-01T00:00:00Z")
                initial["receiptDigest"] = canonical_digest({k: v for k, v in initial.items() if k != "receiptDigest"})
                write(root / name, initial)
                write(
                    root / (name + ".operator-signature.json"),
                    envelope(json.loads(path.read_bytes()), "authorize", operation_id="operation", subject=initial),
                )
                invoke(path, "authorize", name)
                current = json.loads(path.read_bytes())
                # Synthetic final-audit fixture, with no tasks awaiting acceptance.
                current["phase"] = "FINAL_AUDIT"
                previous = current["authorization"]["operatorSignature"]
                subject = renewal(current)
                args = {"operation_id": "renew", "subject": subject}
                selected, signed = (current, envelope(current, "authorize", **args))
                if case is not None:
                    selected, signed = negative_case(current, "authorize", case, **args)
                write(path, selected)
                write(root / "renewal.json", subject)
                if signed is not None:
                    write(root / "renewal.json.operator-signature.json", signed)
                before = inventory(root)

                def apply(path=path):
                    return renew_execution_authorization(
                        path,
                        operation_id="renew",
                        expected_revision=2,
                        source_revision="source",
                        receipt_path="renewal.json",
                        reason="Synthetic renewal",
                    )

                if case is not None:
                    with self.assertRaises(LifecycleError) as caught:
                        apply()
                    self.assertEqual(
                        caught.exception.code,
                        "operator-signature-missing" if case == "missing" else "operator-signature-invalid",
                    )
                    self.assertEqual(before, inventory(root))
                    continue
                apply()
                actual = json.loads(path.read_bytes())
                self.assertEqual(actual["stateRevision"], 3)
                updated = actual["authorization"]["operatorSignature"]
                self.assertNotEqual(updated["payloadDigest"], previous["payloadDigest"])
                event = json.loads((root / "events.jsonl").read_text().splitlines()[-1])
                self.assertEqual(event["payload"]["previousAuthorization"]["operatorSignature"], previous)
                self.assertEqual(event["payload"]["operatorSignature"], updated)
                before = inventory(root)
                with self.assertRaises(LifecycleError):
                    apply()
                self.assertEqual(before, inventory(root))

    def test_valid_signature_crosses_actual_authorize_and_finalize_without_task_gates(self):
        for kind in ("authorize", "accept"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, name = native_fixture(root, kind)
                result = invoke(path, kind, name)
                self.assertEqual(result["phase"], "COMPLETE" if kind == "accept" else "READY")
                current = json.loads(path.read_bytes())
                self.assertEqual(current["schemaVersion"], "agent-workflow-state.v7")
                if kind == "accept":
                    proof = json.loads((root / "proof.json").read_bytes())
                    self.assertTrue(proof["operatorSignature"]["signatureVerified"])
                    event = json.loads((root / "events.jsonl").read_text().splitlines()[-1])
                    bound_proof = event["payload"]["proof"]
                    self.assertEqual(bound_proof["path"], "proof.json")
                    self.assertEqual(bound_proof["sha256"], canonical_digest(proof))
                    self.assertEqual(bound_proof["bytes"], len(canonical_bytes(proof)) + 1)
                    self.assertEqual(
                        proof["bodyDigest"], canonical_digest({k: v for k, v in proof.items() if k != "bodyDigest"})
                    )
                else:
                    self.assertTrue(current["authorization"]["operatorSignature"]["signatureVerified"])
                before = inventory(root)
                with self.assertRaises(LifecycleError):
                    invoke(path, kind, name)
                self.assertEqual(before, inventory(root))

    def test_seven_refusals_per_native_decision_have_zero_protected_mutation(self):
        for kind in ("authorize", "accept"):
            for case in NEGATIVE_CASES:
                with self.subTest(kind=kind, case=case), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path, name = native_fixture(root, kind, case)
                    before = inventory(root)
                    with self.assertRaises(LifecycleError) as caught:
                        invoke(path, kind, name)
                    self.assertEqual(
                        caught.exception.code,
                        "operator-signature-missing" if case == "missing" else "operator-signature-invalid",
                    )
                    self.assertEqual(inventory(root), before)

    def test_advisory_missing_signature_reports_invalid_but_can_authorize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, name = native_fixture(root, "authorize", "missing", "advisory")
            result = invoke(path, "authorize", name)
            self.assertEqual(result["phase"], "READY")
            receipt = json.loads(path.read_bytes())["authorization"]["operatorSignature"]
            self.assertFalse(receipt["signatureVerified"])
            self.assertEqual(receipt["claimStrength"], "Declared")

    def test_concurrent_duplicate_authorization_commits_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, name = native_fixture(root, "authorize")

            def attempt():
                try:
                    invoke(path, "authorize", name)
                    return "committed"
                except LifecycleError:
                    return "refused"

            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(lambda _: attempt(), range(2)))
            self.assertEqual(outcomes.count("committed"), 1)
            self.assertEqual(json.loads(path.read_bytes())["stateRevision"], 2)
            self.assertEqual(len((root / "events.jsonl").read_text().splitlines()), 1)

    def test_event_before_state_failure_is_uncertain_and_retry_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, name = native_fixture(root, "authorize")
            original = path.read_bytes()
            with (
                patch(
                    "agent_lifecycle.workflow.operation_kernel.write_state_replace",
                    side_effect=OSError("synthetic interruption"),
                ),
                self.assertRaises((OSError, LifecycleError)),
            ):
                invoke(path, "authorize", name)
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue((root / "events.jsonl").exists())
            before = inventory(root)
            with self.assertRaises(LifecycleError) as caught:
                invoke(path, "authorize", name)
            self.assertEqual(caught.exception.code, "workflow-split-brain")
            self.assertEqual(inventory(root), before)


if __name__ == "__main__":
    unittest.main()
