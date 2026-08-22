from __future__ import annotations

import sys
import tempfile
import unittest
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.contracts.schemas import get_schema  # noqa: E402
from agent_lifecycle.planning.verification import build_plan_verification  # noqa: E402


class PlanVerificationTests(unittest.TestCase):
    def test_verification_receipt_schema_is_registered(self) -> None:
        self.assertEqual(get_schema("agent-plan-verification-receipt.v1")["$id"], "agent-plan-verification-receipt.v1")

    def test_frozen_plan_requires_lock_and_accepts_valid_v1_lock(self) -> None:
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "plan.manifest.json"
            lock = {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": canonical_digest(manifest)}
            passed = build_plan_verification(
                manifest,
                manifest_path=manifest_path,
                lock=lock,
                acceptance_markdown=_acceptance_markdown(),
                repository_root=Path(tmp),
            )
            missing = build_plan_verification(
                manifest,
                manifest_path=manifest_path,
                acceptance_markdown=_acceptance_markdown(),
                repository_root=Path(tmp),
            )

        self.assertEqual(passed["status"], "PASS")
        self.assertEqual(passed["checks"]["lock"]["status"], "PASS")
        self.assertEqual(missing["status"], "FAIL")
        self.assertIn("plan-lock-required", _codes(missing))

    def test_verifier_does_not_execute_manifest_commands(self) -> None:
        manifest = _manifest()
        marker = Path(tempfile.gettempdir()) / "alk-plan-verification-must-not-run"
        marker.unlink(missing_ok=True)
        manifest["validation"]["commands"] = [f"touch {marker}"]
        lock = {"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": canonical_digest(manifest)}

        result = build_plan_verification(
            manifest,
            manifest_path=Path("plan.manifest.json"),
            lock=lock,
            acceptance_markdown=_acceptance_markdown(),
        )

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["executedCommands"])
        self.assertFalse(marker.exists())

    def test_running_workflow_requires_lock_but_terminal_workflow_does_not(self) -> None:
        manifest = _manifest()
        running = build_plan_verification(
            manifest,
            manifest_path=Path("plan.manifest.json"),
            acceptance_markdown=_acceptance_markdown(),
            workflow_state={"phase": "RUNNING"},
        )
        terminal_manifest = copy.deepcopy(manifest)
        terminal_manifest["status"] = "DRAFT"
        terminal = build_plan_verification(
            terminal_manifest,
            manifest_path=Path("plan.manifest.json"),
            acceptance_markdown=_acceptance_markdown(),
            workflow_state={"phase": "COMPLETE"},
        )

        self.assertIn("plan-lock-required", _codes(running))
        self.assertEqual(terminal["status"], "PASS")


def _manifest() -> dict:
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "verification-fixture"},
        "specification": {"tier": "S1", "requirements": [{"id": "REQ-01", "description": "verify"}]},
        "releaseTarget": {"targetVersion": "1.0.0"},
        "acceptance": {"criteria": [{"id": "AC-01", "requirementIds": ["REQ-01"], "evidenceIds": ["EV-01"]}]},
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV-01"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }


def _acceptance_markdown() -> str:
    return "| ID | Requirements | Evidence | Statement |\n| --- | --- | --- | --- |\n| `AC-01` | `REQ-01` | `EV-01` | Verify the plan. |\n"


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()
