from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class AuditSchemaTests(unittest.TestCase):
    def test_implementation_audit_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-implementation-audit-report.v1", ids)
        self.assertIn("agent-plan-package-audit-report.v1", ids)
        self.assertIn("agent-plan-package-audit-validation.v1", ids)
        self.assertIn("agent-final-implementation-audit.v1", ids)
        self.assertIn("agent-implementation-audit-report-validation.v1", ids)
        self.assertIn("agent-final-implementation-audit-validation.v1", ids)

    def test_implementation_audit_schema_requires_digest_and_verdict(self) -> None:
        schema = get_schema("agent-implementation-audit-report.v1")
        self.assertIn("verdict", schema["required"])
        self.assertIn("reportDigest", schema["required"])

    def test_package_audit_schema_requires_plan_and_implementation_sections(self) -> None:
        schema = get_schema("agent-plan-package-audit-report.v1")
        self.assertIn("plan", schema["required"])
        self.assertIn("implementation", schema["required"])
        self.assertIn("auditDigest", schema["required"])


if __name__ == "__main__":
    unittest.main()
