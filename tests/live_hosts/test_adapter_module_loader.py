from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from tools.live_hosts.adapter_module_loader import load_adapter_usage_normalizer  # noqa: E402


class AdapterModuleLoaderTests(unittest.TestCase):
    def test_loader_binds_declared_adapter_local_module(self) -> None:
        normalizer = load_adapter_usage_normalizer("qwen-code", repository_root=ROOT)

        self.assertEqual(normalizer.adapter_id, "qwen-code")
        self.assertEqual(normalizer.status, "FIXTURE_ONLY")
        self.assertEqual(len(normalizer.digest), 64)
        self.assertTrue(callable(normalizer.parse_usage))

    def test_loader_rejects_invalid_adapter_id(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            load_adapter_usage_normalizer("../qwen-code", repository_root=ROOT)
        self.assertEqual(raised.exception.code, "invalid-adapter-id")

    def test_loader_rejects_symlinked_normalizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/qwen-code"
            adapter_root.mkdir(parents=True)
            source_descriptor = json.loads((ROOT / "adapters/qwen-code/adapter.descriptor.json").read_text(encoding="utf-8"))
            (adapter_root / "adapter.descriptor.json").write_text(json.dumps(source_descriptor), encoding="utf-8")
            target = root / "outside.py"
            shutil.copy2(ROOT / "adapters/qwen-code/usage_normalizer.py", target)
            (adapter_root / "usage_normalizer.py").symlink_to(target)

            with self.assertRaises(LifecycleError) as raised:
                load_adapter_usage_normalizer("qwen-code", repository_root=root)

        self.assertEqual(raised.exception.code, "adapter-usage-normalizer-path")


if __name__ == "__main__":
    unittest.main()
