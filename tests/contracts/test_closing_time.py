"""Shared closing timestamps preserve UTC acceptance and exact refusal envelopes."""

import unittest
from datetime import UTC, datetime

from agent_lifecycle.contracts.closing_time import closing_instant
from agent_lifecycle.contracts.errors import LifecycleError, require_condition
from agent_lifecycle.contracts.workflow_state_schemas import _closing_instant


class ClosingTimeTests(unittest.TestCase):
    def test_utc_forms_and_compatibility_export(self):
        self.assertIs(_closing_instant, closing_instant)
        for value in ("2026-10-24T12:00:00Z", "2026-10-24T12:00:00+00:00", "2026-10-24T12:00:00-00:00"):
            with self.subTest(value=value):
                self.assertEqual(closing_instant(value, "observedAt"), datetime(2026, 10, 24, 12, tzinfo=UTC))

    def test_invalid_time_keeps_code_message_and_details(self):
        for value, message in (
            (None, "observedAt must be an aware UTC timestamp"),
            (123, "observedAt must be an aware UTC timestamp"),
            ("bad", "observedAt is invalid"),
            ("2026-10-24T12:00:00", "observedAt must be UTC"),
            ("2026-10-24T12:00:00+03:00", "observedAt must be UTC"),
        ):
            with self.subTest(value=value), self.assertRaises(LifecycleError) as caught:
                closing_instant(value, "observedAt")
            self.assertEqual(caught.exception.code, "closing-context-invalid")
            self.assertEqual(str(caught.exception), message)
            self.assertEqual(caught.exception.details, {})

    def test_condition_preserves_caller_error(self):
        self.assertIsNone(require_condition(True, "unused", "unused"))
        with self.assertRaises(LifecycleError) as caught:
            require_condition(False, "r11-result-identity", "identity missing")
        self.assertEqual(
            caught.exception.to_json(),
            {
                "schemaVersion": "agent-lifecycle-error.v1",
                "code": "r11-result-identity",
                "message": "identity missing",
                "details": {},
            },
        )
