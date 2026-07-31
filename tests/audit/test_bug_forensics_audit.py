from __future__ import annotations

import unittest

from agent_lifecycle.audit import build_bug_forensics_audit, validate_bug_forensics_audit
from agent_lifecycle.workflow import build_bug_forensics_gate_receipt


class BugForensicsAuditTests(unittest.TestCase):
    def test_skipped_gate_audits_as_skipped(self) -> None:
        gate = build_bug_forensics_gate_receipt(task={"id": "WS-01", "taskType": "feature"})

        audit = build_bug_forensics_audit(gate_receipt=gate)
        validation = validate_bug_forensics_audit(audit)

        self.assertEqual(audit["status"], "SKIPPED")
        self.assertEqual(validation["status"], "PASS")

    def test_failed_active_gate_audits_as_fail(self) -> None:
        gate = build_bug_forensics_gate_receipt(task={"id": "BUG-1", "qualityProfile": "bug-forensics"})

        audit = build_bug_forensics_audit(gate_receipt=gate)
        validation = validate_bug_forensics_audit(audit)

        self.assertEqual(audit["status"], "FAIL")
        self.assertEqual(validation["status"], "PASS")
        self.assertIn("bug-forensics-active-gate-not-pass", {item["code"] for item in audit["blockers"]})


if __name__ == "__main__":
    unittest.main()
