from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))

from release_common import iter_payload_files  # noqa: E402


class ReleaseCandidateTests(unittest.TestCase):
    def test_release_inventory_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            inventory = out / "inventory.json"
            assembly = out / "release-assembly.json"
            verification = out / "release-verification.json"
            _run("tools/release/assemble_release_candidate.py", "--manifest", "plans/standalone-v1/plan.manifest.json", "--inventory", str(inventory), "--evidence", str(assembly))
            _run("tools/release/verify_release_candidate.py", "--inventory", str(inventory), "--evidence", str(verification))
            inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
            payload = json.loads(verification.read_text(encoding="utf-8"))
            self.assertIn("tools/release/validate_deferred_promotion.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/release/validate_live_calibration.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/release/validate_live_host_conformance.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/common.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/codex_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/claude_code_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/cursor_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/hermes_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("tools/live_hosts/opencode_harness.py", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("fixtures/synthetic/negative-matrix-01.json", {item["path"] for item in inventory_payload["files"]})
            self.assertIn("evals/synthetic/cost-baseline.v1.json", {item["path"] for item in inventory_payload["files"]})
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_release_payload_excludes_build_egg_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src/agent_lifecycle"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            egg_info = root / "src/agent_lifecycle_kit.egg-info"
            egg_info.mkdir()
            (egg_info / "PKG-INFO").write_text("generated\n", encoding="utf-8")

            files = {path.as_posix() for path in iter_payload_files(root)}

            self.assertIn("src/agent_lifecycle/__init__.py", files)
            self.assertNotIn("src/agent_lifecycle_kit.egg-info/PKG-INFO", files)

    def test_support_matrix_and_deferred_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            matrix_evidence = out / "support-matrix-contract.json"
            deferred_evidence = out / "deferred-promotion-contract.json"
            _run("tools/release/validate_support_matrix.py", "--support-matrix", "docs/adapters/support-matrix.md", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json", "--evidence", str(matrix_evidence))
            _run("tools/release/validate_deferred_promotion.py", "--profile", "plans/standalone-v1/.agent-plan/standalone-v1/benchmark-authority-profile.v1.json", "--evidence", str(deferred_evidence))
            matrix = json.loads(matrix_evidence.read_text(encoding="utf-8"))
            deferred = json.loads(deferred_evidence.read_text(encoding="utf-8"))
            self.assertEqual(matrix["adapterMaturity"], "EXPERIMENTAL")
            self.assertTrue(deferred["deferredProductionPromotion"])
            self.assertFalse(deferred["liveModelExecutionClaimed"])

    def test_live_calibration_validator_accepts_live_receipt_with_4k_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt = out / "live-calibration-receipt.json"
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipt, synthetic=False)

            _run(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt",
                str(receipt),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            scenarios = {item["scenarioId"] for item in payload["aggregates"]}
            self.assertEqual(payload["status"], "PASS")
            self.assertIn("S1-SMALL-CONTEXT-4K-STRICT-01", scenarios)
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_calibration_validator_rejects_synthetic_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt = out / "live-calibration-receipt.json"
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipt, synthetic=True)

            result = _run_no_check(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt",
                str(receipt),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("synthetic-live-calibration-receipt", {item["code"] for item in payload["blockers"]})

    def test_live_calibration_validator_accepts_promoted_host_receipt_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "receipts"
            receipts.mkdir()
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipts / "codex.json", synthetic=False)

            _run(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["promotedHosts"], ["codex"])
            self.assertEqual(payload["hosts"], ["codex"])

    def test_live_calibration_validator_requires_receipt_per_promoted_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "receipts"
            receipts.mkdir()
            evidence = out / "live-calibration-evidence.json"
            _write_live_calibration_receipt(receipts / "codex.json", synthetic=False)

            result = _run_no_check(
                "tools/release/validate_live_calibration.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--budget-targets",
                "conformance/core/budget-targets.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex,claude-code",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("missing-live-calibration-receipt", {item["code"] for item in payload["blockers"]})

    def test_live_host_conformance_validator_accepts_contract_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=False)

            _run(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["checks"][0]["passedOperationCount"], payload["checks"][0]["requiredOperationCount"])
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_host_conformance_validator_rejects_synthetic_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=True)

            result = _run_no_check(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("synthetic-live-host-receipt", {item["code"] for item in payload["blockers"]})

    def test_live_host_conformance_validator_rejects_host_protocol_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipts = out / "live-host"
            receipts.mkdir()
            evidence = out / "live-host-conformance.json"
            _write_live_host_conformance_receipt(receipts / "codex.json", host="codex", synthetic=False, bypass=True)

            result = _run_no_check(
                "tools/release/validate_live_host_conformance.py",
                "--profile",
                "conformance/core/live-calibration-profile.v1.json",
                "--baseline",
                "conformance/core/adapter-baseline.v1.json",
                "--receipt-dir",
                str(receipts),
                "--promoted-hosts",
                "codex",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("host-protocol-envelope-invalid", {item["code"] for item in payload["blockers"]})

    def test_live_host_promotion_plan_validator_accepts_structural_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            evidence = out / "live-host-promotion-plan-validation.json"

            _run(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "agent-live-host-promotion-plan-validation.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_live_host_promotion_plan_validator_rejects_missing_operation_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            plan = _load_json(plan_path)
            del plan["operationEvidenceRequirements"]["final-audit"]
            _write_json(plan_path, plan)
            evidence = out / "live-host-promotion-plan-validation.json"

            result = _run_no_check(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("invalid-operation-evidence-requirements", {item["code"] for item in payload["blockers"]})

    def test_live_host_promotion_plan_validator_requires_budget_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package_root = out / "live-host-promotion"
            plan_path = _write_live_host_promotion_plan_fixture(package_root)
            plan = _load_json(plan_path)
            del plan["budgetPolicy"]["requiresPerInvocationAccountingReconciliation"]
            _write_json(plan_path, plan)
            evidence = out / "live-host-promotion-plan-validation.json"

            result = _run_no_check(
                "tools/release/validate_live_host_promotion_plan.py",
                "--plan",
                str(plan_path),
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("invalid-live-host-budget-policy", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_requires_release_evidence_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            output = out / "final-audit.json"
            _run("tools/release/verify_final_candidate.py", "--manifest", str(manifest), "--state", str(state), "--release-evidence-dir", str(evidence_dir), "--output", str(output))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["semanticStatus"], "READY_FOR_FINALIZATION")
            self.assertEqual(payload["status"], "PASS")
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertTrue(all(item["status"] == "PASS" for item in payload["lineageChecks"]))

    def test_final_candidate_rejects_failed_release_evidence(self) -> None:
        # NEG-R03-01 Failed Release Verification
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            verification = json.loads((evidence_dir / "release-verification.json").read_text(encoding="utf-8"))
            verification["status"] = "FAIL"
            (evidence_dir / "release-verification.json").write_text(json.dumps(verification), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("evidence-status-not-pass", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_malformed_release_evidence(self) -> None:
        # NEG-R03-02 Malformed Evidence
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            (evidence_dir / "release-verification.json").write_text("[]", encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("malformed-release-evidence", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_malformed_neutrality_counters(self) -> None:
        # NEG-R03-02 Malformed Evidence
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            report = json.loads((evidence_dir / "release-neutrality-report.json").read_text(encoding="utf-8"))
            report["counters"]["findings"] = "zero"
            (evidence_dir / "release-neutrality-report.json").write_text(json.dumps(report), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("evidence-counters-non-zero", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_manifest_state_mismatch(self) -> None:
        # NEG-R03-03 Manifest/State Mismatch
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            state_payload["planRevision"] = 14
            state.write_text(json.dumps(state_payload), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            failed = {item["id"] for item in payload["lineageChecks"] if item["status"] == "FAIL"}
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("state.planRevision", failed)

    def test_final_candidate_rejects_packet_index_mismatch(self) -> None:
        # NEG-R03-04 Packet Index Mismatch
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            index = Path(manifest_payload["package"]["artifactRoot"]) / "workflow/task-packets/index.json"
            index_payload = json.loads(index.read_text(encoding="utf-8"))
            index_payload["manifestDigest"] = "9" * 64
            index.write_text(json.dumps(index_payload), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            failed = {item["id"] for item in payload["lineageChecks"] if item["status"] == "FAIL"}
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("taskPacketIndex.manifestDigest", failed)

    def test_release_verification_rejects_stale_inventory_identity(self) -> None:
        # NEG-R03-05 Inventory Stale
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            payload = out / "payload.txt"
            payload.write_text("before\n", encoding="utf-8")
            inventory_body = {
                "schemaVersion": "agent-release-candidate-inventory.v1",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "payloadRoots": [],
                "files": [_identity(payload)],
            }
            inventory = out / "inventory.json"
            _write_json(inventory, {**inventory_body, "candidatePayloadInventoryDigest": _digest(inventory_body)})
            payload.write_text("after\n", encoding="utf-8")
            evidence = out / "release-verification.json"

            result = _run_no_check(
                "tools/release/verify_release_candidate.py",
                "--inventory",
                str(inventory),
                "--evidence",
                str(evidence),
            )

            verification = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(verification["status"], "FAIL")
            self.assertEqual(verification["mismatches"][0]["reason"], "identity-mismatch")

    def test_final_candidate_derives_required_tasks_from_manifest(self) -> None:
        # NEG-R03-15 Required Task Set Hole
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out, accepted_tasks=["WS-01"])
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WS-02", payload["notAcceptedTasks"])

    def test_final_candidate_rejects_unknown_evidence_schema(self) -> None:
        # NEG-R03-16 Release Evidence Schema Drift
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            evidence = json.loads((evidence_dir / "support-matrix-contract.json").read_text(encoding="utf-8"))
            evidence["schemaVersion"] = "agent-release-unknown.v1"
            (evidence_dir / "support-matrix-contract.json").write_text(json.dumps(evidence), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown-evidence-schema", {item["code"] for item in payload["blockers"]})

    def test_final_candidate_rejects_production_promotion_claim(self) -> None:
        # NEG-R03-06 Production Promotion Claim In Offline Mode
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest, state, evidence_dir = _write_final_candidate_fixture(out)
            evidence = json.loads((evidence_dir / "deferred-promotion-contract.json").read_text(encoding="utf-8"))
            evidence["productionPromotionClaimed"] = True
            (evidence_dir / "deferred-promotion-contract.json").write_text(json.dumps(evidence), encoding="utf-8")
            output = out / "final-audit.json"

            result = _run_no_check(
                "tools/release/verify_final_candidate.py",
                "--manifest",
                str(manifest),
                "--state",
                str(state),
                "--release-evidence-dir",
                str(evidence_dir),
                "--output",
                str(output),
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("production-promotion-claim", {item["code"] for item in payload["blockers"]})

    def test_negative_suite_coverage_verifier_requires_catalog_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = out / "catalog.md"
            tests_root = out / "tests"
            evidence = out / "evidence.json"
            catalog.write_text("## NEG-R03-01 One\n## NEG-R03-02 Two\n", encoding="utf-8")
            tests_root.mkdir()
            (tests_root / "test_negative.py").write_text(
                "# NEG-R03-01\n# NEG-R03-02\n",
                encoding="utf-8",
            )

            _run(
                "tools/release/verify_negative_suite_coverage.py",
                "--catalog",
                str(catalog),
                "--tests-root",
                str(tests_root),
                "--expected-range",
                "NEG-R03-01..NEG-R03-02",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(len(payload["coveredScenarios"]), 2)

    def test_negative_suite_coverage_verifier_fails_for_missing_test_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = out / "catalog.md"
            tests_root = out / "tests"
            evidence = out / "evidence.json"
            catalog.write_text("## NEG-R03-01 One\n## NEG-R03-02 Two\n", encoding="utf-8")
            tests_root.mkdir()
            (tests_root / "test_negative.py").write_text("# NEG-R03-01\n", encoding="utf-8")

            result = _run_no_check(
                "tools/release/verify_negative_suite_coverage.py",
                "--catalog",
                str(catalog),
                "--tests-root",
                str(tests_root),
                "--expected-range",
                "NEG-R03-01..NEG-R03-02",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["missingScenarios"][0]["id"], "NEG-R03-02")

    def test_task_packet_context_verifier_compiles_and_checks_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = _write_context_manifest(out)
            summary = out / "summary.json"
            evidence = out / "context-fit.json"
            _write_json(
                summary,
                {
                    "acceptedEvidence": [],
                    "activeDecisions": ["Use compact context."],
                    "changedFiles": [],
                    "doNotDo": ["Do not truncate."],
                    "latestUserIntent": "Implement the task.",
                    "nextRequiredAction": "Run validation.",
                    "openBlockers": [],
                },
            )

            _run(
                "tools/release/verify_task_packet_context.py",
                "--manifest",
                str(manifest),
                "--profile",
                "profiles/small-context-profile.v1.json",
                "--summary",
                str(summary),
                "--out-dir",
                str(out / "packets"),
                "--target-windows",
                "4k-strict,8k",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual({item["window"] for item in payload["checks"]}, {"4k-strict", "8k"})


def _write_final_candidate_fixture(
    out: Path,
    *,
    accepted_tasks: list[str] | None = None,
) -> tuple[Path, Path, Path]:
    artifact_root = out / "package"
    plan_root = artifact_root / ".agent-plan/package"
    evidence_dir = out / "evidence"
    inventory_path = out / "candidate/inventory.json"
    manifest_path = out / "plan.manifest.json"
    state_path = out / "run.state.json"
    manifest = {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "package",
            "artifactRoot": artifact_root.as_posix(),
            "planArtifactRoot": plan_root.as_posix(),
        },
        "workstreams": [
            {"id": "WS-01", "required": True},
            {"id": "WS-02", "required": True},
        ],
    }
    manifest_digest = _digest(manifest)
    _write_json(manifest_path, manifest)
    _write_json(plan_root / "plan.lock.json", {"schemaVersion": "agent-plan-lock.v1", "packageId": "package", "planRevision": 1, "manifestHash": manifest_digest})
    _write_json(artifact_root / "workflow/task-packets/index.json", {"packageId": "package", "manifestDigest": manifest_digest, "packets": []})
    accepted = set(accepted_tasks or ["WS-01", "WS-02"])
    _write_json(
        state_path,
        {
            "schemaVersion": "agent-workflow-state.v3",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": manifest_digest,
            "stateRevision": 1,
            "tasks": [{"id": task_id, "status": "ACCEPTED" if task_id in accepted else "READY", "required": True} for task_id in ["WS-01", "WS-02"]],
        },
    )
    inventory_body = {
        "schemaVersion": "agent-release-candidate-inventory.v1",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": manifest_digest,
        "payloadRoots": [],
        "files": [],
    }
    _write_json(inventory_path, {**inventory_body, "candidatePayloadInventoryDigest": _digest(inventory_body)})
    inventory_identity = _identity(inventory_path)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        evidence_dir / "release-assembly.json",
        {
            "schemaVersion": "agent-release-assembly-evidence.v1",
            "status": "PASS",
            "inventory": inventory_identity,
            "productionPromotionClaimed": False,
        },
    )
    _write_json(
        evidence_dir / "release-verification.json",
        {
            "schemaVersion": "agent-release-verification-evidence.v1",
            "status": "PASS",
            "inventory": inventory_identity,
            "mismatches": [],
            "productionPromotionClaimed": False,
        },
    )
    _write_json(
        evidence_dir / "support-matrix-contract.json",
        {
            "schemaVersion": "agent-support-matrix-contract-evidence.v1",
            "status": "PASS",
            "adapterMaturity": "EXPERIMENTAL",
            "productionPromotionClaimed": False,
        },
    )
    _write_json(
        evidence_dir / "deferred-promotion-contract.json",
        {
            "schemaVersion": "agent-deferred-promotion-contract-evidence.v1",
            "status": "PASS",
            "deferredProductionPromotion": True,
            "productionPromotionClaimed": False,
        },
    )
    _write_json(
        evidence_dir / "release-neutrality-report.json",
        {
            "schemaVersion": "agent-neutrality-report.v1",
            "counters": {"findings": 0, "readErrors": 0, "archiveLimitBreaches": 0},
        },
    )
    return manifest_path, state_path, evidence_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _identity(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": path.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _write_context_manifest(out: Path) -> Path:
    manifest = {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": "context-fixture",
            "artifactRoot": (out / "artifact").as_posix(),
            "planArtifactRoot": (out / "plan").as_posix(),
        },
        "specification": {"tier": "S1", "revision": 1},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Small task",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "plannedItems": [{"id": "R-1", "description": "Do the work."}],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {"criteria": [{"id": "AC-1", "statement": "Done", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]}]},
    }
    digest = _digest(manifest)
    manifest_path = out / "manifest.json"
    _write_json(manifest_path, manifest)
    _write_json(out / "plan/plan.lock.json", {"schemaVersion": "agent-plan-lock.v1", "packageId": "context-fixture", "planRevision": 1, "manifestHash": digest})
    return manifest_path


def _write_live_host_promotion_plan_fixture(package_root: Path) -> Path:
    hosts = ["codex", "opencode", "claude-code", "cursor", "hermes"]
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    (package_root / "hosts").mkdir(parents=True)
    for host in hosts:
        (package_root / f"hosts/{host}.md").write_text(f"# {host}\n", encoding="utf-8")

    workstreams = []
    for index, host in enumerate(hosts):
        workstream_id = f"LHP-{host.upper().replace('-', '-')}"
        previous_id = workstreams[index - 1]["id"] if index else None
        workstreams.append(
            {
                "id": workstream_id,
                "host": host,
                "title": f"{host} live host promotion proof",
                "owner": f"{host}-worker",
                "dependsOn": [] if previous_id is None else [previous_id],
                "plan": f"hosts/{host}.md",
                "evidence": [
                    f"tasks/release-0-3/evidence/live-host-receipts/{host}.json",
                    f"tasks/release-0-3/evidence/live-calibration/{host}.json",
                    f"tasks/release-0-3/evidence/live-host-conformance-{host}.json",
                    f"tasks/release-0-3/evidence/live-calibration-verification-{host}.json",
                    f"tasks/release-0-3/evidence/live-promotion-audit-{host}.json",
                ],
            }
        )

    plan = {
        "schemaVersion": "agent-live-host-promotion-plan.v1",
        "packageId": "test-live-host-promotion",
        "sddTier": "S2",
        "tierResolution": {
            "schemaVersion": "agent-sdd-tier-resolution.v1",
            "tier": "S2",
            "requestDigest": "6" * 64,
            "reasons": ["externalEnvironment-risk"],
            "rules": {},
        },
        "status": "DRAFT",
        "intent": "Produce host-bound live receipts.",
        "hostOrder": hosts,
        "sequencingPolicy": {"kind": "operational-one-host-at-a-time"},
        "hostAvailabilitySnapshot": {host: "test" for host in hosts},
        "sharedInputs": {
            "liveCalibrationProfile": "conformance/core/live-calibration-profile.v1.json",
            "budgetTargets": "conformance/core/budget-targets.v1.json",
            "adapterBaseline": "conformance/core/adapter-baseline.v1.json",
            "planManifest": "plans/standalone-v1/plan.manifest.json",
            "planLock": "plans/standalone-v1/.agent-plan/standalone-v1/plan.lock.json",
        },
        "artifactRootPolicy": {
            "kind": "parent-release-live-evidence-carveout",
            "requiresParentRefreezeBeforeMove": True,
        },
        "budgetPolicy": {
            "requiresHumanApprovedCapBeforeLiveCalls": True,
            "onCapExceeded": "BLOCKED_BUDGET_EXHAUSTED",
            "requiresPerInvocationAccountingReconciliation": True,
            "supportedModes": ["metered", "subscription", "local"],
            "meteredModeRequiresUsdCap": True,
            "nonMeteredModesRequireResourceCaps": True,
            "resourceCapFields": ["maxInvocations", "maxBillableTokens", "maxWallSeconds"],
            "costAccountingRequiredModes": ["metered"],
            "minimumRunsPerHost": 14,
            "recommendedRunsPerHost": 70,
        },
        "blockerCodes": [
            "BLOCKED_USAGE_ATTESTATION",
            "BLOCKED_NON_INTERACTIVE_HOST_SURFACE",
            "BLOCKED_BUDGET_EXHAUSTED",
            "BLOCKED_DIRTY_WORKTREE",
            "BLOCKED_HOST_AUTH",
            "BLOCKED_HOST_CLI_MISSING",
            "BLOCKED_HARNESS_TESTS",
            "BLOCKED_GATEWAY_STARTUP",
        ],
        "operationEvidenceRequirements": {name: "test-requirement" for name in baseline["requiredOperations"]},
        "validationCommands": [
            {
                "id": "LHP-VAL-PLAN-CHECK",
                "argv": "PYTHONPATH=src python tools/release/validate_live_host_promotion_plan.py --plan tasks/release-0-3/live-host-promotion/host-promotion.plan.json --evidence tasks/release-0-3/evidence/live-host-promotion-plan-validation.json",
            }
        ],
        "evidenceArtifacts": [
            {
                "id": "LHP-EV-PLAN-CHECK",
                "schemaVersion": "agent-live-host-promotion-plan-validation.v1",
                "path": "tasks/release-0-3/evidence/live-host-promotion-plan-validation.json",
            }
        ],
        "sharedNonGoals": [],
        "workstreams": workstreams,
        "acceptanceCriteria": [
            {"id": f"LHP-AC-{index:02d}", "statement": f"Acceptance {index}."}
            for index in range(1, 9)
        ],
    }
    plan_path = package_root / "host-promotion.plan.json"
    _write_json(plan_path, plan)
    return plan_path


def _run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, script, *args], cwd=ROOT, check=True)


def _run_no_check(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, script, *args], cwd=ROOT, check=False, text=True, capture_output=True)


def _write_live_calibration_receipt(path: Path, *, synthetic: bool) -> None:
    profile = _load_json(ROOT / "conformance/core/live-calibration-profile.v1.json")
    targets = _load_json(ROOT / "conformance/core/budget-targets.v1.json")
    runs = []
    for scenario in profile["requiredScenarios"]:
        for cohort in profile["requiredCohorts"]:
            runs.append(
                {
                    "runId": f"{scenario}-{cohort}-run-01",
                    "scenarioId": scenario,
                    "cohort": cohort,
                    "usageAttested": True,
                    "qualityStatus": "PASS",
                    "usage": {
                        "billableTokens": 1000,
                        "inputTokens": 700,
                        "outputTokens": 300,
                        "cumulativeContextBytes": 4096,
                        "toolCalls": 2,
                        "wallSeconds": 10,
                    },
                }
            )
    receipt = {
        "schemaVersion": "agent-lifecycle-live-calibration-receipt.v1",
        "status": "PASS",
        "receiptId": "test-live-calibration-receipt",
        "host": "codex",
        "profileId": profile["profileId"],
        "profileDigest": _digest(profile),
        "budgetTargetsDigest": _digest(targets),
        "sourceRevision": "test-source",
        "liveModelInvocations": len(runs),
        "syntheticReplayUsed": synthetic,
        "qualityRegressionCount": 0,
        "usageAttestationPolicy": {"missingOrUnattestedUsage": "FAIL"},
        "runs": runs,
    }
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _write_live_host_conformance_receipt(path: Path, *, host: str, synthetic: bool, bypass: bool = False) -> None:
    baseline = _load_json(ROOT / "conformance/core/adapter-baseline.v1.json")
    operations = []
    for name in baseline["requiredOperations"]:
        operation_id = f"{host}-{name}-01"
        request = {
            "schemaVersion": "agent-host-operation-request.v1",
            "operationId": operation_id,
            "capability": name,
            "inputs": {"host": host},
            "outputs": [],
            "constraints": {"usageReceiptRequired": True},
        }
        if bypass:
            request["provider"] = "concrete-provider"
        operations.append(
            {
                "name": name,
                "status": "PASS",
                "syntheticReplayUsed": False,
                "hostOperationRequest": request,
                "hostOperationReceipt": {
                    "schemaVersion": "agent-host-operation-receipt.v1",
                    "operationId": operation_id,
                    "capability": name,
                    "status": "PASS",
                    "outputs": [],
                    "usage": {"toolCalls": 1, "billableTokens": 1},
                },
            }
        )
    receipt = {
        "schemaVersion": "agent-lifecycle-live-host-conformance-receipt.v1",
        "status": "PASS",
        "receiptId": f"{host}-live-host-conformance",
        "host": host,
        "adapterId": host,
        "hostRange": "test-host-range",
        "sourceRevision": "test-source",
        "syntheticReplayUsed": synthetic,
        "usageAttested": True,
        "operations": operations,
    }
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _digest(value: dict) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
