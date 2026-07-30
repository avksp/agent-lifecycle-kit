from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdapterConformanceToolTests(unittest.TestCase):
    def test_current_adapters_pass_offline_conformance_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "adapter-conformance.json"

            result = _run_tool("--evidence", str(evidence))

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(payload["schemaVersion"], "agent-adapter-conformance-verification.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(set(payload["hosts"]), {"claude", "codex", "cursor", "gemini-cli", "hermes", "kimi-code", "opencode", "qwen-code"})
            self.assertFalse(payload["productionPromotionClaimed"])

    def test_tool_fails_closed_when_capability_manifest_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_dir = root / "adapters/opencode"
            conformance_dir = root / "conformance/adapters/opencode"
            adapter_dir.mkdir(parents=True)
            conformance_dir.mkdir(parents=True)
            shutil.copyfile(ROOT / "adapters/opencode/adapter.descriptor.json", adapter_dir / "adapter.descriptor.json")
            shutil.copyfile(ROOT / "conformance/adapters/opencode/offline-baseline.json", conformance_dir / "offline-baseline.json")
            evidence = root / "adapter-conformance.json"

            result = _run_tool(
                "--adapter-root",
                str(root / "adapters"),
                "--conformance-root",
                str(root / "conformance/adapters"),
                "--host",
                "opencode",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("missing-capability-manifest", {item["code"] for item in payload["blockers"]})

    def test_tool_fails_closed_when_declared_event_capture_lacks_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_dir = root / "adapters/opencode"
            conformance_dir = root / "conformance/adapters/opencode"
            adapter_dir.mkdir(parents=True)
            conformance_dir.mkdir(parents=True)
            for filename in ("adapter.descriptor.json", "capabilities.manifest.json"):
                shutil.copyfile(ROOT / f"adapters/opencode/{filename}", adapter_dir / filename)
            shutil.copyfile(ROOT / "conformance/adapters/opencode/offline-baseline.json", conformance_dir / "offline-baseline.json")
            evidence = root / "adapter-conformance.json"

            result = _run_tool(
                "--adapter-root",
                str(root / "adapters"),
                "--conformance-root",
                str(root / "conformance/adapters"),
                "--host",
                "opencode",
                "--evidence",
                str(evidence),
            )

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("adapter-event-capture-receipt-missing", {item["code"] for item in payload["blockers"]})


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "tools/release/validate_adapter_conformance.py",
            "--baseline",
            "conformance/core/adapter-baseline.v1.json",
            *args,
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


if __name__ == "__main__":
    unittest.main()
