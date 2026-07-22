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
        self.assertEqual(get_schema("agent-lifecycle-error.v1")["additionalProperties"], False)
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
