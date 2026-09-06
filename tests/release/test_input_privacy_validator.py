from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.validate_input_privacy import validate_input_privacy

from agent_lifecycle.contracts import canonical

ROOT = Path(__file__).resolve().parents[2]


class InputPrivacyValidatorTests(unittest.TestCase):
    def inputs(self):
        return {
            "canonical_path": ROOT / "src/agent_lifecycle/contracts/canonical.py",
            "ed25519_path": ROOT / "src/agent_lifecycle/neutrality/ed25519.py",
            "session_store_path": ROOT / "src/agent_lifecycle/adapter_sessions/session_store.py",
            "planning_session_path": ROOT / "src/agent_lifecycle/adapter_sessions/planning_session.py",
            "checkpoint_store_path": ROOT / "src/agent_lifecycle/context/checkpoint_store.py",
            "workflow_state_path": ROOT / "src/agent_lifecycle/workflow/state.py",
        }

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

    def test_marker_only_canonical_source_fails_without_runtime_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "canonical.py"
            source.write_text(
                "# MAX_JSON_INPUT_BYTES MAX_JSON_NESTING RecursionError _private_directory_chain _validate_json_nesting\n"
            )
            payload = validate_input_privacy(**{**self.inputs(), "canonical_path": source})
        self.assertEqual(payload["status"], "FAIL")
        self.assertFalse(any(c["id"] == "json-unicode" for c in payload["checks"]))

    def test_private_backend_is_bound_and_new_json_negatives_are_executed(self):
        payload = validate_input_privacy(**self.inputs())
        self.assertEqual(payload["status"], "PASS", payload["blockers"])
        checks = {c["id"]: c for c in payload["checks"]}
        for name in (
            "authority-backend",
            "authority-validator",
            "json-duplicate",
            "json-nested-duplicate",
            "json-escaped-duplicate",
            "json-utf8",
            "json-nonfinite-input",
        ):
            self.assertEqual(checks[name]["status"], "PASS")
        self.assertTrue(any(f["name"] == "authority_io.py" and len(f["sha256"]) == 64 for f in payload["files"]))

    def test_changed_live_json_limit_is_not_attested_from_stale_source(self):
        with patch.object(canonical, "MAX_JSON_NESTING", 1):
            payload = validate_input_privacy(**self.inputs())
        self.assertEqual(payload["status"], "FAIL")
        check = next(c for c in payload["checks"] if c["id"] == "canonical-json")
        self.assertIn("source-runtime-constant-mismatch", check["sourceErrors"])


if __name__ == "__main__":
    unittest.main()
