from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.adapter_sessions.lifecycle_control import (
    post_action_gate,
    pre_action_gate,
    require_pre_action,
    stop_gate,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    build_default_lifecycle_control_policy,
    build_lifecycle_control_event,
)

ROOT = Path(__file__).resolve().parents[2]
V2_FIXTURE = ROOT / "tests/freeze/fixtures/canonical-v2-plan-package"


class AdapterLifecycleControlTests(unittest.TestCase):
    def test_pre_and_post_wrappers_bind_the_adapter_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, state_path, policy_path = _write_bundle(root)
            pre = pre_action_gate(
                manifest_path=manifest_path,
                lock_path=lock_path,
                state_path=state_path,
                operation="file-edit",
                action_digest="c" * 64,
                paths=["src/example.py"],
                next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
                task_id="WS-01",
                expected_state_revision=1,
                policy_path=policy_path,
            )
            self.assertEqual(pre["status"], "PASS")
            event = build_lifecycle_control_event(
                pre["request"],
                event_id="event-1",
                event_type="post-action",
                status="PASS",
                producer_id="adapter-hook",
                outcome={"status": "PASS"},
            )
            post = post_action_gate(
                pre_action=pre,
                manifest_path=manifest_path,
                actual_changed_paths=["src/example.py"],
                outcome={"status": "PASS", "changed": True},
                event=event,
                policy_path=policy_path,
            )

            self.assertEqual(post["status"], "PASS")
            self.assertEqual(post["requestDigest"], pre["request"]["requestDigest"])

    def test_explicit_stale_state_revision_is_blocked_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, state_path, policy_path = _write_bundle(root)

            gate = pre_action_gate(
                manifest_path=manifest_path,
                lock_path=lock_path,
                state_path=state_path,
                operation="file-edit",
                action_digest="c" * 64,
                paths=["src/example.py"],
                requested_level="ENFORCED",
                expected_state_revision=2,
                policy_path=policy_path,
            )

            self.assertEqual(gate["status"], "BLOCKED")
            self.assertIn("state-revision-mismatch", {item["code"] for item in gate["blockers"]})
            with self.assertRaises(LifecycleError):
                require_pre_action(
                    manifest_path=manifest_path,
                    lock_path=lock_path,
                    state_path=state_path,
                    operation="file-edit",
                    action_digest="c" * 64,
                    paths=["src/example.py"],
                    requested_level="ENFORCED",
                    expected_state_revision=2,
                    policy_path=policy_path,
                )

    def test_stop_wrapper_requires_post_action_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, state_path, policy_path = _write_bundle(root)
            final_audit = {"status": "PASS", "planDigest": json.loads(state_path.read_text())["planDigest"]}
            final_proof = {
                "schemaVersion": "agent-run-final-proof.v1",
                "runId": "run",
                "planDigest": final_audit["planDigest"],
            }

            gate = stop_gate(
                state_path=state_path,
                final_audit=final_audit,
                final_proof=final_proof,
                policy_path=policy_path,
            )

            self.assertEqual(gate["status"], "BLOCKED")
            self.assertIn("pre-action-evidence-missing", {item["code"] for item in gate["blockers"]})
            self.assertIn("post-action-evidence-missing", {item["code"] for item in gate["blockers"]})

    def test_pre_action_requires_explicit_state_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, lock_path, state_path, policy_path = _write_bundle(root)
            gate = pre_action_gate(
                manifest_path=manifest_path,
                lock_path=lock_path,
                state_path=state_path,
                operation="file-edit",
                action_digest="c" * 64,
                paths=["src/example.py"],
                next_action={"projectedAction": {"type": "launch-tasks", "taskIds": ["WS-01"]}},
                task_id="WS-01",
                policy_path=policy_path,
            )

            self.assertEqual(gate["status"], "BLOCKED")
            self.assertIn("state-revision-mismatch", {item["code"] for item in gate["blockers"]})

    def test_v2_package_requires_repository_root_for_pre_action(self) -> None:
        manifest_path = V2_FIXTURE / "plan.manifest.json"
        lock_path = V2_FIXTURE / "plan.lock.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = canonical_digest(manifest)
        policy = deepcopy(build_default_lifecycle_control_policy())
        policy["operations"]["run-finalize"] = {
            "declaredLevel": "ENFORCED",
            "supported": True,
            "qualified": True,
            "effectiveLevel": "ENFORCED",
            "qualificationStatus": "QUALIFIED",
            "hostOwnedPreAction": True,
        }
        policy_body = {key: value for key, value in policy.items() if key != "policyDigest"}
        policy = {**policy_body, "policyDigest": canonical_digest(policy_body)}
        state = {
            "runId": "run",
            "packageId": manifest["package"]["id"],
            "planRevision": manifest["planRevision"],
            "planDigest": digest,
            "stateRevision": 1,
            "lifecycleControl": {
                "level": "ENFORCED",
                "source": "frozen-plan",
                "planDigest": digest,
                "planRevision": manifest["planRevision"],
                "policy": policy,
            },
            "tasks": [{"id": "WS-FIXTURE", "status": "ACCEPTED", "required": True}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            kwargs = {
                "manifest_path": manifest_path,
                "lock_path": lock_path,
                "state_path": state_path,
                "operation": "run-finalize",
                "action_digest": "c" * 64,
                "paths": [],
                "next_action": {"projectedAction": {"type": "finalize-run", "taskIds": []}},
                "expected_state_revision": 1,
            }

            without_root = pre_action_gate(**kwargs)
            self.assertEqual(without_root["status"], "BLOCKED")
            self.assertIn("plan-package-integrity-failed", {item["code"] for item in without_root["blockers"]})

            with_root = pre_action_gate(**kwargs, repository_root=ROOT)
            self.assertEqual(with_root["status"], "PASS")
            self.assertTrue(with_root["decision"]["hostActionAllowed"])


def _write_bundle(root: Path) -> tuple[Path, Path, Path, Path]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [{"id": "WS-01", "writes": ["src"]}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lock = {
        "schemaVersion": "agent-plan-lock.v1",
        "packageId": "package",
        "planRevision": 1,
        "manifestHash": digest,
    }
    lock_path = manifest_path.with_name("plan.lock.json")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    policy = deepcopy(build_default_lifecycle_control_policy())
    for operation in ("file-edit", "run-finalize"):
        policy["operations"][operation] = {
            "declaredLevel": "ENFORCED",
            "supported": True,
            "qualified": True,
            "effectiveLevel": "ENFORCED",
            "qualificationStatus": "QUALIFIED",
            "hostOwnedPreAction": True,
        }
    policy_body = {key: value for key, value in policy.items() if key != "policyDigest"}
    policy = {**policy_body, "policyDigest": canonical_digest(policy_body)}
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    state = {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": digest,
        "stateRevision": 1,
        "lifecycleControl": {
            "level": "ENFORCED",
            "source": "frozen-plan",
            "planDigest": digest,
            "planRevision": 1,
        },
        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "required": True}],
    }
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return manifest_path, lock_path, state_path, policy_path


if __name__ == "__main__":
    unittest.main()
