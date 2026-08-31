from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.planning.completeness import validate_plan_completeness  # noqa: E402
from agent_lifecycle.quality.validation_ladder import build_validation_check_catalog  # noqa: E402


class CanonicalPlanCompletenessTests(unittest.TestCase):
    def test_canonical_graph_and_literal_paths_pass(self) -> None:
        result = validate_plan_completeness(_manifest())

        self.assertEqual(result["status"], "PASS")
        self.assertIn("traceability", result["requiredChecks"])
        self.assertIn("path-authority", result["requiredChecks"])

    def test_pseudo_glob_path_is_rejected(self) -> None:
        manifest = _manifest()
        manifest["readOnly"] = ["src/agent_lifecycle/**"]

        result = validate_plan_completeness(manifest)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("authority-path-invalid", _codes(result))

    def test_unordered_cross_workstream_writes_are_rejected(self) -> None:
        manifest = _manifest()
        manifest["workstreams"] = [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/shared"],
                "acceptanceIds": ["AC-01"],
                "evidenceIds": ["EV-01"],
            },
            {
                "id": "WS-02",
                "dependsOn": [],
                "writes": ["src/shared/file.py"],
                "acceptanceIds": ["AC-02"],
                "evidenceIds": ["EV-02"],
            },
        ]

        result = validate_plan_completeness(manifest)

        self.assertIn("authority-write-conflict", _codes(result))

    def test_validation_ladder_authority_is_all_or_none_and_resolved(self) -> None:
        manifest = _manifest()
        command = manifest["validation"]["commands"][0]
        manifest["validation"]["checkCatalog"] = build_validation_check_catalog({"full": command})

        missing_peer = validate_plan_completeness(manifest)
        self.assertIn("validation-ladder-authority", missing_peer["requiredChecks"])
        self.assertIn("validation-ladder-authority-missing-peer", _codes(missing_peer))

        manifest["validation"]["validationLadderProfile"] = {
            "path": "profiles/validation.json",
            "digest": "1" * 64,
        }
        self.assertEqual(validate_plan_completeness(manifest)["status"], "PASS")

        manifest["validation"]["checkCatalog"]["checks"][0]["commandDigest"] = "2" * 64
        self.assertIn("validation-ladder-check-missing", _codes(validate_plan_completeness(manifest)))


def _manifest() -> dict:
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "canonical-fixture", "planArtifactRoot": "tasks/canonical-fixture"},
        "packageIntegrity": {
            "required": True,
            "lockSchemaVersion": "agent-plan-lock.v2",
            "inventorySource": "planFiles",
            "undeclaredTopLevelFiles": "reject",
        },
        "specification": {
            "tier": "S2",
            "requirements": [
                {"id": "REQ-01", "description": "first"},
                {"id": "REQ-02", "description": "second"},
            ],
            "tierResolutionRequest": {"requirementsBytes": 1024},
        },
        "acceptance": {
            "criteria": [
                {"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]},
                {"id": "AC-02", "requirementIds": ["REQ-02"], "evidenceIds": ["EV-02"]},
            ]
        },
        "workstreams": [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/one.py"],
                "acceptanceIds": ["AC-01", "AC-02"],
                "evidenceIds": ["EV-01", "EV-02"],
            }
        ],
        "validation": {"commands": ["python -m unittest"]},
        "budgets": {"maxInvocations": 3},
        "contextLimits": {"targetTokens": 1024},
        "forbiddenWrites": [".git"],
        "finalAuditGates": [
            "[AC-01|EV-01] first",
            "[AC-02|EV-02] second",
        ],
        "releaseTarget": {"targetVersion": "1.0.0"},
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()
