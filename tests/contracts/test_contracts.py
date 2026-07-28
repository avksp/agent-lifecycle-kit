from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import (  # noqa: E402
    LifecycleError,
    canonical_digest,
    is_under_repo_path,
    normalize_repo_path,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_canonical_digest_is_key_order_stable(self) -> None:
        self.assertEqual(canonical_digest({"b": 2, "a": 1}), canonical_digest({"a": 1, "b": 2}))

    def test_write_json_create_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            write_json_create(path, {"ok": True})
            self.assertEqual(read_json_object(path)["ok"], True)
            with self.assertRaises(FileExistsError):
                write_json_create(path, {"ok": False})

    def test_repo_path_rejects_absolute_and_traversal(self) -> None:
        self.assertEqual(normalize_repo_path("plans/run/state.json"), "plans/run/state.json")
        for bad in ["/tmp/x", "../x", "a/../x", "a\\b", "file://x"]:
            with self.assertRaises(LifecycleError):
                normalize_repo_path(bad)

    def test_repo_path_under_helper_matches_path_segment_boundaries(self) -> None:
        self.assertTrue(is_under_repo_path("plans/run/state.json", "plans"))
        self.assertTrue(is_under_repo_path("plans", "plans"))
        self.assertFalse(is_under_repo_path("plans-old/state.json", "plans"))

    def test_host_operation_request_is_closed(self) -> None:
        request = HostOperationRequest(
            operation_id="op-1",
            capability="run-tests",
            inputs={"target": "tests"},
            outputs=[],
            constraints={"network": "denied"},
        )
        self.assertEqual(HostOperationRequest.from_json(request.to_json()), request)
        invalid = request.to_json()
        invalid["provider"] = "opaque-host-name"
        with self.assertRaises(LifecycleError):
            HostOperationRequest.from_json(invalid)

    def test_host_operation_request_carries_attempt_model_route(self) -> None:
        request = HostOperationRequest(
            operation_id="op-1",
            capability="task-attempt",
            inputs={"taskId": "WS-01"},
            outputs=[{"role": "task-result", "path": "tasks/WS-01/attempt-1/task-result.json"}],
            constraints={"usageReceiptRequired": True},
            model_route={
                "schemaVersion": "agent-lifecycle-model-route-decision.v1",
                "operationId": "route-WS-01",
                "modelClass": "standard-code",
                "decisionDigest": "4" * 64,
            },
        )
        decoded = HostOperationRequest.from_json(request.to_json())
        self.assertEqual(decoded.model_route["modelClass"], "standard-code")

    def test_host_operation_receipt_status_is_bounded(self) -> None:
        receipt = HostOperationReceipt(
            operation_id="op-1",
            capability="run-tests",
            status="PASS",
            outputs=[],
            usage={"toolCalls": 1},
        )
        self.assertEqual(HostOperationReceipt.from_json(receipt.to_json()), receipt)
        invalid = receipt.to_json()
        invalid["status"] = "OK"
        with self.assertRaises(LifecycleError):
            HostOperationReceipt.from_json(invalid)

    def test_schema_registry_is_stable_and_closed(self) -> None:
        index = list_schemas()
        ids = {item["id"] for item in index["schemas"]}
        self.assertIn("agent-host-operation-request.v1", ids)
        self.assertIn("agent-lifecycle-model-route-request.v1", ids)
        self.assertIn("agent-lifecycle-model-usage-receipt.v1", ids)
        for schema_id in [
            "agent-host-adapter-validation.v1",
            "agent-release-candidate-inventory.v1",
            "agent-release-assembly-evidence.v1",
            "agent-release-verification-evidence.v1",
            "agent-final-candidate-audit.v1",
            "agent-support-matrix-contract-evidence.v1",
            "agent-deferred-promotion-contract-evidence.v1",
            "agent-neutrality-report.v1",
            "agent-live-calibration-verification.v1",
            "agent-lifecycle-live-calibration-receipt.v1",
            "agent-lifecycle-live-host-conformance-receipt.v1",
            "agent-live-host-conformance-verification.v1",
            "agent-live-host-promotion-plan.v1",
            "agent-live-host-promotion-plan-validation.v1",
            "agent-digest-authority-evidence.v1",
            "agent-docs-compat-evidence.v1",
            "agent-negative-suite-coverage.v1",
            "agent-task-packet-context-fit.v1",
            "agent-packaging-smoke-evidence.v1",
            "agent-adapter-scaffold-result.v1",
            "agent-workflow-lineage-check.v1",
        ]:
            self.assertIn(schema_id, ids)
        self.assertEqual(get_schema("agent-lifecycle-error.v1")["additionalProperties"], False)
        self.assertIn("status", get_schema("agent-final-candidate-audit.v1")["required"])
        self.assertEqual(
            get_schema("agent-release-verification-evidence.v1")["properties"]["productionPromotionClaimed"],
            {"const": False},
        )
        self.assertIn("commands", get_schema("agent-packaging-smoke-evidence.v1")["required"])
        self.assertEqual(get_schema("agent-adapter-scaffold-result.v1")["properties"]["maturity"], {"const": "EXPERIMENTAL"})
        self.assertEqual(get_schema("agent-lifecycle-live-host-conformance-receipt.v1")["properties"]["syntheticReplayUsed"], {"const": False})
        self.assertIn("validationCommands", get_schema("agent-live-host-promotion-plan.v1")["required"])
        self.assertEqual(get_schema("agent-live-host-promotion-plan-validation.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        with self.assertRaises(LifecycleError):
            get_schema("missing.v1")

    def test_json_object_loader_rejects_arrays(self) -> None:
        with self.assertRaises(LifecycleError):
            read_json_object(_json_array_file())


def _json_array_file() -> Path:
    path = Path(tempfile.mkdtemp()) / "array.json"
    path.write_text(json.dumps([]), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
