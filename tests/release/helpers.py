from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))

from release_common import iter_payload_files  # noqa: E402

__all__ = [
    "ROOT",
    "iter_payload_files",
    "_digest",
    "_identity",
    "_load_json",
    "_run",
    "_run_no_check",
    "_write_context_manifest",
    "_write_final_candidate_fixture",
    "_write_json",
    "_write_live_calibration_receipt",
    "_write_live_host_conformance_receipt",
    "_write_live_host_promotion_plan_fixture",
    "_write_r04_candidate_manifest",
    "_write_r04_final_proof",
    "_write_r04_required_evidence",
    "_write_unittest_evidence",
]

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


def _write_r04_required_evidence(evidence_dir: Path) -> None:
    _write_json(
        evidence_dir / "plan-check.json",
        {
            "schemaVersion": "agent-plan-check.v1",
            "manifest": {
                "schemaVersion": "agent-plan-validation.v1",
                "status": "FROZEN",
            },
            "lock": {
                "schemaVersion": "agent-plan-lock-verification.v1",
            },
        },
    )
    _write_unittest_evidence(evidence_dir / "profile-contracts.json", tests_run=27)
    _write_json(
        evidence_dir / "cursor-compat.json",
        {
            "schemaVersion": "agent-cursor-compat-evidence.v1",
            "status": "PASS",
        },
    )
    _write_unittest_evidence(evidence_dir / "workflow-budget.json", tests_run=35)
    _write_unittest_evidence(evidence_dir / "cli-ux.json", tests_run=26)
    _write_unittest_evidence(evidence_dir / "harness-model-selection.json", tests_run=43)
    _write_json(
        evidence_dir / "negative-suite-coverage.json",
        {
            "schemaVersion": "agent-negative-suite-coverage.v1",
            "status": "PASS",
        },
    )
    _write_json(
        evidence_dir / "context-fit.json",
        {
            "schemaVersion": "agent-task-packet-context-fit.v1",
            "status": "PASS",
        },
    )
    _write_json(
        evidence_dir / "neutrality-report.json",
        {
            "schemaVersion": "agent-neutrality-report.v1",
            "counters": {"findings": 0, "readErrors": 0, "archiveLimitBreaches": 0},
        },
    )


def _write_r04_candidate_manifest(path: Path) -> Path:
    manifest = {
        "schemaVersion": "3.0",
        "status": "FROZEN",
        "planRevision": 6,
        "package": {
            "id": "release-0-4",
            "artifactRoot": path.parent.as_posix(),
            "planArtifactRoot": (path.parent / ".agent-plan" / "release-0-4").as_posix(),
        },
        "workstreams": [
            {"id": "WS-01", "required": True},
            {"id": "WS-02", "required": True},
            {"id": "WS-03", "required": True},
            {"id": "WS-04", "required": True},
            {"id": "WS-05", "required": True},
        ],
    }
    _write_json(path, manifest)
    return path


def _write_r04_final_proof(path: Path, manifest_path: Path) -> None:
    manifest = _load_json(manifest_path)
    package = manifest.get("package")
    if not isinstance(package, dict):
        raise AssertionError("release 0.4 manifest fixture must include package")
    accepted = [
        {"id": item["id"], "attempt": 1, "review": {"verdict": "ACCEPTED"}}
        for item in manifest.get("workstreams", [])
        if isinstance(item, dict) and item.get("required", True)
    ]
    _write_json(
        path,
        {
            "schemaVersion": "agent-run-final-proof.v1",
            "semanticStatus": "READY_FOR_FINALIZATION",
            "packageId": package["id"],
            "planRevision": manifest["planRevision"],
            "planDigest": _digest(manifest),
            "sourceRevision": "test-source",
            "productionPromotionClaimed": False,
            "acceptedTasks": accepted,
            "finalAudit": {"path": "final/final-audit.json"},
        },
    )


def _write_unittest_evidence(path: Path, *, tests_run: int) -> None:
    _write_json(
        path,
        {
            "schemaVersion": "agent-lifecycle-unittest-report.v1",
            "verdict": "PASS",
            "suite": {
                "testsRun": tests_run,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "expectedFailures": 0,
                "unexpectedSuccesses": 0,
            },
        },
    )


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
                    f"tasks/release-0-5/evidence/live-host-receipts/{host}.json",
                    f"tasks/release-0-5/evidence/live-calibration/{host}.json",
                    f"tasks/release-0-5/evidence/live-host-conformance-{host}.json",
                    f"tasks/release-0-5/evidence/live-calibration-verification-{host}.json",
                    f"tasks/release-0-5/evidence/live-promotion-audit-{host}.json",
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
        "evidenceRoot": "tasks/release-0-5/evidence",
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
                "argv": "PYTHONPATH=src python tools/release/validate_live_host_promotion_plan.py --plan tasks/release-0-5/patches/0.5.0-claude-live-promotion/host-promotion.plan.json --evidence tasks/release-0-5/evidence/live-host-promotion-plan-validation.json",
            }
        ],
        "evidenceArtifacts": [
            {
                "id": "LHP-EV-PLAN-CHECK",
                "schemaVersion": "agent-live-host-promotion-plan-validation.v1",
                "path": "tasks/release-0-5/evidence/live-host-promotion-plan-validation.json",
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
