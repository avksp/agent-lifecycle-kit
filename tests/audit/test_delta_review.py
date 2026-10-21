from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit.delta_review import build_delta_review_packet
from agent_lifecycle.contracts import canonical_bytes, canonical_digest
from tests.review import review_for, subject_for, synthetic_case, write_json


class DeltaReviewPacketTests(unittest.TestCase):
    def test_blocked_full_report_cannot_establish_a_reusable_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp), negative=False)
            case["baseline"]["verdict"] = "BLOCKED"
            packet = build_delta_review_packet(case["delta"]["subject"], baseline=case["baseline"])
        self.assertEqual(packet["mode"], "FULL_REQUIRED")
        self.assertEqual(packet["reasons"], ["review-baseline-verdict-unavailable"])
        self.assertFalse(packet["modelCallsStarted"])

    def test_unsupported_or_missing_subject_identity_refuses_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            cases = [
                ("schemaVersion", None),
                ("schemaVersion", "agent-plan.v99"),
                ("status", None),
                ("status", "UNKNOWN"),
                ("planRevision", 0),
            ]
            for field, value in cases:
                subject = copy.deepcopy(case["delta"]["subject"])
                subject["manifest"][field] = value
                with self.subTest(field=field, value=value):
                    packet = build_delta_review_packet(subject, baseline=case["baseline"])
                    self.assertEqual(packet["mode"], "FULL_REQUIRED")
                    self.assertFalse(packet["modelCallsStarted"])

    def test_supported_draft_to_exact_frozen_projection_remains_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = synthetic_case(root, negative=False)
            manifest = case["baseline"]["subject"]["manifest"]
            manifest["status"] = "DRAFT"
            write_json(root, "plans/r1/plan.manifest.json", manifest)
            baseline = review_for(root, subject_for(root, manifest), "draft-full")
            packet = build_delta_review_packet(case["delta"]["subject"], baseline=baseline)
        self.assertEqual(packet["mode"], "DELTA_ELIGIBLE")
        self.assertNotEqual(packet["baseHash"], packet["candidateHash"])

    def test_full_default_and_bound_delta_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            subject = case["delta"]["subject"]
            full = build_delta_review_packet(subject)
            delta = build_delta_review_packet(subject, baseline=case["baseline"])
        self.assertEqual(full["mode"], "FULL")
        self.assertEqual(delta["mode"], "DELTA_ELIGIBLE")
        self.assertFalse(delta["modelCallsStarted"])
        self.assertTrue(delta["readOnly"])
        self.assertTrue(delta["admissionRequired"])
        self.assertEqual(
            delta["packetDigest"], canonical_digest({k: v for k, v in delta.items() if k != "packetDigest"})
        )

    def test_unbound_or_partial_old_report_never_authorizes_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            for baseline in ({"schemaVersion": "agent-plan-review.v1"}, case["delta"]):
                packet = build_delta_review_packet(case["delta"]["subject"], baseline=baseline)
                self.assertEqual(packet["mode"], "FULL_REQUIRED")

    def test_packet_limit_returns_bounded_refusal_without_autorun(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = synthetic_case(Path(tmp))
            packet = build_delta_review_packet(case["delta"]["subject"], baseline=case["baseline"], max_bytes=1024)
        self.assertEqual(packet["mode"], "FULL_REQUIRED")
        self.assertEqual(packet["reasons"], ["PACKET_LIMIT_EXCEEDED"])
        self.assertLess(len(canonical_bytes(packet)), 1024)
