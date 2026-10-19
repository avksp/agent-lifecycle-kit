from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.accounting.contracts import RunClosure
from agent_lifecycle.accounting.input_fit import assess_local_input_fit, select_source_excerpts
from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.adapter_sessions import bootstrap_r11
from agent_lifecycle.adapter_sessions import codex_exact_prompt as exact_prompt_module
from agent_lifecycle.adapter_sessions import codex_source_exposure as source_exposure_module
from agent_lifecycle.adapter_sessions import codex_source_subject as source_subject_module
from agent_lifecycle.adapter_sessions.codex_exact_prompt import (
    CLAIM,
    ROUTE_ID,
    _build_source_exposure_packet,
    _check_source_exposure,
    _matches_closed_schema,
    _observed_bundled_catalog,
    _observed_prompt_diagnostic,
    _private_dir,
    _r69h_check_test_dependency_closure,
    _r69h_codex_exposure,
    _recheck_active_workflow_state,
    _recheck_alk_fit_sources,
    _recompute_bootstrap_subject,
    _record_transport_witness,
    _remove_snapshot_no_start,
    _require_current_manifest,
    _require_fresh_catalog,
    _review_findings_match_v4,
    _selected_binary_path,
    _selected_host_evidence,
    _single_turn_projection,
    _snapshot_digest,
    _source_test_ids,
    _write_exclusive,
    assess_retention_pre_fixture,
    assess_single_turn_bootstrap_context_fit,
    build_single_turn_bootstrap_review_request,
    cleanup_no_start,
    cleanup_prestart_raw,
    create_prestart_raw_inventory,
    prepare_exact_prompt,
    read_codex_app_server_thread,
    reconcile_prelaunch_intents,
    record_proven_no_start,
    require_bootstrap_audit,
    stage_input_request,
    verify_prestart_raw_inventory,
)
from agent_lifecycle.adapter_sessions.launch_preflight import (
    _managed_task,
    _run_exact_managed_process,
    launch_from_local_profile,
)
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.unified_start import start_lifecycle
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.private_storage import PinnedPrivateDirectory
from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash
from tests.accounting.test_journal import PROOF
from tests.accounting.test_opening_balances import import_data
from tests.adapter_sessions.test_bootstrap_r11 import bound_current_invocation_fixture
from tests.adapter_sessions.test_windows_pipe import (
    assert_private_path,
    install_windows_fixture_process,
    process_is_running,
)
from tests.contracts.test_private_storage import unsafe_private_access

_CODEX_FIXTURE_NAME = "codex.exe" if os.name == "nt" else "codex"



