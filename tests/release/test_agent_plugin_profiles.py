from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_agent_plugin_profiles import validate_profiles


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginProfileReleaseTests(unittest.TestCase):
    def test_release_profiles_cover_codex_claude_and_cursor(self) -> None:
        paths = [ROOT / "adapters" / adapter / "agent_plugin_profile.json" for adapter in ("codex", "claude", "cursor")]
        result = validate_profiles(paths)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual({check["adapterId"] for check in result["checks"]}, {"codex", "claude", "cursor"})


if __name__ == "__main__":
    unittest.main()
