from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.policy.execution_strategy import resolve_execution_strategy, validate_execution_strategy
from agent_lifecycle.workflow import start_task
from agent_lifecycle.workflow.task_transitions import _require_control_task_acceptance

from .helpers import _write_state


class TaskTransitionAuthorityTests(unittest.TestCase):
    def test_start_task_rejects_pseudo_glob_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["writes"] = ["src/**"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-invalid-authority",
                    expected_revision=1,
                    source_revision="source",
                    reason="test",
                )

            self.assertEqual(raised.exception.code, "invalid-authority-path")
            self.assertEqual(state_path.read_bytes(), before)

    def test_guidance_control_does_not_require_post_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lifecycleControl"] = {
                "level": "GUIDANCE_ONLY",
                "source": "frozen-plan",
                "planDigest": state["planDigest"],
                "planRevision": state["planRevision"],
            }

            _require_control_task_acceptance(state, state["tasks"][0])

    def test_enforced_control_rejects_tampered_post_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lifecycleControl"] = {
                "level": "ENFORCED",
                "source": "frozen-plan",
                "planDigest": state["planDigest"],
                "planRevision": state["planRevision"],
            }
            post_action = {
                "schemaVersion": "agent-lifecycle-control-gate.v1",
                "gateType": "post-action",
                "status": "PASS",
                "blocking": False,
                "selected": True,
                "enforcementActive": True,
                "blockers": [],
                "productionPromotionClaimed": False,
            }
            post_action["gateDigest"] = canonical_digest(post_action)
            post_action["status"] = "FAIL"
            state["tasks"][0]["lifecycleControlPostAction"] = post_action

            with self.assertRaises(LifecycleError) as raised:
                _require_control_task_acceptance(state, state["tasks"][0])

            self.assertEqual(raised.exception.code, "lifecycle-control-evidence-required")

    def test_task_start_adopts_exact_strategy_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, strategy = _write_strategy_start_bundle(root)

            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-strategy",
                expected_revision=1,
                source_revision="source",
                strategy_path=strategy_path,
                strategy_inputs=_strategy_start_inputs(),
                reason="strategy-aware launch",
            )

            task = json.loads(state_path.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(task["attemptExecutionStrategy"]["strategyDigest"], strategy["strategyDigest"])
            self.assertEqual(task["attemptExecutionStrategy"]["attempt"], 1)
            self.assertEqual(task["modelRoute"]["decisionDigest"], strategy["modelRoute"]["decisionDigest"])

    def test_task_start_rejects_capability_drift_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, _strategy = _write_strategy_start_bundle(root)
            capability_path = root / "adapters/codex/capabilities.manifest.json"
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
            capability["maturity"] = "drifted"
            capability_path.write_text(json.dumps(capability), encoding="utf-8")
            before = state_path.read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-strategy",
                    expected_revision=1,
                    source_revision="source",
                    strategy_path=strategy_path,
                    strategy_inputs=_strategy_start_inputs(),
                    reason="must fail closed",
                )

            self.assertEqual(raised.exception.code, "execution-strategy-capability-stale")
            self.assertEqual(state_path.read_bytes(), before)

    def test_task_start_rejects_descriptor_drift_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, _strategy = _write_strategy_start_bundle(root)
            descriptor_path = root / "adapters/codex/adapter.descriptor.json"
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["maturity"] = "drifted"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            self._assert_strategy_start_fails_closed(
                state_path,
                strategy_path,
                expected_code="execution-strategy-descriptor-stale",
            )

    def test_task_start_rejects_stale_target_attempt_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, strategy = _write_strategy_start_bundle(root)
            strategy["lineage"]["targetAttempt"] = 2
            strategy["adoptionBinding"]["targetAttempt"] = 2
            _rewrite_strategy(root / strategy_path, strategy)

            self.assertEqual(validate_execution_strategy(strategy)["status"], "PASS")
            self._assert_strategy_start_fails_closed(
                state_path,
                strategy_path,
                expected_code="execution-strategy-lineage-mismatch",
            )

    def test_task_start_rejects_present_project_profile_drift_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = {"schemaVersion": "agent-project-profile.v1", "profileId": "test-profile"}
            state_path, strategy_path, _strategy = _write_strategy_start_bundle(root, project_profile=profile)
            profile["profileId"] = "drifted"
            (root / ".alk/project-profile.json").write_text(json.dumps(profile), encoding="utf-8")

            self._assert_strategy_start_fails_closed(
                state_path,
                strategy_path,
                expected_code="execution-strategy-project-profile-stale",
            )

    def test_task_start_rejects_policy_input_drift_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, _strategy = _write_strategy_start_bundle(root)
            policy_path = root / "profiles/risk-execution-policy.v1.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["tiers"]["S2"]["maxInvocations"] -= 1
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            self._assert_strategy_start_fails_closed(
                state_path,
                strategy_path,
                expected_code="execution-strategy-policy-input-stale",
            )

    def test_task_start_rejects_recomputed_quality_floor_forgery(self) -> None:
        self._assert_recomputed_strategy_forgery_rejected(
            lambda strategy: strategy["quality"].update(
                {"qualityFloor": "light", "selectedMode": "light", "qualityFloorPreserved": True}
            )
        )

    def test_task_start_rejects_recomputed_route_forgery(self) -> None:
        def forge(strategy: dict) -> None:
            route = strategy["modelRoute"]
            route["modelClass"] = "compact-code"
            route["decisionDigest"] = canonical_digest(
                {key: value for key, value in route.items() if key != "decisionDigest"}
            )
            strategy["sourceDecisionDigests"]["modelRoute"] = route["decisionDigest"]

        self._assert_recomputed_strategy_forgery_rejected(forge)

    def test_task_start_rejects_recomputed_resource_cap_forgery(self) -> None:
        def forge(strategy: dict) -> None:
            for field in ("maxBillableTokens", "maxInvocations", "maxWallSeconds"):
                strategy["resourceCaps"][field] *= 1000

        self._assert_recomputed_strategy_forgery_rejected(forge)

    def _assert_recomputed_strategy_forgery_rejected(
        self,
        mutate: Callable[[dict[str, Any]], None],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, strategy_path, strategy = _write_strategy_start_bundle(root)
            mutate(strategy)
            _rewrite_strategy(root / strategy_path, strategy)

            self.assertEqual(validate_execution_strategy(strategy)["status"], "PASS")
            self._assert_strategy_start_fails_closed(
                state_path,
                strategy_path,
                expected_code="execution-strategy-policy-content-mismatch",
            )

    def _assert_strategy_start_fails_closed(
        self,
        state_path: Path,
        strategy_path: str,
        *,
        expected_code: str,
    ) -> None:
        before = state_path.read_bytes()
        with self.assertRaises(LifecycleError) as raised:
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-strategy",
                expected_revision=1,
                source_revision="source",
                strategy_path=strategy_path,
                strategy_inputs=_strategy_start_inputs(),
                reason="must fail closed",
            )
        self.assertEqual(raised.exception.code, expected_code)
        self.assertEqual(state_path.read_bytes(), before)


