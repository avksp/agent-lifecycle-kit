from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.start_routing import resolve_managed_execution_strategy
from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle
from agent_lifecycle.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[2]


class UnifiedStartStrategyTests(unittest.TestCase):
    def test_raw_intake_reports_deferred_strategy_without_route(self) -> None:
        receipt = start_lifecycle(
            adapter_id="codex",
            mode="plan",
            task_text="Investigate the subsystem and prepare a reviewed plan.",
        )

        strategy = receipt["executionStrategy"]
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(strategy["status"], "DEFERRED_UNTIL_FREEZE")
        self.assertIsNone(strategy["implementationModelClass"])
        self.assertIsNone(strategy["packetMode"])
        self.assertFalse(strategy["automaticAdoptionEligible"])

    def test_frozen_managed_start_projects_quality_preserving_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, lock, state = _write_frozen_bundle(root)
            descriptor = root / "adapters/codex/adapter.descriptor.json"
            capability = descriptor.with_name("capabilities.manifest.json")
            descriptor.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "adapters/codex/adapter.descriptor.json", descriptor)
            shutil.copyfile(ROOT / "adapters/codex/capabilities.manifest.json", capability)
            request = {
                "schemaVersion": "agent-adapter-task-run-request.v1",
                "adapterId": "codex",
                "state": state.as_posix(),
                "manifest": manifest.as_posix(),
                "lock": lock.as_posix(),
                "task": "WS-01",
                "operationId": "start-strategy",
                "expectedRevision": 3,
                "sourceRevision": "source-sha",
                "productionPromotionClaimed": False,
            }
            resolved = resolve_managed_execution_strategy(
                adapter_id="codex",
                descriptor_path=descriptor,
                state_path=state,
                manifest_path=manifest,
                lock_path=lock,
                task_id="WS-01",
                operation_id="start-strategy",
                expected_revision=3,
                source_revision="source-sha",
                requested_risk="auto",
                host_model_profile_path=ROOT / "profiles/hosts/codex-live-profile.v1.json",
                project_profile_path=root / ".alk/project-profile.json",
            )
            managed = {
                "schemaVersion": "agent-adapter-session-receipt.v1",
                "status": "READY",
                "blockers": [],
                "lifecycleCoverageClaimed": True,
                "hostLaunchStarted": False,
                "nextAction": {"executionStrategy": resolved["strategy"]},
                "receiptDigest": "a" * 64,
            }
            with patch(
                "agent_lifecycle.adapter_sessions.task_intake.managed_adapter_run",
                return_value=managed,
            ):
                receipt = start_lifecycle(
                    adapter_id="codex",
                    descriptor_path=descriptor,
                    mode="implement",
                    task_text=json.dumps(request),
                    host_model_profile_path=ROOT / "profiles/hosts/codex-live-profile.v1.json",
                )

        strategy = receipt["executionStrategy"]
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(strategy["status"], "PASS")
        self.assertEqual(strategy["resolvedRiskTier"], "S2")
        self.assertEqual(strategy["packetMode"], "FULL")
        self.assertTrue(strategy["advisoryOnly"])
        self.assertFalse(receipt["hostLaunchStarted"])


def _write_frozen_bundle(root: Path) -> tuple[Path, Path, Path]:
    manifest_payload = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "strategy-package", "title": "Architecture change"},
        "specification": {
            "tier": "S2",
            "requirements": [{"id": "R-1", "description": "Review architecture"}],
            "tierResolutionRequest": {
                "riskFlags": {"architecture": True, "security": True},
                "capabilityHints": ["architecture"],
            },
        },
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Implement architecture change",
                "owner": "worker",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {"criteria": [{"id": "AC-1", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]}]},
    }
    digest = canonical_digest(manifest_payload)
    lock_payload = {
        "schemaVersion": "agent-plan-lock.v1",
        "packageId": "strategy-package",
        "planRevision": 1,
        "manifestHash": digest,
    }
    state_payload = {
        "runId": "run-1",
        "packageId": "strategy-package",
        "planRevision": 1,
        "planDigest": digest,
        "stateRevision": 3,
        "sourceRevision": "source-sha",
        "tasks": [{"id": "WS-01", "attemptCount": 0}],
    }
    manifest = root / "plan.manifest.json"
    lock = root / "plan.lock.json"
    state = root / "run.state.json"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    lock.write_text(json.dumps(lock_payload), encoding="utf-8")
    state.write_text(json.dumps(state_payload), encoding="utf-8")
    return manifest, lock, state


if __name__ == "__main__":
    unittest.main()
