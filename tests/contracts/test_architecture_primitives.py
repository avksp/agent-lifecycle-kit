from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.quality_modes import MODES, max_mode, mode_index
from agent_lifecycle.contracts.token_estimation import estimate_tokens
from agent_lifecycle.contracts.validation import load_bounded_literal_profile


class ArchitecturePrimitiveTests(unittest.TestCase):
    def test_shared_primitives_are_deterministic(self) -> None:
        self.assertGreater(estimate_tokens({"text": "bounded"}), 0)
        self.assertEqual(max_mode("light", "strict"), "strict")
        self.assertEqual(mode_index(MODES[-1]), len(MODES) - 1)

    def test_literal_profile_loader_does_not_execute_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.py").write_text("PROFILE = {'status': 'PASS'}\n", encoding="utf-8")
            profile = load_bounded_literal_profile(Path("profile.py"), root=root, error_prefix="test-profile")
        self.assertEqual(profile, {"status": "PASS"})


if __name__ == "__main__":
    unittest.main()