class ExactPromptPrivateInputTests(unittest.TestCase):
    def _runtime_inventory_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        private = root / "work/release-2-16/private-details/codex-exact-prompt/run-1/task-1/1"
        for name in ("input-request.json", "prompt-input.json", "effective-config.json"):
            _write_exclusive(private / name, name.encode(), root=root)
        snapshot = self._snapshot(root)
        state = self._workflow_state(root)
        inventory, marker, digest = create_prestart_raw_inventory(
            root, run_id="run-1", task_id="task-1", attempt_id="1",
            sealed_request=private / "input-request.json", state=state, plan_digest="a" * 64)
        verify = lambda started=True: verify_prestart_raw_inventory(
            root, inventory_path=inventory, pending_path=marker, state=state,
            plan_digest="a" * 64, started=started)
        return root, private, snapshot, state, inventory, marker, digest, verify

    def test_runtime_additions_are_not_prestart_input_changes(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        runtime = snapshot / "tmp/arg0/codex-arg0-fixture"
        runtime.mkdir(parents=True, mode=0o755)
        runtime.chmod(0o755)
        (runtime / "apply_patch").symlink_to("/missing/host-wrapper")
        with self.assertRaises(LifecycleError):
            verify(False)
        self.assertEqual(verify(), digest)
        self.assertEqual(json.loads(marker.read_text())["status"], "PENDING")
        self.assertTrue((runtime / "apply_patch").is_symlink())

    def test_runtime_boundary_rejects_changed_pinned_config(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        config = snapshot / "config.toml"
        config.chmod(0o600)
        config.write_text("model = 'changed'\n")
        config.chmod(0o400)
        with self.assertRaises(LifecycleError) as rejected:
            verify()
        self.assertEqual(rejected.exception.code, "codex-exact-raw-inventory-stale")

    def test_runtime_boundary_accepts_large_readonly_and_writable_pinned_files(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        for mode in (0o400, 0o600):
            with self.subTest(mode=mode):
                # Rebuild before-start authority for each admitted file mode.
                large = snapshot / "model-catalog.json"
                if large.exists():
                    large.chmod(0o600)
                large.write_bytes(b"x" * 196608)
                large.chmod(mode)
                inventory.unlink()
                marker.unlink()
                inventory, marker, digest = create_prestart_raw_inventory(
                    root, run_id="run-1", task_id="task-1", attempt_id="1",
                    sealed_request=private / "input-request.json", state=state, plan_digest="a" * 64)
                self.assertEqual(verify(), digest)

    def test_runtime_boundary_rejects_changed_sealed_request(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        (private / "input-request.json").write_text("changed")
        with self.assertRaises(LifecycleError):
            verify()

    def test_runtime_boundary_rejects_replaced_journal(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        journal = root / state["eventLog"]
        journal.rename(journal.with_suffix(".old"))
        journal.write_text("")
        with self.assertRaises(LifecycleError):
            verify()

    def test_runtime_boundary_rejects_replaced_snapshot_root(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        old = snapshot.with_name("previous-home")
        snapshot.rename(old)
        shutil.copytree(old, snapshot)
        snapshot.chmod(0o700)
        with self.assertRaises(LifecycleError):
            verify()

    @unittest.skipUnless(os.name == "posix", "snapshot link fixture requires POSIX")
    def test_runtime_boundary_rejects_pinned_file_symlink(self) -> None:
        root, private, snapshot, state, inventory, marker, digest, verify = self._runtime_inventory_fixture()
        config = snapshot / "config.toml"
        outside = root / "outside-config.toml"
        outside.write_bytes(config.read_bytes())
        outside.chmod(0o400)
        config.unlink()
        config.symlink_to(outside)
        with self.assertRaises(LifecycleError):
            verify()
        self.assertTrue(outside.exists())

    def test_runtime_callback_preserves_pipe_proof_without_whole_tree_claim(self) -> None:
        # Local Python child; existing fixture mocks host fit and inventory.
        # The six inventory tests above exercise real sealed records separately.
        from tests.adapter_sessions import test_bootstrap_r11 as fixtures
        fixture = fixtures.PreparedAttemptIntegrationTests()
        try:
            fixture.setUp()
            original = fixture.prepared["onStarted"]
            def host_runtime_then_observe(event):
                runtime = fixture.home / "tmp/arg0/codex-arg0-fixture"
                runtime.mkdir(parents=True, mode=0o755)
                runtime.chmod(0o755)
                (runtime / "apply_patch").symlink_to("/missing/host-wrapper")
                original(event)
            fixture.prepared["onStarted"] = host_runtime_then_observe
            result = fixture.launch()
            self.assertEqual(result["status"], "PASS", result)
            observed = json.loads((fixture.evidence / "process-start.json").read_text())
            self.assertEqual(observed["observedCodexHomeContentDigest"], "UNPROVEN")
            self.assertEqual(observed["prelaunchCodexHomeContentDigest"], observed["codexHomeContentDigest"])
            self.assertEqual(observed["childInternalEffectiveConfig"], "UNPROVEN")
            pipe = json.loads((fixture.evidence / "process-input.json").read_text())
            self.assertEqual(pipe["status"], "COMPLETE")
            self.assertTrue(pipe["closeSucceeded"])
        finally:
            fixture.doCleanups()

    def test_r11_late_prepared_receipts_cannot_promote_failed_result(self) -> None:
        # The shared fixture drives actual prepared callbacks and a local child.
        from tests.adapter_sessions import test_bootstrap_r11 as fixtures
        fixture = fixtures.PreparedAttemptIntegrationTests()
        try:
            fixture.setUp()
            fixture.exercise_late_prepared_receipts()
        finally:
            fixture.doCleanups()

    def test_r11_terminal_publish_failure_retains_uncertain_hold(self) -> None:
        from tests.adapter_sessions import test_bootstrap_r11 as fixtures
        fixture = fixtures.PreparedAttemptIntegrationTests()
        try:
            fixture.setUp()
            fixture.exercise_terminal_publication_failure()
        finally:
            fixture.doCleanups()

    def test_bootstrap_case_names_rederived_from_current_sources(self) -> None:
        root = Path(__file__).parents[2]
        names, hashes = _source_test_ids(root, [
            "tests.adapter_sessions.test_codex_exact_prompt",
            "tests.cli.test_host_launch_commands",
        ])
        self.assertIn(
            "tests.adapter_sessions.test_codex_exact_prompt."
            "ExactPromptPrivateInputTests.test_orphan_staged_input_blocks_next_attempt",
            names)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(hashes["tests/adapter_sessions/test_codex_exact_prompt.py"],
                         hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def test_rb11_pre_is_pure_due_not_due_open_and_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with Journal(Path(temporary) / "retention.db", PROOF) as journal:
                scope, policy, opening = import_data("run-1")
                self.assertEqual(journal.import_opening(scope, policy, opening).status, "IMPORTED")
                now = datetime.now(timezone.utc) + timedelta(seconds=1)
                self.assertIsNone(journal.closed_run("run-1"))
                oracle = lambda fixture, instant, clear=True: assess_retention_pre_fixture(
                    "run-1", fixture, instant, reconciliation_clear=clear)
                self.assertEqual(oracle(journal.closed_run("run-1"), now.isoformat())["status"],
                                 "OPEN_NO_PURGE_CLOCK")
                revision = journal.snapshot("run-1").journal_revision
                closure = RunClosure("close-1", "run-1", "reportedTokens:fixture:v1",
                                     now.isoformat(), (("run-1", revision),), PROOF, PROOF)
                closed_outcome = journal.close_run(closure, now.isoformat())
                self.assertEqual(closed_outcome.status, "CLOSED")
                verified = journal.closed_run("run-1")
                self.assertIsNotNone(verified)
                due_at = datetime.fromisoformat(closed_outcome.eligible_after)
                self.assertEqual(oracle(verified, (due_at - timedelta(microseconds=1)).isoformat())["status"],
                                 "NOT_DUE_PRE_ONLY")
                self.assertEqual(oracle(verified, due_at.isoformat()),
                                 {"caseId": "RB11-PRE", "runtimeStatus": "NOT_RUN",
                                  "status": "DUE_PRE_ONLY"})
                self.assertEqual(oracle(verified, due_at.isoformat(), False)["status"],
                                 "REFUSED_PRE_ONLY")
                self.assertEqual(oracle({**verified, "eligible_after": now.isoformat()},
                                        due_at.isoformat())["status"], "REFUSED_PRE_ONLY")
                self.assertEqual(oracle({**verified, "summary_digest": "0" * 64},
                                        due_at.isoformat())["status"], "REFUSED_PRE_ONLY")

    @staticmethod
    def _workflow_state(root: Path) -> dict[str, str]:
        event_log = root / "work/run.events.jsonl"
        event_log.parent.mkdir(parents=True, exist_ok=True)
        event_log.write_text("")
        return {"runId": "run-1", "eventLog": "work/run.events.jsonl"}

    @staticmethod
    def _snapshot(root: Path) -> Path:
        snapshot = (root / "work/release-2-16/runtime-private/codex-exact-prompt"
                    / "run-1/task-1/1/codex-home")
        _private_dir(snapshot.parent, boundary=root)
        snapshot.mkdir(mode=0o700)
        snapshot.chmod(0o700)
        config = snapshot / "config.toml"
        config.write_bytes(b"model = 'test-model'\n")
        config.chmod(0o400)
        return snapshot

    @unittest.skipUnless(os.name == "posix", "snapshot symlink fixture requires POSIX")
    def test_snapshot_symlink_ancestor_refuses_inventory_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            outside = Path(external)
            snapshot = outside / "codex-exact-prompt/run-1/task-1/1/codex-home"
            snapshot.mkdir(parents=True, mode=0o700)
            (snapshot / "config.toml").write_text("private")
            parent = root / "work/release-2-16"
            parent.mkdir(parents=True)
            (parent / "runtime-private").symlink_to(outside, target_is_directory=True)
            selected = parent / "runtime-private/codex-exact-prompt/run-1/task-1/1/codex-home"
            with self.assertRaises(LifecycleError) as inventory:
                _snapshot_digest(selected, root=root)
            self.assertEqual(inventory.exception.code, "codex-exact-private-path-unsafe")
            with self.assertRaises(LifecycleError) as cleanup:
                _remove_snapshot_no_start(selected, root=root)
            self.assertEqual(cleanup.exception.code, "codex-exact-private-path-unsafe")
            self.assertTrue((snapshot / "config.toml").exists())

    def test_prestart_inventory_lists_snapshot_tree_and_no_start_cleans_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            for name, raw in (("input-request.json", b"request"),
                              ("prompt-input.json", b"diagnostic"),
                              ("effective-config.json", b"config")):
                _write_exclusive(private / name, raw, root=root)
            snapshot = self._snapshot(root)
            inventory, marker, digest = create_prestart_raw_inventory(
                root, run_id="run-1", task_id="task-1", attempt_id="1",
                sealed_request=private / "input-request.json",
                state=self._workflow_state(root),
                plan_digest="a" * 64,
            )
            body = json.loads(inventory.read_text())
            self.assertEqual(body["journalAuthorityKind"], "WORKFLOW_EVENT_LOG_PRE_WS01")
            self.assertEqual(len(body["journalIdentity"]), 64)
            self.assertEqual([row["kind"] for row in body["sources"]],
                             ["sealed-request", "diagnostic", "effective-config",
                              "codex-home-snapshot-tree", "codex-home-snapshot-file"])
            self.assertEqual(body["sources"][3]["cleanupScope"],
                             "WHOLE_TREE_INCLUDING_POST_START_ADDITIONS")
            self.assertEqual(body["sources"][4]["path"],
                             str((snapshot / "config.toml").relative_to(root)))
            self.assertEqual(json.loads(marker.read_text())["inventorySha256"], digest)
            self.assertEqual(json.loads(marker.read_text())["status"], "PENDING")
            cleanup_prestart_raw(root, run_id="run-1", task_id="task-1", attempt_id="1",
                                 staging_source=None, proven_no_start=True)
            self.assertEqual(json.loads(marker.read_text())["status"], "DONE")
            self.assertEqual(list(private.glob("*.json")), [])
            self.assertFalse(snapshot.exists())

    def test_prestart_inventory_requires_journal_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(LifecycleError) as raised:
                create_prestart_raw_inventory(
                    root, run_id="run-1", task_id="task-1", attempt_id="1",
                    sealed_request=root / "unbound.json",
                    state={"runId": "run-1", "eventLog": "work/missing.events.jsonl"},
                    plan_digest="a" * 64)
            self.assertEqual(raised.exception.code, "codex-exact-journal-unavailable")

    def test_prestart_inventory_refuses_symlinked_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.events.jsonl"
            outside.write_text("")
            (root / "work").mkdir()
            (root / "work/run.events.jsonl").symlink_to(outside)
            with self.assertRaises(LifecycleError) as raised:
                create_prestart_raw_inventory(
                    root, run_id="run-1", task_id="task-1", attempt_id="1",
                    sealed_request=root / "unbound.json",
                    state={"runId": "run-1", "eventLog": "work/run.events.jsonl"},
                    plan_digest="a" * 64)
            self.assertEqual(raised.exception.code, "codex-exact-journal-unavailable")

    def test_last_boundary_detects_replaced_event_log_and_changed_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            for name in ("input-request.json", "prompt-input.json", "effective-config.json"):
                _write_exclusive(private / name, name.encode(), root=root)
            snapshot = self._snapshot(root)
            state = self._workflow_state(root)
            inventory, marker, _ = create_prestart_raw_inventory(
                root, run_id="run-1", task_id="task-1", attempt_id="1",
                sealed_request=private / "input-request.json", state=state,
                plan_digest="a" * 64)
            self.assertEqual(len(verify_prestart_raw_inventory(
                root, inventory_path=inventory, pending_path=marker,
                state=state, plan_digest="a" * 64)), 64)
            event_log = root / state["eventLog"]
            event_log.rename(event_log.with_name("old.events.jsonl"))
            event_log.write_text("")
            with self.assertRaises(LifecycleError) as replaced:
                verify_prestart_raw_inventory(
                    root, inventory_path=inventory, pending_path=marker,
                    state=state, plan_digest="a" * 64)
            self.assertEqual(replaced.exception.code, "codex-exact-raw-inventory-stale")
            event_log.unlink()
            event_log.with_name("old.events.jsonl").rename(event_log)
            (private / "prompt-input.json").write_text("changed")
            with self.assertRaises(LifecycleError) as changed:
                verify_prestart_raw_inventory(
                    root, inventory_path=inventory, pending_path=marker,
                    state=state, plan_digest="a" * 64)
            self.assertEqual(changed.exception.code, "codex-exact-raw-inventory-stale")
            (private / "prompt-input.json").write_text("prompt-input.json")
            (snapshot / "config.toml").chmod(0o600)
            (snapshot / "config.toml").write_bytes(b"changed")
            (snapshot / "config.toml").chmod(0o400)
            with self.assertRaises(LifecycleError) as changed_snapshot:
                verify_prestart_raw_inventory(
                    root, inventory_path=inventory, pending_path=marker,
                    state=state, plan_digest="a" * 64)
            self.assertEqual(changed_snapshot.exception.code, "codex-exact-raw-inventory-stale")

    def test_last_boundary_refusal_never_calls_runner(self) -> None:
        from tests.adapter_sessions.test_bootstrap_r11 import PreparedAttemptIntegrationTests
        fixture = PreparedAttemptIntegrationTests(methodName="test_success_is_joined_to_reserved_terminal_and_current_sources")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        runner = Mock()
        fixture.context = SimpleNamespace(**{**fixture.context.__dict__, "runner": runner})
        refusal = Mock(side_effect=LifecycleError("codex-exact-raw-inventory-stale", "changed"))
        fixture.prepared["verifyBeforeStart"] = refusal
        receipt = fixture.launch()
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["hostLaunchStarted"])
        runner.assert_not_called()
        refusal.assert_called_once()

    def test_observed_start_prevents_raw_early_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            for name in ("input-request.json", "prompt-input.json", "effective-config.json"):
                _write_exclusive(private / name, name.encode(), root=root)
            snapshot = self._snapshot(root)
            _, marker, _ = create_prestart_raw_inventory(
                root, run_id="run-1", task_id="task-1", attempt_id="1",
                sealed_request=private / "input-request.json",
                state=self._workflow_state(root),
                plan_digest="a" * 64)
            _write_exclusive(marker.with_name("process-start.json"), b"observed", root=root)
            with self.assertRaises(LifecycleError) as raised:
                cleanup_prestart_raw(root, run_id="run-1", task_id="task-1", attempt_id="1",
                                     staging_source=None, proven_no_start=True)
            self.assertEqual(raised.exception.code, "codex-exact-start-uncertain")
            self.assertTrue((private / "input-request.json").exists())
            self.assertTrue((snapshot / "config.toml").exists())
            self.assertEqual(json.loads(marker.read_text())["status"], "PENDING")

    def test_failed_attempt_raw_unlink_keeps_private_cleanup_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            for name in ("input-request.json", "prompt-input.json", "effective-config.json"):
                _write_exclusive(private / name, name.encode(), root=root)
            self._snapshot(root)
            _, marker, _ = create_prestart_raw_inventory(
                root, run_id="run-1", task_id="task-1", attempt_id="1",
                sealed_request=private / "input-request.json",
                state=self._workflow_state(root),
                plan_digest="a" * 64)
            diagnostic = private / "prompt-input.json"
            original_unlink = Path.unlink

            def refuse_diagnostic(path: Path, *args: object, **kwargs: object) -> None:
                if path == diagnostic:
                    raise OSError("unlink refused")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", refuse_diagnostic):
                with self.assertRaises(LifecycleError) as raised:
                    cleanup_prestart_raw(root, run_id="run-1", task_id="task-1", attempt_id="1",
                                         staging_source=None, proven_no_start=True)
            self.assertEqual(raised.exception.code, "codex-exact-private-cleanup-pending")
            self.assertEqual(json.loads(marker.read_text())["status"], "PRIVATE_CLEANUP_PENDING")
            self.assertTrue(diagnostic.exists())

    def test_failed_snapshot_unlink_keeps_private_cleanup_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            for name in ("input-request.json", "prompt-input.json", "effective-config.json"):
                _write_exclusive(private / name, name.encode(), root=root)
            snapshot = self._snapshot(root)
            _, marker, _ = create_prestart_raw_inventory(
                root, run_id="run-1", task_id="task-1", attempt_id="1",
                sealed_request=private / "input-request.json",
                state=self._workflow_state(root), plan_digest="a" * 64)
            config = snapshot / "config.toml"
            original_unlink = Path.unlink

            def refuse_snapshot(path: Path, *args: object, **kwargs: object) -> None:
                if path == config:
                    raise OSError("snapshot unlink refused")
                original_unlink(path, *args, **kwargs)

            original_pinned_unlink = PinnedPrivateDirectory.unlink

            def refuse_pinned(parent, name):
                if parent.directory.path / name == config:
                    raise OSError("snapshot unlink refused")
                return original_pinned_unlink(parent, name)

            injected = patch.object(PinnedPrivateDirectory, "unlink", refuse_pinned) \
                if os.name == "nt" else patch.object(Path, "unlink", refuse_snapshot)
            with injected:
                with self.assertRaises(LifecycleError) as raised:
                    cleanup_prestart_raw(root, run_id="run-1", task_id="task-1", attempt_id="1",
                                         staging_source=None, proven_no_start=True)
            self.assertEqual(raised.exception.code, "codex-exact-private-cleanup-pending")
            self.assertEqual(json.loads(marker.read_text())["status"], "PRIVATE_CLEANUP_PENDING")
            self.assertTrue(config.exists())

    def test_unresolved_prelaunch_intent_holds_unknown_start_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            intent = evidence / "prelaunch-intent.json"
            start = evidence / "process-start.json"
            body = {"schemaVersion": "alk-codex-prelaunch-intent.v1",
                    "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                    "finalPromptSha256": "a" * 64, "hostLaunchStarted": False}
            _write_exclusive(intent, json.dumps(body).encode(), root=root)
            _write_exclusive(start, b"", root=root)
            with self.assertRaises(LifecycleError) as raised:
                reconcile_prelaunch_intents(root)
            self.assertEqual(raised.exception.code, "codex-exact-start-uncertain")
            marker = evidence / "start-uncertain.json"
            self.assertEqual(json.loads(marker.read_text())["costStatus"], "UNAVAILABLE")
            with self.assertRaises(LifecycleError):
                reconcile_prelaunch_intents(root)

    def test_started_receipt_without_input_holds_raw_and_unknown_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1/input-request.json")
            _write_exclusive(private, b"retained started raw", root=root)
            identity = {"runId": "run-1", "taskId": "task-1", "attemptId": "1",
                        "finalPromptSha256": "a" * 64}
            _write_exclusive(evidence / "prelaunch-intent.json", canonical_bytes({
                "schemaVersion": "alk-codex-prelaunch-intent.v1", **identity,
                "plannedStdinBytes": 10, "hostLaunchStarted": False}), root=root)
            _write_exclusive(evidence / "process-start.json", canonical_bytes({
                "schemaVersion": "alk-codex-process-start.v1", **identity,
                "hostLaunchStarted": True, "stdinStatus": "PENDING"}), root=root)
            _write_exclusive(evidence / "process-input.json", b"", root=root)
            with self.assertRaises(LifecycleError) as raised:
                reconcile_prelaunch_intents(root)
            self.assertEqual(raised.exception.code, "codex-exact-start-uncertain")
            self.assertEqual(json.loads((evidence / "start-uncertain.json").read_text())["costStatus"],
                             "UNAVAILABLE")
            self.assertEqual(private.read_bytes(), b"retained started raw")

            _write_exclusive(evidence / "transport-equivalence.json", canonical_bytes({
                "schemaVersion": "alk-codex-os-pipe-transport.v1", **identity,
                "status": "OS_PIPE_ACCEPTED"}), root=root)
            with self.assertRaises(LifecycleError) as still_uncertain:
                reconcile_prelaunch_intents(root)
            self.assertEqual(still_uncertain.exception.code, "codex-exact-start-uncertain")

    def test_orphan_staged_input_blocks_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = stage_input_request(root, "current", {"routeId": ROUTE_ID})
            orphan = stage_input_request(root, "orphan", {"routeId": ROUTE_ID})
            with self.assertRaises(LifecycleError) as staged:
                reconcile_prelaunch_intents(root, active_staging_request=current)
            self.assertEqual(staged.exception.code, "codex-exact-start-uncertain")
            self.assertTrue(orphan.exists())
            marker = (root / "work/release-2-16/evidence/codex-exact-prompt/prestart"
                      / "orphan/orphan-private-input.json")
            self.assertEqual(json.loads(marker.read_text())["costStatus"], "UNAVAILABLE")

    def test_uncertain_prior_attempt_keeps_its_raw_when_new_staging_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = (root / "work/release-2-16/private-details/codex-exact-prompt"
                     / "run-1/task-1/1/input-request.json")
            _write_exclusive(prior, b"prior started raw", root=root)
            snapshot = self._snapshot(root)
            intent = (root / "work/release-2-16/evidence/codex-exact-prompt"
                      / "run-1/task-1/1/prelaunch-intent.json")
            _write_exclusive(intent, canonical_bytes({
                "schemaVersion": "alk-codex-prelaunch-intent.v1", "runId": "run-1",
                "taskId": "task-1", "attemptId": "1", "hostLaunchStarted": False,
                "finalPromptSha256": "a" * 64}), root=root)
            _write_exclusive(intent.with_name("process-start.json"), b"", root=root)
            fresh = stage_input_request(root, "new-request", {"routeId": ROUTE_ID})
            with self.assertRaises(LifecycleError) as blocked:
                prepare_exact_prompt(
                    project_root=root, input_request=fresh,
                    route_id=ROUTE_ID, requested_claim=CLAIM,
                    state={"runId": "run-1", "sourceRevision": "rev-1"},
                    task={"id": "task-1", "attempt": 1, "status": "RUNNING"},
                    manifest={}, lock_path=root / "plan.lock.json",
                    source_revision="rev-1", operation_id="op-1",
                    executable_identity={"status": "PASS"}, executable="codex",
                )
            self.assertEqual(blocked.exception.code, "codex-exact-start-uncertain")
            self.assertFalse(fresh.exists())
            self.assertEqual(prior.read_bytes(), b"prior started raw")
            self.assertTrue((snapshot / "config.toml").exists())

    def test_sealed_input_without_intent_blocks_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed = (root / "work/release-2-16/private-details/codex-exact-prompt"
                      / "run-1/task-1/1/input-request.json")
            _write_exclusive(sealed, b"sealed before intent", root=root)
            with self.assertRaises(LifecycleError) as lost_intent:
                reconcile_prelaunch_intents(root)
            self.assertEqual(lost_intent.exception.code, "codex-exact-start-uncertain")
            self.assertEqual(sealed.read_bytes(), b"sealed before intent")
            marker = (root / "work/release-2-16/evidence/codex-exact-prompt"
                      / "run-1/task-1/1/orphan-private-input.json")
            self.assertEqual(json.loads(marker.read_text())["costStatus"], "UNAVAILABLE")

    def test_active_workflow_state_is_reopened_before_child_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            state = {"runId": "run-1", "sourceRevision": "rev-1",
                     "tasks": [{"id": "task-1", "status": "RUNNING", "attempt": 1}]}
            state_path.write_bytes(canonical_bytes(state))
            _recheck_active_workflow_state(root, state_path, state, "run-1", "task-1", 1)
            state_path.write_bytes(canonical_bytes({
                **state, "tasks": [{"id": "task-1", "status": "CANCELLED", "attempt": 1}]}))
            with self.assertRaises(LifecycleError) as cancelled:
                _recheck_active_workflow_state(root, state_path, state, "run-1", "task-1", 1)
            self.assertEqual(cancelled.exception.code, "codex-exact-state-stale")
            state_path.write_bytes(canonical_bytes({
                **state, "tasks": [{"id": "task-1", "status": "RUNNING", "attempt": 2}]}))
            with self.assertRaises(LifecycleError) as advanced:
                _recheck_active_workflow_state(root, state_path, state, "run-1", "task-1", 1)
            self.assertEqual(advanced.exception.code, "codex-exact-state-stale")

    def test_post_popen_start_receipt_failure_reconciles_as_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1/input-request.json")
            _write_exclusive(private, b"retained raw", root=root)
            raw = b"private prompt"
            intent = {"schemaVersion": "alk-codex-prelaunch-intent.v1",
                      "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                      "finalPromptSha256": hashlib.sha256(raw).hexdigest(),
                      "hostLaunchStarted": False}
            _write_exclusive(evidence / "prelaunch-intent.json", canonical_bytes(intent), root=root)
            _write_exclusive(evidence / "process-start.json", b"", root=root)

            def lose_start_receipt(event: dict) -> None:
                self.assertEqual(event["plannedStdinSha256"], intent["finalPromptSha256"])
                raise OSError("start receipt unavailable after Popen")

            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text=raw.decode(),
                on_started=lose_start_receipt, on_input=lambda _event: None,
            )
            self.assertTrue(result["processStarted"])
            self.assertTrue(result["startedFailure"])
            self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")
            with self.assertRaises(LifecycleError) as raised:
                reconcile_prelaunch_intents(root)
            self.assertEqual(raised.exception.code, "codex-exact-start-uncertain")
            self.assertEqual(json.loads((evidence / "start-uncertain.json").read_text())["costStatus"],
                             "UNAVAILABLE")
            self.assertFalse((evidence / "proven-no-start.json").exists())
            self.assertEqual(private.read_bytes(), b"retained raw")

    @unittest.skipUnless(os.name == "posix", "crash fixture requires POSIX signals")
    def test_child_crash_after_observed_start_before_complete_input_is_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1/input-request.json")
            _write_exclusive(private, b"retained after crash", root=root)
            raw = "x" * 70_000
            _write_exclusive(evidence / "prelaunch-intent.json", canonical_bytes({
                "schemaVersion": "alk-codex-prelaunch-intent.v1",
                "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                "finalPromptSha256": hashlib.sha256(raw.encode()).hexdigest(),
                "hostLaunchStarted": False}), root=root)
            _write_exclusive(evidence / "process-start.json", b"", root=root)
            started: list[dict] = []
            inputs: list[dict] = []

            def crash_after_start(event: dict) -> None:
                started.append(event)
                os.kill(event["pid"], signal.SIGKILL)
                time.sleep(0.05)

            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text=raw,
                max_input_bytes=80_000, on_started=crash_after_start,
                on_input=inputs.append,
            )
            self.assertEqual(started[0]["stdinStatus"], "PENDING")
            self.assertTrue(result["processStarted"])
            self.assertTrue(result["startedFailure"])
            self.assertEqual(inputs[0]["status"], "PARTIAL_OR_FAILED")
            self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")
            with self.assertRaises(LifecycleError) as uncertain:
                reconcile_prelaunch_intents(root)
            self.assertEqual(uncertain.exception.code, "codex-exact-start-uncertain")
            self.assertEqual(private.read_bytes(), b"retained after crash")

    @unittest.skipUnless(os.name == "posix", "controller exit fixture requires POSIX process")
    def test_launcher_exit_after_popen_before_receipt_reconciles_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1/input-request.json")
            _write_exclusive(private, b"retained across launcher restart", root=root)
            _write_exclusive(evidence / "prelaunch-intent.json", canonical_bytes({
                "schemaVersion": "alk-codex-prelaunch-intent.v1",
                "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                "finalPromptSha256": hashlib.sha256(b"private prompt").hexdigest(),
                "hostLaunchStarted": False}), root=root)
            _write_exclusive(evidence / "process-start.json", b"", root=root)
            controller = (
                "import os,sys\n"
                "from agent_lifecycle.adapter_sessions.process import run_process\n"
                "def crash_after_popen(_event): os._exit(77)\n"
                "run_process([sys.executable,'-c','import time;time.sleep(0.2)'],"
                " env=dict(os.environ),timeout_seconds=5,stdin_text='private prompt',"
                " on_started=crash_after_popen,on_input=lambda _event: None)\n"
            )
            env = {**os.environ,
                   "PYTHONPATH": str(Path(__file__).parents[2] / "src"),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            ended = subprocess.run([sys.executable, "-c", controller],
                                   cwd=root, env=env, capture_output=True,
                                   timeout=5, check=False)
            self.assertEqual(ended.returncode, 77, ended.stderr.decode(errors="replace"))
            self.assertEqual((evidence / "process-start.json").read_bytes(), b"")
            with self.assertRaises(LifecycleError) as uncertain:
                reconcile_prelaunch_intents(root)
            self.assertEqual(uncertain.exception.code, "codex-exact-start-uncertain")
            marker = json.loads((evidence / "start-uncertain.json").read_bytes())
            self.assertEqual(marker["costStatus"], "UNAVAILABLE")
            self.assertFalse((evidence / "proven-no-start.json").exists())
            self.assertEqual(private.read_bytes(), b"retained across launcher restart")

    def test_proven_runner_no_start_resolves_reserved_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            intent = evidence / "prelaunch-intent.json"
            start = evidence / "process-start.json"
            _write_exclusive(intent, json.dumps({
                "schemaVersion": "alk-codex-prelaunch-intent.v1",
                "hostLaunchStarted": False,
            }).encode(), root=root)
            _write_exclusive(start, b"", root=root)
            record_proven_no_start(root, start)
            reconcile_prelaunch_intents(root)
            self.assertEqual(json.loads((evidence / "proven-no-start.json").read_text())["costStatus"],
                             "NOT_STARTED")

    def test_failed_no_start_unlink_retains_sticky_privacy_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = stage_input_request(root, "request-1", {"routeId": ROUTE_ID})
            original_unlink = Path.unlink

            def fail_first_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path == source:
                    raise OSError("unlink refused")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_first_unlink):
                with self.assertRaises(LifecycleError) as raised:
                    cleanup_no_start(root, None, source)
            self.assertEqual(raised.exception.code, "codex-exact-private-cleanup-pending")
            marker = (root / "work/release-2-16/evidence/codex-exact-prompt/prestart"
                      / "request-1/raw-cleanup-pending.json")
            self.assertEqual(json.loads(marker.read_text())["status"], "PRIVATE_CLEANUP_PENDING")
            assert_private_path(self, marker, 0o600)

            second = stage_input_request(root, "request-2", {"routeId": ROUTE_ID})
            with self.assertRaises(LifecycleError) as blocked:
                prepare_exact_prompt(
                    project_root=root, input_request=second,
                    route_id=ROUTE_ID, requested_claim=CLAIM,
                    state={"runId": "run-1", "sourceRevision": "rev-1"},
                    task={"id": "task-1", "attempt": 1, "status": "RUNNING"},
                    manifest={"planRevision": 68}, lock_path=root / "plan.lock.json",
                    source_revision="rev-1", operation_id="op-1",
                    executable_identity={"status": "PASS"}, executable="codex",
                )
            self.assertEqual(blocked.exception.code, "codex-exact-private-cleanup-pending")
            self.assertFalse(second.exists())
            cleanup_no_start(root, None, source)
            self.assertEqual(json.loads(marker.read_text())["status"], "DONE")
            self.assertFalse(source.exists())

    def test_staging_is_private_and_prelaunch_binding_failure_cleans_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = stage_input_request(root, "request-1", {
                "routeId":ROUTE_ID, "requestedClaim":CLAIM,
                "runId":"run-1", "taskId":"task-1", "planDigest":"wrong",
            })
            assert_private_path(self, source, 0o600)
            assert_private_path(self, source.parent, 0o700)
            lock = root / "plan.lock.json"
            lock.write_text("{}")
            with self.assertRaises(LifecycleError) as raised:
                prepare_exact_prompt(
                    project_root=root, input_request=source,
                    route_id=ROUTE_ID, requested_claim=CLAIM,
                    state={"runId":"run-1", "sourceRevision":"rev-1"},
                    task={"id":"task-1", "attempt":1, "status":"RUNNING"},
                    manifest={"planRevision":67}, lock_path=lock,
                    source_revision="rev-1", operation_id="op-1",
                    executable_identity={"status":"PASS"}, executable="codex",
                )
            self.assertEqual(raised.exception.code, "codex-exact-request-binding-mismatch")
            self.assertEqual(list(root.rglob("input-request.json")), [])

    def test_symlinked_private_parent_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "work/release-2-16").mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (root / "work/release-2-16/private-details").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(LifecycleError) as raised:
                stage_input_request(root, "request-1", {"routeId":ROUTE_ID})
            self.assertEqual(raised.exception.code, "codex-exact-private-path-unsafe")
            self.assertEqual(list(outside.iterdir()), [])

    def test_missing_independent_bootstrap_audit_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(LifecycleError) as raised:
                require_bootstrap_audit(Path(temporary), plan_digest="a" * 64,
                                        lock_sha256="b" * 64, selected_binary_sha256="c" * 64)
            self.assertEqual(raised.exception.code, "codex-exact-bootstrap-audit-missing")

    @patch("agent_lifecycle.adapter_sessions.codex_source_subject._source_test_ids",
           side_effect=lambda _root, modules: (
               ["fixture.c34"] if "test_codex_exact_prompt" in modules[0]
               else ["fixture.c35"], {}))
    def test_bootstrap_subject_reopens_real_wip_and_private_support(
        self, _synthetic_ids: Mock,
    ) -> None:
        # Synthetic Git/WIP fixture tests the verifier; it is never an audit verdict.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            contract = json.loads((Path(__file__).parents[2] / "tasks/release-2-16/historical-r69q"
                                   / "route-bootstrap-contract.json").read_text())
            owned = contract["ownership"]["temporaryLeadWritePaths"]

            def git(*args: str) -> bytes:
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True).stdout

            git("init", "-q")
            for relative in owned[:4]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("base:" + relative).encode())
            git("add", "--", "src")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "-qm", "base")
            for relative in owned:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("after:" + relative).encode())
            six = {}
            tracked, untracked = [], []
            for relative in owned:
                current = (root / relative).read_bytes()
                head = subprocess.run(["git", "show", f"HEAD:{relative}"], cwd=root,
                                      capture_output=True)
                six[relative] = {"beforeExists": head.returncode == 0,
                                 "beforeSha256": hashlib.sha256(head.stdout).hexdigest()
                                 if head.returncode == 0 else None,
                                 "afterSha256": hashlib.sha256(current).hexdigest()}
                row = {"path": relative, "currentBytes": len(current),
                       "currentSha256": hashlib.sha256(current).hexdigest()}
                (tracked if head.returncode == 0 else untracked).append(row)
            diff = git("diff", "--binary", "--", "src", "tests", "policy", "tools")
            inventory_subject = {
                "gitHead": git("rev-parse", "HEAD").decode().strip(),
                "trackedDiff": {"sha256": hashlib.sha256(diff).hexdigest(),
                                "bytes": len(diff)},
                "trackedModified": tracked, "untracked": untracked,
            }
            inventory = {"inventorySubject": inventory_subject,
                         "canonicalInventorySubjectSha256": canonical_digest(inventory_subject)}
            support = root / "work/release-2-16/evidence/route-bootstrap/support"
            admission = {"status": "ADMITTED_PREAPPROVED_BY_USER",
                         "bootstrapAdmissionId": "fixture-admission",
                         "implementationOriginAdmissionId": "r166-pre-ws01-route-bootstrap",
                         "priorUnknownHolds": 7, "tokenCap": 3,
                         "admittedUnknownHolds": 10, "actualModelTokens": None,
                         "costStatus": "UNAVAILABLE"}
            admission_raw = canonical_bytes(admission)
            raw = {"before-wip-inventory.json": canonical_bytes(inventory),
                   "after-wip-inventory.json": canonical_bytes(inventory),
                   "cost.json": canonical_bytes({"costStatus": "UNAVAILABLE",
                                                  "heldUnknownTokens": 10,
                                                  "actualModelTokens": None,
                                                  "priorUnknownHolds": 7,
                                                  "windowCap": 3,
                                                  "implementationOriginAdmissionId":
                                                      "r166-pre-ws01-route-bootstrap",
                                                  "admissionSha256": hashlib.sha256(
                                                      admission_raw).hexdigest()}),
                   "admission.json": admission_raw}
            outputs = []
            for command in contract["validation"]["commands"]:
                ident = command["id"].lower()
                stderr = b"----------------------------------------------------------------------\nRan 1 test in 0.001s\n\nOK\n"
                test_names = [f"fixture.{ident}"]
                case_ids = (["RB01", "RB02", "RB03", "RB04", "RB07", "RB09", "RB11-PRE", "RB12"]
                            if ident == "c34" else ["RB05", "RB06", "RB08", "RB10"])
                cases = {"commandId": command["id"], "testNames": test_names,
                         "sourceTestFileSha256": {},
                         "localCaseMapping": {case: test_names for case in case_ids}}
                raw[f"{ident}.stdout"] = b""
                raw[f"{ident}.stderr"] = stderr
                raw[f"{ident}-result.json"] = canonical_bytes({
                    ident: "PASS_1_TESTS", f"{ident}StderrSha256": hashlib.sha256(stderr).hexdigest()})
                raw[f"{ident}-cases.json"] = canonical_bytes(cases)
                python_path = Path(sys.executable).resolve()
                raw[f"{ident}-execution.json"] = canonical_bytes({
                    "source": "SUBPROCESS_CAPTURE",
                    "contractCommand": command["command"],
                    "commandDigest": command["canonicalDigest"],
                    "argv": command["command"].split()[2:],
                    "environment": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "src"},
                    "cwd": str(root), "exitCode": 0,
                    "stdoutSha256": hashlib.sha256(b"").hexdigest(),
                    "stderrSha256": hashlib.sha256(stderr).hexdigest(),
                    "testNames": test_names, "sourceTestFileSha256": {},
                    "pythonResolvedPath": str(python_path),
                    "pythonSha256": hashlib.sha256(python_path.read_bytes()).hexdigest(),
                    "processId": 12345,
                    "startedAtUtc": "2026-09-25T00:00:00+00:00",
                    "endedAtUtc": "2026-09-25T00:00:01+00:00",
                })
                outputs.append({"commandDigest": command["canonicalDigest"],
                                "outputSha256": canonical_digest({
                                    "stdoutSha256": hashlib.sha256(b"").hexdigest(),
                                    "stderrSha256": hashlib.sha256(stderr).hexdigest()}),
                                "caseDigest": canonical_digest(cases)})
            for name, value in raw.items():
                _write_exclusive(support / name, value, root=root)
            subject = {
                "r69LockSha256": "a" * 64, "r69PlanDigest": "b" * 64,
                "bootstrapAdmissionId": "fixture-admission", "bootstrapId": "fixture-bootstrap",
                "sixPathBeforeAfterSha256": six,
                "wholeWipBeforeAfterInventoryDigest": {
                    "before": inventory["canonicalInventorySubjectSha256"],
                    "after": inventory["canonicalInventorySubjectSha256"]},
                "C34C35CommandOutputCaseDigests": outputs,
                "privateSupportReceiptDigests": {
                    name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
                "costStatus": "UNAVAILABLE", "heldUnknownTokens": 10,
            }
            subject["reviewedInputDigest"] = canonical_digest(subject)
            base = support.parent
            _recompute_bootstrap_subject(root, base, contract, subject)
            changed = root / owned[0]
            changed.write_bytes(b"unreviewed edit")
            with self.assertRaises(LifecycleError):
                _recompute_bootstrap_subject(root, base, contract, subject)
            changed.write_bytes(("after:" + owned[0]).encode())
            (support / "admission.json").write_bytes(canonical_bytes({**admission, "tokenCap": 4}))
            with self.assertRaises(LifecycleError):
                _recompute_bootstrap_subject(root, base, contract, subject)
            (support / "admission.json").write_bytes(admission_raw)
            (support / "c34.stderr").write_bytes(b"forged OK\n")
            with self.assertRaises(LifecycleError):
                _recompute_bootstrap_subject(root, base, contract, subject)

    def test_r69_review_gate_requires_two_completed_turns_and_exact_transport(self) -> None:
        # The frozen case ID is preserved; r69h replaces its two-turn subject.
        root = Path(__file__).parents[2]
        contract = json.loads((root / "tasks/release-2-16/historical-r69q/route-bootstrap-contract.json").read_text())
        body_schema = contract["artifacts"]["reviewerBody"]["closedSchema"]
        subject = {"phase": "PRE_WS01", "nonce": "reviewed-input"}
        packet = b"source path=src/example.py\nprint('review me')\n"
        request_raw = build_single_turn_bootstrap_review_request(
            request_id=5, thread_id="review-thread", subject=subject,
            packet=packet, output_schema=body_schema, cwd=root)
        request = json.loads(request_raw)
        self.assertIn(packet.decode(), request["params"]["input"][0]["text"])
        self.assertIn(canonical_bytes(subject).decode(), request["params"]["input"][0]["text"])
        self.assertIn("ASSIGNED_SUBJECT_SHA256=" + canonical_digest(subject),
                      request["params"]["input"][0]["text"])
        changed_subject_request = build_single_turn_bootstrap_review_request(
            request_id=5, thread_id="review-thread", subject={**subject, "nonce": "changed"},
            packet=packet, output_schema=body_schema, cwd=root)
        self.assertNotEqual(request_raw, changed_subject_request)
        self.assertIn("ASSIGNED_SUBJECT_SHA256=" + canonical_digest(
            {**subject, "nonce": "changed"}), changed_subject_request.decode())
        self.assertEqual(request["params"]["outputSchema"], body_schema)
        self.assertEqual(assess_single_turn_bootstrap_context_fit(
            request_bytes=request_raw, model_context_window=300000)["hostHiddenInput"],
            "UNPROVEN")
        body = {"schemaVersion": "alk-route-bootstrap-reviewer-body.v4",
                "subjectSha256": hashlib.sha256(canonical_bytes(subject)).hexdigest(),
                "verdict": "PASS", "phase": "PRE_WS01", "rb11RuntimeStatus": "NOT_RUN",
                "coverageComplete": True, "reviewText": "NO_CURRENT_FINDINGS", "findings": []}
        body_text = canonical_bytes(body).decode()
        response = {"thread": {"id": "review-thread", "turns": [{
            "id": "review-turn", "status": "completed", "items": [
                {"id": "input-item", "type": "userMessage",
                 "content": request["params"]["input"]},
                {"id": "body-item", "type": "agentMessage", "text": body_text}]}]}}
        projection = _single_turn_projection(
            response, thread_id="review-thread", turn_id="review-turn", request=request)
        self.assertEqual(projection["bodyText"], body_text)
        self.assertEqual(projection["inputItemId"], "input-item")
        with_reasoning = json.loads(json.dumps(response))
        with_reasoning["thread"]["turns"][0]["items"][1:1] = [
            {"id": "reasoning-1", "type": "reasoning", "summary": []},
            {"id": "reasoning-2", "type": "reasoning", "summary": []}]
        reasoning_projection = _single_turn_projection(
            with_reasoning, thread_id="review-thread", turn_id="review-turn", request=request)
        self.assertEqual([item["type"] for item in reasoning_projection["items"]],
                         ["userMessage", "reasoning", "reasoning", "agentMessage"])
        self.assertEqual(reasoning_projection["bodyItemId"], "body-item")
        changed = json.loads(json.dumps(with_reasoning))
        changed["thread"]["turns"][0]["items"][1]["id"] = "input-item"
        with self.assertRaises(LifecycleError):
            _single_turn_projection(changed, thread_id="review-thread",
                                    turn_id="review-turn", request=request)
        changed = json.loads(json.dumps(with_reasoning))
        changed["thread"]["turns"][0]["items"].insert(2, {
            "id": "extra-agent", "type": "agentMessage", "text": "unapproved"})
        with self.assertRaises(LifecycleError):
            _single_turn_projection(changed, thread_id="review-thread",
                                    turn_id="review-turn", request=request)
        changed = json.loads(json.dumps(response))
        changed["thread"]["turns"][0]["items"][0]["content"][0]["text"] += " altered"
        with self.assertRaises(LifecycleError):
            _single_turn_projection(changed, thread_id="review-thread",
                                    turn_id="review-turn", request=request)
        changed = json.loads(json.dumps(response))
        changed["thread"]["turns"][0]["items"].insert(1, {"id": "tool", "type": "commandExecution"})
        with self.assertRaises(LifecycleError):
            _single_turn_projection(changed, thread_id="review-thread",
                                    turn_id="review-turn", request=request)
        changed = json.loads(json.dumps(response))
        changed["thread"]["turns"].append({"id": "intervening", "status": "completed", "items": []})
        with self.assertRaises(LifecycleError):
            _single_turn_projection(changed, thread_id="review-thread",
                                    turn_id="review-turn", request=request)
        with self.assertRaises(LifecycleError):
            assess_single_turn_bootstrap_context_fit(
                request_bytes=request_raw, model_context_window=len(request_raw) + 24575)

        one_byte_request = build_single_turn_bootstrap_review_request(
            request_id=5, thread_id="review-thread", subject=subject,
            packet=b"x", output_schema=body_schema, cwd=root)
        over_old_packet = b"x" * (229_377 - len(one_byte_request) + 1)
        over_old_request = build_single_turn_bootstrap_review_request(
            request_id=5, thread_id="review-thread", subject=subject,
            packet=over_old_packet, output_schema=body_schema, cwd=root)
        self.assertEqual(len(over_old_request), 229_377)
        self.assertEqual(assess_single_turn_bootstrap_context_fit(
            request_bytes=over_old_request, model_context_window=229_377 + 8192 + 16384
        )["requiredUpperBoundTokens"], 229_377 + 8192 + 16384)

        at_cap_packet = b"x" * (245_760 - len(one_byte_request) + 1)
        at_cap_request = build_single_turn_bootstrap_review_request(
            request_id=5, thread_id="review-thread", subject=subject,
            packet=at_cap_packet, output_schema=body_schema, cwd=root)
        self.assertEqual(len(at_cap_request), 245_760)
        self.assertEqual(assess_single_turn_bootstrap_context_fit(
            request_bytes=at_cap_request, model_context_window=245_760 + 8192 + 16384
        )["requiredUpperBoundTokens"], 245_760 + 8192 + 16384)
        with self.assertRaises(LifecycleError):
            build_single_turn_bootstrap_review_request(
                request_id=5, thread_id="review-thread", subject=subject,
                packet=at_cap_packet + b"x", output_schema=body_schema, cwd=root)
        with self.assertRaises(LifecycleError):
            assess_single_turn_bootstrap_context_fit(
                request_bytes=b"x" * 245_761, model_context_window=300_000)
        with self.assertRaises(LifecycleError):
            assess_single_turn_bootstrap_context_fit(
                request_bytes=at_cap_request, model_context_window=0)
        with self.assertRaises(LifecycleError):
            assess_single_turn_bootstrap_context_fit(
                request_bytes=at_cap_request, model_context_window=245_760 + 8192 + 16384 - 1)

    def test_r69_review_prefix_and_finding_mapping_fail_closed(self) -> None:
        root = Path(__file__).parents[2]
        contract = json.loads((root / "tasks/release-2-16/historical-r69q/route-bootstrap-contract.json").read_text())
        body_schema = contract["artifacts"]["reviewerBody"]["closedSchema"]
        # The retained v4 parent parser still needs its own versioned fixture;
        # current R11 v5 schema is not a v4 review or native admission.
        legacy_keys = ("schemaVersion", "subjectSha256", "verdict", "phase", "rb11RuntimeStatus",
                       "coverageComplete", "reviewText", "findings")
        body_schema["properties"]["coverageComplete"] = {"type": "boolean"}
        body_schema = {"type": "object", "required": list(legacy_keys), "additionalProperties": False,
                       "properties": {key: body_schema["properties"][key] for key in legacy_keys}}
        body_schema["properties"]["schemaVersion"] = {"type": "string", "const": "alk-route-bootstrap-reviewer-body.v4"}
        body_schema["properties"]["reviewText"] = {"type": "string"}
        line = "- [P1] F1 | src/example.py:42 | required receipt absent"
        finding = {"id": "F1", "reviewLevel": "P1", "severity": "HIGH",
                   "status": "OPEN", "sourcePath": "src/example.py", "sourceLine": 42,
                   "evidence": "required receipt absent", "rawSpan": line, "spanOrdinal": 1}
        body = {"schemaVersion": "alk-route-bootstrap-reviewer-body.v4",
                "subjectSha256": "a" * 64, "verdict": "FAIL", "phase": "PRE_WS01",
                "rb11RuntimeStatus": "NOT_RUN", "coverageComplete": True,
                "reviewText": line, "findings": [finding]}
        self.assertTrue(_matches_closed_schema(body, body_schema))
        self.assertTrue(_review_findings_match_v4(body))
        for changed in (
            {**body, "verdict": "PASS"},
            {**body, "findings": []},
            {**body, "findings": [{**finding, "severity": "LOW"}]},
            {**body, "findings": [{**finding, "spanOrdinal": 2}]},
            {**body, "reviewText": line + "\nUnmapped prose"},
            {**body, "coverageComplete": False},
            {**body, "reviewText": "NO_CURRENT_FINDINGS", "verdict": "PASS"},
        ):
            self.assertFalse(_review_findings_match_v4(changed))
        clean = {**body, "verdict": "PASS", "reviewText": "NO_CURRENT_FINDINGS",
                 "findings": []}
        self.assertTrue(_review_findings_match_v4(clean))
        self.assertFalse(_review_findings_match_v4({**clean, "coverageComplete": False}))
        self.assertFalse(_matches_closed_schema({**clean, "unreviewed": True}, body_schema))

    def test_review_finding_parser_bounds_malformed_repeated_slashes(self) -> None:
        body = {"coverageComplete": True, "verdict": "FAIL",
                "reviewText": "- [P1] F1 | " + "!/" * 8000,
                "findings": [{}]}
        program = (
            "import json,sys; "
            "from agent_lifecycle.adapter_sessions.codex_source_subject "
            "import _review_findings_match_v4; "
            "print(_review_findings_match_v4(json.loads(sys.stdin.read())))"
        )
        observed = subprocess.run(
            [sys.executable, "-B", "-c", program], input=json.dumps(body),
            text=True, capture_output=True, timeout=5, check=False,
        )
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertEqual(observed.stdout.strip(), "False")

    def test_local_app_server_fresh_read_uses_only_documented_read_protocol(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / _CODEX_FIXTURE_NAME
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json,sys\n"
                "from pathlib import Path\n"
                "for line in sys.stdin:\n"
                "    message = json.loads(line)\n"
                "    with Path('methods.log').open('a') as stream:\n"
                "        stream.write(message['method'] + '\\n')\n"
                "    if message['method'] == 'initialize':\n"
                "        print(json.dumps({'id': message['id'], 'result': {}}), flush=True)\n"
                "    elif message['method'] == 'thread/read':\n"
                "        print(json.dumps({'id': message['id'], 'result': {'thread': "
                "{'id': message['params']['threadId'], 'turns': []}}}), flush=True)\n"
            )
            executable.chmod(0o700)
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            response = read_codex_app_server_thread(
                root, executable=str(executable), expected_binary_sha256=digest,
                thread_id="review-thread")
            self.assertEqual(response["thread"]["id"], "review-thread")
            self.assertEqual((root / "methods.log").read_text().splitlines(),
                             ["initialize", "initialized", "thread/read"])
            # A text Python fixture is not an executable PE image. Inject its
            # selected path on Windows and still check the exact resolver input.
            resolution = patch.object(exact_prompt_module.shutil, "which", return_value=str(executable)) \
                if os.name == "nt" else nullcontext()
            with resolution as resolver:
                path_response = read_codex_app_server_thread(
                    root, executable="codex", expected_binary_sha256=digest,
                    thread_id="review-thread", process_env={**os.environ, "PATH": str(root)})
            if os.name == "nt":
                resolver.assert_called_once_with("codex", path=str(root))
            self.assertEqual(path_response["thread"]["id"], "review-thread")
            with self.assertRaises(LifecycleError) as wrong_binary:
                read_codex_app_server_thread(root, executable=str(executable),
                                             expected_binary_sha256="0" * 64,
                                             thread_id="review-thread")
            self.assertEqual(wrong_binary.exception.code,
                             "codex-exact-bootstrap-review-unavailable")

    def test_app_server_rejects_ambiguous_json_and_response_id_types(self) -> None:
        install_windows_fixture_process(self)
        invalid = [
            ("initialize", '{"id":true,"result":{}}'),
            ("initialize", '{"id":1.0,"result":{}}'),
            ("initialize", '{"id":1,"id":1,"result":{}}'),
            ("initialize", '{"id":1,"result":{},"result":{"x":1}}'),
            ("thread/read", '{"id":2.0,"result":{"thread":{}}}'),
            ("thread/read", '{"id":2,"result":{"thread":{},"thread":{"id":"other"}}}'),
            ("thread/read", '{"id":2,"result":{"thread":{"id":"x","id":"y"}}}'),
            ("thread/read", '{"id":2,"result":{"unavailable":NaN}}'),
        ]
        for method, response in invalid:
            with self.subTest(method=method, response=response), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                executable = root / _CODEX_FIXTURE_NAME
                executable.write_text(
                    f"#!{sys.executable}\nimport json,sys\n"
                    "for line in sys.stdin:\n"
                    " q=json.loads(line)\n"
                    f" if q['method']=={method!r}:print({response!r},flush=True)\n"
                    " elif q['method']=='initialize':print('{\"id\":1,\"result\":{}}',flush=True)\n"
                )
                executable.chmod(0o700)
                with self.assertRaises(LifecycleError) as error:
                    read_codex_app_server_thread(
                        root, executable=str(executable),
                        expected_binary_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), thread_id="fixture",
                    )
                self.assertEqual(error.exception.code, "codex-exact-bootstrap-review-unavailable")

    def _app_server_io_fixture(self, root: Path, *, stall: bool = False) -> Path:
        executable = root / _CODEX_FIXTURE_NAME
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json,os,sys,time\n"
            "from pathlib import Path\n"
            "Path('child.pid').write_text(str(os.getpid()))\n"
            "for line in sys.stdin:\n"
            "    message=json.loads(line)\n"
            "    if message['method']=='initialize':\n"
            "        print(json.dumps({'id':1,'result':{}}),flush=True)\n"
            + ("        time.sleep(60)\n" if stall else "")
            + "    elif message['method']=='thread/read':\n"
            "        print(json.dumps({'id':2,'result':{'thread':{'id':message['params']['threadId']}}}),flush=True)\n"
        )
        executable.chmod(0o700)
        return executable

    def test_app_server_rejects_expiry_during_decode_hash_or_cleanup_and_reaps_child(self) -> None:
        install_windows_fixture_process(self)
        for mode in ["matching-decode", "notification-decode", "final-hash", "cleanup"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                executable = self._app_server_io_fixture(root)
                if mode == "notification-decode":
                    text = executable.read_text().replace(
                        "print(json.dumps({'id':2,'result':{'thread':{'id':message['params']['threadId']}}}),flush=True)",
                        "print(json.dumps({'method':'tick'})+'\\n'+json.dumps("
                        "{'id':2,'result':{'thread':{'id':message['params']['threadId']}}}),flush=True)",
                    )
                    executable.write_text(text)
                digest = hashlib.sha256(executable.read_bytes()).hexdigest()
                clock = [0.0]
                decode, hash_bytes, start_process = (
                    exact_prompt_module.load_json_object, exact_prompt_module._sha, subprocess.Popen,
                )
                hash_calls = []

                def late_decode(*args, _decode=decode, _mode=mode, _clock=clock, **kwargs):
                    message = _decode(*args, **kwargs)
                    if ((_mode == "matching-decode" and message.get("id") == 2)
                            or (_mode == "notification-decode" and message.get("method") == "tick")):
                        _clock[0] = 31.0
                    return message

                def late_hash(raw, _hash_calls=hash_calls, _hash_bytes=hash_bytes, _mode=mode, _clock=clock):
                    _hash_calls.append(raw)
                    result = _hash_bytes(raw)
                    if _mode == "final-hash" and len(_hash_calls) == 2:
                        _clock[0] = 31.0
                    return result

                def start(*args, _start_process=start_process, _mode=mode, _clock=clock, **kwargs):
                    process = _start_process(*args, **kwargs)
                    wait = process.wait

                    def late_wait(*args, **kwargs):
                        result = wait(*args, **kwargs)
                        if _mode == "cleanup":
                            _clock[0] = 31.0
                        return result

                    process.wait = late_wait
                    return process

                with patch.object(exact_prompt_module.time, "monotonic", side_effect=lambda _clock=clock: _clock[0]), \
                        patch.object(exact_prompt_module, "load_json_object", side_effect=late_decode), \
                        patch.object(exact_prompt_module, "_sha", side_effect=late_hash), \
                        patch.object(exact_prompt_module.subprocess, "Popen", side_effect=start), \
                        self.assertRaises(LifecycleError) as error:
                    read_codex_app_server_thread(root, executable=str(executable),
                                                expected_binary_sha256=digest, thread_id="late")
                self.assertEqual(error.exception.code, "codex-exact-bootstrap-review-unavailable")
                self.assertIn("timed out", str(error.exception))
                self.assertFalse(process_is_running(int((root / "child.pid").read_text())))

    def test_app_server_rejects_oversized_requests_before_start(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = self._app_server_io_fixture(root)
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            for thread_id in ("x" * 1_048_576, "é" * 200_000):
                with self.subTest(utf8_bytes=len(thread_id.encode())), patch.object(
                        exact_prompt_module.subprocess, "Popen") as start:
                    with self.assertRaises(LifecycleError) as error:
                        read_codex_app_server_thread(root, executable=str(executable),
                                                    expected_binary_sha256=digest, thread_id=thread_id)
                    self.assertEqual(error.exception.code, "codex-exact-bootstrap-review-unavailable")
                    start.assert_not_called()

    def test_app_server_stalled_request_write_times_out_and_reaps_child(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = self._app_server_io_fixture(root, stall=True)
            real_start = subprocess.Popen
            started = time.monotonic()
            with patch.object(exact_prompt_module, "_APP_SERVER_TIMEOUT_SECONDS", 0.25), patch.object(
                    exact_prompt_module.subprocess, "Popen", wraps=real_start) as start, self.assertRaises(
                        LifecycleError) as error:
                read_codex_app_server_thread(root, executable=str(executable),
                                            expected_binary_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                                            thread_id="x" * 200_000)
            self.assertEqual(error.exception.code, "codex-exact-bootstrap-review-unavailable")
            self.assertIn("timed out", str(error.exception))
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertEqual(start.call_count, 1)
            self.assertTrue((root / "child.pid").is_file())
            self.assertFalse(process_is_running(int((root / "child.pid").read_text())))

    def test_app_server_delivers_short_writes_and_retries_would_block(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = self._app_server_io_fixture(root)
            from agent_lifecycle.adapter_sessions import windows_pipe

            target = windows_pipe if os.name == "nt" else exact_prompt_module.os
            operation = "write_pipe" if os.name == "nt" else "write"
            real_write = getattr(target, operation)
            calls = []

            def short_write(fd, data):
                calls.append(len(data))
                if len(calls) == 1:
                    raise BlockingIOError()
                return real_write(fd, data[:3])

            with patch.object(target, operation, side_effect=short_write):
                response = read_codex_app_server_thread(
                    root, executable=str(executable),
                    expected_binary_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                    thread_id="complete-short-write")
            self.assertEqual(response["thread"]["id"], "complete-short-write")
            self.assertGreater(len(calls), 3)


class ExactPromptPublicGateTests(unittest.TestCase):
    def test_public_unified_early_refusals_cleanup_staged_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for profile in (None, {}):
                with self.subTest(project_profile=profile):
                    source = stage_input_request(root, f"early-{len(list(root.rglob('input-request.json')))}",
                                                 {"routeId": ROUTE_ID})
                    receipt = start_lifecycle(
                        adapter_id="codex", mode="implement", project_root=root,
                        project_profile=profile, route_id=ROUTE_ID,
                        requested_claim=CLAIM, input_request=source)
                    self.assertEqual(receipt["status"], "BLOCKED")
                    self.assertFalse(receipt["hostLaunchStarted"])
                    self.assertFalse(source.exists())
                    self.assertEqual(receipt["receiptDigest"], canonical_digest({
                        k: v for k, v in receipt.items() if k != "receiptDigest"}))

    def test_public_unified_cleanup_failure_retains_privacy_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = stage_input_request(root, "sticky-unified", {"routeId": ROUTE_ID})
            with patch("agent_lifecycle.adapter_sessions.unified_start.cleanup_no_start",
                       side_effect=LifecycleError("codex-exact-private-cleanup-pending",
                                                  "cleanup failed")):
                receipt = start_lifecycle(adapter_id="codex", mode="implement",
                                          project_root=root, input_request=source)
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][-1]["code"],
                             "codex-exact-private-cleanup-pending")
            self.assertTrue(source.exists())
            cleanup_no_start(root, None, source)

    def test_direct_context_and_managed_read_failure_cleanup_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = stage_input_request(root, "missing-profile", {"routeId": ROUTE_ID})
            missing_profile = launch_from_local_profile(
                profile_path=root / "missing-profile.json", operation="managedTask",
                adapter_id="codex", project_root=root, route_id=ROUTE_ID,
                requested_claim=CLAIM, input_request=source)
            self.assertEqual(missing_profile["status"], "BLOCKED")
            self.assertFalse(missing_profile["hostLaunchStarted"])
            self.assertEqual(missing_profile["receiptDigest"], canonical_digest({
                k: v for k, v in missing_profile.items() if k != "receiptDigest"}))
            self.assertFalse(source.exists())

            source = stage_input_request(root, "missing-profile-sticky", {"routeId": ROUTE_ID})
            original_unlink = Path.unlink

            def refuse_source(path: Path, *args: object, **kwargs: object) -> None:
                if path == source:
                    raise OSError("simulated cleanup refusal")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", refuse_source):
                sticky = launch_from_local_profile(
                    profile_path=root / "missing-profile.json", operation="managedTask",
                    adapter_id="codex", project_root=root, route_id=ROUTE_ID,
                    requested_claim=CLAIM, input_request=source)
            self.assertEqual(sticky["status"], "BLOCKED")
            self.assertEqual(sticky["blockers"][-1]["code"],
                             "codex-exact-private-cleanup-pending")
            self.assertTrue(source.exists())
            cleanup_no_start(root, None, source)

            source = stage_input_request(root, "missing-manifest", {"routeId": ROUTE_ID})
            runner = Mock()
            context = SimpleNamespace(root=root, profile_adapter="codex",
                                      timeout_seconds=5.0, env_receipt={},
                                      profile_digest="profile", runner=runner)
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers",
                       return_value=[]), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight._identity",
                       return_value={"status": "PASS"}):
                receipt = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=root / "state.json", manifest_path=root / "missing.json",
                    lock_path=root / "lock.json", task_id="task-1", operation_id="op-1",
                    source_revision="rev-1", risk_profile={"profileDigest": "risk"},
                    route_id=ROUTE_ID, requested_claim=CLAIM, input_request=source)
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(receipt["hostLaunchStarted"])
            self.assertFalse(source.exists())
            runner.assert_not_called()

    def test_direct_planning_route_refusal_cleans_staged_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = stage_input_request(root, "planning-refusal", {"routeId": ROUTE_ID})
            context = SimpleNamespace(root=root, profile_adapter="codex",
                                      timeout_seconds=5.0, env_receipt={},
                                      profile_digest="profile")
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._load_context",
                       return_value=context):
                receipt = launch_from_local_profile(
                    profile_path=root / "profile.json", operation="planningTask",
                    project_root=root, route_id=ROUTE_ID,
                    requested_claim=CLAIM, input_request=source)
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(source.exists())

    def test_rb12_dynamic_catalog_change_refuses_with_same_binary(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            catalog_file = root / "catalog.json"
            catalog_file.write_text(json.dumps({
                "models": [{"slug": "test-model", "context_window": 32768}]}))
            binary = root / _CODEX_FIXTURE_NAME
            binary.write_text(
                f"#!{sys.executable}\n"
                "import sys\nfrom pathlib import Path\n"
                "if sys.argv[1:] == ['--version']:\n"
                "    print('codex-cli test')\n"
                "elif sys.argv[1:] == ['debug', 'models', '--bundled']:\n"
                f"    print(Path({str(catalog_file)!r}).read_text())\n"
                "else:\n    sys.exit(2)\n")
            binary.chmod(0o755)
            identity = {"status": "PASS",
                        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(binary))).hexdigest(),
                        "executableContentSha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
            expected = _observed_bundled_catalog(
                root, str(binary), identity, "test-model", dict(os.environ))
            _require_fresh_catalog(
                root, str(binary), identity, "test-model", dict(os.environ), expected)
            catalog_file.write_text(json.dumps({
                "models": [{"slug": "test-model", "context_window": 32769}]}))
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(),
                             identity["executableContentSha256"])
            with self.assertRaises(LifecycleError) as stale:
                _require_fresh_catalog(
                    root, str(binary), identity, "test-model", dict(os.environ), expected)
            self.assertEqual(stale.exception.code, "codex-exact-catalog-stale")

    def test_rb12_final_packet_source_and_output_plan_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_repo = Path(__file__).parents[2]
            contract_raw = (source_repo / "tasks/release-2-16/alk-input-fit-contract.json").read_bytes()
            profile_raw = (source_repo / "profiles/small-context-profile.v1.json").read_bytes()
            contract = json.loads(contract_raw)
            profile = json.loads(profile_raw)
            paths = contract["sourceScope"]["orderedContextRefs"]
            source = root / paths[0]
            source.parent.mkdir(parents=True)
            source_bytes = b"bounded selected source"
            source.write_bytes(source_bytes)
            packet = {"schemaVersion": "agent-task-packet.v1",
                      "plan": {"planDigest": "a" * 64, "packageId": "release-2-16"},
                      "task": {"id": "task-1", "plannedItems": []},
                      "context": {"refs": paths}, "ownership": {}, "specification": {},
                      "validation": {}, "acceptance": []}
            summary = {key: [] for key in profile["requiredSummaryFields"]}
            selected = select_source_excerpts(
                root, packet, contract,
                [{"path": paths[0], "fileSha256": hashlib.sha256(source_bytes).hexdigest(),
                  "startByte": 0, "endByte": len(source_bytes),
                  "selectedSha256": hashlib.sha256(source_bytes).hexdigest(),
                  "candidateDigest": "a" * 64,
                  "estimatorId": "canonical-json-bytes-div-4-ceil"}],
                run_id="run-1", attempt_id="1", manifest_sha256="a" * 64,
                candidate_digest="a" * 64,
                estimator_id="canonical-json-bytes-div-4-ceil")
            binding = {key: selected[key] for key in
                       ("runId", "taskId", "attemptId", "planDigest", "manifestSha256",
                        "candidateDigest", "estimatorId")}
            request = {"role": "worker", "hostVersion": "0.test",
                       "hostMode": "managedTask", "estimatorId": "canonical-json-bytes-div-4-ceil",
                       "instruction": "bounded task", "schema": {}, "latestUser": ""}
            fit = assess_local_input_fit(
                root, contract, profile, packet, summary, selected,
                role="worker", host_adapter_id="codex", host_version="0.test",
                host_mode="managedTask", estimator_id=request["estimatorId"],
                instruction=request["instruction"], schema={}, current_binding=binding,
                latest_user="", window="16k")
            self.assertEqual(fit["status"], "PASS_ALK_COMPONENTS_ONLY")
            files = {
                "packet": (root / "work/release-2-16/packet.json", canonical_bytes(packet)),
                "contract": (root / "tasks/release-2-16/alk-input-fit-contract.json", contract_raw),
                "profile": (root / "profiles/small-context-profile.v1.json", profile_raw),
                "source": (source, source_bytes),
            }
            for path, raw in files.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)

            def recheck() -> None:
                _recheck_alk_fit_sources(
                    root, request, "work/release-2-16/packet.json",
                    hashlib.sha256(files["packet"][1]).hexdigest(),
                    hashlib.sha256(contract_raw).hexdigest(),
                    hashlib.sha256(profile_raw).hexdigest(),
                    "a" * 64, "task-1", selected, summary, binding, fit["receiptDigest"])

            recheck()
            altered_contract = {**contract, "commonEnvelope": {
                **contract["commonEnvelope"], "reservedOutputEstimatedTokens": 3073}}
            mutations = {"packet": files["packet"][1] + b"\n",
                         "source": b"changed selected source",
                         "contract": canonical_bytes(altered_contract),
                         "profile": profile_raw + b"\n"}
            for name, changed in mutations.items():
                with self.subTest(changed=name):
                    path, original = files[name]
                    path.write_bytes(changed)
                    with self.assertRaises(LifecycleError):
                        recheck()
                    path.write_bytes(original)

    def test_final_manifest_reopen_refuses_manifest_only_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest_path = root / "manifest.json"
            captured = {"status": "FROZEN", "planRevision": 69}
            manifest_path.write_bytes(canonical_bytes(captured))
            expected = canonical_digest(captured)
            _require_current_manifest(root, manifest_path, captured, expected)
            manifest_path.write_bytes(canonical_bytes({**captured, "planRevision": 70}))
            with self.assertRaises(LifecycleError) as changed:
                _require_current_manifest(root, manifest_path, captured, expected)
            self.assertEqual(changed.exception.code, "codex-exact-plan-stale")
            with self.assertRaises(LifecycleError) as missing:
                _require_current_manifest(root, None, captured, expected)
            self.assertEqual(missing.exception.code, "codex-exact-plan-stale")

    def test_selected_binary_path_refuses_changed_bytes_before_start(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / _CODEX_FIXTURE_NAME
            binary.write_bytes(b"first")
            identity = {"status": "PASS",
                        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(binary))).hexdigest(),
                        "executableContentSha256": hashlib.sha256(b"first").hexdigest()}
            self.assertEqual(_selected_binary_path(str(binary), identity, dict(os.environ)), binary)
            binary.write_bytes(b"changed")
            with self.assertRaises(LifecycleError) as changed:
                _selected_binary_path(str(binary), identity, dict(os.environ))
            self.assertEqual(changed.exception.code, "codex-exact-binary-mismatch")

    def test_transport_witness_requires_observed_start_and_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            event = {"status": "COMPLETE", "acceptedBytes": 5,
                     "acceptedSha256": "a" * 64, "closeSucceeded": True}
            input_body = {"schemaVersion": "alk-codex-process-input.v1",
                          "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                          "role": "worker", "finalPromptSha256": "a" * 64, **event}
            _write_exclusive(evidence / "process-input.json",
                             canonical_bytes(input_body), root=root)
            with self.assertRaises(LifecycleError):
                _record_transport_witness(
                    root, evidence, run_id="run-1", task_id="task-1",
                    attempt_id="1", role="worker", final_sha="a" * 64,
                    config_manifest_sha="b" * 64,
                    diagnostic={"rawSha256": "c" * 64, "items": []}, event=event)
            self.assertFalse((evidence / "transport-equivalence.json").exists())
            start_body = {"schemaVersion": "alk-codex-process-start.v1",
                          "hostLaunchStarted": True, "stdinStatus": "PENDING",
                          "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                          "role": "worker", "finalPromptSha256": "a" * 64}
            _write_exclusive(evidence / "process-start.json",
                             canonical_bytes(start_body), root=root)
            _record_transport_witness(
                root, evidence, run_id="run-1", task_id="task-1",
                attempt_id="1", role="worker", final_sha="a" * 64,
                config_manifest_sha="b" * 64,
                diagnostic={"rawSha256": "c" * 64, "items": []}, event=event)
            body = json.loads((evidence / "transport-equivalence.json").read_text())
            self.assertEqual(body["status"], "OS_PIPE_ACCEPTED")
            self.assertEqual(body["childConsumption"], "UNPROVEN")

    @unittest.skipUnless(os.name == "posix", "joined OS-pipe fixture uses POSIX descriptors")
    @patch("agent_lifecycle.adapter_sessions.launch_preflight.verify_fresh_task_gate", return_value=None)
    def test_local_one_attempt_process_receipts_join_transport_witness(self, _bootstrap_gate) -> None:
        # This is a Python child fixture through the real runner, not selected Codex proof.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            start_path = evidence / "process-start.json"
            input_path = evidence / "process-input.json"
            final = "one attempt local prompt"
            final_sha = hashlib.sha256(final.encode()).hexdigest()
            diagnostic = {"rawSha256": "d" * 64, "items": []}
            for relative in bootstrap_r11._SOURCES:
                copied = root / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(__file__).parents[2] / relative, copied)
            plan = root / "tasks/release-2-16"
            plan.mkdir(parents=True)
            manifest = {"status": "FROZEN", "planRevision": 69}
            (plan / "plan.manifest.json").write_bytes(canonical_bytes(manifest))
            lock = plan / "plan.lock.json"
            lock.write_bytes(b'{}')
            argv = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(); print(\"RAW_PREFIX_PRIVATE_MARKER\" + \"x\" * 8000)"]
            intent_path = evidence / "prelaunch-intent.json"
            intent = {"schemaVersion": "alk-codex-prelaunch-intent.v1", "hostLaunchStarted": False,
                      "runId": "run-1", "taskId": "task-1", "attemptId": "1", "operationId": "op-1",
                      "routeId": ROUTE_ID, "requestedClaim": CLAIM, "sourceRevision": "fixture",
                      "planDigest": canonical_digest(manifest), "lockDigest": hashlib.sha256(lock.read_bytes()).hexdigest(),
                      "requestSha256": "a" * 64, "finalPromptSha256": final_sha,
                      "commandIdentityHash": command_identity_hash(argv), "plannedStdinBytes": len(final.encode()),
                      **bootstrap_r11.capture_attempt_authority(root, lock_path=lock)}
            _write_exclusive(intent_path, canonical_bytes(intent), root=root)
            bootstrap_r11.reserve_attempt_result(root, intent_path=intent_path)

            def on_started(event: dict) -> None:
                _write_exclusive(start_path, canonical_bytes({
                    "schemaVersion": "alk-codex-process-start.v1",
                    "hostLaunchStarted": True, "stdinStatus": "PENDING",
                    "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                    "role": "worker", "finalPromptSha256": final_sha,
                    "processIdentityHash": event["processIdentityHash"],
                    "commandIdentityHash": event["commandIdentityHash"],
                    "plannedStdinSha256": event["plannedStdinSha256"],
                    "plannedStdinBytes": event["plannedStdinBytes"],
                }), root=root)

            def on_input(event: dict) -> None:
                _write_exclusive(input_path, canonical_bytes({
                    "schemaVersion": "alk-codex-process-input.v1",
                    "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                    "role": "worker", "finalPromptSha256": final_sha,
                    **event,
                }), root=root)
                _record_transport_witness(
                    root, evidence, run_id="run-1", task_id="task-1",
                    attempt_id="1", role="worker", final_sha=final_sha,
                    config_manifest_sha="c" * 64, diagnostic=diagnostic,
                    event=event)

            context = SimpleNamespace(
                root=root, runner=run_process, timeout_seconds=5.0,
                profile={"executable": sys.executable}, profile_adapter="codex",
                env=dict(os.environ), env_receipt={}, profile_digest="profile",
            )
            prepared = {
                "verifyBeforeStart": lambda: None,
                "argv": argv, "intentPath": intent_path,
                "codexHome": str(root / "codex-home"), "stdinText": final,
                "runId": "run-1", "taskId": "task-1", "attemptId": "1",
                "sealedSha256": "a" * 64, "finalPromptSha256": final_sha,
                "operationId": "op-1",
                "fitReceiptDigest": "b" * 64,
                "startReceiptPath": start_path, "inputReceiptPath": input_path,
                "onStarted": on_started, "onInput": on_input,
            }
            with bound_current_invocation_fixture(
                    root, task_id="task-1", operation_id="op-1", source_revision="fixture",
                    manifest_path=plan / "plan.manifest.json", lock_path=lock) as bindings:
                receipt = _run_exact_managed_process(
                    context, prepared=prepared, audit={"auditSha256": "e" * 64},
                    session_id="session", risk_profile={"profileDigest": "risk"},
                    host_identity={"status": "PASS"}, operation_id="op-1",
                    absolute_deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000, **bindings)
            self.assertEqual(receipt["status"], "PASS", receipt)
            self.assertTrue(receipt["hostLaunchStarted"])
            start_raw, input_raw = start_path.read_bytes(), input_path.read_bytes()
            joined = json.loads((evidence / "transport-equivalence.json").read_bytes())
            self.assertEqual(joined["status"], "OS_PIPE_ACCEPTED")
            self.assertEqual(joined["attemptId"], "1")
            self.assertEqual(joined["processStartSha256"], hashlib.sha256(start_raw).hexdigest())
            self.assertEqual(joined["processInputSha256"], hashlib.sha256(input_raw).hexdigest())
            self.assertEqual(joined["observedPipe"]["acceptedSha256"], final_sha)
            self.assertEqual(receipt["exactPrompt"]["startReceiptSha256"],
                             joined["processStartSha256"])
            self.assertEqual(receipt["exactPrompt"]["inputReceiptSha256"],
                             joined["processInputSha256"])
            self.assertEqual(joined["childConsumption"], "UNPROVEN")
            observed = receipt["exactPrompt"]["observedProcessResult"]
            self.assertNotIn("stdout", observed)
            self.assertNotIn("stderr", observed)
            self.assertNotIn(b"RAW_PREFIX_PRIVATE_MARKER", canonical_bytes(receipt))
            terminal = json.loads((evidence / "attempt-result-terminal.json").read_bytes())
            self.assertEqual(terminal["processResultSha256"], canonical_digest(observed))
            self.assertEqual(observed["stdoutTail"][-2000:], receipt["stdout"]["tail"])
            changed = {**observed, "stdoutTail": "invented native completion"}
            self.assertNotEqual(terminal["processResultSha256"], canonical_digest(changed))

    def test_prelaunch_sources_config_and_diagnostic_without_caller_pass(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / _CODEX_FIXTURE_NAME
            binary.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "if sys.argv[1:] == ['--version']:\n"
                "    print('codex-cli test')\n"
                "elif sys.argv[1:] == ['debug', 'models', '--bundled']:\n"
                "    print(json.dumps({'models':[{'slug':'test-model','context_window':32768}]}))\n"
                "elif sys.argv[1:3] == ['debug', 'prompt-input']:\n"
                "    print(json.dumps([{'type':'message','role':'user','content':sys.argv[3]}]))\n"
                "else:\n"
                "    sys.exit(2)\n"
            )
            binary.chmod(0o755)
            binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            identity = {"status": "PASS", "executableContentSha256": binary_sha,
                        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(binary))).hexdigest()}
            snapshot = (root / "work/release-2-16/runtime-private/codex-exact-prompt"
                        / "run-1/task-1/1/codex-home")
            _private_dir(snapshot.parent, boundary=root)
            snapshot.mkdir(mode=0o700)
            request = {"selectedHost": {"model": "test-model", "binarySha256": binary_sha,
                                        "catalogWindowTokens": 32768}}
            observed = _selected_host_evidence(
                root, request, identity, "a" * 64, "run-1", "task-1", "1",
                str(binary), dict(os.environ), "worker")
            self.assertEqual(observed[0], "test-model")
            self.assertEqual(observed[3]["actualChildWindow"], "UNPROVEN")
            self.assertEqual(observed[4]["execStdinEquivalence"], "UNPROVEN")
            private = (root / "work/release-2-16/private-details/codex-exact-prompt"
                       / "run-1/task-1/1")
            config = json.loads((private / "effective-config.json").read_text())
            self.assertEqual(config["childInternalEffectiveConfig"], "UNPROVEN")
            assert_private_path(self, (private / "prompt-input.json"), 0o600)
            evidence = (root / "work/release-2-16/evidence/codex-exact-prompt"
                        / "run-1/task-1/1")
            manifest = json.loads((evidence / "config-snapshot-manifest.json").read_text())
            self.assertEqual(manifest["status"], "OBSERVED_ALK_SOURCE")
            self.assertFalse((evidence / "transport-equivalence.json").exists())
            request["selectedHost"]["configManifestSha256"] = "b" * 64
            with self.assertRaises(LifecycleError) as legacy:
                _selected_host_evidence(root, request, identity, "a" * 64,
                                        "run-2", "task-1", "1", str(binary),
                                        dict(os.environ), "worker")
            self.assertEqual(legacy.exception.code, "codex-exact-legacy-witness-refused")

    def test_per_role_diagnostic_is_private_and_only_a_candidate(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / _CODEX_FIXTURE_NAME
            binary.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "assert sys.argv[1:3] == ['debug', 'prompt-input']\n"
                "home = Path(os.environ['CODEX_HOME'])\n"
                "p = home / 'installation_id'\n"
                "scenario = os.environ.get('ALK_TEST_METADATA', 'absent')\n"
                "if scenario in {'reset', 'failed-command'}: p.chmod(0o644)\n"
                "elif scenario == 'contents': p.write_bytes(b'b' * 36); p.chmod(0o644)\n"
                "elif scenario == 'replacement':\n"
                "    old = p.read_bytes(); p.unlink(); p.write_bytes(old); p.chmod(0o644)\n"
                "elif scenario == 'symlink':\n"
                "    p.unlink(); p.symlink_to(home / 'config.toml')\n"
                "elif scenario == 'hardlink': os.link(p, home / 'metadata-copy')\n"
                "elif scenario == 'other-mode':\n"
                "    if os.name == 'nt':\n"
                "        import subprocess\n"
                "        subprocess.run(['icacls', str(p), '/grant', '*S-1-1-0:F'], check=True, capture_output=True)\n"
                "    else: p.chmod(0o640)\n"
                "elif scenario == 'config': (home / 'config.toml').write_bytes(b'changed')\n"
                "elif scenario == 'config-replacement':\n"
                "    c = home / 'config.toml'; t = home / 'replacement'\n"
                "    t.write_bytes(c.read_bytes()); t.chmod(0o600); t.replace(c)\n"
                "elif scenario == 'directory-add': (home / 'empty-new').mkdir(mode=0o700)\n"
                "elif scenario == 'directory-remove': (home / 'empty-before').rmdir()\n"
                "elif scenario == 'unexpected-file': (home / 'new-file').write_bytes(b'new')\n"
                "if scenario == 'failed-command': sys.exit(2)\n"
                "print(json.dumps([{'type':'message','role':'user',"
                "'content':sys.argv[3]}]))\n"
            )
            binary.chmod(0o755)
            binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            identity = {"status": "PASS", "executableContentSha256": binary_sha,
                        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(binary))).hexdigest()}
            cases = [("absent", 0o600), ("reset", 0o600), ("reset", 0o400),
                     ("unchanged", 0o600), ("contents", 0o600), ("replacement", 0o600),
                     ("symlink", 0o600), ("hardlink", 0o600), ("other-mode", 0o600),
                     ("other-mode", 0o400), ("failed-command", 0o400),
                     ("config", 0o600), ("config-replacement", 0o600),
                     ("directory-add", 0o600), ("directory-remove", 0o600),
                     ("unexpected-file", 0o600), ("failed-command", 0o600)]
            for index, (scenario, mode) in enumerate(cases):
                with self.subTest(scenario=scenario, mode=mode):
                    snapshot = root / f"snapshot-{index}"
                    snapshot.mkdir(mode=0o700)
                    config = snapshot / "config.toml"
                    config.write_bytes(b"private config")
                    config.chmod(0o600)
                    if scenario == "directory-remove":
                        (snapshot / "empty-before").mkdir(mode=0o700)
                    metadata = snapshot / "installation_id"
                    if scenario != "absent":
                        metadata.write_bytes(b"a" * 36)
                        metadata.chmod(mode)
                    actual_before_mode = metadata.stat().st_mode & 0o777 if metadata.exists() else None
                    before = _snapshot_digest(snapshot, root=root)
                    run_id = f"run-{index}"
                    raw = (root / "work/release-2-16/private-details/codex-exact-prompt"
                           / run_id / "task-1/1/prompt-input.json")
                    arguments = dict(snapshot=snapshot, model="test-model", role="worker",
                                     run_id=run_id, task_id="task-1", attempt_id="1",
                                     final_sha="a" * 64,
                                     process_env={**os.environ, "ALK_TEST_METADATA": scenario})
                    if scenario in {"absent", "reset", "unchanged"}:
                        observed = _observed_prompt_diagnostic(root, str(binary), identity, **arguments)
                        self.assertEqual(_snapshot_digest(snapshot, root=root), before)
                        self.assertEqual(observed["rawSha256"], hashlib.sha256(raw.read_bytes()).hexdigest())
                        assert_private_path(self, raw, 0o600)
                        self.assertEqual(observed["itemCount"], 1)
                        self.assertEqual(observed["execStdinEquivalence"], "UNPROVEN")
                        self.assertNotIn("private model input", raw.read_text())
                    else:
                        with self.assertRaises(LifecycleError):
                            _observed_prompt_diagnostic(root, str(binary), identity, **arguments)
                        self.assertFalse(raw.exists())
                        if scenario == "failed-command":
                            self.assertEqual(_snapshot_digest(snapshot, root=root), before)
                    if scenario in {"reset", "unchanged", "failed-command"}:
                        self.assertEqual(metadata.stat().st_mode & 0o777, actual_before_mode)
            snapshot = root / "foreign-metadata"
            snapshot.mkdir(mode=0o700)
            metadata = snapshot / "installation_id"
            metadata.write_bytes(b"a" * 36)
            metadata.chmod(0o600)
            private_access = unsafe_private_access(metadata) if os.name == "nt" else nullcontext()
            owner_change = nullcontext() if os.name == "nt" else patch.object(
                exact_prompt_module.os, "getuid", return_value=os.getuid() + 1)
            with private_access, owner_change, self.assertRaises(LifecycleError):
                _observed_prompt_diagnostic(
                    root, str(binary), identity, snapshot=snapshot, model="test-model",
                    role="worker", run_id="foreign-run", task_id="task-1", attempt_id="1",
                    final_sha="a" * 64, process_env=dict(os.environ))

    def test_selected_binary_bundled_catalog_is_observed_and_bounded(self) -> None:
        install_windows_fixture_process(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / _CODEX_FIXTURE_NAME
            binary.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "if sys.argv[1:] == ['--version']:\n"
                "    print('codex-cli test')\n"
                "elif sys.argv[1:] == ['debug', 'models', '--bundled']:\n"
                "    print(json.dumps({'models':[{'slug':'test-model','context_window':32768}]}))\n"
                "else:\n"
                "    sys.exit(2)\n"
            )
            binary.chmod(0o755)
            binary = binary.resolve(strict=True)
            binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            identity = {"status": "PASS", "executableContentSha256": binary_sha,
                        "resolvedPathSha256": hashlib.sha256(os.fsencode(str(binary))).hexdigest()}
            observed = _observed_bundled_catalog(
                root, str(binary), identity, "test-model", dict(os.environ))
            self.assertEqual(observed["catalogWindowTokens"], 32768)
            self.assertEqual(observed["binarySha256"], binary_sha)
            self.assertEqual(observed["actualChildWindow"], "UNPROVEN")
            with self.assertRaises(LifecycleError) as missing:
                _observed_bundled_catalog(root, str(binary), identity,
                                          "absent-model", dict(os.environ))
            self.assertEqual(missing.exception.code, "codex-exact-model-unavailable")

    def test_early_managed_blocker_cleans_staged_request_without_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = stage_input_request(root, "request-early", {"routeId": ROUTE_ID})
            runner = Mock()
            context = SimpleNamespace(
                root=root, profile_adapter="codex", timeout_seconds=5.0,
                env_receipt={}, profile_digest="profile", runner=runner,
            )
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers",
                       return_value=[{"code": "local-launch-required-field-missing"}]):
                receipt = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=None, manifest_path=None, lock_path=None,
                    task_id=None, operation_id=None, source_revision=None,
                    risk_profile=None, route_id=ROUTE_ID, requested_claim=CLAIM,
                    input_request=source,
                )
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(receipt["hostLaunchStarted"])
            self.assertEqual(receipt["blockers"][0]["code"],
                             "local-launch-required-field-missing")
            self.assertFalse(source.exists())
            runner.assert_not_called()

    def test_early_refusal_cannot_delete_another_attempt_sealed_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed = (root / "work/release-2-16/private-details/codex-exact-prompt"
                      / "run-1/task-1/1/input-request.json")
            _write_exclusive(sealed, b"started raw from another attempt", root=root)
            context = SimpleNamespace(
                root=root, profile_adapter="codex", timeout_seconds=5.0,
                env_receipt={}, profile_digest="profile", runner=Mock(),
            )
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers",
                       return_value=[{"code": "local-launch-required-field-missing"}]):
                receipt = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=None, manifest_path=None, lock_path=None,
                    task_id=None, operation_id=None, source_revision=None,
                    risk_profile=None, route_id=ROUTE_ID, requested_claim=CLAIM,
                    input_request=sealed,
                )
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][-1]["code"],
                             "codex-exact-private-path-unsafe")
            self.assertEqual(sealed.read_bytes(), b"started raw from another attempt")
            context.runner.assert_not_called()

    def test_early_identity_failure_cleans_staged_request_without_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = stage_input_request(root, "request-identity", {"routeId": ROUTE_ID})
            runner = Mock()
            context = SimpleNamespace(
                root=root, profile_adapter="codex", timeout_seconds=5.0,
                env_receipt={}, profile_digest="profile", runner=runner,
            )
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers",
                       return_value=[]), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight._identity",
                       return_value={"status": "BLOCKED"}):
                receipt = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=root / "state.json", manifest_path=root / "manifest.json",
                    lock_path=root / "lock.json", task_id="task-1", operation_id="op-1",
                    source_revision="rev-1", risk_profile={"profileDigest": "risk"},
                    route_id=ROUTE_ID, requested_claim=CLAIM, input_request=source,
                )
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["blockers"][0]["code"],
                             "local-launch-executable-identity-unavailable")
            self.assertFalse(source.exists())
            runner.assert_not_called()

    def test_direct_managed_route_missing_arguments_never_calls_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = Mock()
            context = SimpleNamespace(
                root=root, profile_adapter="codex", timeout_seconds=5.0,
                env_receipt={}, profile_digest="profile", runner=runner,
                profile={"executable":"codex"}, env=dict(os.environ),
            )
            manifest = {"status":"FROZEN", "package":{"id":"release-2-16"},
                        "runtimePolicy":{"preExecutionBootstrap":{}}, "planRevision":67}
            state = {"tasks":[{"id":"task-1", "attempt":1, "status":"RUNNING"}]}
            paths = [root / name for name in ("state.json", "manifest.json", "lock.json")]
            values = {paths[0]:state, paths[1]:manifest, paths[2]:{}}
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers", return_value=[]), \
                 patch("agent_lifecycle.adapter_sessions.launch_preflight._identity", return_value={"status":"PASS"}), \
                 patch("agent_lifecycle.adapter_sessions.launch_preflight.read_json_object", side_effect=lambda p, **_: values[p]), \
                 patch("agent_lifecycle.adapter_sessions.launch_preflight.verify_plan_package_integrity"), \
                 patch("agent_lifecycle.adapter_sessions.launch_preflight.validate_task_risk_profile"), \
                 bound_current_invocation_fixture(root, task_id="task-1", operation_id="op-1", source_revision="rev-1",
                                                  state_path=paths[0], manifest_path=paths[1], lock_path=paths[2]):
                receipt = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=paths[0], manifest_path=paths[1], lock_path=paths[2],
                    task_id="task-1", operation_id="op-1", source_revision="rev-1",
                    risk_profile={"profileDigest":"risk", "adapterId":"codex"},
                    route_id=None, requested_claim=None, input_request=None,
                )
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(receipt["hostLaunchStarted"])
            self.assertEqual(receipt["blockers"][0]["code"], "codex-exact-route-required")
            runner.assert_not_called()

    def test_direct_and_unified_route_reach_same_prestart_attempt_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            state_path, manifest_path, lock_path = (
                root / name for name in ("state.json", "manifest.json", "lock.json"))
            lock_path.write_text("{}")
            original_deadline = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
            state = {"runDeadlineAt": original_deadline,
                     "tasks": [{"id": "task-1", "attempt": 1, "status": "RUNNING",
                                "attemptDeadlineAt": original_deadline}]}
            manifest = {"status": "FROZEN", "package": {"id": "release-2-16"},
                        "runtimePolicy": {"preExecutionBootstrap": {}}, "planRevision": 69}
            values = {state_path: state, manifest_path: manifest, lock_path: {}}
            context = SimpleNamespace(
                root=root, profile_adapter="codex", timeout_seconds=5.0,
                env_receipt={}, profile_digest="profile", runner=run_process,
                profile={"executable": "codex"}, env=dict(os.environ),
            )
            binary_sha = "7" * 64
            blocked = {"status": "BLOCKED", "hostLaunchStarted": False,
                       "blockers": [{"code": "local-prestart-stop"}]}
            task_receipt = {
                "status": "READY", "action": "MANAGED_RUN", "input": {},
                "workflowBinding": {
                    "state": str(state_path), "manifest": str(manifest_path),
                    "lock": str(lock_path), "task": "task-1",
                    "operationId": "op-1", "sourceRevision": "rev-1"},
                "adapterSessionReceipt": {"sessionId": "session", "nextAction": {
                    "riskExecutionProfile": {"profileDigest": "risk"}}},
            }
            with patch("agent_lifecycle.adapter_sessions.launch_preflight._managed_launch_blockers",
                       return_value=[]), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight._identity",
                       return_value={"status": "PASS", "executableContentSha256": binary_sha}), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight.read_json_object",
                       side_effect=lambda path, **_: values[path]), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight.verify_plan_package_integrity"), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight.validate_task_risk_profile"), patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight.require_bootstrap_audit",
                       return_value={"status": "PASS"}) as audit, patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight.prepare_exact_prompt",
                       return_value={"attemptId": "1"}) as prepare, patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight._run_exact_managed_process",
                       return_value=blocked) as stop, patch(
                       "agent_lifecycle.adapter_sessions.launch_preflight._load_context",
                       return_value=context), patch(
                       "agent_lifecycle.adapter_sessions.unified_start._inspect_task_source",
                       return_value=({}, {"schemaVersion": "agent-adapter-task-run-request.v1"}, b"{}")), patch(
                       "agent_lifecycle.adapter_sessions.unified_start._missing_frozen_bindings",
                       return_value=[]), patch(
                       "agent_lifecycle.adapter_sessions.unified_start.start_adapter_task",
                       return_value=task_receipt), patch(
                       "agent_lifecycle.adapter_sessions.unified_start.strategy_projection_for_receipt",
                       return_value={}), bound_current_invocation_fixture(
                       root, task_id="task-1", operation_id="op-1", source_revision="rev-1",
                       state_path=state_path, manifest_path=manifest_path, lock_path=lock_path):
                direct_source = stage_input_request(root, "direct-positive", {"routeId": ROUTE_ID})
                direct = _managed_task(
                    context, session_id="session", explicit_launch=True,
                    state_path=state_path, manifest_path=manifest_path,
                    lock_path=lock_path, task_id="task-1", operation_id="op-1",
                    source_revision="rev-1", risk_profile={"profileDigest": "risk"},
                    route_id=ROUTE_ID, requested_claim=CLAIM,
                    input_request=direct_source)
                self.assertFalse(direct["hostLaunchStarted"])
                cleanup_no_start(root, None, direct_source)

                unified_source = stage_input_request(root, "unified-positive", {"routeId": ROUTE_ID})
                unified = start_lifecycle(
                    adapter_id="codex", mode="implement", task_text="{}", launch=True,
                    host_launch_profile_path=root / "profile.json", project_root=root,
                    route_id=ROUTE_ID, requested_claim=CLAIM,
                    input_request=unified_source)
                self.assertFalse(unified["hostLaunchStarted"])
                self.assertFalse(unified_source.exists())

            self.assertEqual(audit.call_count, 2)
            self.assertEqual(prepare.call_count, 2)
            self.assertEqual(stop.call_count, 2)
            for called in prepare.call_args_list:
                self.assertEqual(called.kwargs["task"]["attempt"], 1)
                self.assertEqual(called.kwargs["operation_id"], "op-1")
                self.assertEqual(called.kwargs["route_id"], ROUTE_ID)
            for called in audit.call_args_list:
                self.assertEqual(called.kwargs["selected_binary_sha256"], binary_sha)

    def test_unified_no_profile_preserves_explicit_route_fields(self) -> None:
        source = Path("work/release-2-16/private-details/codex-exact-prompt/staging/r/input-request.json")
        with patch("agent_lifecycle.adapter_sessions.unified_start._start_lifecycle_core", return_value={"status":"BLOCKED"}) as core:
            start_lifecycle(adapter_id="codex", mode="implement", route_id=ROUTE_ID,
                            requested_claim=CLAIM, input_request=source)
        self.assertEqual(core.call_args.kwargs["route_id"], ROUTE_ID)
        self.assertEqual(core.call_args.kwargs["requested_claim"], CLAIM)
        self.assertEqual(core.call_args.kwargs["input_request"], source)

    def test_unified_project_profile_preserves_explicit_route_fields(self) -> None:
        source = Path("work/release-2-16/private-details/codex-exact-prompt/staging/r/input-request.json")
        effective = {"defaultAdapter":"codex", "defaultMode":"implement", "defaultRisk":"S0"}
        with patch("agent_lifecycle.adapter_sessions.unified_start._profile_plan_authority", return_value=({},{})), \
             patch("agent_lifecycle.adapter_sessions.unified_start.build_effective_project_profile", return_value=effective), \
             patch("agent_lifecycle.adapter_sessions.unified_start._start_lifecycle_core", return_value={"status":"BLOCKED"}) as core, \
             patch("agent_lifecycle.adapter_sessions.unified_start._build_guided_action_receipt", return_value={"status":"BLOCKED"}):
            start_lifecycle(adapter_id="codex", mode="implement", project_profile={},
                            route_id=ROUTE_ID, requested_claim=CLAIM, input_request=source)
        self.assertEqual(core.call_args.kwargs["route_id"], ROUTE_ID)
        self.assertEqual(core.call_args.kwargs["requested_claim"], CLAIM)
        self.assertEqual(core.call_args.kwargs["input_request"], source)

    def test_r69h_r8_typed_source_selection_refuses_ambiguous_changes(self) -> None:
        # A fixed v8 unit fixture: current R11 imports are deliberately outside
        # the old oracle, so current repository bytes cannot be its positive case.
        header = b'import os\n_MAX_REQUEST_BYTES = 131_072\n\n'
        selected = (b'def _review_projection():\n'
                    b'    invalid = "codex-exact-source-exposure-invalid"\n'
                    b'    return os.name\n\n')
        context = b'def prepare_exact_prompt():\n    return 1\n'
        current = before = header + selected + context
        imported = {"kind": "Import", "origin": "os", "member": None, "alias": None}
        function = {"kind": "FunctionDef", "origin": None, "member": None, "alias": None}
        bindings = {"os": imported, "_review_projection": function,
                    "prepare_exact_prompt": function,
                    "_MAX_REQUEST_BYTES": {"kind": "Assign", "origin": None,
                                           "member": None, "alias": None}}
        masked = b'<MODULE_HEADER><_review_projection>' + context
        rule = {
            "baselineTypedBindingInventorySha256": exact_prompt_module._sha(canonical_bytes(bindings)),
            "currentCandidateTypedBindingInventorySha256": exact_prompt_module._sha(canonical_bytes(bindings)),
            "approvedNewTopLevelBindings": [], "approvedRemovedTopLevelBindings": [],
            "permittedFutureFunctionPrefix": "_r69h_", "permittedFutureGlobalPrefix": "_R69H_",
            "unchangedContextIdentityOnlySha256": {"prepare_exact_prompt": exact_prompt_module._sha(context)},
            "currentRequiredFunctionSymbols": ["_review_projection"],
            "currentRequiredGlobalAssignments": [], "changedFunctionClosureSeeds": ["_review_projection"],
            "currentLocalDependencyClosure": ["_review_projection"],
            "currentImportedAliasIdentitiesUsedByClosure": {"os": imported},
            "baselineDeletedFunctionTombstones": [], "maskedNonContentSha256": exact_prompt_module._sha(masked),
            "maskedNonContentBytes": len(masked),
        }
        ranges, identity_only = _r69h_codex_exposure(current, before, rule)
        self.assertEqual(len(ranges), 2)
        self.assertEqual([row["symbol"] for row in ranges], ["MODULE_HEADER", "_review_projection"])
        self.assertEqual(len(identity_only), 1)
        self.assertEqual(current[ranges[1]["start"]:ranges[1]["end"]], selected)
        mutations = (
            current.replace(b"import os\n", b"os = 1\n", 1),
            current.replace(b"import os\n", b"import os; import sys\n", 1),
            current.replace(b"_MAX_REQUEST_BYTES = 131_072", b"_MAX_REQUEST_BYTES = _x = 131_072", 1),
            current.replace(b"def prepare_exact_prompt(", b"def prepare_exact_prompt (", 1),
            current + b"\n\ndef _review_projection():\n    pass\n",
            current.replace(b'    invalid = "codex-exact-source-exposure-invalid"\n',
                            b'    invalid = "codex-exact-source-exposure-invalid"\n    globals()\n', 1),
        )
        self.assertEqual(len(set(mutations)), len(mutations))
        for changed in mutations:
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()):
                with self.assertRaises(LifecycleError):
                    _r69h_codex_exposure(changed, before, rule)

    def test_r69h_r8_packet_builder_rechecks_complete_checker_selection(self) -> None:
        # Exercise the packet writer against an explicit checker result. Route
        # admission is separate; a historical v8 packet must not use live v9 WIP.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = "source.py"
            selected = b"def _sha():\n    return 1\n\n"
            identity = b"def context():\n    return 2\n"
            raw = selected + identity
            (root / relative).write_bytes(raw)
            checked = {"oracleSha256": "d19e5edb56f4908c949f4239763038915f27798f54e8cdbbc13db6a361f93834",
                       "testDependencyClosure": {"fixture": "packet-writer-unit-only"},
                       "sources": [{"path": relative, "beforeExists": True,
                           "beforeSha256": hashlib.sha256(raw).hexdigest(),
                           "currentFullSha256": hashlib.sha256(raw).hexdigest(),
                           "currentFullBytes": len(raw),
                           "ranges": [{"start": 0, "end": len(selected), "symbol": "_sha", "role": "CONTENT"}],
                           "identityOnly": [{"start": len(selected), "end": len(raw), "symbol": "context",
                                             "sha256": hashlib.sha256(identity).hexdigest()}]}]}
            with patch.object(source_exposure_module, "_check_source_exposure", return_value=checked):
                manifest, packet = _build_source_exposure_packet(root, checked)
                self.assertEqual(manifest["oracleSha256"], checked["oracleSha256"])
                self.assertIn(b"@@ IDENTITY_ONLY ", packet)
                self.assertIn("R69J_V8_AST_SLICE_OR_FULL", {row["generationRule"] for row in manifest["blocks"]})
                self.assertIn(selected, packet)
                self.assertNotIn(identity, packet)
                v7 = json.loads(json.dumps(checked))
                v7["oracleSha256"] = "5f7b3cee3f074ebfbf4129bd4058d38116ef8385be20e6fbcd965158bc07a4fe"
                with patch.object(source_exposure_module, "_check_source_exposure", return_value=v7):
                    old_manifest, _ = _build_source_exposure_packet(root, v7)
                self.assertIn("R69I_V7_AST_SLICE_OR_FULL",
                              {row["generationRule"] for row in old_manifest["blocks"]})
                tampered = json.loads(json.dumps(checked))
                tampered["sources"][0]["ranges"] = []
                with self.assertRaises(LifecycleError):
                    _build_source_exposure_packet(root, tampered)
                (root / relative).write_bytes(raw + b"changed")
                with self.assertRaises(LifecycleError):
                    _build_source_exposure_packet(root, checked)
        root = Path(__file__).parents[2]
        route = json.loads((root / "tasks/release-2-16/historical-r69q/route-bootstrap-contract.json").read_text())
        route["auditJoin"]["delivery"]["sourceOracleSha256"] = "0" * 64
        with patch.object(source_exposure_module, "read_json_object", return_value=route):
            with self.assertRaises(LifecycleError):
                _check_source_exposure(root)

    def test_r69h_r9_shared_roster_roundtrip_and_refusals(self) -> None:
        root = Path(__file__).parents[2]
        oracle = json.loads((root / "tasks/release-2-16/historical-r69q/SUPPORT-MEMBERSHIP-ORACLE-v3.json").read_text())
        roster = ["fixture.Case.test_r69h_case"]
        source = {"fixture.py": "a" * 64}
        stderr = b"----------------------------------------------------------------------\nRan 1 test in 0.001s\n\nOK\n"
        execution = {
            "argv": ["python3", "-m", "unittest", "fixture", "-q"],
            "commandDigest": "b" * 64, "contractCommand": "fixture", "cwd": str(root),
            "environment": {"PYTHONPATH": "src"}, "exitCode": 0,
            "sourceTestFileSha256": source, "testNames": roster,
            "stdoutSha256": hashlib.sha256(b"").hexdigest(),
            "stderrSha256": hashlib.sha256(stderr).hexdigest(),
            "startedAtUtc": "2026-09-25T00:00:00+00:00",
            "endedAtUtc": "2026-09-25T00:00:01+00:00",
        }
        discovery = {
            "moduleNames": ["fixture"], "sourceFileSha256": source,
            "sourceBeforeSha256": source, "sourceAfterSha256": source,
            "discoveredCaseIds": roster, "discoveredCaseCount": 1,
            "discoveryMethod": "unittest.TestLoader.loadTestsFromNames",
            "discoveryStartedAtUtc": "2026-09-25T00:00:02+00:00",
            "discoveryEndedAtUtc": "2026-09-25T00:00:03+00:00",
        }
        oracle["testBlocks"]["C34"]["modules"] = ["fixture"]
        oracle["testBlocks"]["C34"]["baselineCaseIds"] = roster
        block = exact_prompt_module._r69h_project_test_support(
            "C34", execution, discovery, b"", stderr, oracle)
        self.assertEqual(block["caseRoster"], roster)
        self.assertEqual(block["executionReceipt"]["testNamesRef"], "caseRoster")
        exact_prompt_module._r69h_expand_test_support(
            block, "C34", execution, discovery, b"", stderr, oracle)
        for invalid_field in ("executionRef", "discoveryRef", "duplicateRoster",
                              "commandId", "stderrEncoding"):
            wrong = json.loads(json.dumps(block))
            if invalid_field == "executionRef":
                wrong["executionReceipt"]["testNamesRef"] = "other"
            elif invalid_field == "discoveryRef":
                wrong["loaderDiscoveryReceipt"]["discoveredCaseIdsRef"] = "other"
            elif invalid_field == "duplicateRoster":
                wrong["caseRoster"] = roster + roster
            elif invalid_field == "commandId":
                wrong["commandId"] = "C35"
            else:
                wrong["stderrRawBase64"] = "not-base64"
            with self.assertRaises(LifecycleError):
                exact_prompt_module._r69h_expand_test_support(
                    wrong, "C34", execution, discovery, b"", stderr, oracle)
        wrong_discovery = {**discovery, "discoveryStartedAtUtc": execution["endedAtUtc"]}
        with self.assertRaises(LifecycleError):
            exact_prompt_module._r69h_project_test_support(
                "C34", execution, wrong_discovery, b"", stderr, oracle)

    def test_r69h_test_dependency_closure_refuses_unknown_self_call(self) -> None:
        root = Path(__file__).parents[2]
        oracle = json.loads((root / "tasks/release-2-16/historical-r69q/SOURCE-EXPOSURE-ORACLE-v7.json").read_text())
        roster = root / "tasks/release-2-16/TEST-DEPENDENCY-ROSTER-v1.json"
        adapter_test = root / "tests/adapter_sessions/test_codex_exact_prompt.py"
        process_test = root / "tests/adapter_sessions/test_process_cleanup.py"
        # Full current test files are exposed to this unit check; it must still
        # reject an unresolved local call rather than fail at v9 route admission.
        checked = [{"path": path.relative_to(root).as_posix(), "ranges": [{"symbol": "FULL"}]}
                   for path in (adapter_test, process_test)]
        before = b"        self.assertEqual(len(ranges), 2)\n"
        current = adapter_test.read_bytes()
        self.assertIn(before, current)
        replacements = {str(roster): (root / "tasks/release-2-16/historical-r69q/TEST-DEPENDENCY-ROSTER-v1.json").read_bytes(),
                        str(adapter_test): current.replace(before, b"        self.unknown_local_helper()\n" + before, 1),
                        str(process_test): process_test.read_bytes()}
        with patch.object(source_subject_module, "read_authority_bytes",
                          side_effect=lambda path, **_kwargs: replacements[str(path)]):
            with self.assertRaises(LifecycleError) as caught:
                _r69h_check_test_dependency_closure(root, oracle, checked)
        self.assertIn("unknown self/cls test callee", str(caught.exception))




