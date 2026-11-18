"""Positive and read-only contracts for an independently anchored run fixture."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent_lifecycle.audit import chain_verification
from agent_lifecycle.audit.chain_verification import verify_chain
from agent_lifecycle.audit.implementation import build_final_implementation_audit
from agent_lifecycle.compiler.task_packets import compile_task_packets
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.chain_verification_schemas import ANCHOR, BUNDLE, TRUST
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.operator_signature_schemas import operator_authority_marker
from agent_lifecycle.contracts.proof_validation import build_receipt_hash_chain
from agent_lifecycle.contracts.reviewer_identity_schemas import reviewer_attestation_authority
from agent_lifecycle.freeze.package_integrity import build_reviewed_plan_lock_v2
from agent_lifecycle.review.provenance import reviewer_observed_at
from agent_lifecycle.workflow.authorization import authorize_execution
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from agent_lifecycle.workflow.plan_adoption import adopt_plan, start_execution
from agent_lifecycle.workflow.reviewer_gate import reviewer_decision_lineage
from agent_lifecycle.workflow.task_start import start_task
from agent_lifecycle.workflow.task_transitions import accept_task, commit_task_result
from tests.contracts.test_operator_signature import envelope, inventory
from tests.contracts.test_operator_signature import policy as operator_policy
from tests.review.test_reviewer_attestation_strict import REVIEWER, WORKER, attest, policy_for
from tests.workflow.helpers import _final_audit, _fresh_result, _review
from tests.workflow.test_operator_signature_gates import write

LINEAGE = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


class AnchoredRunFixture:
    """Synthetic selected public roots, native final decisions, no external custody claim."""

    def __init__(
        self, root: Path, *, operator_required: bool, task_bearing: bool = False, operator_advisory: bool = False
    ) -> None:
        self.repo = root / "evidence"
        self.trust = root / "verifier" / "trust.json"
        self.anchor = self.trust.with_name("anchor.json")
        self.bundle_name = "receipts/bundle.json"
        self.bundle = {
            "schemaVersion": BUNDLE,
            "manifest": "plan/plan.manifest.json",
            "lock": "plan/plan.lock.json",
            "state": "state.json",
            "journal": "events.jsonl",
            "chain": "receipts/chain.json",
        }
        self.state_path = self.repo / self.bundle["state"]
        self.base = self._prepare_git()
        self.manifest_path = self.repo / self.bundle["manifest"]
        manifest = self._freeze(operator_required, operator_advisory, task_bearing)
        self._start(operator_required)
        self._complete_task(task_bearing)
        self._finish(operator_required, task_bearing)
        self.value = self.read(self.bundle["state"])
        write(self.repo / self.bundle_name, self.bundle)
        operator = manifest.get("operatorSignaturePolicy")
        write(
            self.trust,
            {
                "schemaVersion": TRUST,
                "reviewerPolicyDigest": canonical_digest(manifest["reviewerAttestationPolicy"]),
                "operatorPolicyDigest": canonical_digest(operator) if operator is not None else None,
            },
        )
        self.paths = self._paths(manifest, operator_required)
        self.rebuild_chain()
        self.refresh_anchor()

    def _prepare_git(self) -> str:
        self.repo.mkdir(parents=True)
        (self.repo / ".gitignore").write_text(
            "plan/\nreceipts/\nwork/\nstate.json\nstate.json.storage/\nevents.jsonl\n", encoding="utf-8"
        )
        (self.repo / "src").mkdir()
        (self.repo / "src/example.py").write_text("value = 1\n", encoding="utf-8")
        self._git("init", "-q")
        self._git("add", ".gitignore", "src/example.py")
        self._git(
            "-c", "user.name=ALK Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Baseline"
        )
        return self._git("rev-parse", "HEAD").strip()

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, timeout=30)

    def _freeze(self, required: bool, advisory: bool, typed: bool) -> dict:
        base = Path(__file__).resolve().parents[1]
        seed = base / "freeze/fixtures/release-2-17-canonical-v2-plan-package/plan.manifest.json"
        manifest = json.loads(seed.read_bytes())
        manifest.pop("releaseTarget")
        roles = ["freeze", "task-review:WS-01", "final-audit"]
        if typed:
            roles += ["implementation-audit:WS-01", "final-implementation-audit"]
            manifest["implementationAudit"] = {"required": True, "finalRequired": True}
        policy = policy_for(*roles)
        manifest.update(
            package={"id": "strict-archive", "planArtifactRoot": "plan", "artifactRoot": "work"},
            author={"id": WORKER[0], "runId": WORKER[1], "surface": "test"},
            baseRevision={"sha": self.base, "ref": "fixture"},
            planFiles=sorted([self.bundle["manifest"], "plan/plan-review.json", "plan/acceptance-criteria.md"]),
            planReview={
                "report": "plan/plan-review.json",
                "required": True,
                "verdict": "READY_TO_FREEZE",
                "reviewedRevision": manifest["planRevision"],
            },
            orchestration={"startMode": "approval-required", "maxTaskAttempts": 2},
            reviewerAttestationPolicy=policy,
            reviewerAttestationAuthority=reviewer_attestation_authority(policy),
        )
        manifest["workstreams"][0].update(owner="worker", reviewer="reviewer", plannedItems=["Do the work"])
        if required or advisory:
            operator = operator_policy()
            operator["mode"] = "required" if required else "advisory"
            manifest["operatorSignaturePolicy"] = operator
            if required:
                manifest["operatorSignatureAuthority"] = operator_authority_marker(operator)
                manifest["packageIntegrity"]["allowedUnlistedFiles"].append("operator-freeze-signature.json")
                write(self.repo / "plan/operator-freeze-signature.json", envelope(manifest))
        write(self.manifest_path, manifest)
        criteria = base / "planning/fixtures/canonical-acceptance-criteria.md"
        (self.repo / "plan/acceptance-criteria.md").write_bytes(criteria.read_bytes())
        digest = canonical_digest(manifest)
        review = {
            "schemaVersion": "agent-plan-review.v1",
            "packageId": "strict-archive",
            "reviewedPlanHash": digest,
            "planRevision": manifest["planRevision"],
            "reviewId": "plan-review",
            "fullReview": True,
            "findings": [],
            "verdict": "READY_TO_FREEZE",
            "reviewer": REVIEWER,
        }
        lineage = {
            "packageId": "strict-archive",
            "planRevision": manifest["planRevision"],
            "sourceRevision": self.base,
            "planDigest": digest,
        }
        report = self._attest(policy, review, "freeze", lineage)
        write(self.repo / "plan/plan-review.json", report)
        lock = build_reviewed_plan_lock_v2(
            manifest,
            report,
            review_path="plan/plan-review.json",
            review_sha256=self.digest("plan/plan-review.json"),
            repository_root=self.repo,
        )
        write(self.repo / self.bundle["lock"], lock)
        compile_task_packets(self.manifest_path, repository_root=self.repo, write=True)
        return manifest

    def _start(self, operator_required: bool) -> None:
        initialize_workflow_state(self.state_path, run_id="run", package_id="strict-archive")
        adopt_plan(
            self.state_path,
            manifest_path=self.manifest_path,
            operation_id="adopt",
            expected_revision=1,
            source_revision=self.base,
            reset_tasks=False,
            start_mode="approval-required",
        )
        current = self.read("state.json")
        issued = datetime.now(UTC).replace(microsecond=0)
        receipt = {
            **{key: current[key] for key in (*LINEAGE, "stateRevision")},
            "schemaVersion": "agent-workflow-authorization-receipt.v1",
            "status": "PASS",
            "decision": "ALLOW",
            "authorizationId": "test-grant",
            "authorizedBy": "fixture-operator",
            "issuedAt": issued.isoformat(),
            "expiresAt": (issued + timedelta(minutes=5)).isoformat(),
        }
        receipt["receiptDigest"] = canonical_digest(receipt)
        path = "receipts/authorization.json"
        write(self.repo / path, receipt)
        if operator_required:
            write(
                self.repo / (path + ".operator-signature.json"),
                envelope(current, "authorize", operation_id="grant", subject=receipt),
            )
        authorize_execution(self.state_path, receipt_path=path, **self._operation("grant"))
        start_execution(self.state_path, **self._operation("run-start"))
        start_task(self.state_path, task_id="WS-01", **self._operation("task-start"))

    def _operation(self, name: str) -> dict:
        current = self.read("state.json")
        return {
            "operation_id": name,
            "expected_revision": current["stateRevision"],
            "source_revision": self.base,
            "reason": "Isolated signed fixture",
        }

    @staticmethod
    def _attest(policy: dict, report: dict, phase: str, lineage: dict) -> dict:
        return attest(policy, report, phase=phase, lineage=lineage, observed=reviewer_observed_at())

    def _complete_task(self, typed: bool) -> None:
        current = self.read("state.json")
        task = current["tasks"][0]
        (self.repo / "src/example.py").write_text("value = 2\n", encoding="utf-8")
        result = _fresh_result(self.repo, self.state_path, attempt=1)
        result.update(actor=WORKER[0], actorRunId=WORKER[1], taskPacketHash=task["packet"]["sha256"])
        result_path = task["artifactPaths"]["result"].replace("{attempt}", "1")
        review_path = task["artifactPaths"]["review"].replace("{attempt}", "1")
        write(self.repo / result_path, result)
        commit_task_result(
            self.state_path,
            task_id="WS-01",
            result_path=result_path,
            **self._operation("task-result"),
        )
        current = self.read("state.json")
        task = current["tasks"][0]
        lineage = reviewer_decision_lineage(current, task)
        policy = current["reviewerAttestationPolicy"]
        review = _review(attempt=1, result_hash=task["result"]["sha256"], plan_digest=current["planDigest"])
        review.update(reviewer=REVIEWER, taskPacketHash=task["packet"]["sha256"])
        report = self._attest(policy, review, "task-review", lineage)
        write(self.repo / review_path, report)
        typed_path = None
        if typed:
            typed_path = self._typed_task_report(current, task, lineage)
        operation = self._operation("task-accept")
        operation.pop("source_revision")
        accept_task(
            self.state_path,
            task_id="WS-01",
            review_path=review_path,
            implementation_audit_path=typed_path,
            **operation,
        )

    def _typed_task_report(self, current: dict, task: dict, lineage: dict) -> str:
        typed_path = "receipts/task-audit.json"
        audit = {
            **{key: current[key] for key in LINEAGE},
            "schemaVersion": "agent-implementation-audit-report.v1",
            "taskId": task["id"],
            "attempt": task["attempt"],
            "status": "PASS",
            "verdict": "ACCEPTED",
            "findings": [],
            "blockers": [],
            "auditor": REVIEWER,
            "productionPromotionClaimed": False,
        }
        signed = self._attest(current["reviewerAttestationPolicy"], audit, "implementation-audit", lineage)
        signed["reportDigest"] = canonical_digest(signed)
        write(self.repo / typed_path, signed)
        return typed_path

    def _finish(self, operator_required: bool, typed: bool) -> None:
        current = self.read("state.json")
        policy = current["reviewerAttestationPolicy"]
        audit = _final_audit()
        lineage = {key: current[key] for key in LINEAGE}
        audit.update(**lineage, verdict="ACCEPTED", taskIds=[], findingIds=[], auditor=REVIEWER)
        audit["completionSignal"].update(lineage)
        audit = self._attest(policy, audit, "final-audit", reviewer_decision_lineage(current))
        path = "receipts/final-review.json"
        write(self.repo / path, audit)
        apply_final_audit_outcome(
            self.state_path,
            final_audit_path=path,
            verdict="ACCEPTED",
            **self._operation("outcome"),
        )
        current = self.read("state.json")
        if operator_required:
            write(
                self.repo / (path + ".operator-signature.json"),
                envelope(current, "accept", operation_id="finish", subject=audit),
            )
        typed_path = None
        if typed:
            typed_path = "receipts/final-implementation.json"
            aggregate = build_final_implementation_audit(
                manifest_path=self.manifest_path,
                state_path=self.state_path,
                report_paths=["receipts/task-audit.json"],
                auditor_id=REVIEWER["id"],
                auditor_surface=REVIEWER["surface"],
            )
            aggregate["auditor"] = REVIEWER
            aggregate.pop("auditDigest")
            aggregate = self._attest(
                policy, aggregate, "final-implementation-audit", reviewer_decision_lineage(current)
            )
            aggregate["auditDigest"] = canonical_digest(aggregate)
            write(self.repo / typed_path, aggregate)
        finalize_run(
            self.state_path,
            final_audit_path=path,
            final_implementation_audit_path=typed_path,
            proof_path="receipts/proof.json",
            **self._operation("finish"),
        )

    def _paths(self, manifest: dict, operator_required: bool) -> set[str]:
        value = self.value
        paths = set(manifest["planFiles"]) | {self.bundle[k] for k in ("state", "lock", "journal")}
        paths.update({"receipts/authorization.json", "receipts/final-review.json", "receipts/proof.json"})
        paths.add(value["packetSet"]["path"])
        storage_root = value["storage"]["root"]
        for snapshot in value["priorSnapshots"]:
            paths.add(f"{storage_root}/{snapshot['path']}")
        for task in value["tasks"]:
            paths.update(task[field]["path"] for field in ("packet", "result", "review"))
            paths.update(
                f"{storage_root}/{task[field]['path']}" for field in ("ownershipReceipt", "resultChangeSetEvidence")
            )
            if "implementationAuditReport" in task:
                paths.add(task["implementationAuditReport"]["path"])
        if "finalImplementationAudit" in value:
            paths.add(value["finalImplementationAudit"]["path"])
        if operator_required:
            paths |= {
                "plan/operator-freeze-signature.json",
                "receipts/authorization.json.operator-signature.json",
                "receipts/final-review.json.operator-signature.json",
            }
        return paths

    def read(self, path: str) -> dict:
        return json.loads((self.repo / path).read_bytes())

    def digest(self, path: str) -> str:
        return sha256((self.repo / path).read_bytes()).hexdigest()

    def rebuild_chain(self) -> None:
        chain = build_receipt_hash_chain(
            [{"path": path, "digest": self.digest(path)} for path in sorted(self.paths)],
            chain_id="test-run",
            lineage={key: self.value[key] for key in LINEAGE},
        )
        write(self.repo / self.bundle["chain"], chain)

    def refresh_anchor(self) -> None:
        selected = {
            "schemaVersion": ANCHOR,
            "runId": self.value["runId"],
            "packageId": self.value["packageId"],
            "sourceRevision": self.value["sourceRevision"],
            "planDigest": self.value["planDigest"],
            "terminalRevision": self.value["stateRevision"],
            "terminalPhase": "COMPLETE",
            "trustConfigSha256": sha256(self.trust.read_bytes()).hexdigest(),
            "bundleSha256": self.digest(self.bundle_name),
            **{key + "Sha256": self.digest(self.bundle[key]) for key in ("lock", "journal", "state", "chain")},
        }
        write(self.anchor, selected)

    def verify(self) -> dict:
        return verify_chain(self.repo, self.bundle_name, trust_config_path=self.trust, anchor_path=self.anchor)


class ChainVerificationTests(TestCase):
    def test_optional_final_implementation_audit_requires_consistent_absence(self):
        with TemporaryDirectory() as temp:
            snapshot = chain_verification._Snapshot(Path(temp))
            check = chain_verification._verify_final_implementation_receipt
            check(snapshot, {}, {}, {}, {})
            with self.assertRaises(LifecycleError) as caught:
                check(snapshot, {}, {}, {"finalImplementationAudit": {}}, {})
            self.assertEqual(caught.exception.code, "chain-final-implementation-mismatch")

    def test_journal_payload_must_be_an_object(self):
        with self.assertRaises(LifecycleError) as caught:
            chain_verification._verify_checkpoint_scope({"payload": None})
        self.assertEqual(caught.exception.code, "chain-journal-payload-invalid")

    def test_execution_window_requires_live_grant(self):
        start = datetime(2026, 1, 1, 12, tzinfo=UTC)
        event = {"recordedAt": "2026-01-01T12:00:00Z", "payload": {"previousPhase": "READY", "phase": "RUNNING"}}
        check = chain_verification._verify_execution_window
        check([event], authorized_at=start, expires_at="2026-01-01T12:00:01Z")
        with self.assertRaises(LifecycleError) as caught:
            check([event], authorized_at=start, expires_at="2026-01-01T12:00:00Z")
        self.assertEqual(caught.exception.code, "authorization-expired")
        with self.assertRaises(LifecycleError) as later:
            check(
                [event, {"recordedAt": "2026-01-01T12:00:01Z"}], authorized_at=start, expires_at="2026-01-01T12:00:01Z"
            )
        self.assertEqual(later.exception.code, "authorization-expired")

    def test_fractional_operator_window_inside_a_second_is_partial_coverage(self):
        second = datetime(2026, 1, 1, 12, tzinfo=UTC)
        start = second.replace(microsecond=100_000)
        expiry = second.replace(microsecond=900_000)
        sample, covered = chain_verification._operator_observation_sample(second, start, expiry)
        self.assertEqual(sample, start)
        self.assertFalse(covered)

    def test_both_roots_are_verified_with_zero_writes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve(strict=True)
            fixture = AnchoredRunFixture(root, operator_required=True, task_bearing=True)
            before = inventory(root)
            with (
                patch("subprocess.Popen", side_effect=AssertionError("offline verifier launched a process")),
                patch("socket.socket", side_effect=AssertionError("offline verifier opened a socket")),
                patch("tempfile.gettempdir", side_effect=AssertionError("offline verifier probed a temp directory")),
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
            self.assertIn(
                {
                    "check": "operator-signatures",
                    "status": "NOT_APPLICABLE",
                    "reason": "operator-signature-profile-disabled",
                },
                result["checks"],
            )
