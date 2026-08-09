from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from tools.live_hosts.adapter_module_loader import load_adapter_usage_normalizer  # noqa: E402

FIXTURES = ROOT / "tests/adapters/fixtures/host_usage"


class HostLocalUsageNormalizerTests(unittest.TestCase):
    def test_reference_fixtures_extract_only_allowlisted_usage(self) -> None:
        for fixture_name in ("gemini-cli.json", "kimi-code.json", "qwen-code.json", "redacted-secret.json"):
            fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
            with self.subTest(fixture=fixture_name):
                normalizer = load_adapter_usage_normalizer(fixture["adapterId"], repository_root=ROOT)
                usage = normalizer.parse_usage(
                    fixture["artifact"],
                    max_bytes=normalizer.max_artifact_bytes,
                )
                expected = fixture["expected"]
                self.assertEqual(usage.input_tokens, expected["inputTokens"])
                self.assertEqual(usage.output_tokens, expected["outputTokens"])
                self.assertEqual(usage.billable_tokens, expected["billableTokens"])
                self.assertEqual(usage.session_id, expected["sessionId"])
                self.assertEqual(usage.event_count, expected["eventCount"])
                if "cumulativeContextBytes" in expected:
                    self.assertEqual(usage.cumulative_context_bytes, expected["cumulativeContextBytes"])
                self.assertNotIn("secret", json.dumps(usage.to_receipt_usage()).lower())
                self.assertNotIn("/home/", json.dumps(usage.to_receipt_usage()).lower())
                self.assertNotIn("/users/", json.dumps(usage.to_receipt_usage()).lower())

    def test_bounded_parser_rejects_invalid_and_oversized_artifacts(self) -> None:
        normalizer = load_adapter_usage_normalizer("qwen-code", repository_root=ROOT)
        with self.assertRaises(LifecycleError) as malformed:
            normalizer.parse_usage("not-json\n", max_bytes=normalizer.max_artifact_bytes)
        self.assertEqual(malformed.exception.code, "invalid-usage-artifact-json")

        with self.assertRaises(LifecycleError) as oversized:
            normalizer.parse_usage(b"{}\n" * 10, max_bytes=4)
        self.assertEqual(oversized.exception.code, "usage-artifact-too-large")

    def test_reference_normalizers_are_fixture_only(self) -> None:
        for adapter_id in ("claude", "codex", "gemini-cli", "kimi-code", "opencode", "qwen-code"):
            with self.subTest(adapter=adapter_id):
                normalizer = load_adapter_usage_normalizer(adapter_id, repository_root=ROOT)
                self.assertEqual(normalizer.status, "FIXTURE_ONLY")

    def test_new_host_normalizers_extract_allowlisted_counters(self) -> None:
        fixtures = {
            "codex": ('{"type":"turn.completed","thread_id":"thread-1","usage":{"input_tokens":12,"output_tokens":5,"total_tokens":17},"secret":"no"}\n', 12, 5, 17),
            "claude": ('{"type":"result","session_id":"session-1","usage":{"input_tokens":10,"output_tokens":4,"cache_read_input_tokens":2}}\n', 10, 4, 16),
            "opencode": ('{"type":"step_finish","sessionID":"session-1","part":{"tokens":{"input":9,"output":3,"total":12}},"path":"private/path"}\n', 9, 3, 12),
        }
        for adapter_id, (artifact, expected_input, expected_output, expected_total) in fixtures.items():
            with self.subTest(adapter=adapter_id):
                normalizer = load_adapter_usage_normalizer(adapter_id, repository_root=ROOT)
                usage = normalizer.parse_usage(artifact, max_bytes=normalizer.max_artifact_bytes)
                self.assertEqual(usage.input_tokens, expected_input)
                self.assertEqual(usage.output_tokens, expected_output)
                self.assertEqual(usage.billable_tokens, expected_total)
                serialized = json.dumps(usage.to_receipt_usage()).lower()
                self.assertNotIn("secret", serialized)
                self.assertNotIn("/users/", serialized)


if __name__ == "__main__":
    unittest.main()
