"""Existing formats and unrelated native semantics remain independent of signatures."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.operator_signature_schemas import operator_authority_marker
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from agent_lifecycle.workflow import adopt_plan, authorize_execution
from agent_lifecycle.workflow.initialization import migrate_workflow_state
from tests.contracts.test_operator_signature import envelope, inventory, policy, state
from tests.workflow.helpers import _write_state
from tests.workflow.test_authorization import _receipt
from tests.workflow.test_plan_adoption import _write_authority_bundle


class OperatorSignatureCompatibilityTests(unittest.TestCase):
    def test_actual_adoption_uses_v7_and_refuses_automatic_authorization(self):
        for case in ("approval-required", "auto-after-freeze", "missing-freeze-signature"):
            start_mode = "approval-required" if case == "missing-freeze-signature" else case
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_state(root, phase="READY")
                manifest_path = _write_authority_bundle(root, kind="integrity")
                m = json.loads(manifest_path.read_bytes())
                m["baseRevision"] = {"sha": "source-2", "ref": "synthetic"}
                m["operatorSignaturePolicy"] = policy()
                m["operatorSignatureAuthority"] = operator_authority_marker(m["operatorSignaturePolicy"])
                m["packageIntegrity"]["allowedUnlistedFiles"].append("operator-freeze-signature.json")
                manifest_path.write_bytes(canonical_bytes(m) + b"\n")
                (manifest_path.parent / "operator-freeze-signature.json").write_bytes(
                    canonical_bytes(envelope(m)) + b"\n"
                )
                (manifest_path.parent / "plan.lock.json").write_bytes(
                    canonical_bytes(build_plan_lock_v2(m, repository_root=root)) + b"\n"
                )
                index_path = root / m["package"]["artifactRoot"] / "workflow/task-packets/index.json"
                index = json.loads(index_path.read_bytes())
                index["manifestDigest"] = canonical_digest(m)
                index_path.write_bytes(canonical_bytes(index) + b"\n")
                if case == "missing-freeze-signature":
                    (manifest_path.parent / "operator-freeze-signature.json").unlink()
                before = inventory(root)
                args = {
                    "manifest_path": manifest_path,
                    "operation_id": "adopt",
                    "expected_revision": 1,
                    "source_revision": "source-2",
                    "reset_tasks": True,
                    "start_mode": start_mode,
                }
                if case != "approval-required":
                    with self.assertRaises(LifecycleError) as caught:
                        adopt_plan(path, **args)
                    self.assertEqual(
                        caught.exception.code,
                        "operator-signature-missing"
                        if case == "missing-freeze-signature"
                        else "operator-signature-invalid",
                    )
                    self.assertEqual(before, inventory(root))
                else:
                    adopt_plan(path, **args)
                    actual = json.loads(path.read_bytes())
                    self.assertEqual(actual["schemaVersion"], "agent-workflow-state.v7")
                    self.assertEqual(actual["operatorSignaturePolicy"], m["operatorSignaturePolicy"])
                    self.assertEqual(actual["phase"], "AWAITING_AUTHORIZATION")
                    self.assertFalse(actual["authorization"]["granted"])

    def test_legacy_authorization_avoids_signature_io_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = state("advisory")
            value.pop("operatorSignaturePolicy")
            value.pop("storage")
            path = root / "run.state.json"
            path.write_bytes(canonical_bytes(value) + b"\n")
            (root / "authorization.json").write_bytes(canonical_bytes(_receipt(value)) + b"\n")
            with patch(
                "agent_lifecycle.contracts.operator_signature.read_stable_repository_file",
                side_effect=AssertionError("off must not read signatures"),
            ):
                authorize_execution(
                    path,
                    operation_id="operation",
                    expected_revision=1,
                    source_revision="source",
                    receipt_path="authorization.json",
                    reason="Legacy fixture",
                )
            current = json.loads(path.read_bytes())
            self.assertEqual(current["schemaVersion"], "agent-workflow-state.v4")
            self.assertNotIn("operatorSignature", current["authorization"])
            self.assertNotIn("operatorSignaturePolicy", current)

    def test_required_marker_cannot_hide_inside_legacy_tag(self):
        original = state()
        for version in ("v3", "v4", "v5", "v6"):
            value = deepcopy(original)
            value["schemaVersion"] = "agent-workflow-state." + version
            with self.subTest(version=version), self.assertRaises(LifecycleError):
                validate_workflow_state(value)

    def test_required_v7_cannot_use_existing_migration_to_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            path.write_bytes(canonical_bytes(state()) + b"\n")
            before = path.read_bytes()
            with self.assertRaises(LifecycleError) as caught:
                migrate_workflow_state(path, operation_id="downgrade", expected_revision=1, source_revision="source")
            self.assertEqual(caught.exception.code, "operator-signature-downgrade-unsupported")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
