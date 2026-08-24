from __future__ import annotations

import unittest

from agent_lifecycle.context.checkpoints import (
    build_context_checkpoint,
    validate_context_checkpoint,
)
from agent_lifecycle.contracts import LifecycleError


def _checkpoint(**overrides):
    values = {
        "session_id": "session-1",
        "run_id": "run-1",
        "adapter_id": "adapter-1",
        "package_id": "release-1-64",
        "plan_revision": 1,
        "plan_digest": "a" * 64,
        "state_revision": 2,
        "source_revision": "main@abc123",
        "capture_mode": "AGENT_REQUESTED",
        "reason": "operator requested context continuity",
        "summary": {
            "latestUserIntent": "Finish the lifecycle task.",
            "activeDecisions": ["Keep the plan authoritative."],
            "openBlockers": [],
            "nextRequiredAction": "Run the focused tests.",
        },
        "created_at": "2026-08-13T12:00:00Z",
    }
    values.update(overrides)
    return build_context_checkpoint(**values)


class ContextCheckpointTests(unittest.TestCase):
    def test_repeated_structured_input_is_deterministic(self) -> None:
        self.assertEqual(_checkpoint(), _checkpoint())

    def test_checkpoint_is_redacted_and_advisory(self) -> None:
        checkpoint = _checkpoint(summary={"decision": "api_key=secret", "note": "continue"})
        self.assertEqual(checkpoint["summary"]["decision"], "api_key=<redacted>")
        self.assertIsNone(checkpoint["captureEvidence"])
        self.assertFalse(checkpoint["implementationAuthorized"])
        self.assertEqual(checkpoint["proofAuthority"], "none")
        self.assertEqual(validate_context_checkpoint(checkpoint)["status"], "PASS")

    def test_native_hook_requires_adapter_owned_evidence(self) -> None:
        with self.assertRaises(LifecycleError):
            _checkpoint(capture_mode="NATIVE_HOOK")

        checkpoint = _checkpoint(
            capture_mode="NATIVE_HOOK",
            capture_evidence={
                "status": "PASS",
                "accepted": True,
                "producerBoundary": "adapter-owned",
                "capabilityReceiptDigest": "b" * 64,
                "eventReceiptDigest": "c" * 64,
            },
        )
        self.assertEqual(validate_context_checkpoint(checkpoint)["status"], "PASS")

        tampered = dict(checkpoint)
        tampered.pop("captureEvidence")
        self.assertEqual(validate_context_checkpoint(tampered)["status"], "FAIL")

    def test_checkpoint_redacts_posix_paths_before_validation(self) -> None:
        paths = [
            "/Volumes/Work/repo/private.txt",
            "/root/.ssh/id_rsa",
            "/opt/data/private.txt",
            "/etc/passwd",
            "/var/log/private.log",
            r"C:\Users\operator\private.txt",
        ]

        checkpoint = _checkpoint(summary={"paths": paths})

        self.assertEqual(checkpoint["summary"]["paths"], ["<redacted>"] * len(paths))
        self.assertEqual(validate_context_checkpoint(checkpoint)["status"], "PASS")

    def test_checkpoint_redacts_windows_unc_paths_before_validation(self) -> None:
        paths = [
            r"\\corp-filesvr\eng\secret\roadmap.md",
            r"\\filesvr/share/secret",
            r"\\?\C:\Users\operator\secret.txt",
            r"C:\Users/operator\secret.txt",
            r"C:\foo/bar\baz",
            r"\Windows\System32\drivers",
            r"file:///etc/passwd",
        ]

        checkpoint = _checkpoint(summary={"paths": paths})

        self.assertEqual(checkpoint["summary"]["paths"], ["<redacted>"] * len(paths))
        self.assertEqual(validate_context_checkpoint(checkpoint)["status"], "PASS")

    def test_checkpoint_normalizes_public_url_without_storing_local_path(self) -> None:
        checkpoint = _checkpoint(summary={"citation": "HTTPS://EXAMPLE.COM:443/checkpoint#Context"})

        self.assertEqual(checkpoint["summary"]["citation"], "https://example.com/checkpoint#Context")
        self.assertTrue(checkpoint["redactionStatus"]["applied"])
        self.assertEqual(validate_context_checkpoint(checkpoint)["status"], "PASS")

    def test_authority_and_raw_transcript_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            _checkpoint(summary={"rawTranscript": "not stored"})
        with self.assertRaises(LifecycleError):
            _checkpoint(summary={"implementationAuthorized": True})

    def test_lineage_mismatch_fails_closed(self) -> None:
        checkpoint = _checkpoint()
        result = validate_context_checkpoint(
            checkpoint,
            expected_lineage={"sessionId": "other-session", "stateRevision": 2},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("context-checkpoint-lineage-mismatch", {item["code"] for item in result["blockers"]})

    def test_digest_tampering_fails_closed(self) -> None:
        checkpoint = _checkpoint()
        checkpoint["summary"]["nextRequiredAction"] = "tampered"
        result = validate_context_checkpoint(checkpoint)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("context-checkpoint-digest-mismatch", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
