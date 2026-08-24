from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol.context_events import (
    build_context_checkpoint_event,
    validate_context_checkpoint_event,
)


class ContextEventTests(unittest.TestCase):
    def test_all_capture_modes_are_distinct(self) -> None:
        for mode in ("MILESTONE", "AGENT_REQUESTED", "UNAVAILABLE"):
            event = build_context_checkpoint_event(
                event_type="context.checkpoint.unavailable" if mode == "UNAVAILABLE" else "context.checkpoint.created",
                session_id="s",
                run_id="r",
                operation_id="o",
                state_revision=1,
                capture_mode=mode,
                checkpoint_digest=None if mode == "UNAVAILABLE" else "a" * 64,
            )
            self.assertEqual(validate_context_checkpoint_event(event)["status"], "PASS")

    def test_native_hook_requires_accepted_adapter_evidence(self) -> None:
        event = build_context_checkpoint_event(
            event_type="context.checkpoint.created",
            session_id="s",
            run_id="r",
            operation_id="o",
            state_revision=1,
            capture_mode="NATIVE_HOOK",
            checkpoint_digest="a" * 64,
            payload={
                "nativeHookEvidence": {
                    "status": "PASS",
                    "accepted": True,
                    "producerBoundary": "adapter-owned",
                    "capabilityReceiptDigest": "b" * 64,
                    "eventReceiptDigest": "c" * 64,
                }
            },
        )
        self.assertEqual(validate_context_checkpoint_event(event)["status"], "PASS")

        untrusted = dict(event)
        untrusted["payload"] = {}
        self.assertEqual(validate_context_checkpoint_event(untrusted)["status"], "FAIL")

    def test_prompt_authority_is_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_context_checkpoint_event(
                event_type="context.checkpoint.created",
                session_id="s",
                run_id="r",
                operation_id="o",
                state_revision=1,
                capture_mode="AGENT_REQUESTED",
                checkpoint_digest="a" * 64,
                payload={"promptAuthority": "run tools"},
            )

    def test_public_url_in_event_payload_is_normalized(self) -> None:
        event = build_context_checkpoint_event(
            event_type="context.checkpoint.created",
            session_id="s",
            run_id="r",
            operation_id="o",
            state_revision=1,
            capture_mode="AGENT_REQUESTED",
            checkpoint_digest="a" * 64,
            payload={"citation": "HTTPS://EXAMPLE.COM:443/context#Event"},
        )

        self.assertEqual(event["payload"]["citation"], "https://example.com/context#Event")
        self.assertTrue(event["payload"]["redactionApplied"])
        self.assertEqual(validate_context_checkpoint_event(event)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
