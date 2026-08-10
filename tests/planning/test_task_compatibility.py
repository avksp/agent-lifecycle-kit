from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.task_compatibility import (
    build_task_plan_compatibility_receipt,
    task_contract_digest,
    task_contracts_compatible,
    validate_task_plan_compatibility_receipt,
)


class TaskPlanCompatibilityTests(unittest.TestCase):
    def test_helper_imports_only_lower_level_contracts(self) -> None:
        path = Path(__file__).resolve().parents[2] / "src/agent_lifecycle/planning/task_compatibility.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        project_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and isinstance(node.module, str)
            and node.module.startswith("agent_lifecycle.")
        }
        self.assertEqual(project_imports, {"agent_lifecycle.contracts"})

    def test_receipt_binds_plans_contract_and_artifacts(self) -> None:
        previous_state = _state(plan_revision=1, plan_digest="1" * 64, source_revision="old")
        previous_task = _task()
        current_task = copy.deepcopy(previous_task)
        receipt = build_task_plan_compatibility_receipt(
            previous_state=previous_state,
            current_plan=_plan(plan_revision=2, plan_digest="2" * 64, source_revision="new"),
            previous_task=previous_task,
            current_task=current_task,
        )
        current_task["planCompatibilityReceipt"] = receipt

        validation = validate_task_plan_compatibility_receipt(
            receipt,
            state=_state(plan_revision=2, plan_digest="2" * 64, source_revision="new"),
            task=current_task,
            report=_report(),
            report_identity={"path": "audit.json", "sha256": "4" * 64, "bytes": 40},
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(receipt["taskContract"]["currentDigest"], task_contract_digest(current_task))

    def test_validation_rejects_changed_contract_and_report_identity(self) -> None:
        previous_state = _state(plan_revision=1, plan_digest="1" * 64, source_revision="old")
        previous_task = _task()
        current_task = copy.deepcopy(previous_task)
        receipt = build_task_plan_compatibility_receipt(
            previous_state=previous_state,
            current_plan=_plan(plan_revision=2, plan_digest="2" * 64, source_revision="new"),
            previous_task=previous_task,
            current_task=current_task,
        )
        current_task["writes"] = ["src/changed.py"]
        current_task["result"]["sha256"] = "8" * 64
        current_task["planCompatibilityReceipt"] = receipt

        validation = validate_task_plan_compatibility_receipt(
            receipt,
            state=_state(plan_revision=2, plan_digest="2" * 64, source_revision="new"),
            task=current_task,
            report=_report(),
            report_identity={"path": "audit.json", "sha256": "9" * 64, "bytes": 40},
        )

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("task-plan-compatibility-contract", codes)
        self.assertIn("task-plan-compatibility-artifact-mismatch", codes)
        self.assertIn("task-plan-compatibility-report-identity", codes)

    def test_contract_comparison_rejects_material_change(self) -> None:
        previous = _task()
        current = copy.deepcopy(previous)
        self.assertTrue(task_contracts_compatible(previous, current))
        current["acceptanceIds"].append("AC-02")
        self.assertFalse(task_contracts_compatible(previous, current))

    def test_contract_comparison_rejects_controller_gate_change(self) -> None:
        previous = _task()
        current = copy.deepcopy(previous)
        self.assertTrue(task_contracts_compatible(previous, current))
        current["controllerGates"] = [
            {"id": "G-SECURITY", "requiredFor": ["task-acceptance"]}
        ]
        self.assertFalse(task_contracts_compatible(previous, current))


def _plan(*, plan_revision: int, plan_digest: str, source_revision: str) -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": plan_revision,
        "planDigest": plan_digest,
        "sourceRevision": source_revision,
    }


def _state(*, plan_revision: int, plan_digest: str, source_revision: str) -> dict:
    return _plan(
        plan_revision=plan_revision,
        plan_digest=plan_digest,
        source_revision=source_revision,
    )


def _task() -> dict:
    report_identity = {
        "path": "audit.json",
        "sha256": "4" * 64,
        "bytes": 40,
        "taskId": "WS-01",
        "attempt": 1,
        "verdict": "ACCEPTED",
        "reportDigest": "5" * 64,
    }
    return {
        "id": "WS-01",
        "title": "Task",
        "owner": "worker",
        "dependsOn": [],
        "writes": ["src/example.py"],
        "reviewer": "reviewer",
        "launchGate": "ready",
        "capabilityHints": [],
        "requiredTools": [],
        "contextRefs": [],
        "acceptanceIds": ["AC-01"],
        "evidenceIds": ["EV-01"],
        "executionPolicy": {"network": "denied"},
        "modelRoute": None,
        "reviewMesh": None,
        "artifactPaths": {"result": "result.json", "review": "review.json"},
        "required": True,
        "status": "ACCEPTED",
        "attempt": 1,
        "result": {"path": "result.json", "sha256": "2" * 64, "bytes": 20},
        "review": {"path": "review.json", "sha256": "3" * 64, "bytes": 30},
        "implementationAuditReport": report_identity,
    }


def _report() -> dict:
    body = {
        "schemaVersion": "agent-implementation-audit-report.v1",
        "status": "PASS",
        "verdict": "ACCEPTED",
        "runId": "run",
        "packageId": "package",
        "taskId": "WS-01",
        "attempt": 1,
        "planRevision": 1,
        "planDigest": "1" * 64,
        "sourceRevision": "old",
        "auditor": {"id": "auditor", "independent": True},
        "findings": [],
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": "5" * 64}


if __name__ == "__main__":
    unittest.main()
