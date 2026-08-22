from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.planning.traceability import validate_plan_traceability  # noqa: E402


class PlanTraceabilityTests(unittest.TestCase):
    def test_canonical_graph_passes(self) -> None:
        result = validate_plan_traceability(_manifest())

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])

    def test_orphan_requirement_is_rejected(self) -> None:
        manifest = _manifest()
        manifest["specification"]["requirements"].append({"id": "REQ-ORPHAN", "description": "unused"})

        result = validate_plan_traceability(manifest)

        self.assertIn("traceability-requirement-orphan", _codes(result))

    def test_acceptance_must_have_one_workstream_owner(self) -> None:
        manifest = _manifest()
        manifest["workstreams"].append({"id": "WS-02", "dependsOn": ["WS-01"], "acceptanceIds": ["AC-01"], "evidenceIds": []})

        result = validate_plan_traceability(manifest)

        self.assertIn("traceability-owner-count", _codes(result))

    def test_final_gate_must_cover_every_acceptance(self) -> None:
        manifest = _manifest()
        manifest["finalAuditGates"] = ["[AC-02|EV-02] only the second criterion"]

        result = validate_plan_traceability(manifest)

        self.assertIn("traceability-acceptance-not-final-gated", _codes(result))


def _manifest() -> dict:
    return {
        "package": {"id": "traceability-fixture"},
        "specification": {
            "requirements": [
                {"id": "REQ-01", "description": "first"},
                {"id": "REQ-02", "description": "second"},
            ]
        },
        "acceptance": {
            "criteria": [
                {"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]},
                {"id": "AC-02", "requirementIds": ["REQ-02"], "evidenceIds": ["EV-02"]},
            ]
        },
        "workstreams": [
            {"id": "WS-01", "dependsOn": [], "acceptanceIds": ["AC-01", "AC-02"], "evidenceIds": ["EV-01", "EV-02"]}
        ],
        "finalAuditGates": [
            "[AC-01|EV-01] first gate",
            "[AC-02|EV-02] second gate",
        ],
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()
