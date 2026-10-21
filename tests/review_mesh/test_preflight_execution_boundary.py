"""Real Git/I/O target observations consumed at owned-effect boundaries."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.adapter_sessions.external_jobs import run_external_job
from agent_lifecycle.adapter_sessions.launch_preflight import launch_from_local_profile
from agent_lifecycle.adapter_sessions.process_admission import (
    ExecutionTargetSelection,
    JournalPreparationAdmission,
    preparation_operation_reason,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.execution_target import inspect_execution_target
from agent_lifecycle.review_mesh.preflight import reviewer_preflight
from tests.accounting.test_journal import PROOF, open_scope
from tests.adapter_sessions.test_external_jobs import _request
from tests.adapter_sessions.test_process_admission import (
    preparation_operation,
    qualified_context,
)


def target_fixture(root, state_name=".alk/run.json"):
    subprocess.run(["git", "init", "-q", str(root)], check=True,
                   capture_output=True)
    (root / ".gitignore").write_text(".alk/\njobs/\n*.db*\n", encoding="utf-8")
    (root / "source.txt").write_text("stable source", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit",
                    "-qm", "fixture"], check=True, capture_output=True)
    source = {"revision": "e" * 40, "subject": canonical_digest("source")}
    args = {
        "source_identity": source, "plan_identity": {"digest": "f" * 64},
        "source_paths": ["source.txt"], "outputs": [
            {"path": state_name, "role": "state"},
            {"path": ".alk/events.jsonl", "role": "events"},
        ], "state_path": state_name, "event_log": ".alk/events.jsonl",
        "stage": "PLANNING",
    }
    binding = inspect_execution_target(root, **args)
    return ExecutionTargetSelection(root=root, expected_digest=binding["bindingDigest"], **args)


class ExecutionBoundaryTests(unittest.TestCase):
    def admission(self, journal, target, input_digest="b" * 64, service=True,
                  service_name="declared-service"):
        source = canonical_digest(target.source_identity)
        reason = preparation_operation_reason(
            goal_digest="b" * 64, phase_digest="c" * 64, source_digest=source,
            charged_milliseconds=100, semantic_round=1,
            quantity="RESERVATION_TOKENS",
        )
        op = replace(preparation_operation(), attribution_reason=reason,
                     input_digest=input_digest)
        def qualify(prefix):
            context = qualified_context(prefix)
            context.update(sourceDigest=source, executionChain=True,
                           targetId=target.recheck()["targetId"], inputDigest=input_digest)
            context["progress"]["sourceDigest"] = source
            context["readiness"]["sourceDigest"] = source
            context["readiness"]["checks"][service_name] = "PASS" if service else "UNAVAILABLE"
            return context
        return JournalPreparationAdmission(journal, op, qualify, clock=lambda: 100, target=target)

    def test_clean_occupied_ignored_target_refuses_real_external_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = target_fixture(root)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                request = _request("occupied")
                admission = self.admission(journal, target, request["requestDigest"])
                (root / ".alk").mkdir()
                (root / ".alk/run.json").write_text("foreign", encoding="utf-8")
                clean = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                       check=True, capture_output=True)
                self.assertEqual(clean.stdout, b"")
                runner = Mock(side_effect=AssertionError("model started"))
                with self.assertRaises(LifecycleError):
                    run_external_job(request, [sys.executable, "-c", "pass"],
                                     env=dict(os.environ), cwd=root, job_root=root / "jobs",
                                     preparation=admission, process_runner=runner)
                runner.assert_not_called()
                self.assertEqual(journal.snapshot("run").journal_revision, 1)
                self.assertEqual((root / ".alk/run.json").read_text(), "foreign")

    def test_two_real_projects_current_target_rechecked_at_dispatch(self):
        for state_name in (".alk/run.json", ".alk/other/state.json"):
            with self.subTest(state_name=state_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = target_fixture(root, state_name)
                with Journal(root / "usage.db", PROOF) as journal:
                    open_scope(journal)
                    request = _request("bound")
                    admission = self.admission(
                        journal, target, request["requestDigest"],
                        service_name="first-project-cache" if "other" not in state_name
                        else "second-project-index",
                    )
                    with patch("agent_lifecycle.adapter_sessions.process_admission.inspect_execution_target",
                               wraps=inspect_execution_target) as inspect:
                        result = run_external_job(
                            request, [sys.executable, "-c", "print('response')"],
                            env=dict(os.environ), cwd=root, job_root=root / "jobs",
                            preparation=admission,
                        )
                    self.assertEqual(result["result"]["state"], "SUCCEEDED")
                    self.assertGreaterEqual(inspect.call_count, 3)
                    self.assertFalse((root / state_name).exists())

    def test_wrong_clone_and_service_missing_start_zero_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, other = base / "real", base / "clone"
            root.mkdir()
            other.mkdir()
            target = target_fixture(root)
            target_fixture(other)
            with Journal(base / "usage.db", PROOF) as journal:
                open_scope(journal)
                request = _request("wrong-target")
                runner = Mock()
                with self.assertRaises(LifecycleError):
                    run_external_job(request, ["never"], env={}, cwd=other,
                                     job_root=base / "jobs", process_runner=runner,
                                     preparation=self.admission(journal, target, request["requestDigest"]))
                with self.assertRaises(LifecycleError):
                    run_external_job(request, ["never"], env={}, cwd=root,
                                     job_root=base / "jobs", process_runner=runner,
                                     preparation=self.admission(journal, target, request["requestDigest"], service=False))
                runner.assert_not_called()
                self.assertEqual(journal.snapshot("run").journal_revision, 1)

    def test_target_guard_is_consumed_by_local_generic_and_review_preflight(self):
        from agent_lifecycle.adapter_sessions.launch_execution import launch_from_descriptor
        from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = target_fixture(root)
            profile = load_shipped_launch_profile(
                "codex", repository_root=Path(__file__).resolve().parents[2],
            )
            profile["executable"] = sys.executable
            path = root / ".alk/host-launch/profile.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(profile), encoding="utf-8")
            pins = {"source.txt": hashlib.sha256((root / "source.txt").read_bytes()).hexdigest()}
            packet, rendered, argv = {"subject": "read-only audit"}, b"bounded", [sys.executable]
            request = _request("target-preflight")
            request["sourceSnapshotDigest"] = canonical_digest(pins)
            request["requestDigest"] = canonical_digest({
                k: v for k, v in request.items() if k != "requestDigest"
            })
            qualification = {
                "requestDigest": request["requestDigest"],
                "repositoryRootDigest": canonical_digest(str(root.resolve())),
                "inputTransport": "STDIN",
                "qualified": True, "sourceSnapshotDigest": canonical_digest(pins),
                "packetDigest": canonical_digest(packet),
                "renderedInputDigest": hashlib.sha256(rendered).hexdigest(),
                "renderedInputBytes": len(rendered), "inputComplete": True,
                "providerReady": True, "readOnlyEnforced": True,
                "restrictionBasis": "HOST_RESTRICTIONS",
                "allowedArgvDigest": canonical_digest(argv),
            }
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                admission = self.admission(journal, target)
                (root / ".alk/run.json").write_text("foreign", encoding="utf-8")
                runner = Mock()
                for operation in ("planningTask", "managedTask"):
                    with self.assertRaises(LifecycleError):
                        launch_from_local_profile(
                            profile_path=path, operation=operation, project_root=root,
                            explicit_launch=True, requested_mode="plan", task_text="audit",
                            preparation=admission, process_runner=runner,
                        )
                generic = launch_from_descriptor(
                    descriptor={"adapterId": "fixture"}, session_id="bounded",
                    launch_mode="managedTask", preparation=admission, project_root=root,
                )
                self.assertEqual(generic["status"], "BLOCKED")
                review = reviewer_preflight(
                    request=request,
                    repository_root=root, source_pins=pins, packet=packet,
                    rendered_input=rendered, argv=argv, qualification=qualification,
                    preparation=admission,
                )
                self.assertEqual(review["status"], "UNAVAILABLE")
                runner.assert_not_called()
                self.assertEqual(journal.snapshot("run").journal_revision, 1)
                self.assertEqual((root / ".alk/run.json").read_text(), "foreign")

    def test_environment_repair_keeps_report_lock_and_source_change_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = target_fixture(root)
            (root / ".alk").mkdir()
            report, lock = root / ".alk/review.json", root / ".alk/plan.lock.json"
            report.write_bytes(b'{"fixture":"unchanged reviewed subject"}')
            lock.write_bytes(b'{"fixture":"unchanged lock"}')
            before = (report.read_bytes(), lock.read_bytes())
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                admission = self.admission(journal, target)
                self.assertEqual(admission.check(repository_root=root)["status"], "PASS")
                occupied = root / ".alk/run.json"
                occupied.write_text("environment conflict", encoding="utf-8")
                with self.assertRaises(LifecycleError):
                    admission.check(repository_root=root)
                occupied.unlink()  # Explicit test-environment correction only.
                self.assertEqual(admission.check(repository_root=root)["status"], "PASS")
                self.assertEqual((report.read_bytes(), lock.read_bytes()), before)
                self.assertEqual(journal.snapshot("run").journal_revision, 1)
                (root / "source.txt").write_text("changed reviewed dependency", encoding="utf-8")
                with self.assertRaises(LifecycleError):
                    admission.invoke(lambda: self.fail("stale positive reuse"),
                                     input_digest="b" * 64, repository_root=root)
                self.assertEqual((report.read_bytes(), lock.read_bytes()), before)

    def test_target_change_after_claim_preserves_hold_without_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = target_fixture(root)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                original = self.admission(journal, target)
                calls = 0
                def qualify(prefix):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        (root / ".alk").mkdir(exist_ok=True)
                        (root / ".alk/run.json").write_text("competing writer", encoding="utf-8")
                    return original.qualify(prefix)
                changed = replace(original, qualify=qualify)
                with self.assertRaises(LifecycleError):
                    changed.invoke(lambda: self.fail("stale dispatch"),
                                   input_digest="b" * 64, repository_root=root)
                self.assertEqual(journal.snapshot("run").active_reservations, 100)
                self.assertEqual((root / ".alk/run.json").read_text(), "competing writer")