class CodexLimitedQualificationTests(unittest.TestCase):
    """Opt-in native24; normal unit discovery has no model authority."""

    def _qualify(self, role: str, polarity: str) -> None:
        if not os.environ.get("ALK_R69_FINITE_ADMISSION"):
            self.skipTest("explicit native finite admission is absent")
        from tests.adapter_sessions.codex_limited_native_support import produce_case
        produce_case(Path.cwd(), f"IF69-{role.upper()}-{polarity}", self.id())

    def test_worker_positive(self):
        self._qualify("worker", "POSITIVE")

    def test_worker_prelaunch_refusal(self):
        self._qualify("worker", "PRELAUNCH_REFUSAL")

    def test_worker_started_failure(self):
        self._qualify("worker", "STARTED_FAILURE")

    def test_worker_strong_refusal(self):
        self._qualify("worker", "STRONG_REFUSAL")

    def test_validator_positive(self):
        self._qualify("validator", "POSITIVE")

    def test_validator_prelaunch_refusal(self):
        self._qualify("validator", "PRELAUNCH_REFUSAL")

    def test_validator_started_failure(self):
        self._qualify("validator", "STARTED_FAILURE")

    def test_validator_strong_refusal(self):
        self._qualify("validator", "STRONG_REFUSAL")

    def test_auditor_positive(self):
        self._qualify("auditor", "POSITIVE")

    def test_auditor_prelaunch_refusal(self):
        self._qualify("auditor", "PRELAUNCH_REFUSAL")

    def test_auditor_started_failure(self):
        self._qualify("auditor", "STARTED_FAILURE")

    def test_auditor_strong_refusal(self):
        self._qualify("auditor", "STRONG_REFUSAL")

    def test_retry_positive(self):
        self._qualify("retry", "POSITIVE")

    def test_retry_prelaunch_refusal(self):
        self._qualify("retry", "PRELAUNCH_REFUSAL")

    def test_retry_started_failure(self):
        self._qualify("retry", "STARTED_FAILURE")

    def test_retry_strong_refusal(self):
        self._qualify("retry", "STRONG_REFUSAL")

    def test_coordinator_positive(self):
        self._qualify("coordinator", "POSITIVE")

    def test_coordinator_prelaunch_refusal(self):
        self._qualify("coordinator", "PRELAUNCH_REFUSAL")

    def test_coordinator_started_failure(self):
        self._qualify("coordinator", "STARTED_FAILURE")

    def test_coordinator_strong_refusal(self):
        self._qualify("coordinator", "STRONG_REFUSAL")

    def test_closing_positive(self):
        self._qualify("closing", "POSITIVE")

    def test_closing_prelaunch_refusal(self):
        self._qualify("closing", "PRELAUNCH_REFUSAL")

    def test_closing_started_failure(self):
        self._qualify("closing", "STARTED_FAILURE")

    def test_closing_strong_refusal(self):
        self._qualify("closing", "STRONG_REFUSAL")


if __name__ == "__main__":
    unittest.main()