def _write_strategy_start_bundle(
    root: Path,
    *,
    project_profile: dict[str, Any] | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    state_path = _write_state(root, phase="RUNNING")
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "title": "Strategy task"},
        "specification": {
            "tier": "S2",
            "requirements": [{"id": "R-1", "description": "Use exact strategy"}],
            "tierResolutionRequest": {"riskFlags": {"architecture": True}, "capabilityHints": []},
        },
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Task",
                "owner": "worker",
                "dependsOn": [],
                "writes": ["src"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {"criteria": [{"id": "AC-1", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]}]},
    }
    plan_digest = canonical_digest(manifest)
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "packageId": "package",
        "planRevision": 1,
        "manifestHash": plan_digest,
    }
    manifest_path = "tasks/strategy/plan.manifest.json"
    write_json_create(root / manifest_path, manifest)
    write_json_create(root / "tasks/strategy/plan.lock.json", lock)
    descriptor = _load_repo_json("adapters/codex/adapter.descriptor.json")
    capability = _load_repo_json("adapters/codex/capabilities.manifest.json")
    write_json_create(root / "adapters/codex/adapter.descriptor.json", descriptor)
    write_json_create(root / "adapters/codex/capabilities.manifest.json", capability)
    for path in (
        "profiles/risk-execution-policy.v1.json",
        "profiles/model-routing-profile.v1.json",
        "profiles/lifecycle-baselines.v1.json",
        "profiles/hosts/codex-live-profile.v1.json",
    ):
        write_json_create(root / path, _load_repo_json(path))
    if project_profile is not None:
        write_json_create(root / ".alk/project-profile.json", project_profile)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["planDigest"] = plan_digest
    state["manifestPath"] = manifest_path
    state_path.write_text(json.dumps(state), encoding="utf-8")
    strategy = resolve_execution_strategy(
        manifest=deepcopy(manifest),
        lock=deepcopy(lock),
        state=deepcopy(state),
        task_id="WS-01",
        adapter_id="codex",
        adapter_host="codex",
        operation_id="start-strategy",
        expected_revision=1,
        source_revision="source",
        requested_risk="auto",
        risk_policy=_load_temp_json(root, "profiles/risk-execution-policy.v1.json"),
        routing_profile=_load_temp_json(root, "profiles/model-routing-profile.v1.json"),
        baseline_profile=_load_temp_json(root, "profiles/lifecycle-baselines.v1.json"),
        host_profile=_load_temp_json(root, "profiles/hosts/codex-live-profile.v1.json"),
        project_profile_digest=canonical_digest(project_profile) if project_profile is not None else None,
        descriptor=descriptor,
        capability_manifest=capability,
        target_attempt=1,
        descriptor_path="adapters/codex/adapter.descriptor.json",
        capability_manifest_path="adapters/codex/capabilities.manifest.json",
        project_profile_path=".alk/project-profile.json",
    )
    strategy_path = "work/WS-01/execution-strategy.json"
    write_json_create(root / strategy_path, strategy)
    return state_path, strategy_path, strategy


def _strategy_start_inputs() -> dict[str, Any]:
    return {
        "requestedRisk": "auto",
        "riskPolicyPath": "profiles/risk-execution-policy.v1.json",
        "routingProfilePath": "profiles/model-routing-profile.v1.json",
        "baselineProfilePath": "profiles/lifecycle-baselines.v1.json",
        "hostProfilePath": "profiles/hosts/codex-live-profile.v1.json",
        "descriptorPath": "adapters/codex/adapter.descriptor.json",
        "capabilityManifestPath": "adapters/codex/capabilities.manifest.json",
        "projectProfilePath": ".alk/project-profile.json",
    }


def _rewrite_strategy(path: Path, strategy: dict[str, Any]) -> None:
    strategy["strategyDigest"] = canonical_digest(
        {key: value for key, value in strategy.items() if key != "strategyDigest"}
    )
    path.write_text(json.dumps(strategy), encoding="utf-8")


def _load_temp_json(root: Path, path: str) -> dict[str, Any]:
    return json.loads((root / path).read_text(encoding="utf-8"))


def _load_repo_json(path: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
