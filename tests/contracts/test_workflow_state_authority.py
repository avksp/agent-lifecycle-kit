"""Lower reader and journal data-candidate proof, without host qualification."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.accounting.workflow_authority_store import (
    prepare_legacy_adoption_candidate,
    validate_legacy_adoption_history,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.workflow_state_authority import (
    decode_workflow_authority,
    read_workflow_authority,
    validate_workflow_authority,
    workflow_authority_operation,
)
from agent_lifecycle.contracts.workflow_storage import persist_storage, prepare_storage
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from tests.accounting import test_workflow_store_recovery as journal_fixtures
from tests.workflow.test_state_storage import state_fixture


def authority_fixture(root: Path) -> tuple[Path, dict]:
    state = state_fixture()
    state.update(stateRevision=1, phase="RUNNING", eventLog="events.jsonl")
    prepared = prepare_storage(state, storage_root="state.json.storage")
    persist_storage(root, prepared)
    path = root / "state.json"
    path.write_bytes(canonical_bytes(prepared.state) + b"\n")
    return path, prepared.state


class WorkflowStateAuthorityTests(unittest.TestCase):
    def test_missing_authority_needs_explicit_creation_root_and_keeps_one_lifetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            with workflow_authority_operation(path, allow_missing=True) as missing:
                self.assertIsNone(missing)
                self.assertIsNone(StorageOperation.current())
            with self.assertRaises(FileNotFoundError), workflow_authority_operation(path, creation_root=root):
                self.fail("A root alone must not allow a missing state")
            with workflow_authority_operation(path, allow_missing=True, creation_root=root) as operation:
                self.assertIsNotNone(operation)
                lifetime = (operation.started, operation.deadline)
                with workflow_authority_operation(path, allow_missing=True, creation_root=root) as nested:
                    self.assertIs(nested, operation)
                    self.assertEqual((nested.started, nested.deadline), lifetime)
                other = root / "other"
                other.mkdir()
                with (
                    self.assertRaises(LifecycleError),
                    workflow_authority_operation(path, allow_missing=True, creation_root=other),
                ):
                    self.fail("A nested creator must not select a different root")
            self.assertIsNone(StorageOperation.current())
            with self.assertRaises(LifecycleError):
                operation.check()
            self.assertFalse(path.exists())

    def test_lower_reader_retains_compact_identity_and_validates_unselected_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            self.assertEqual(read_workflow_authority(path), state)
            self.assertEqual(canonical_digest(read_workflow_authority(path)), canonical_digest(state))
            reference = state["priorSnapshots"][0]
            (root / state["storage"]["root"] / reference["path"]).unlink()
            with self.assertRaises(LifecycleError):
                read_workflow_authority(path)

    def test_v5_decode_requires_explicit_root_path_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            for kwargs in ({}, {"root": root}, {"root": root, "state_path": path}):
                with self.subTest(kwargs=kwargs), self.assertRaises(LifecycleError) as raised:
                    validate_workflow_authority(state, **kwargs)
                self.assertEqual(raised.exception.code, "workflow-storage-context-required")
            with StorageOperation(root, state_path=path) as operation:
                self.assertEqual(
                    decode_workflow_authority(path.read_bytes(), root=root, state_path=path, operation=operation),
                    state,
                )
            with self.assertRaises(LifecycleError):
                validate_legacy_adoption_history(state, [])

    def test_reader_refuses_wrong_root_and_noncanonical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            with StorageOperation(root, state_path=path) as operation:
                with self.assertRaises(LifecycleError):
                    decode_workflow_authority(path.read_bytes()[:-1], root=root, state_path=path, operation=operation)
                changed = deepcopy(state)
                changed["storage"]["root"] = "other.storage"
                with self.assertRaises(LifecycleError):
                    validate_workflow_authority(changed, root=root, state_path=path, operation=operation)

    def test_v5_journal_candidate_keeps_exact_raw_ref_and_compact_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adoption, selection = journal_fixtures.LegacyAdoptionHistoryTests._candidate_fixture(root)
            import json

            path = root / "state.json"
            state = json.loads(path.read_bytes())
            snapshot = deepcopy(state)
            snapshot["financialRole"] = "HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING"
            state["priorSnapshots"] = [snapshot]
            prepared = prepare_storage(state, storage_root="state.json.storage")
            persist_storage(root, prepared)
            raw = canonical_bytes(prepared.state) + b"\n"
            path.write_bytes(raw)
            adoption["legacyStateRef"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            candidate = prepare_legacy_adoption_candidate(
                adoption, selection, artifact_root=root, observed_at="2026-04-01T00:00:00.000000Z"
            )
            self.assertEqual(candidate["stateDigest"], canonical_digest(prepared.state))
            self.assertFalse(candidate["nativePermissionGranted"])
            reference = prepared.state["priorSnapshots"][0]
            (root / prepared.state["storage"]["root"] / reference["path"]).write_bytes(b"{}\n")
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-04-01T00:00:00.000000Z"
                )
