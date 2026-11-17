"""Positive and read-only contracts for an independently anchored run fixture."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.audit.chain_verification import verify_chain
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.chain_verification_schemas import ANCHOR, BUNDLE, TRUST
from agent_lifecycle.contracts.proof_validation import build_receipt_hash_chain
from agent_lifecycle.contracts.reviewer_identity_schemas import REVIEWER_REQUIRED_STATE, reviewer_attestation_authority
from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
from agent_lifecycle.review.provenance import verify_reviewer_decision
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from agent_lifecycle.workflow.reviewer_gate import reviewer_decision_lineage
from tests.contracts.test_operator_signature import envelope, inventory, state
from tests.review.test_reviewer_attestation_strict import OBSERVED, REVIEWER, WORKER, attest, policy_for
from tests.workflow.helpers import _final_audit
from tests.workflow.test_operator_signature_gates import write

LINEAGE = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


class AnchoredRunFixture:
    """Synthetic selected public roots, native final decisions, no external custody claim."""

    def __init__(self, root: Path, *, operator_required: bool, task_bearing: bool = False,
                 operator_advisory: bool = False) -> None:
        self.repo = root / "evidence"
        self.trust = root / "verifier" / "trust.json"
        self.anchor = self.trust.with_name("anchor.json")
        self.bundle_name = "receipts/bundle.json"
        self.bundle = {"schemaVersion": BUNDLE, "manifest": "plan/plan.manifest.json",
                       "lock": "plan/plan.lock.json", "state": "state.json",
                       "journal": "events.jsonl", "chain": "receipts/chain.json"}
        self.state_path = self.repo / self.bundle["state"]
        value = state(phase="FINAL_AUDIT")
        if operator_advisory:
            value["operatorSignaturePolicy"]["mode"] = "advisory"
            value.pop("operatorSignatureAuthority")
        elif not operator_required:
            value.pop("operatorSignaturePolicy")
            value.pop("operatorSignatureAuthority")
        roles = ["freeze", "final-audit"]
        if task_bearing:
            roles += ["task-review:WS-01", "implementation-audit:WS-01", "final-implementation-audit"]
        policy = policy_for(*roles)
        marker = reviewer_attestation_authority(policy)
        manifest = {
            "schemaVersion": "agent-plan-manifest.v1",
            "status": "FROZEN",
            "package": {"id": value["packageId"], "planArtifactRoot": "plan"},
            "planRevision": 1,
            "baseRevision": {"sha": value["sourceRevision"]},
            "author": {"id": WORKER[0], "runId": WORKER[1]},
            "planFiles": sorted([self.bundle["manifest"], "plan/plan-review.json"]),
            "packageIntegrity": {"required": True, "lockSchemaVersion": "agent-plan-lock.v2"},
            "planReview": {"required": True, "report": "plan/plan-review.json",
                           "reviewedRevision": 1, "verdict": "READY_TO_FREEZE"},
            "reviewerAttestationPolicy": policy,
            "reviewerAttestationAuthority": marker,
        }
        if task_bearing:
            manifest["implementationAudit"] = {"required": True, "finalRequired": True}
        if operator_advisory:
            manifest["operatorSignaturePolicy"] = value["operatorSignaturePolicy"]
        if operator_required:
            for field in ("operatorSignaturePolicy", "operatorSignatureAuthority"):
                manifest[field] = value[field]
            manifest["packageIntegrity"]["allowedUnlistedFiles"] = [
                "plan.lock.json", "operator-freeze-signature.json",
            ]
            write(self.repo / "plan/operator-freeze-signature.json", envelope(manifest))
        digest = canonical_digest(manifest)
        review = {
            "schemaVersion": "agent-plan-review.v1", "verdict": "READY_TO_FREEZE", "fullReview": True,
            "reviewId": "fixture-review", "reviewer": REVIEWER, "findings": [], "planRevision": 1,
            "packageId": value["packageId"], "reviewedPlanHash": digest,
        }
        review = attest(policy, review, phase="freeze", lineage={
            "packageId": value["packageId"], "planRevision": 1, "sourceRevision": value["sourceRevision"],
            "planDigest": digest,
        })
        write(self.repo / self.bundle["manifest"], manifest)
        write(self.repo / "plan/plan-review.json", review)
        with patch("agent_lifecycle.freeze.package_integrity.reviewer_observed_at", return_value=OBSERVED):
            lock = build_reviewed_plan_lock_v2(manifest, review, review_path="plan/plan-review.json",
                review_sha256=self.digest("plan/plan-review.json"), repository_root=self.repo)
        write(self.repo / self.bundle["lock"], lock)
        value.update(schemaVersion=REVIEWER_REQUIRED_STATE, planDigest=digest, stateRevision=3,
                     reviewerAttestationPolicy=policy, reviewerAttestationAuthority=marker,
                     manifestPath=self.bundle["manifest"], packetSet={"planLockSha256": self.digest(self.bundle["lock"])})
        value["storage"]["root"] = "state.json.storage"
        auth = self._authorization(value, operator_required)
        payloads = {"plan-adopted": {"planDigest": digest}, "execution-authorized": auth}
        task_paths = set()
        if task_bearing:
            task_paths = self._typed_task(value, payloads)
            value["stateRevision"] += 2
        value["operationLedger"] = {
            action: {"stateRevision": revision, "eventType": action, "recordedAt": OBSERVED}
            for revision, action in enumerate(payloads, 2)
        }
        journal = self.repo / "events.jsonl"
        with journal.open("wb") as f:
            for revision, (action, payload) in enumerate(payloads.items(), 2):
                f.write(canonical_bytes({
                    "schemaVersion": "agent-workflow-event.v1", "runId": value["runId"], "packageId": value["packageId"],
                    "stateRevision": revision, "operationId": action, "eventType": action,
                    "payload": payload, "recordedAt": OBSERVED,
                }) + b"\n")
        write(self.state_path, value)
        self._finish(value, operator_required, task_bearing)
        self.value = self.read(self.bundle["state"])
        write(self.repo / self.bundle_name, self.bundle)
        write(self.trust, {"schemaVersion": TRUST, "reviewerPolicyDigest": canonical_digest(policy),
              "operatorPolicyDigest": canonical_digest(manifest["operatorSignaturePolicy"])
              if operator_required or operator_advisory else None})
        paths = set(manifest["planFiles"]) | {self.bundle[k] for k in ("state", "lock", "journal")}
        paths |= {"receipts/authorization.json", "receipts/final-review.json", "receipts/proof.json"}
        if operator_required:
            paths |= {"plan/operator-freeze-signature.json", "receipts/authorization.json.operator-signature.json",
                      "receipts/final-review.json.operator-signature.json"}
        self.paths = paths | task_paths
        self.rebuild_chain()
        self.refresh_anchor()

    def _authorization(self, value: dict, operator_required: bool) -> dict:
        receipt = {key: value[key] for key in LINEAGE}
        receipt.update(status="PASS", decision="ALLOW")
        path = "receipts/authorization.json"
        write(self.repo / path, receipt)
        identity = {"path": path, "sha256": canonical_digest(receipt), "bytes": (self.repo / path).stat().st_size}
        value["authorization"] = {"required": False, "granted": True, "authorizationReceipt": identity}
        payload = {"authorizationReceipt": identity}
        if operator_required:
            from agent_lifecycle.contracts.operator_signature import verify_operator_subject

            signature_path = path + ".operator-signature.json"
            old = {**value, "stateRevision": 2}
            write(
                self.repo / signature_path,
                envelope(old, "authorize", operation_id="execution-authorized", subject=receipt),
            )
            verified = verify_operator_subject(old, "authorize", operation_id="execution-authorized", subject=receipt,
                root=self.repo, signature_path=signature_path, observed_at=OBSERVED[:-1] + ".000000Z")
            payload["operatorSignature"] = verified
            value["authorization"]["operatorSignature"] = verified
        return payload

    def _identity(self, path: str, body: dict) -> dict:
        write(self.repo / path, body)
        return {"path": path, "sha256": canonical_digest(body), "bytes": (self.repo / path).stat().st_size}

    def _typed_task(self, value: dict, payloads: dict) -> set[str]:
        policy = value["reviewerAttestationPolicy"]
        actor = {"actor": WORKER[0], "actorRunId": WORKER[1]}
        task = {"id": "WS-01", "owner": WORKER[0], "attempt": 1, "status": "ACCEPTED",
                "required": True, "dependsOn": [], "writes": [], "packet": {"sha256": "c" * 64},
                "result": self._identity("receipts/result.json", actor)}
        lineage = reviewer_decision_lineage(value, task)
        for phase, name, body, key in (
            ("task-review", "receipts/task-review.json", {"reviewer": REVIEWER, "verdict": "ACCEPTED"}, "review"),
            ("implementation-audit", "receipts/task-audit.json",
             {"auditor": REVIEWER, "verdict": "ACCEPTED"}, "implementationAuditReport"),
        ):
            report = attest(policy, body, phase=phase, lineage=lineage)
            admission = verify_reviewer_decision(
                policy, report, phase=phase, lineage=lineage, author=WORKER, observed_at=OBSERVED,
            )
            task[key] = {**self._identity(name, report), "verdict": "ACCEPTED", "reviewerAdmission": admission}
        value["tasks"] = [task]
        payloads["task-result-committed"] = {"taskId": task["id"], "attempt": 1, "result": task["result"]}
        payloads["task-accepted"] = {"taskId": task["id"], "attempt": 1, "review": task["review"]}
        return {"receipts/result.json", "receipts/task-review.json", "receipts/task-audit.json",
                "receipts/final-implementation.json"}

    def _finish(self, value: dict, operator_required: bool, task_bearing: bool) -> None:
        audit = _final_audit()
        lineage = {key: value[key] for key in LINEAGE}
        audit.update(**lineage, verdict="ACCEPTED", taskIds=[], findingIds=[], auditor=REVIEWER)
        audit["completionSignal"].update(lineage)
        audit = attest(value["reviewerAttestationPolicy"], audit, phase="final-audit",
                       lineage=reviewer_decision_lineage(value))
        path = "receipts/final-review.json"
        write(self.repo / path, audit)
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            apply_final_audit_outcome(self.state_path, operation_id="outcome",
                expected_revision=value["stateRevision"], source_revision=value["sourceRevision"], final_audit_path=path,
                verdict="ACCEPTED", reason="Fixture independent review")
        current = self.read("state.json")
        if operator_required:
            write(self.repo / (path + ".operator-signature.json"),
                  envelope(current, "accept", operation_id="finish", subject=audit))
        typed_path = None
        if task_bearing:
            typed_path = "receipts/final-implementation.json"
            typed = {**lineage, "schemaVersion": "agent-final-implementation-audit.v1", "status": "PASS",
                     "findings": [], "blockers": [], "auditor": REVIEWER, "productionPromotionClaimed": False}
            typed = attest(value["reviewerAttestationPolicy"], typed, phase="final-implementation-audit",
                           lineage=reviewer_decision_lineage(current))
            typed["auditDigest"] = canonical_digest(typed)
            write(self.repo / typed_path, typed)
        with patch("agent_lifecycle.workflow.reviewer_gate.reviewer_observed_at", return_value=OBSERVED):
            finalize_run(self.state_path, operation_id="finish", expected_revision=current["stateRevision"],
                source_revision=value["sourceRevision"], final_audit_path=path, final_implementation_audit_path=typed_path,
                proof_path="receipts/proof.json", reason="Finish fixture")

    def read(self, path: str) -> dict:
        return json.loads((self.repo / path).read_bytes())

    def digest(self, path: str) -> str:
        return sha256((self.repo / path).read_bytes()).hexdigest()

    def rebuild_chain(self) -> None:
        chain = build_receipt_hash_chain(
            [{"path": path, "digest": self.digest(path)} for path in sorted(self.paths)],
            chain_id="test-run", lineage={key: self.value[key] for key in LINEAGE},
        )
        write(self.repo / self.bundle["chain"], chain)

    def refresh_anchor(self) -> None:
        selected = {
            "schemaVersion": ANCHOR, "runId": self.value["runId"], "packageId": self.value["packageId"],
            "sourceRevision": self.value["sourceRevision"], "planDigest": self.value["planDigest"],
            "terminalRevision": self.value["stateRevision"], "terminalPhase": "COMPLETE",
            "trustConfigSha256": sha256(self.trust.read_bytes()).hexdigest(),
            "bundleSha256": self.digest(self.bundle_name),
            **{key + "Sha256": self.digest(self.bundle[key]) for key in ("lock", "journal", "state", "chain")},
        }
        write(self.anchor, selected)

    def verify(self) -> dict:
        return verify_chain(self.repo, self.bundle_name, trust_config_path=self.trust, anchor_path=self.anchor)


class ChainVerificationTests(TestCase):
    def test_both_roots_are_verified_with_zero_writes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve(strict=True)
            fixture = AnchoredRunFixture(root, operator_required=True, task_bearing=True)
            before = inventory(root)
            with (
                patch("subprocess.Popen", side_effect=AssertionError("offline verifier launched a process")),
                patch("socket.socket", side_effect=AssertionError("offline verifier opened a socket")),
            ):
                result = fixture.verify()
            self.assertEqual(result["exitCode"], 0, result)
            self.assertIn({"check": "operator-signatures", "status": "VERIFIED"}, result["checks"])
            self.assertEqual(inventory(root), before)

    def test_disabled_operator_profile_is_explicitly_not_applicable(self):
        with TemporaryDirectory() as temp:
            fixture = AnchoredRunFixture(Path(temp).resolve(strict=True), operator_required=False)
            result = fixture.verify()
            self.assertEqual(result["exitCode"], 0, result)
            self.assertIn({
                "check": "operator-signatures", "status": "NOT_APPLICABLE",
                "reason": "operator-signature-profile-disabled",
            }, result["checks"])
