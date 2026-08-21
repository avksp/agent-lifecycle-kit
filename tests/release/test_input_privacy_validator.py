from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.release.validate_input_privacy import validate_input_privacy


ROOT = Path(__file__).resolve().parents[2]


class InputPrivacyValidatorTests(unittest.TestCase):
    def test_validator_uses_separate_json_crypto_and_storage_inputs(self) -> None:
        payload = validate_input_privacy(
            canonical_path=ROOT / "src/agent_lifecycle/contracts/canonical.py",
            ed25519_path=ROOT / "src/agent_lifecycle/neutrality/ed25519.py",
            session_store_path=ROOT / "src/agent_lifecycle/adapter_sessions/session_store.py",
            planning_session_path=ROOT / "src/agent_lifecycle/adapter_sessions/planning_session.py",
            checkpoint_store_path=ROOT / "src/agent_lifecycle/context/checkpoint_store.py",
            workflow_state_path=ROOT / "src/agent_lifecycle/workflow/state.py",
        )
        self.assertEqual(payload["status"], "PASS")
        expected_platform = "POSIX" if os.name != "nt" else "WINDOWS"
        self.assertEqual(payload["permissionContract"]["platform"], expected_platform)
        self.assertEqual(payload["permissionContract"]["posixModesAuthoritative"], os.name != "nt")
        self.assertFalse(any(Path(item["name"]).is_absolute() for item in payload["files"]))

    def test_validator_fails_when_a_required_boundary_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "canonical.py"
            source = (ROOT / "src/agent_lifecycle/contracts/canonical.py").read_text(encoding="utf-8")
            altered.write_text(source.replace("MAX_JSON_NESTING", "REMOVED_JSON_NESTING"), encoding="utf-8")
            payload = validate_input_privacy(
                canonical_path=altered,
                ed25519_path=ROOT / "src/agent_lifecycle/neutrality/ed25519.py",
                session_store_path=ROOT / "src/agent_lifecycle/adapter_sessions/session_store.py",
                planning_session_path=ROOT / "src/agent_lifecycle/adapter_sessions/planning_session.py",
                checkpoint_store_path=ROOT / "src/agent_lifecycle/context/checkpoint_store.py",
                workflow_state_path=ROOT / "src/agent_lifecycle/workflow/state.py",
            )
        self.assertEqual(payload["status"], "FAIL")
        self.assertTrue(any(item["code"] == "input-privacy-source-invariant-missing" for item in payload["blockers"]))


if __name__ == "__main__":
    unittest.main()
