from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.host_protocol.lifecycle_control_qualification import (
    NEGATIVE_SCENARIOS,
    build_fixture_evidence,
    build_qualification_receipt,
    validate_qualification_receipt,
)


class LifecycleControlQualificationTests(unittest.TestCase):
    def _fixture_receipt(self) -> dict[str, object]:
        positive, negative = build_fixture_evidence(host="claude-code", host_version="2.1.226", operation="file-edit")
        return build_qualification_receipt(
            adapter_id="claude",
            host="claude-code",
            host_version="2.1.226",
            expected_host_version="2.1.226",
            operation="file-edit",
            declared_level="GUIDANCE_ONLY",
            supported_level="GUIDANCE_ONLY",
            positive_evidence=positive,
            negative_evidence=negative,
            evidence_refs=["fixture:qualification"],
            live_evidence=False,
        )

    def test_fixture_evidence_is_valid_but_never_qualifies_enforcement(self) -> None:
        receipt = self._fixture_receipt()
        result = validate_qualification_receipt(receipt, expected_host_version="2.1.226")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(receipt["status"], "NO_RECOMMENDATION")
        self.assertEqual(receipt["qualifiedLevel"], "GUIDANCE_ONLY")
        self.assertFalse(receipt["productionPromotionClaimed"])

    def test_live_matrix_can_qualify_only_with_exact_host_and_no_side_effects(self) -> None:
        positive, negative = build_fixture_evidence(host="claude-code", host_version="2.1.226", operation="file-edit")
        for item in positive + negative:
            item["source"] = "live"
            item["syntheticReplayUsed"] = False
        receipt = build_qualification_receipt(
            adapter_id="claude",
            host="claude-code",
            host_version="2.1.226",
            expected_host_version="2.1.226",
            operation="file-edit",
            declared_level="ENFORCED",
            supported_level="ENFORCED",
            positive_evidence=positive,
            negative_evidence=negative,
            evidence_refs=["work/claude/live-matrix.json"],
            live_evidence=True,
        )
        result = validate_qualification_receipt(receipt, expected_host_version="2.1.226", require_live=True)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(receipt["status"], "QUALIFIED")
        self.assertEqual(receipt["qualifiedLevel"], "ENFORCED")

    def test_enforced_request_without_live_evidence_is_explicitly_blocked(self) -> None:
        positive, negative = build_fixture_evidence(host="claude-code", host_version="2.1.226", operation="file-edit")
        receipt = build_qualification_receipt(
            adapter_id="claude",
            host="claude-code",
            host_version="2.1.226",
            expected_host_version="2.1.226",
            operation="file-edit",
            declared_level="ENFORCED",
            supported_level="ENFORCED",
            positive_evidence=positive,
            negative_evidence=negative,
            evidence_refs=["fixture:qualification"],
            live_evidence=False,
        )

        self.assertEqual(receipt["status"], "NO_RECOMMENDATION")
        self.assertEqual(receipt["qualifiedLevel"], "GUIDANCE_ONLY")
        self.assertIn("control-qualification-enforced-needs-live", {item["code"] for item in receipt["blockers"]})

    def test_synthetic_evidence_cannot_claim_qualified_status(self) -> None:
        receipt = self._fixture_receipt()
        receipt.update(
            {
                "status": "QUALIFIED",
                "declaredLevel": "OBSERVED",
                "supportedLevel": "OBSERVED",
                "qualifiedLevel": "OBSERVED",
            }
        )
        receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        )

        result = validate_qualification_receipt(receipt)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "control-qualification-qualified-needs-live",
            {item["code"] for item in result["blockers"]},
        )

    def test_missing_negative_scenario_blocks_qualification(self) -> None:
        receipt = self._fixture_receipt()
        receipt["negativeEvidence"] = [item for item in receipt["negativeEvidence"] if item["scenarioId"] != "replay"]
        receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        )
        result = validate_qualification_receipt(receipt)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "control-qualification-scenarios-missing",
            {item["code"] for item in result["blockers"]},
        )

    def test_side_effect_or_wrong_host_version_blocks_live_claim(self) -> None:
        positive, negative = build_fixture_evidence(host="claude-code", host_version="2.1.226", operation="file-edit")
        for item in positive + negative:
            item["source"] = "live"
            item["syntheticReplayUsed"] = False
        tampered = deepcopy(negative[0])
        tampered["sideEffectObserved"] = True
        negative[0] = tampered
        receipt = build_qualification_receipt(
            adapter_id="claude",
            host="claude-code",
            host_version="2.1.226",
            expected_host_version="2.1.2",
            operation="file-edit",
            declared_level="ENFORCED",
            supported_level="ENFORCED",
            positive_evidence=positive,
            negative_evidence=negative,
            evidence_refs=["work/claude/live-matrix.json"],
            live_evidence=True,
        )
        result = validate_qualification_receipt(receipt, expected_host_version="2.1.2", require_live=True)

        codes = {item["code"] for item in result["blockers"]}
        self.assertIn("control-qualification-host-version-mismatch", codes)
        self.assertIn("control-qualification-side-effect", codes)

    def test_all_required_negative_scenarios_are_explicit(self) -> None:
        _positive, negative = build_fixture_evidence(host="claude-code", host_version="2.1.226", operation="file-edit")
        self.assertEqual({item["scenarioId"] for item in negative}, set(NEGATIVE_SCENARIOS))

    def test_unknown_scenario_is_rejected(self) -> None:
        receipt = self._fixture_receipt()
        receipt["negativeEvidence"].append(
            {
                "scenarioId": "unlisted-control-bypass",
                "adapterId": "claude",
                "host": "claude-code",
                "hostVersion": "2.1.226",
                "operation": "file-edit",
                "source": "fixture",
                "syntheticReplayUsed": True,
                "status": "BLOCKED",
                "deniedBeforeEffect": True,
                "sideEffectObserved": False,
                "processEvidence": {"started": False, "exitCode": None},
                "evidenceDigest": "0" * 64,
            }
        )
        receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        )

        result = validate_qualification_receipt(receipt)

        self.assertIn(
            "control-qualification-evidence-scenario-unknown",
            {item["code"] for item in result["blockers"]},
        )


if __name__ == "__main__":
    unittest.main()
