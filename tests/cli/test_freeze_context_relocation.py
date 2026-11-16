from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from agent_lifecycle.cli.plan_lock_commands import _relocated_candidate
from agent_lifecycle.compiler.task_packets import _packet
from agent_lifecycle.contracts import canonical_digest
from tests.cli.test_artifact_authoring_commands import _write_draft


class FreezeContextRelocationTests(unittest.TestCase):
    def test_mixed_workstreams_relocate_context_and_render_candidate_packets(self):
        with tempfile.TemporaryDirectory() as folder:
            _, manifest = _write_draft(Path(folder))
            first = manifest["workstreams"][0]
            first["contextRefs"] = ["plan/acceptance-criteria.md", "docs/shared.md"]
            second = deepcopy(first)
            second["id"] = "WS-02"
            # Relocation treats this metadata as opaque; its separate validator
            # remains responsible for the actual decision-research contract.
            second["decisionResearch"] = {"opaque": True}
            manifest["workstreams"] = [first, second]
            before = deepcopy(manifest)
            candidate, _ = _relocated_candidate(manifest, "plan", "work/frozen")
            for workstream in candidate["workstreams"]:
                self.assertEqual(workstream["contextRefs"], ["work/frozen/acceptance-criteria.md", "docs/shared.md"])
                packet = _packet(candidate, canonical_digest(candidate), workstream)
                self.assertEqual(packet["context"]["refs"], workstream["contextRefs"])
            self.assertEqual(candidate["workstreams"][1]["decisionResearch"], {"opaque": True})
            self.assertEqual(manifest, before)


if __name__ == "__main__":
    unittest.main()
