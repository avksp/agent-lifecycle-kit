"""Node syntax/export smoke only; this does not qualify an OpenCode host route."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.changesets.git_io import run_bounded_command

ROOT = Path(__file__).resolve().parents[2]
PROJECTION = ROOT / "adapters/opencode/plugins/agent-lifecycle-kit.js"
NODE_SMOKE = """
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
const bytes = readFileSync(process.argv[1]);
const projection = await import('data:text/javascript;base64,' + bytes.toString('base64'));
assert.deepEqual(Object.keys(projection), ['AgentLifecycleKit']);
const plugin = projection.AgentLifecycleKit;
assert.equal(typeof plugin, 'function');
assert.equal(Object.isFrozen(plugin.alkMetadata), true);
assert.deepEqual(plugin.alkMetadata, {
  name: 'agent-lifecycle-kit',
  maturity: 'VERIFIED',
  descriptor: '../adapter.descriptor.json',
  unsupportedOperationPolicy: 'fail-closed',
  coreSemantics: 'delegated-to-agent-lifecycle-core'
});
assert.deepEqual(await plugin(), {});
console.log(JSON.stringify({
  nodeVersion: process.version,
  sourceSha256: createHash('sha256').update(bytes).digest('hex'),
  exports: Object.keys(projection),
  hooks: []
}));
"""


class OpenCodeProjectionRuntimeTests(unittest.TestCase):
    def test_actual_projection_parses_and_exports_an_empty_plugin(self) -> None:
        node = shutil.which("node")
        if node is None:
            if os.environ.get("ALK_REQUIRE_NODE") == "1" or os.environ.get("CI") == "true":
                self.fail("Node is required for the CI OpenCode projection smoke")
            self.skipTest("Node unavailable; syntax/export smoke is unproven on this machine")
        before = PROJECTION.read_bytes()
        # Use the existing bounded transport; never start OpenCode, Bun or a model.
        with patch.dict(os.environ, {"NODE_OPTIONS": "", "NODE_PATH": ""}):
            result = run_bounded_command(
                [node, "--input-type=module", "--eval", NODE_SMOKE, str(PROJECTION)],
                cwd=ROOT,
                timeout_seconds=15,
                max_stdout_bytes=4096,
                max_stderr_bytes=8192,
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        receipt = json.loads(result.stdout)
        self.assertRegex(receipt["nodeVersion"], r"^v\d+\.\d+\.\d+")
        self.assertEqual(receipt["sourceSha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(receipt["exports"], ["AgentLifecycleKit"])
        self.assertEqual(receipt["hooks"], [])
        self.assertEqual(PROJECTION.read_bytes(), before)
        print("OpenCode projection Node smoke: " + json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
