from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.compiler import compile_small_model_packets, compile_task_packets
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.policy.execution_strategy import resolve_execution_strategy

ROOT = Path(__file__).resolve().parents[2]


class StrategyProjectionTests(unittest.TestCase):
    def test_task_packet_projects_only_bounded_strategy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, lock, state = _write_bundle(root, tier="S0")
            strategy = _strategy(manifest, lock, state, tier="S0")
            previous = Path.cwd()
            os.chdir(root)
            try:
                result = compile_task_packets(manifest_path, execution_strategy=strategy)
            finally:
                os.chdir(previous)

        projection = result["packets"][0]["executionStrategy"]
        self.assertEqual(projection["strategyDigest"], strategy["strategyDigest"])
        self.assertEqual(projection["packetMode"], "COMPACT")
        self.assertEqual(projection["modelClass"], "standard-code")
        self.assertTrue(projection["authorityPreserved"])
        self.assertNotIn("resourceCaps", projection)
        self.assertNotIn("phaseRoutes", projection)

    def test_strategy_plan_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, lock, state = _write_bundle(root, tier="S0")
            strategy = _strategy(manifest, lock, state, tier="S0")
            strategy["lineage"]["planDigest"] = "0" * 64
            strategy["strategyDigest"] = canonical_digest(
                {key: value for key, value in strategy.items() if key != "strategyDigest"}
            )
            previous = Path.cwd()
            os.chdir(root)
            try:
                with self.assertRaisesRegex(LifecycleError, "plan digest mismatch"):
                    compile_task_packets(manifest_path, execution_strategy=strategy)
            finally:
                os.chdir(previous)

    def test_small_model_packet_accepts_compact_and_rejects_full_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compact_path, compact_manifest, compact_lock, compact_state = _write_bundle(root / "compact", tier="S0")
            full_path, full_manifest, full_lock, full_state = _write_bundle(root / "full", tier="S2")
            compact = _strategy(compact_manifest, compact_lock, compact_state, tier="S0")
            full = _strategy(full_manifest, full_lock, full_state, tier="S2")
            previous = Path.cwd()
            try:
                os.chdir(root / "compact")
                accepted = compile_small_model_packets(
                    compact_path,
                    context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                    execution_strategy=compact,
                )
                os.chdir(root / "full")
                rejected = compile_small_model_packets(
                    full_path,
                    context_profile_path=ROOT / "profiles/small-context-profile.v1.json",
                    execution_strategy=full,
                )
            finally:
                os.chdir(previous)

        self.assertEqual(accepted["status"], "PASS")
        self.assertEqual(accepted["packets"][0]["executionStrategy"]["packetMode"], "COMPACT")
        self.assertEqual(rejected["status"], "FAIL")
        self.assertIn(
            "execution-strategy-compact-blocked",
            {item["code"] for item in rejected["blockers"]},
        )


def _write_bundle(root: Path, *, tier: str) -> tuple[Path, dict, dict, dict]:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {
            "id": f"strategy-{tier.lower()}",
            "artifactRoot": "plans/p",
            "planArtifactRoot": "plans/p/.agent-plan/p",
        },
        "specification": {
            "tier": tier,
            "revision": 1,
            "artifact": "spec.json",
            "tierResolutionRequest": {"riskFlags": {}, "capabilityHints": []},
        },
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Compile strategy packet",
                "owner": "worker",
                "reviewer": "reviewer",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "plannedItems": [{"id": "REQ-1", "description": "Do it"}],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
                "artifactPaths": {},
            }
        ],
        "acceptanceCriteria": [{"id": "AC-1", "evidenceIds": ["EV-1"]}],
    }
    digest = canonical_digest(manifest)
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "packageId": manifest["package"]["id"],
        "planRevision": 1,
        "manifestHash": digest,
    }
    state = {
        "runId": f"run-{tier.lower()}",
        "packageId": manifest["package"]["id"],
        "planRevision": 1,
        "planDigest": digest,
        "stateRevision": 2,
        "sourceRevision": "source-sha",
        "tasks": [{"id": "WS-01", "attemptCount": 0}],
    }
    lock_path = root / "plans/p/.agent-plan/p/plan.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    manifest_path = root / "plans/p/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest, lock, state


def _strategy(manifest: dict, lock: dict, state: dict, *, tier: str) -> dict:
    return resolve_execution_strategy(
        manifest=deepcopy(manifest),
        lock=deepcopy(lock),
        state=deepcopy(state),
        task_id="WS-01",
        adapter_id="codex",
        adapter_host="codex",
        operation_id=f"strategy-{tier.lower()}",
        expected_revision=2,
        source_revision="source-sha",
        requested_risk="auto",
        risk_policy=_load("profiles/risk-execution-policy.v1.json"),
        routing_profile=_load("profiles/model-routing-profile.v1.json"),
        baseline_profile=_load("profiles/lifecycle-baselines.v1.json"),
        host_profile=_load("profiles/hosts/codex-live-profile.v1.json") if tier != "S0" else None,
    )


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
