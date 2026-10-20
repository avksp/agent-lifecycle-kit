"""Selected preparation policy guards the actual existing planning sink."""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.adapter_sessions.launch_preflight import launch_from_local_profile
from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile
from agent_lifecycle.adapter_sessions.process_admission import (
    JournalPreparationAdmission,
    local_preparation_input_digest,
)
from tests.accounting.test_journal import PROOF, open_scope
from tests.adapter_sessions.test_process_admission import preparation_operation, qualified_context
from tests.review_mesh.test_preflight_execution_boundary import target_fixture


class PlanningPreparationIntegrationTests(unittest.TestCase):
    def test_planning_only_actual_sink_uses_journal_without_execution_target(self):
        fixture = Path(__file__).parent / "fixtures/local_launch_profiles/valid.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_fixture(root)
            profile = json.loads(fixture.read_text())
            profile["executable"] = sys.executable
            path = root / ".alk/host-launch/profile.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(profile), encoding="utf-8")
            profile_digest = validate_local_launch_profile(profile)["profileDigest"]
            binding = local_preparation_input_digest(
                profile_digest=profile_digest, operation="planningTask",
                repository_root=root, source_revision=None, task_id=None,
                task_text="bounded plan", immutable_context=None,
            )
            result = {
                "schemaVersion": "agent-planning-result.v1",
                "status": "REVIEW_REQUIRED", "summary": "bounded fixture",
                "requirements": [{"id": "R1"}], "workstreams": [{"id": "WS1"}],
                "evidenceRoutes": [{"id": "EV1"}],
                "implementationAuthorized": False, "productionPromotionClaimed": False,
            }
            script = "import json,sys; json.load(sys.stdin); print(" + repr(json.dumps(result)) + ")"
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                def qualify(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = binding
                    return context
                admission = JournalPreparationAdmission(
                    journal, replace(preparation_operation(), input_digest=binding),
                    qualify, clock=lambda: 100,
                )
                # Only host qualification/rendering is fixture supplied. The
                # policy, public local launch, real Git and real process sink run.
                with patch("agent_lifecycle.adapter_sessions.launch_preflight.render_planning_launch_argv",
                           return_value=[sys.executable, "-c", script]), patch(
                    "agent_lifecycle.adapter_sessions.launch_preflight.require_planning_qualification_receipt",
                    return_value={"status": "PASS", "fixtureOnly": True},
                ):
                    actual = launch_from_local_profile(
                        profile_path=path, operation="planningTask", project_root=root,
                        explicit_launch=True, requested_mode="plan", task_text="bounded plan",
                        process_env=dict(os.environ), preparation=admission,
                    )
                self.assertEqual(actual["status"], "REVIEW_REQUIRED", actual)
                self.assertEqual(journal.snapshot("run").active_reservations, 100)
                self.assertFalse(actual["implementationAuthorized"])
