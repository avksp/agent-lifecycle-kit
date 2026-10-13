"""Real local CLI/journal integration; no installed scheduler or native host claim."""

from __future__ import annotations

import json
import time
import unittest
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from agent_lifecycle.accounting.contracts import RunClosure, canonical
from agent_lifecycle.accounting.journal import Journal, JournalUnavailable
from tests.accounting import test_closing_resources_recovery as retention_fixture
from tests.cli.helpers import _run_cli


class WorkflowMaintenanceTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing authoritative local fixture without running its tests.
        self.fixture = retention_fixture.RawRetentionWitnessTests(methodName="runTest")
        # Only fixture construction uses historical observation times. The CLI
        # always reads real UTC; no production timestamp or clock is rewritten.
        with patch("agent_lifecycle.accounting.journal.datetime", wraps=datetime) as historical:
            historical.now.return_value = datetime.now(UTC) - timedelta(days=33)
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.authority_path = self.f.root / self.f.authority_ref["path"]
        self.f._write(self.f.authority_ref["path"] + ".writer.json", canonical(asdict(self.f.proof)).encode())
        self.f._seal()
        self.deadline = (datetime.now(UTC) + timedelta(seconds=45)).isoformat()

    def _call(self, *extra, sha=None, deadline=None, limit=32):
        return _run_cli([
            "workflow", "maintenance", "--authority", str(self.authority_path),
            "--authority-sha", sha or self.f.authority_ref["sha256"],
            "--candidate-limit", str(limit), "--deadline", deadline or self.deadline, *extra,
        ])

    def _close(self, age_days):
        now = datetime.now(UTC)
        closure = RunClosure("cli-closure", "run", "reportedTokens:fixture:v1",
                             (now - timedelta(days=age_days)).isoformat(),
                             (("run", self.f.j.snapshot("run").journal_revision),), self.f.proof, self.f.proof)
        self.assertEqual(self.f.j.close_run(closure, now.isoformat()).status, "CLOSED")
        return self.f.j.closed_run("run")

    def test_unclosed_and_not_due_runs_keep_every_detail(self):
        for closed in (False, True):
            with self.subTest(closed=closed):
                if closed:
                    self._close(0)
                code, result = self._call()
                self.assertEqual(code, 0)
                self.assertEqual(result["outcomes"][0]["status"], "NOT_DUE" if closed else "RUN_NOT_FULLY_CLOSED")
                self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))
                self.assertEqual(self.f.j.snapshot("run").known_spent, 10)
                self.assertNotIn('"run"', json.dumps(result))

    def test_due_run_removes_raw_and_preserves_financial_summary_and_dedup(self):
        closed = self._close(31)
        code, result = self._call()
        self.assertEqual((code, result["status"], result["outcomes"][0]["status"]), (0, "COMPLETE", "DONE"))
        self.assertTrue(all(not p.exists() for p in self.f.sources["attempt-1"]))
        self.assertEqual(self.f.j.closed_run("run"), closed)
        self.assertEqual(self.f.j.snapshot("run").known_spent, 10)
        self.assertEqual(self.f.j.ingest_usage("run", self.f.original).status, "ALREADY_SETTLED")
        self.assertEqual(self._call()[1]["outcomes"], [])
        self.assertTrue(self.authority_path.is_file())
        self.assertTrue(self.authority_path.with_name(self.authority_path.name + ".writer.json").is_file())

    def test_sql_collected_raw_pending_is_still_selected(self):
        self._close(31)
        self.assertEqual(self.f.j.collect_closed_run("run", datetime.now(UTC).isoformat()).status, "COLLECTED")
        self.assertEqual(self.f.j.events("run"), [])
        code, result = self._call()
        self.assertEqual(code, 0)
        self.assertEqual(result["outcomes"][0]["status"], "DONE")
        self.assertTrue(all(not p.exists() for p in self.f.sources["attempt-1"]))

    def test_overdue_failure_remains_enumerable_and_recovers(self):
        self._close(32)
        with patch.object(Journal, "collect_raw_run", side_effect=JournalUnavailable("injected local refusal")):
            code, result = self._call()
        self.assertEqual((code, result["status"]), (0, "PARTIAL"))
        self.assertEqual(result["outcomes"][0]["after"], ["OVERDUE"])
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))
        code, recovered = self._call()
        self.assertEqual(code, 0)
        self.assertEqual(recovered["outcomes"][0]["status"], "DONE")

    def test_wrong_authority_or_writer_refuses_before_writable_open(self):
        before = self.f.journal_path.read_bytes()
        with patch("agent_lifecycle.accounting.host_bridge._MaintenanceJournal") as opened:
            code, result = self._call(sha="0" * 64)
            self.assertEqual(code, 2)
            self.assertEqual(result["code"], "retention-authority-refused")
            opened.assert_not_called()
            self.f._write(self.f.authority_ref["path"] + ".writer.json", b'{"ref":"other","digest":"' + b"0" * 64 + b'"}')
            self.assertEqual(self._call()[0], 2)
            opened.assert_not_called()
        self.assertEqual(self.f.journal_path.read_bytes(), before)
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))

    def test_forbidden_journal_and_root_overrides_refuse(self):
        for flag in ("--journal", "--private-root"):
            with self.subTest(flag=flag):
                code, result = self._call(flag, str(self.f.root / "unrelated"))
                self.assertEqual(code, 2)
                self.assertEqual(result["code"], "retention-override-forbidden")
        self.assertFalse((self.f.root / "unrelated").exists())

    def test_unsupported_filesystem_refuses_before_authority_or_journal_read(self):
        with patch("agent_lifecycle.accounting.host_bridge.os.supports_dir_fd", set()), \
                patch("agent_lifecycle.accounting.host_bridge._open_authority") as opened:
            code, result = self._call()
            self.assertEqual(code, 2)
            self.assertEqual(result["code"], "retention-platform-unsupported")
            opened.assert_not_called()
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))

    def test_expired_deadline_and_invalid_limit_refuse_without_effects(self):
        before = self.f.journal_path.read_bytes()
        self.assertEqual(self._call(deadline=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())[0], 2)
        for limit in (0, 33):
            self.assertEqual(self._call(limit=limit)[0], 2)
        self.assertEqual(self.f.journal_path.read_bytes(), before)

    def test_changed_manifest_and_symlink_authority_refuse_without_effects(self):
        before = self.f.journal_path.read_bytes()
        self.f._write(self.f.manifest["path"], b'{"changed":true}')
        self.assertEqual(self._call()[0], 2)
        self.assertEqual(self.f.journal_path.read_bytes(), before)
        alias = self.f.root / "authority-alias.json"
        alias.symlink_to(self.authority_path)
        with patch.object(self, "authority_path", alias):
            self.assertEqual(self._call()[0], 2)
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))

    def test_preflight_expiry_refuses_before_writable_journal_construction(self):
        before = self.f.journal_path.read_bytes()
        initial = datetime.now(UTC)
        with patch("agent_lifecycle.accounting.host_bridge.datetime", wraps=datetime) as clock, \
                patch("agent_lifecycle.accounting.host_bridge._MaintenanceJournal") as opened:
            clock.now.side_effect = [initial, initial + timedelta(seconds=61)]
            code, result = self._call()
            self.assertEqual(code, 2)
            self.assertEqual(result["code"], "retention-authority-refused")
            opened.assert_not_called()
        self.assertEqual(self.f.journal_path.read_bytes(), before)
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))

    def test_initial_writer_contention_obeys_original_short_deadline(self):
        before = self.f.journal_path.read_bytes()
        with self.f.j._write_admission():
            started = time.monotonic()
            deadline = (datetime.now(UTC) + timedelta(milliseconds=120)).isoformat()
            code, result = self._call(deadline=deadline)
            elapsed = time.monotonic() - started
        self.assertEqual(code, 2)
        self.assertEqual(result["code"], "retention-authority-refused")
        self.assertLess(elapsed, 0.75)
        self.assertEqual(self.f.journal_path.read_bytes(), before)
        self.assertTrue(all(p.exists() for p in self.f.sources["attempt-1"]))


if __name__ == "__main__":
    unittest.main()
