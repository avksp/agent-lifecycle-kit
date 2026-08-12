from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class CliPackageAuditTests(unittest.TestCase):
    def test_audit_package_supports_plan_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "plan"
            package.mkdir()
            _write_minimal_package(package)
            out = Path(tmp) / "package-audit.json"

            code, payload = _run_cli(
                [
                    "audit",
                    "package",
                    "--plan-dir",
                    str(package),
                    "--out",
                    str(out),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-plan-package-audit-report.v1")
            self.assertEqual(payload["implementation"]["status"], "NOT_PROVIDED")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["auditDigest"], payload["auditDigest"])

    def test_strict_mode_returns_error_for_draft_without_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "plan"
            package.mkdir()
            _write_minimal_package(package)

            code, payload = _run_cli(
                [
                    "audit",
                    "package",
                    "--plan-dir",
                    str(package),
                    "--require-frozen",
                    "--require-implementation",
                    "--strict",
                ]
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "package-audit-failed")


def _write_minimal_package(package: Path) -> None:
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "DRAFT",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plan"},
        "specification": {"tier": "S1", "requirements": [{"id": "R-01", "description": "Audit."}]},
        "releaseTarget": {"targetVersion": "1.0.0"},
        "forbiddenWrites": [],
        "leadOwned": [],
        "readOnly": [],
        "acceptance": {"criteria": [{"id": "AC-01", "requirementIds": ["R-01"], "evidenceIds": ["EV-01"]}]},
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"], "evidenceIds": ["EV-01"]}],
        "validation": {"commands": ["python -m unittest"], "extraEvidence": []},
    }
    (package / "plan.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("README.md", "00-developer-overview.md", "write-set.md", "evidence-plan.md", "plan-review.md"):
        (package / name).write_text("# plan\n", encoding="utf-8")
    (package / "acceptance-criteria.md").write_text(
        "| ID | Requirement IDs | Evidence IDs | Statement |\n"
        "| --- | --- | --- | --- |\n"
        "| `AC-01` | `R-01` | `EV-01` | Audit. |\n",
        encoding="utf-8",
    )
    (package / "plan.lock.json").write_text(
        json.dumps(
            {
                "schemaVersion": "agent-plan-lock.v1",
                "packageId": "package",
                "planRevision": 1,
                "manifestHash": _manifest_digest(manifest),
            }
        ),
        encoding="utf-8",
    )


def _manifest_digest(manifest: dict) -> str:
    from agent_lifecycle.contracts import canonical_digest

    return canonical_digest(manifest)


if __name__ == "__main__":
    unittest.main()
