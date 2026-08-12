from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_package_audit, validate_package_audit
from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.contracts.compatibility import build_contract_policy
from agent_lifecycle.contracts.schemas import get_schema


class PackageAuditTests(unittest.TestCase):
    def test_package_audit_contract_is_registered(self) -> None:
        schema = get_schema("agent-plan-package-audit-report.v1")
        validation_schema = get_schema("agent-plan-package-audit-validation.v1")
        policy = build_contract_policy()

        self.assertEqual(schema["$id"], "agent-plan-package-audit-report.v1")
        self.assertEqual(validation_schema["$id"], "agent-plan-package-audit-validation.v1")
        self.assertIn(
            {"command": "audit package", "schemaVersion": "agent-plan-package-audit-report.v1", "compatibility": "stable-json"},
            policy["cliOutputs"],
        )

    def test_draft_plan_is_review_required_without_false_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = _write_package(Path(tmp), status="DRAFT")

            audit = build_package_audit(plan_dir=package)

            self.assertEqual(audit["status"], "REVIEW_REQUIRED")
            self.assertEqual(audit["plan"]["status"], "REVIEW_REQUIRED")
            self.assertEqual(audit["implementation"]["status"], "NOT_PROVIDED")
            self.assertEqual(audit["blockers"], [])

    def test_frozen_plan_and_discovered_implementation_audit_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = _write_package(root, status="FROZEN")
            state_path = _write_state(root, package)
            _write_implementation_report(state_path.parent, package, state_path)

            audit = build_package_audit(
                plan_dir=package,
                state_path=state_path,
                changed_paths=[],
                require_frozen=True,
                require_implementation=True,
            )

            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["plan"]["status"], "PASS")
            self.assertEqual(audit["implementation"]["status"], "PASS")
            self.assertEqual(audit["implementation"]["finalValidation"]["status"], "PASS")
            self.assertEqual(validate_package_audit(audit)["status"], "PASS")

    def test_package_audit_validation_rejects_tampered_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = build_package_audit(plan_dir=_write_package(Path(tmp), status="DRAFT"))
            audit["auditDigest"] = "0" * 64

            validation = validate_package_audit(audit)

            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("package-audit-digest", {item["code"] for item in validation["blockers"]})

    def test_package_audit_rejects_unowned_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = _write_package(root, status="FROZEN")
            state_path = _write_state(root, package)
            _write_implementation_report(state_path.parent, package, state_path)

            audit = build_package_audit(
                plan_dir=package,
                state_path=state_path,
                changed_paths=["src/unplanned.py"],
                require_frozen=True,
                require_implementation=True,
            )

            self.assertEqual(audit["status"], "FAIL")
            self.assertIn("package-ownership-failed", {item["code"] for item in audit["blockers"]})


def _write_package(root: Path, *, status: str) -> Path:
    package = root / "plan"
    package.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": status,
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plan"},
        "specification": {
            "tier": "S1",
            "requirements": [{"id": "R-01", "description": "Audit a package."}],
        },
        "releaseTarget": {"targetVersion": "1.0.0"},
        "forbiddenWrites": [],
        "leadOwned": [],
        "readOnly": [],
        "acceptance": {
            "criteria": [{"id": "AC-01", "requirementIds": ["R-01"], "evidenceIds": ["EV-01"]}],
        },
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV-01"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }
    write_json_create(package / "plan.manifest.json", manifest)
    write_json_create(
        package / "plan.lock.json",
        {
            "schemaVersion": "agent-plan-lock.v1",
            "packageId": "package",
            "planRevision": 1,
            "manifestHash": canonical_digest(manifest),
        },
    )
    for name in ("README.md", "00-developer-overview.md", "write-set.md", "evidence-plan.md", "plan-review.md"):
        (package / name).write_text(f"# {name}\n", encoding="utf-8")
    (package / "acceptance-criteria.md").write_text(
        "| ID | Requirement IDs | Evidence IDs | Statement |\n"
        "| --- | --- | --- | --- |\n"
        "| `AC-01` | `R-01` | `EV-01` | The package is audited. |\n",
        encoding="utf-8",
    )
    return package


def _write_state(root: Path, package: Path) -> Path:
    state_path = root / "workflow" / "run.state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((package / "plan.manifest.json").read_text(encoding="utf-8"))
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": canonical_digest(manifest),
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "FINAL_AUDIT",
        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1, "required": True}],
    }
    write_json_create(state_path, state)
    return state_path


def _write_implementation_report(root: Path, package: Path, state_path: Path) -> None:
    manifest = json.loads((package / "plan.manifest.json").read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    body = {
        "schemaVersion": "agent-implementation-audit-report.v1",
        "status": "PASS",
        "verdict": "ACCEPTED",
        "runId": state["runId"],
        "packageId": state["packageId"],
        "taskId": "WS-01",
        "attempt": 1,
        "planRevision": state["planRevision"],
        "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"],
        "auditor": {"id": "independent", "independent": True},
        "findings": [],
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    report = {**body, "reportDigest": canonical_digest(body)}
    write_json_create(root / "implementation-audit.json", report)


if __name__ == "__main__":
    unittest.main()
