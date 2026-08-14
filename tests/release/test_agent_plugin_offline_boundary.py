from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.release.validate_agent_plugin_offline_boundary import validate_offline_boundary


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginOfflineBoundaryTests(unittest.TestCase):
    def test_safe_source_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "safe.py"
            path.write_text("from pathlib import Path\nvalue = Path('.')\n", encoding="utf-8")
            self.assertEqual(validate_offline_boundary([path])["status"], "PASS")

    def test_process_and_network_imports_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe.py"
            path.write_text("import subprocess\nsubprocess.run(['echo', 'x'])\n", encoding="utf-8")
            result = validate_offline_boundary([path])
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(result["blockers"])

    def test_live_probe_scope_is_explicit_but_offline_scope_cannot_start_processes(self) -> None:
        shipped = validate_offline_boundary(
            [ROOT / "src/agent_lifecycle/host_protocol/agent_plugin_qualification.py"]
        )
        self.assertEqual(shipped["status"], "PASS")
        self.assertIn("_default_probe_runner", shipped["checks"][0]["scope"]["liveHostExecutionFunctions"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_plugin_qualification.py"
            path.write_text(
                "def build_offline_qualification_receipt():\n"
                "    from agent_lifecycle.adapter_sessions.process import run_process as execute\n"
                "    return execute([])\n",
                encoding="utf-8",
            )
            result = validate_offline_boundary([path])
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("offline-process-call", {item["code"] for item in result["blockers"]})

            for call in ("os.popen('x')", "os.posix_spawn('x', ['x'], os.environ)"):
                path.write_text(
                    "def build_offline_qualification_receipt():\n"
                    "    import os\n"
                    f"    return {call}\n",
                    encoding="utf-8",
                )
                result = validate_offline_boundary([path])
                self.assertEqual(result["status"], "FAIL")
                self.assertIn("offline-process-call", {item["code"] for item in result["blockers"]})

            path.write_text(
                "def _default_probe_runner():\n"
                "    from agent_lifecycle.adapter_sessions.process import run_process\n"
                "    return run_process([])\n",
                encoding="utf-8",
            )
            result = validate_offline_boundary([path])
            self.assertEqual(result["status"], "FAIL")

            fake_module = Path(tmp) / "src/agent_lifecycle/host_protocol/agent_plugin_qualification.py"
            fake_module.parent.mkdir(parents=True)
            fake_module.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            result = validate_offline_boundary([fake_module])
            self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
