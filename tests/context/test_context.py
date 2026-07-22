from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.context import load_context_profile, render_context  # noqa: E402
from agent_lifecycle.contracts import LifecycleError  # noqa: E402


class ContextTests(unittest.TestCase):
    def test_small_context_profile_validates(self) -> None:
        result = load_context_profile(ROOT / "profiles/small-context-profile.v1.json")
        self.assertEqual(result["schemaVersion"], "agent-small-context-profile-validation.v1")
        self.assertEqual(result["defaultWindow"], "8k")
        self.assertIn("4k-strict", result["windows"])
        self.assertIn("8k", result["windows"])

    def test_rendered_packet_fits_4k_strict_profile(self) -> None:
        profile = _profile()
        result = render_context(profile, _packet(), _summary(), latest_user="Implement exactly this task.", window="4k-strict")
        self.assertEqual(result["status"], "PASS")
        receipt = result["receipt"]
        self.assertEqual(receipt["window"], "4k-strict")
        self.assertEqual(receipt["limits"]["maxRecentUserTurnsVerbatim"], 1)
        self.assertLessEqual(
            receipt["estimatedTokens"]["renderedEnvelope"],
            receipt["limits"]["maxRenderedEnvelopeTokens"],
        )

    def test_rendered_packet_fits_8k_profile(self) -> None:
        profile = _profile()
        result = render_context(profile, _packet(), _summary(), latest_user="Implement exactly this task.")
        self.assertEqual(result["status"], "PASS")
        receipt = result["receipt"]
        self.assertEqual(receipt["window"], "8k")
        self.assertLessEqual(
            receipt["estimatedTokens"]["renderedEnvelope"],
            receipt["limits"]["maxRenderedEnvelopeTokens"],
        )

    def test_oversized_packet_fails_closed_without_truncation(self) -> None:
        packet = _packet()
        packet["task"]["plannedItems"] = ["REQ-" + ("x" * 200)] * 300
        result = render_context(_profile(), packet, _summary())
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["receipt"]["overflowPolicy"]["truncateAllowed"])
        self.assertEqual(result["receipt"]["overflowPolicy"]["defaultAction"], "split-task")

    def test_missing_summary_field_is_rejected(self) -> None:
        summary = _summary()
        summary.pop("doNotDo")
        with self.assertRaises(LifecycleError):
            render_context(_profile(), _packet(), summary)


def _profile() -> dict:
    import json

    return json.loads((ROOT / "profiles/small-context-profile.v1.json").read_text(encoding="utf-8"))


def _packet() -> dict:
    return {
        "schemaVersion": "agent-task-packet.v1",
        "plan": {"packageId": "package", "planRevision": 1, "planDigest": "0" * 64},
        "task": {
            "id": "WS-01",
            "title": "Add compact context support",
            "owner": "worker",
            "reviewer": "reviewer",
            "dependsOn": [],
            "required": True,
            "plannedItems": ["REQ-CONTEXT"],
            "acceptanceIds": ["AC-CONTEXT"],
            "evidenceIds": ["EV-CONTEXT"],
            "artifactPaths": {},
            "capabilityHints": [],
            "requiredTools": [],
            "executionPolicy": {},
        },
        "ownership": {
            "writes": ["src/agent_lifecycle/context"],
            "readOnly": ["profiles/small-context-profile.v1.json"],
            "forbiddenWrites": [],
            "leadOwned": [],
        },
        "specification": {
            "tier": "S1",
            "revision": 1,
            "requirements": ["REQ-CONTEXT"],
            "traceDigest": "1" * 64,
        },
        "context": {"refs": ["profiles/small-context-profile.v1.json"]},
        "validation": {"acceptanceIds": ["AC-CONTEXT"], "evidenceIds": ["EV-CONTEXT"]},
        "acceptance": [{"id": "AC-CONTEXT", "statement": "context receipt passes"}],
    }


def _summary() -> dict:
    return {
        "latestUserIntent": "Add compact context mode for small local models.",
        "activeDecisions": ["Use deterministic renderer and fail closed on overflow."],
        "openBlockers": [],
        "acceptedEvidence": [{"id": "EV-CONTEXT", "status": "pending"}],
        "changedFiles": ["src/agent_lifecycle/context/rendering.py"],
        "nextRequiredAction": "render compact envelope",
        "doNotDo": ["Do not load the full plan package into an 8k context."],
    }


if __name__ == "__main__":
    unittest.main()
