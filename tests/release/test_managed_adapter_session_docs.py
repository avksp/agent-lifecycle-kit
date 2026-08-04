from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ManagedAdapterSessionDocsTests(unittest.TestCase):
    def test_reference_docs_define_managed_session_boundary(self) -> None:
        english = (ROOT / "docs/reference/managed-adapter-sessions.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/managed-adapter-sessions.md").read_text(encoding="utf-8")

        for text in (english, russian):
            self.assertIn("agent-adapter-session-receipt.v1", text)
            self.assertIn("agent-managed-adapter-launch-receipt.v1", text)
            self.assertIn("agent-adapter-session-resume-receipt.v1", text)
            self.assertIn("adapter session start", text)
            self.assertIn("adapter session resume", text)
            self.assertIn("adapter run", text)
            self.assertIn("WRAPPER_ONLY", text)
            self.assertIn("shell: false", text)

    def test_adapter_docs_match_descriptor_managed_launch_status(self) -> None:
        matrix = (ROOT / "docs/adapters/managed-session-support.md").read_text(encoding="utf-8")
        matrix_ru = (ROOT / "docs/ru/adapters/managed-session-support.md").read_text(encoding="utf-8")

        for descriptor_path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            adapter_id = descriptor_path.parent.name
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            readme = (descriptor_path.parent / "README.md").read_text(encoding="utf-8")
            status = descriptor["managedLaunch"]["status"]

            with self.subTest(adapter=adapter_id):
                self.assertEqual(status, "WRAPPER_ONLY")
                self.assertIn("Managed adapter sessions", readme)
                self.assertIn("Managed session support: `WRAPPER_ONLY`", readme)
                self.assertIn(f"--adapter {adapter_id}", readme)
                self.assertIn("WRAPPER_ONLY", matrix)
                self.assertIn("WRAPPER_ONLY", matrix_ru)

    def test_install_docs_do_not_treat_plugin_as_lifecycle_proof(self) -> None:
        english = (ROOT / "docs/adapters/install.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/adapters/install.md").read_text(encoding="utf-8")

        self.assertIn("plugin installation separate from lifecycle proof", english)
        self.assertIn("установку plugin от доказательства", russian)
        for text in (english, russian):
            self.assertIn("managedLaunch.status: WRAPPER_ONLY", text)
            self.assertIn("agent-adapter-session-receipt.v1", text)


if __name__ == "__main__":
    unittest.main()
