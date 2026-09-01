from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli.dispatch_audit import dispatch_audit
from agent_lifecycle.cli.dispatch_lifecycle import dispatch_lifecycle


class AuditDispatchTests(unittest.TestCase):
    def test_delta_dispatch_passes_closed_inputs_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "delta.json"
            payload = {"schemaVersion": "agent-rework-delta-audit-receipt.v1", "status": "PASS"}
            args = argparse.Namespace(
                audit_command="delta",
                manifest="plans/release/plan.manifest.json",
                lock="plans/release/plan.lock.json",
                state="work/release/run.state.json",
                task="WS-01",
                dependency_report="work/dependencies.json",
                validation_selection="work/selection.json",
                finding_check_binding=["work/binding-1.json", "work/binding-2.json"],
                finding_check_evidence=["work/evidence.json"],
                out=str(out),
            )

            with patch(
                "agent_lifecycle.cli.dispatch_audit.build_rework_delta_audit",
                return_value=payload,
            ) as builder:
                result = dispatch_audit(args)

            self.assertEqual(result, payload)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)
            builder.assert_called_once_with(
                manifest_path=Path("plans/release/plan.manifest.json"),
                lock_path=Path("plans/release/plan.lock.json"),
                state_path=Path("work/release/run.state.json"),
                task_id="WS-01",
                dependency_report_path=Path("work/dependencies.json"),
                validation_selection_path=Path("work/selection.json"),
                finding_check_binding_paths=[Path("work/binding-1.json"), Path("work/binding-2.json")],
                finding_check_evidence_paths=[Path("work/evidence.json")],
            )

    def test_lifecycle_dispatch_delegates_audit_group(self) -> None:
        args = argparse.Namespace(command="audit", audit_command="review-check")
        with patch(
            "agent_lifecycle.cli.dispatch_lifecycle.dispatch_audit",
            return_value={"status": "PASS"},
        ) as handler:
            self.assertEqual(dispatch_lifecycle(args), {"status": "PASS"})
        handler.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
