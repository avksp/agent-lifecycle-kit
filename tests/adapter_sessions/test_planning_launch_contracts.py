from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.adapter_sessions.planning_launch import (  # noqa: E402
    build_planning_envelope,
    parse_planning_result,
    run_planning_launch,
)
from agent_lifecycle.adapter_sessions.launcher import run_planning_qualification_candidate  # noqa: E402
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile  # noqa: E402
from agent_lifecycle.contracts.schemas import get_schema  # noqa: E402


class PlanningLaunchContractTests(unittest.TestCase):
    def test_public_contracts_are_registered(self) -> None:
        for schema_id in (
            "agent-planning-launch-envelope.v1",
            "agent-planning-result.v1",
            "agent-planning-launch-receipt.v1",
            "agent-planning-session-state.v1",
        ):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_envelope_labels_raw_task_as_untrusted_and_planning_only(self) -> None:
        envelope = build_planning_envelope(
            adapter_id="codex",
            session_id="session-1",
            requested_mode="plan",
            task_text="inspect the repository",
            input_source="text",
        )

        self.assertEqual(envelope["task"]["untrustedText"], "inspect the repository")
        self.assertTrue(envelope["authority"]["planningOnly"])
        self.assertFalse(envelope["authority"]["implementationAuthorized"])

    def test_successful_launch_returns_review_required_without_raw_task(self) -> None:
        raw_task = "private customer task"
        result = {
            "schemaVersion": "agent-planning-result.v1",
            "status": "REVIEW_REQUIRED",
            "summary": "A bounded plan candidate",
            "requirements": [{"id": "R1", "statement": "Inspect inputs"}],
            "workstreams": [{"id": "WS1", "goal": "Research"}],
            "evidenceRoutes": [{"id": "EV1", "route": "tests"}],
            "implementationAuthorized": False,
            "productionPromotionClaimed": False,
        }
        command = [sys.executable, "-c", f"print({json.dumps(json.dumps(result))})"]

        receipt = run_planning_launch(
            adapter_id="codex",
            session_id="session-1",
            requested_mode="plan",
            task_text=raw_task,
            input_source="text",
            argv=command,
            env=dict(os.environ),
        )

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertFalse(receipt["implementationAuthorized"])
        self.assertTrue(receipt["requiresReview"])
        self.assertNotIn(raw_task, json.dumps(receipt))
        self.assertEqual(receipt["usageEvidence"]["confidence"], "MISSING")

    def test_authority_claim_is_rejected(self) -> None:
        payload = {
            "schemaVersion": "agent-planning-result.v1",
            "status": "REVIEW_REQUIRED",
            "summary": "bad",
            "requirements": ["R"],
            "workstreams": [{"id": "WS"}],
            "evidenceRoutes": [{"id": "EV"}],
            "implementationAuthorized": True,
            "productionPromotionClaimed": False,
        }

        result, blockers = parse_planning_result(json.dumps(payload))

        self.assertIsNone(result)
        self.assertIn("planning-result-authority-claim", {item["code"] for item in blockers})

    def test_launch_uses_explicit_child_cwd(self) -> None:
        result = {
            "schemaVersion": "agent-planning-result.v1",
            "status": "REVIEW_REQUIRED",
            "summary": "cwd supplied by the controller",
            "requirements": [{"id": "R1"}],
            "workstreams": [{"id": "WS1"}],
            "evidenceRoutes": [{"id": "EV1"}],
            "implementationAuthorized": False,
            "productionPromotionClaimed": False,
        }
        script = "import json,sys; json.load(sys.stdin); print(json.dumps(" + repr(result) + "))"
        with tempfile.TemporaryDirectory() as tmp:
            receipt = run_planning_launch(
                adapter_id="codex",
                session_id="session-cwd",
                requested_mode="plan",
                task_text="inspect",
                input_source="text",
                argv=[sys.executable, "-c", script],
                env=dict(os.environ),
                process_cwd=Path(tmp),
            )
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")

    def test_qualification_enforces_timeout_and_attested_token_budget(self) -> None:
        profile = load_shipped_launch_profile("gemini-cli", repository_root=ROOT)
        receipt = {
            "status": "REVIEW_REQUIRED",
            "blockers": [],
            "hostLaunchStarted": True,
            "modelCallsStarted": True,
            "usageEvidence": {
                "confidence": "ATTESTED",
                "inputTokens": 80,
                "outputTokens": 30,
                "moneyFieldsCanonical": False,
            },
            "receiptDigest": "planning-receipt",
        }
        identity = {"identityDigest": "unchanged"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_path = root / ".alk/host-launch/gemini-cli.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with (
                mock.patch(
                    "agent_lifecycle.adapter_sessions.launcher.capture_git_worktree_identity",
                    side_effect=[identity, identity],
                ),
                mock.patch(
                    "agent_lifecycle.adapter_sessions.launcher.run_planning_launch",
                    return_value=receipt,
                ) as launch,
            ):
                evidence = run_planning_qualification_candidate(
                    profile_path=profile_path,
                    project_root=root,
                    approval_digest="approval",
                    max_wall_seconds=25,
                    model_token_budget=100,
                    process_env={"HOME": tmp, "PATH": os.environ.get("PATH", "")},
                )
        self.assertEqual(evidence["status"], "FAIL")
        self.assertIn(
            "planning-qualification-token-budget-exceeded",
            {item["code"] for item in evidence["blockers"]},
        )
        self.assertEqual(launch.call_args.kwargs["timeout_seconds"], 25)
        self.assertEqual(launch.call_args.kwargs["process_cwd"], root)

    def test_qualification_rejects_unattested_usage(self) -> None:
        profile = load_shipped_launch_profile("gemini-cli", repository_root=ROOT)
        receipt = {
            "status": "REVIEW_REQUIRED",
            "blockers": [],
            "hostLaunchStarted": True,
            "modelCallsStarted": True,
            "usageEvidence": {
                "confidence": "ESTIMATED",
                "inputTokens": 10,
                "outputTokens": 10,
                "moneyFieldsCanonical": False,
            },
            "receiptDigest": "planning-receipt",
        }
        identity = {"identityDigest": "unchanged"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_path = root / ".alk/host-launch/gemini-cli.json"
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with (
                mock.patch(
                    "agent_lifecycle.adapter_sessions.launcher.capture_git_worktree_identity",
                    side_effect=[identity, identity],
                ),
                mock.patch(
                    "agent_lifecycle.adapter_sessions.launcher.run_planning_launch",
                    return_value=receipt,
                ),
            ):
                evidence = run_planning_qualification_candidate(
                    profile_path=profile_path,
                    project_root=root,
                    approval_digest="approval",
                    max_wall_seconds=25,
                    model_token_budget=100,
                    process_env={"HOME": tmp, "PATH": os.environ.get("PATH", "")},
                )
        self.assertEqual(evidence["status"], "FAIL")
        self.assertIn(
            "planning-qualification-usage-unattested",
            {item["code"] for item in evidence["blockers"]},
        )


if __name__ == "__main__":
    unittest.main()
