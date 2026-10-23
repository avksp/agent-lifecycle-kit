"""Exercise the review-packet application boundary without CLI ownership."""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.audit.review_packet import prepare_review_packet
from agent_lifecycle.cli import main
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.review_input_types import ReviewPacketRequest
from tests.review import synthetic_case


class ReviewPacketServiceTests(unittest.TestCase):
    def test_service_and_cli_have_identical_packets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            synthetic_case(root, git_repository=True)
            request = ReviewPacketRequest(
                manifest="plans/r2/plan.manifest.json",
                baseline="plans/r1/review.json",
            )
            packet = prepare_review_packet(root, request)
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "plan",
                        "review-packet",
                        "--repository-root",
                        str(root),
                        "--manifest",
                        request.manifest,
                        "--baseline",
                        request.baseline,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(packet, json.loads(stdout.getvalue()))
            self.assertEqual(packet["mode"], "DELTA_ELIGIBLE")
            self.assertFalse(packet["modelCallsStarted"])

    def test_source_drift_refuses_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            synthetic_case(root, git_repository=True)
            (root / "runtime.py").write_text("unreviewed change")
            request = ReviewPacketRequest(
                manifest="plans/r2/plan.manifest.json",
                baseline="plans/r1/review.json",
                out="packet.review-packet.json",
                subject_out="packet.review-subject.json",
            )
            result = prepare_review_packet(root, request)
            self.assertEqual(result["mode"], "FULL_REQUIRED")
            self.assertIn("review-runtime-changed", result["reasons"])
            self.assertFalse(result["modelCallsStarted"])
            self.assertFalse((root / request.out).exists())
            self.assertFalse((root / request.subject_out).exists())

    def test_service_publishes_only_advisory_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = synthetic_case(root, git_repository=True)
            request = ReviewPacketRequest(
                manifest="plans/r2/plan.manifest.json",
                baseline="plans/r1/review.json",
                out="packet.review-packet.json",
                subject_out="packet.review-subject.json",
            )
            packet = prepare_review_packet(root, request)
            self.assertEqual(json.loads((root / request.out).read_bytes()), packet)
            self.assertEqual(json.loads((root / request.subject_out).read_bytes()), case["delta"]["subject"])
            self.assertFalse((root / "plans/r2/plan.lock.json").exists())

    def test_invalid_limit_is_rejected_before_reading_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(LifecycleError) as raised:
                prepare_review_packet(Path(directory), ReviewPacketRequest(manifest="missing.json", max_bytes=1023))
            self.assertEqual(raised.exception.code, "review-packet-limit")

    def test_missing_input_refuses_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = prepare_review_packet(
                root, ReviewPacketRequest(manifest="missing.json", out="x.review-packet.json")
            )
            self.assertEqual(result["mode"], "FULL_REQUIRED")
            self.assertFalse(result["modelCallsStarted"])
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
