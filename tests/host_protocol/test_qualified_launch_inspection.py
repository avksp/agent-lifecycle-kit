from __future__ import annotations

import unittest

from agent_lifecycle.host_protocol.inspection_claude import _inspect_claude
from agent_lifecycle.host_protocol.inspection_codex import _inspect_codex
from agent_lifecycle.host_protocol.inspection_common import CommandRun


class QualifiedLaunchInspectionTests(unittest.TestCase):
    def test_codex_safe_surface_is_discovered_without_task(self) -> None:
        def run(argv: list[str], timeout: float) -> CommandRun:
            del timeout
            return CommandRun(0, "codex-cli 0.147.0" if "--version" in argv else "--json --sandbox", "")
        checks, capabilities, blockers = _inspect_codex(descriptor_path=None, host_bin="codex", project_root=None, timeout_seconds=1, command_runner=run)  # type: ignore[arg-type]
        self.assertFalse(blockers)
        self.assertTrue(all(item["status"] == "PASS" for item in checks))
        self.assertFalse(capabilities["permissionMode"]["implicitApproval"])

    def test_claude_safe_surface_is_discovered_without_task(self) -> None:
        def run(argv: list[str], timeout: float) -> CommandRun:
            del timeout
            return CommandRun(0, "2.1.226 (Claude Code)" if "--version" in argv else "--print --output-format --permission-mode", "")
        checks, capabilities, blockers = _inspect_claude(descriptor_path=None, host_bin="claude", project_root=None, timeout_seconds=1, command_runner=run)  # type: ignore[arg-type]
        self.assertFalse(blockers)
        self.assertTrue(all(item["status"] == "PASS" for item in checks))
        self.assertFalse(capabilities["permissionMode"]["implicitApproval"])
