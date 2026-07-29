from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class CliAdapterCommandTests(unittest.TestCase):
    def test_adapter_scaffold_dry_run_does_not_write(self) -> None:
        # NEG-R03-14 Unsafe Adapter Scaffold
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload = _run_cli(["adapter", "scaffold", "--host", "synthetic-host", "--target", str(root), "--dry-run"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-adapter-scaffold-result.v1")
            self.assertEqual(payload["status"], "DRY_RUN")
            self.assertFalse((root / "adapters/synthetic-host/adapter.descriptor.json").exists())

    def test_adapter_scaffold_writes_experimental_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload = _run_cli(["adapter", "scaffold", "--host", "synthetic-host", "--target", str(root)])

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "PASS")
            descriptor = root / "adapters/synthetic-host/adapter.descriptor.json"
            projection = root / "adapters/synthetic-host/projection.manifest.json"
            event_bridge = root / "adapters/synthetic-host/event-bridge.md"
            validation_doc = root / "adapters/synthetic-host/validation.md"
            baseline = root / "conformance/adapters/synthetic-host/offline-baseline.json"
            docs = root / "docs/adapters/synthetic-host.md"
            self.assertTrue(descriptor.is_file())
            self.assertTrue(projection.is_file())
            self.assertTrue(event_bridge.is_file())
            self.assertTrue(validation_doc.is_file())
            self.assertTrue(baseline.is_file())
            self.assertTrue(docs.is_file())
            descriptor_payload = json.loads(descriptor.read_text(encoding="utf-8"))
            projection_payload = json.loads(projection.read_text(encoding="utf-8"))
            self.assertEqual(descriptor_payload["maturity"], "EXPERIMENTAL")
            self.assertIsNone(descriptor_payload["liveTestedHostRange"])
            self.assertFalse(descriptor_payload["modelRouting"]["providerModelNamesInCore"])
            self.assertEqual(projection_payload["maturity"], "EXPERIMENTAL")
            self.assertEqual(projection_payload["eventBridge"]["status"], "placeholder")
            self.assertEqual(projection_payload["eventBridge"]["runtimeDispatch"], "not-implemented-fail-closed")
            self.assertFalse(projection_payload["providerModelNamesInCore"])
            self.assertIn("requires bounded live host conformance", validation_doc.read_text(encoding="utf-8"))

            code, validation = _run_cli(
                [
                    "adapter",
                    "validate",
                    "--descriptor",
                    str(descriptor),
                    "--baseline",
                    str(ROOT / "conformance/core/adapter-baseline.v1.json"),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(validation["status"], "PASS")

    def test_adapter_scaffold_accepts_future_host_fixture_without_live_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload = _run_cli(["adapter", "scaffold", "--host", "gemini-cli", "--target", str(root)])

            self.assertEqual(code, 0)
            self.assertEqual(payload["maturity"], "EXPERIMENTAL")
            roles = {item["role"] for item in payload["files"]}
            self.assertIn("projection-manifest", roles)
            self.assertIn("event-bridge-placeholder", roles)
            self.assertIn("validation-instructions", roles)

            descriptor = json.loads((root / "adapters/gemini-cli/adapter.descriptor.json").read_text(encoding="utf-8"))
            self.assertEqual(descriptor["host"], "gemini-cli")
            self.assertEqual(descriptor["maturity"], "EXPERIMENTAL")
            self.assertFalse(descriptor["modelRouting"]["liveVerified"])
            self.assertEqual(descriptor["unsupportedOperationPolicy"], "fail-closed")

    def test_adapter_scaffold_rejects_existing_files(self) -> None:
        # NEG-R03-14 Unsafe Adapter Scaffold
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_run_cli(["adapter", "scaffold", "--host", "synthetic-host", "--target", str(root)])[0], 0)

            code, payload = _run_cli(["adapter", "scaffold", "--host", "synthetic-host", "--target", str(root)])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "adapter-scaffold-target-exists")

    def test_adapter_scaffold_rejects_invalid_host_and_verified_maturity(self) -> None:
        # NEG-R03-14 Unsafe Adapter Scaffold
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload = _run_cli(["adapter", "scaffold", "--host", "Bad.Host", "--target", str(root)])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "invalid-adapter-host")

            code, payload = _run_cli(
                [
                    "adapter",
                    "scaffold",
                    "--host",
                    "synthetic-host",
                    "--target",
                    str(root),
                    "--maturity",
                    "VERIFIED",
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "adapter-scaffold-verified-forbidden")

    def test_adapter_validate_cli_checks_descriptor_and_host_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            receipt = root / "receipt.json"
            request.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-host-operation-request.v1",
                        "operationId": "adapter-op-1",
                        "capability": "install",
                        "inputs": {},
                        "outputs": [],
                        "constraints": {},
                    }
                ),
                encoding="utf-8",
            )
            receipt.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-host-operation-receipt.v1",
                        "operationId": "adapter-op-1",
                        "capability": "install",
                        "status": "PASS",
                        "outputs": [],
                        "usage": {},
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(
                [
                    "adapter",
                    "validate",
                    "--descriptor",
                    str(ROOT / "adapters/codex/adapter.descriptor.json"),
                    "--baseline",
                    str(ROOT / "conformance/core/adapter-baseline.v1.json"),
                    "--request",
                    str(request),
                    "--receipt",
                    str(receipt),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-host-adapter-validation.v1")
            self.assertEqual(payload["status"], "PASS")

    def test_adapter_validate_allows_verified_descriptor_with_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor = json.loads((ROOT / "adapters/claude/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor["maturity"] = "VERIFIED"
            descriptor["liveTestedHostRange"] = {
                "host": "claude-code",
                "minimumVersion": "2.1.220",
                "maximumVersion": "2.1.220",
                "evidence": [
                    "tasks/release-0-5/evidence/live-host-conformance-claude-code.json",
                    "tasks/release-0-5/evidence/live-calibration-verification-claude-code.json",
                ],
            }
            descriptor["modelRouting"]["liveVerified"] = True
            descriptor_path = root / "claude.verified.descriptor.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "adapter",
                    "validate",
                    "--descriptor",
                    str(descriptor_path),
                    "--baseline",
                    str(ROOT / "conformance/core/adapter-baseline.v1.json"),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["maturity"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
