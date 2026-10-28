"""Isolated payload smoke; release evidence separately checks actual distributions."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tools.release.agent_plugin_package import build_package

ROOT = Path(__file__).resolve().parents[2]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

ISOLATED_SMOKE = """
import contextlib, io, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import agent_lifecycle
from agent_lifecycle.cli import main
from agent_lifecycle.contracts.workflow_storage import (
    iter_historical_snapshots, persist_storage, prepare_storage,
)
from agent_lifecycle.workflow import initialize_workflow_state
from agent_lifecycle.workflow.authorization import renew_execution_authorization
root = Path(sys.argv[2])
assert Path(agent_lifecycle.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
state_path = root / 'initial.json'
initialize_workflow_state(state_path, run_id='isolated-payload', package_id='package')
initial = json.loads(state_path.read_bytes())
assert initial['schemaVersion'] == 'agent-workflow-state.v4'
snapshot = {key: initial[key] for key in (
    'runId', 'packageId', 'planRevision', 'planDigest', 'sourceRevision', 'tasks'
)}
snapshot['financialRole'] = 'HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING'
state = dict(initial, planRevision=1, planDigest='a' * 64,
    sourceRevision='isolated-fixture', priorSnapshots=[snapshot])
prepared = prepare_storage(state, storage_root='store')
persist_storage(root, prepared)
assert list(iter_historical_snapshots(root, prepared.state)) == [snapshot]
assert callable(renew_execution_authorization)
help_text = io.StringIO()
with contextlib.redirect_stdout(help_text):
    try:
        main(['workflow', 'authorization-renew', '--help'])
    except SystemExit as error:
        assert error.code == 0
assert '--receipt' in help_text.getvalue()
assert not any(name == 'tests' or name.startswith('tests.') for name in sys.modules)
print(json.dumps({'status': 'PASS', 'version': agent_lifecycle.__version__}))
"""


class WorkflowStoragePackageTests(unittest.TestCase):
    def test_python_payload_uses_storage_and_renewal_without_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            payload.mkdir()
            shutil.copytree(
                ROOT / "src/agent_lifecycle",
                payload / "agent_lifecycle",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            child = subprocess.run(
                [sys.executable, "-I", "-B", "-c", ISOLATED_SMOKE, str(payload), str(root)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertEqual(json.loads(child.stdout), {"status": "PASS", "version": VERSION})

    def test_plugin_keeps_current_cli_guidance_and_a_separate_runtime_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plugin"
            result = build_package(root=ROOT, version=VERSION, output=output)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse((output / "src").exists())
            for name in ["docs/reference/cli.md", "docs/ru/reference/cli.md"]:
                with self.subTest(name=name):
                    self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())
                    content = (output / name).read_text(encoding="utf-8")
                    self.assertIn("workflow authorization-renew", content)
                    self.assertIn("agent-workflow-state.v5", content)
                    self.assertIn(f"agent-lifecycle-kit=={VERSION}", content)


if __name__ == "__main__":
    unittest.main()
