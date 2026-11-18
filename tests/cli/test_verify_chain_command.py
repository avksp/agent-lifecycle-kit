"""Public CLI reports verification outcomes and their process exit classes."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from agent_lifecycle.cli.main import main
from agent_lifecycle.contracts.chain_verification_schemas import REPORT
from agent_lifecycle.contracts.schemas import get_schema
from tests.audit.test_chain_verification import AnchoredRunFixture
from tests.contracts.test_operator_signature import inventory
from tests.workflow.test_operator_signature_gates import write


class VerifyChainCommandTests(TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        self.fixture = AnchoredRunFixture(self.root, operator_required=True, task_bearing=True)

    def call(self, status: str, exit_code: int) -> dict:
        fixture = self.fixture
        before = inventory(self.root)
        target = io.StringIO()
        with redirect_stdout(target):
            actual = main(
                [
                    "audit",
                    "verify-chain",
                    "--repository-root",
                    str(fixture.repo),
                    "--bundle",
                    fixture.bundle_name,
                    "--trust-config",
                    str(fixture.trust),
                    "--anchor",
                    str(fixture.anchor),
                ]
            )
        self.assertEqual(actual, exit_code)
        report = json.loads(target.getvalue())
        self.assertEqual(report["schemaVersion"], REPORT)
        self.assertEqual(report["exitCode"], actual)
        self.assertEqual(report["status"], status)
        self.assertEqual(inventory(self.root), before)
        self.assertFalse(report["authorityGranted"])
        return report

    def test_success_uses_public_report_schema_with_both_signature_checks(self) -> None:
        report = self.call("VERIFIED", 0)
        self.assertIn({"check": "operator-signatures", "status": "VERIFIED"}, report["checks"])
        self.assertEqual(get_schema(REPORT)["$id"], REPORT)
        self.assertIn("reviewerAdmission", get_schema("agent-plan-lock.v4")["required"])

    def test_tampered_receipt_returns_structured_mismatch_and_exit_one(self) -> None:
        (self.fixture.repo / "receipts/proof.json").unlink()
        report = self.call("MISMATCH", 1)
        self.assertEqual(report["firstFailure"], {"check": "reviewer-signatures", "code": "chain-input-missing"})

    def test_missing_anchor_returns_structured_input_error_and_exit_two(self) -> None:
        self.fixture.anchor.unlink()
        report = self.call("INVALID_INPUT", 2)
        self.assertEqual(report["firstFailure"], {"check": "input", "code": "chain-input-missing"})

    def test_incomplete_history_returns_nonzero_not_checked(self) -> None:
        state = self.fixture.read(self.fixture.bundle["state"])
        state["schemaVersion"] = "agent-workflow-state.v7"
        write(self.fixture.state_path, state)
        self.fixture.rebuild_chain()
        self.fixture.refresh_anchor()
        report = self.call("NOT_CHECKED", 1)
        self.assertEqual(report["firstFailure"]["code"], "chain-state-profile-unsupported")

    def test_ordinary_version_command_retains_exit_zero_and_existing_schema(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["version"]), 0)
        self.assertEqual(json.loads(output.getvalue())["schemaVersion"], "agent-lifecycle-version.v1")
