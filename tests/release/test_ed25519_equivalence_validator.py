from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_ed25519_equivalence import validate_ed25519_equivalence


ROOT = Path(__file__).resolve().parents[2]


class Ed25519EquivalenceValidatorTests(unittest.TestCase):
    def test_current_implementation_passes_vectors_shape_and_ratio(self) -> None:
        payload = validate_ed25519_equivalence(
            module_path=ROOT / "src/agent_lifecycle/neutrality/ed25519.py",
            vectors_path=ROOT / "tests/neutrality/fixtures/rfc8032-ed25519.json",
            reference_path=ROOT / "tests/neutrality/reference_ed25519.py",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["ast"]["scalarPowCalls"], 0)
        self.assertEqual(payload["ast"]["encodeFinalPowCalls"], 1)
        self.assertEqual(payload["benchmark"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
