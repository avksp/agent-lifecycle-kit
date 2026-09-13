"""Authority journal mutations must fail before native workflow state changes."""

from __future__ import annotations

import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.authority_io import resolve_authority_anchor
from agent_lifecycle.workflow import artifacts
from agent_lifecycle.workflow.artifacts import artifact_identity, require_artifact_identity
from agent_lifecycle.workflow.continuation_batch import _events_by_operation
from agent_lifecycle.workflow.events import read_events
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from agent_lifecycle.workflow.run_transitions import block_run
from agent_lifecycle.workflow.state import load_state, write_state_replace


class WorkflowEventBoundaryTests(unittest.TestCase):
    def test_current_and_archived_identity_require_exact_canonical_lf_bytes(self) -> None:
        value = {"value": 1}
        canonical = canonical_bytes(value) + b"\n"
        for role in ("current", "archive"):
            for case, data in (
                ("valid", canonical),
                ("same-size-content", canonical.replace(b"1", b"2")),
                ("missing-lf", canonical[:-1]),
                ("crlf", canonical[:-1] + b"\r\n"),
                ("trailing-space", canonical[:-1] + b" \n"),
                ("duplicate", b'{"value":1,"value":1}\n'),
                ("digest-mismatch", canonical),
                ("size-mismatch", canonical),
            ):
                with self.subTest(role=role, case=case), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    path = root / "result.json"
                    path.write_bytes(data)
                    identity = {"path": path.name, "sha256": canonical_digest(value), "bytes": len(data)}
                    expected_value = value
                    if case == "digest-mismatch":
                        identity["sha256"] = "0" * 64
                        expected_value = {"value": 2}
                    elif case == "size-mismatch":
                        identity["bytes"] += 1
                        if role == "current":
                            continue  # Current identities derive size from the consumed bytes.
                    if case == "valid":
                        self.assertEqual(artifact_identity(root, path.name, value), identity)
                        self.assertEqual(require_artifact_identity(root, identity, label="archive"), value)
                    else:
                        with self.assertRaises(LifecycleError) as raised:
                            if role == "current":
                                artifact_identity(root, path.name, expected_value)
                            else:
                                require_artifact_identity(root, identity, label="archive")
                        expected_code = "non-canonical-artifact" if role == "current" else "archived-artifact-changed"
                        if role == "archive" and case == "duplicate":
                            expected_code = "invalid-json"
                        self.assertEqual(raised.exception.code, expected_code)
                    self.assertEqual(path.read_bytes(), data)

    def test_archived_parser_uses_the_same_single_guarded_read_as_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "result.json"
            value = {"value": 1}
            data = canonical_bytes(value) + b"\n"
            changed = data.replace(b"1", b"2")
            path.write_bytes(data)
            identity = {"path": path.name, "sha256": canonical_digest(value), "bytes": len(data)}
            original_open = authority_io._Directory.open_child
            original_parse = artifacts.load_json_object
            opened = []
            consumed = []

            def observe(parent, name):
                opened.append(name)
                return original_open(parent, name)

            def replace_before_parse(raw, *, label):
                consumed.append(raw)
                path.write_bytes(changed)
                return original_parse(raw, label=label)

            with (
                patch.object(authority_io._Directory, "open_child", observe),
                patch.object(artifacts, "load_json_object", replace_before_parse),
            ):
                self.assertEqual(require_artifact_identity(root, identity, label="archive"), value)
            self.assertEqual(opened, [path.name])
            self.assertEqual(consumed, [data])
            self.assertEqual(path.read_bytes(), changed)
            with self.assertRaises(LifecycleError) as raised:
                require_artifact_identity(root, identity, label="archive")
            self.assertEqual(raised.exception.code, "archived-artifact-changed")

    def test_current_and_archived_identity_reject_same_size_replacement_and_links(self) -> None:
        for role in ("current", "archive"):
            for change in ("replace", "leaf-link", "parent-link"):
                with self.subTest(role=role, change=change), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    folder = root / "attempt-1"
                    folder.mkdir()
                    path = folder / "result.json"
                    value = {"value": 1}
                    data = canonical_bytes(value) + b"\n"
                    path.write_bytes(data)
                    replacement = folder / "replacement.json"
                    replacement.write_bytes(data.replace(b"1", b"2"))
                    if change == "leaf-link":
                        path.unlink()
                        path.symlink_to(replacement)
                    elif change == "parent-link":
                        link = root / "linked"
                        link.symlink_to(folder, target_is_directory=True)
                        path = link / path.name
                    identity = {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": canonical_digest(value),
                        "bytes": len(data),
                    }
                    original_open = authority_io._Directory.open_child
                    touched = []

                    def substitute(
                        parent,
                        name,
                        *,
                        change=change,
                        path=path,
                        replacement=replacement,
                        touched=touched,
                        original_open=original_open,
                    ):
                        if change == "replace" and name == path.name:
                            parent.replace_child(replacement.name, name)
                            touched.append(name)
                        return original_open(parent, name)

                    with (
                        patch.object(authority_io._Directory, "open_child", substitute),
                        self.assertRaises(LifecycleError) as raised,
                    ):
                        if role == "current":
                            artifact_identity(root, identity["path"], value)
                        else:
                            require_artifact_identity(root, identity, label="archive")
                    if change == "replace":
                        self.assertEqual(raised.exception.code, "authority-input-changed")
                        self.assertEqual(touched, [path.name])

    def test_native_artifact_paths_reject_traversal_drive_and_unc_forms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "../outside",
                "C:result.json",
                "C:/result.json",
                "//server/share/result",
                "\\\\server\\share\\result",
            ):
                with self.subTest(name=name), self.assertRaises(LifecycleError):
                    artifact_identity(root, name, {"value": 1})
                self.assertEqual(list(root.iterdir()), [])

    def test_native_state_and_artifact_substitution_cannot_supply_identity(self) -> None:
        for role in ("state", "artifact"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "document.json"
                if role == "state":
                    initialize_workflow_state(path, run_id="run", package_id="package")
                else:
                    path.write_bytes(canonical_bytes({"value": 1}) + b"\n")
                replacement = root / "replacement"
                substituted = path.read_bytes() + b" "
                replacement.write_bytes(substituted)
                original = authority_io._Directory.open_child
                touched = []

                def substitute(
                    parent, name, *, replacement=replacement, path=path, touched=touched, original=original
                ):
                    parent.replace_child(replacement.name, path.name)
                    touched.append(name)
                    return original(parent, name)

                with (
                    patch.object(authority_io._Directory, "open_child", substitute),
                    self.assertRaises(LifecycleError) as raised,
                ):
                    if role == "state":
                        load_state(path)
                    else:
                        artifact_identity(root, "document.json", {"value": 1})
                self.assertEqual(raised.exception.code, "authority-input-changed")
                self.assertEqual(touched, ["document.json"])
                self.assertEqual(path.read_bytes(), substituted)
                self.assertFalse((root / "events.jsonl").exists())

    def test_native_journal_symlinks_block_transition_before_any_state_write(self) -> None:
        for parent_link in (False, True):
            with self.subTest(parent_link=parent_link), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "run.state.json"
                initialize_workflow_state(
                    state_path,
                    run_id="run",
                    package_id="package",
                    event_log="link/events.jsonl" if parent_link else "events.jsonl",
                )
                outside = root / "outside"
                outside.mkdir()
                target = outside / "events.jsonl"
                target.write_bytes(b'{"stateRevision":1}\n')
                link = root / ("link" if parent_link else "events.jsonl")
                link.symlink_to(outside if parent_link else target, target_is_directory=parent_link)
                before = state_path.read_bytes()
                with self.assertRaises(LifecycleError):
                    block_run(
                        state_path,
                        operation_id="no-write",
                        expected_revision=1,
                        blocker_code="test",
                        reason="reject native journal symlink",
                    )
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(target.read_bytes(), b'{"stateRevision":1}\n')
                self.assertTrue(link.is_symlink())

    def test_native_state_symlinks_reject_read_and_replacement(self) -> None:
        for parent_link in (False, True):
            with self.subTest(parent_link=parent_link), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.mkdir()
                target = outside / "run.state.json"
                initialize_workflow_state(target, run_id="run", package_id="package")
                state = load_state(target)
                before = target.read_bytes()
                link = root / "link"
                link.symlink_to(outside if parent_link else target, target_is_directory=parent_link)
                path = link / "run.state.json" if parent_link else link
                with self.assertRaises(LifecycleError):
                    load_state(path)
                with self.assertRaises(LifecycleError):
                    write_state_replace(path, state)
                self.assertEqual(target.read_bytes(), before)
                self.assertTrue(link.is_symlink())
                self.assertFalse((outside / "events.jsonl").exists())

    def test_native_artifact_symlinks_cannot_supply_canonical_identity(self) -> None:
        for parent_link in (False, True):
            with self.subTest(parent_link=parent_link), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outside = root / "outside"
                outside.mkdir()
                value = {"value": 1}
                data = canonical_bytes(value) + b"\n"
                target = outside / "result.json"
                target.write_bytes(data)
                link = root / "link"
                link.symlink_to(outside if parent_link else target, target_is_directory=parent_link)
                with self.assertRaises(LifecycleError):
                    artifact_identity(root, "link/result.json" if parent_link else "link", value)
                self.assertEqual(target.read_bytes(), data)
                self.assertTrue(link.is_symlink())

    def test_native_journal_substitution_blocks_state_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "run.state.json"
            initialize_workflow_state(state_path, run_id="run", package_id="package")
            journal = root / "events.jsonl"
            journal.write_bytes(b'{"stateRevision":1}\n')
            replacement = root / "replacement"
            replacement.write_bytes(b'{"stateRevision":1,"substituted":true}\n')
            before = state_path.read_bytes()
            original = authority_io._Directory.open_child
            substitutions = []

            def substitute(parent, name):
                if name == "events.jsonl":
                    parent.replace_child(replacement.name, journal.name)
                    substitutions.append(name)
                return original(parent, name)

            with (
                patch.object(authority_io._Directory, "open_child", substitute),
                self.assertRaises(LifecycleError) as raised,
            ):
                block_run(
                    state_path,
                    operation_id="no-write",
                    expected_revision=1,
                    blocker_code="test",
                    reason="reject replaced journal",
                )
            self.assertEqual(raised.exception.code, "authority-input-changed")
            self.assertEqual(substitutions, ["events.jsonl"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(journal.read_bytes(), b'{"stateRevision":1,"substituted":true}\n')

    def test_unreadable_journal_keeps_legacy_error_and_state_unchanged(self) -> None:
        from agent_lifecycle.contracts import authority_io

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "run.state.json"
            initialize_workflow_state(state_path, run_id="run", package_id="package")
            journal = root / "events.jsonl"
            journal.write_bytes(b'{"stateRevision":1}\n')
            before = state_path.read_bytes()
            original = authority_io._Directory.open_child

            def unavailable(parent, name):
                if name == "events.jsonl":
                    raise PermissionError("private payload must not escape")
                return original(parent, name)

            with (
                patch.object(authority_io._Directory, "open_child", unavailable),
                self.assertRaises(LifecycleError) as raised,
            ):
                block_run(state_path, operation_id="no-write", expected_revision=1, blocker_code="test", reason="test")
            self.assertEqual(raised.exception.code, "invalid-workflow-event-log")
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(journal.read_bytes(), b'{"stateRevision":1}\n')
            self.assertNotIn("private payload", str(raised.exception))

    def test_duplicate_members_cannot_hide_an_ahead_event_revision(self) -> None:
        for record, code in (
            (b'{"operationId":"prior","stateRevision":9}\n', "workflow-split-brain"),
            (b'{"operationId":"prior","stateRevision":9,"stateRevision":1}\n', "invalid-json"),
            (b'{"operationId":"prior","payload":{"x":1,"x":2},"stateRevision":1}\n', "invalid-json"),
            (b'{"operationId":"prior","stateRevision":9,"stateRevi\\u0073ion":1}\n', "invalid-json"),
            (b"{malformed\n", "invalid-workflow-event-log"),
        ):
            with self.subTest(code=code, record=record), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "run.state.json"
                initialize_workflow_state(state_path, run_id="run", package_id="package")
                before = state_path.read_bytes()
                journal = root / "events.jsonl"
                journal.write_bytes(record)
                with self.assertRaises(LifecycleError) as raised:
                    block_run(
                        state_path,
                        operation_id="must-not-commit",
                        expected_revision=1,
                        blocker_code="test",
                        reason="negative journal test",
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(journal.read_bytes(), record)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(str(journal), rendered)
                self.assertNotIn(record.decode("utf-8").strip(), rendered)

    def test_batch_replay_uses_the_same_duplicate_member_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = b'{"operationId":"first","operationId":"second","stateRevision":1}\n'
            (root / "events.jsonl").write_bytes(record)
            with self.assertRaises(LifecycleError) as raised:
                _events_by_operation(root / "run.state.json", {"packageRoot": ".", "eventLog": "events.jsonl"})
            self.assertEqual(raised.exception.code, "invalid-json")
            self.assertEqual((root / "events.jsonl").read_bytes(), record)

    def test_journal_is_streamed_without_a_whole_log_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            row = b'{"operationId":"prior","stateRevision":1,"padding":"' + b"x" * 1000 + b'"}\n'
            path.write_bytes(row * 1100)
            self.assertGreater(path.stat().st_size, 1_048_576)
            self.assertEqual(sum(1 for _ in read_events(path)), 1100)

    def test_parent_layout_anchor_is_allowed_only_inside_the_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "work" / "release" / "run.state.json"
            with patch.object(Path, "cwd", return_value=root):
                self.assertEqual(resolve_authority_anchor(state_path, "../.."), root)
                with self.assertRaises(LifecycleError) as raised:
                    resolve_authority_anchor(state_path, "../../..")
            self.assertEqual(raised.exception.code, "authority-path-outside-root")


if __name__ == "__main__":
    unittest.main()
