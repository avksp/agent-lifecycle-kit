"""Closed portable storage reference contracts."""

from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.workflow_storage import prepare_storage
from agent_lifecycle.contracts.workflow_storage_schemas import (
    MAX_REACHABLE_BYTES,
    MAX_REACHABLE_OBJECTS,
    MAX_RETAINED_BYTES,
    REFERENCE_VERSION,
    validate_storage_metadata,
    validate_storage_reference,
)


class StorageSchemaTests(unittest.TestCase):
    def reference(self):
        from tests.workflow.test_state_storage import state_fixture

        prepared = prepare_storage(state_fixture(), storage_root="store")
        return prepared.state["tasks"][0]["ownershipReceipt"]

    def initial_reference(self):
        return {
            "schemaVersion": REFERENCE_VERSION,
            "kind": "plan-snapshot",
            "sha256": "1" * 64,
            "path": f"objects/{'1' * 64}.json",
            "bytes": 1,
            "lineage": {
                "runId": "run",
                "packageId": "package",
                "planRevision": 0,
                "planDigest": "",
                "sourceRevision": "",
            },
            "itemCounts": {"tasks": 0},
        }

    def test_initial_and_fully_bound_revision_zero_remain_distinct(self):
        reference = self.initial_reference()
        self.assertEqual(validate_storage_reference(reference), reference)
        bound = deepcopy(reference)
        bound["lineage"].update(planDigest="a" * 64, sourceRevision="source")
        bound["itemCounts"]["tasks"] = 1
        self.assertEqual(validate_storage_reference(bound), bound)

    def test_initial_lineage_exception_is_exact_and_snapshot_only(self):
        for key, value in (
            ("planRevision", False),
            ("planRevision", True),
            ("planRevision", 0.0),
            ("planRevision", 1),
            ("planRevision", -1),
            ("planDigest", "a" * 64),
            ("sourceRevision", "source"),
            ("runId", ""),
            ("packageId", ""),
        ):
            reference = self.initial_reference()
            reference["lineage"][key] = value
            with (
                self.subTest(key=key, value=value),
                self.assertRaises(LifecycleError),
            ):
                validate_storage_reference(reference)
        for kind in ("ownership-receipt", "result-change-set-evidence"):
            reference = self.initial_reference()
            reference["kind"] = kind
            reference["lineage"].update(taskId="T", attempt=1)
            with self.subTest(kind=kind), self.assertRaises(LifecycleError):
                validate_storage_reference(reference)

    def test_initial_reference_keeps_hash_size_header_and_count_guards(self):
        for field, key, value in (
            (None, "sha256", ""),
            (None, "path", "objects/../other.json"),
            (None, "bytes", 1_048_577),
            ("itemCounts", "tasks", 1),
            ("itemCounts", "tasks", False),
            ("lineage", "extra", "unexpected"),
        ):
            reference = self.initial_reference()
            target = reference if field is None else reference[field]
            target[key] = value
            with (
                self.subTest(field=field, key=key, value=value),
                self.assertRaises(LifecycleError),
            ):
                validate_storage_reference(reference)
        reference = self.initial_reference()
        reference["itemCounts"] = {}
        with self.assertRaises(LifecycleError):
            validate_storage_reference(reference)

    def test_reference_is_closed_and_has_exact_portable_digest_path(self):
        reference = self.reference()
        self.assertEqual(validate_storage_reference(reference), reference)
        for key, value in (
            ("path", "../outside.json"),
            ("path", "objects/CON.json"),
            ("path", reference["path"].upper()),
            ("bytes", True),
            ("bytes", 1_048_577),
            ("kind", "other"),
            ("sha256", "A" * 64),
            ("extra", 1),
        ):
            changed = {**reference, key: value}
            with (
                self.subTest(
                    key=key,
                    value=value,
                ),
                self.assertRaises(LifecycleError),
            ):
                validate_storage_reference(changed)

    def test_lineage_and_counts_reject_ambiguous_types(self):
        for field, key, value in (
            ("lineage", "attempt", True),
            ("lineage", "taskId", ""),
            ("lineage", "planDigest", "wrong"),
            ("itemCounts", "entries", -1),
            ("itemCounts", "entries", True),
        ):
            reference = deepcopy(self.reference())
            reference[field][key] = value
            with (
                self.subTest(
                    field=field,
                    key=key,
                ),
                self.assertRaises(LifecycleError),
            ):
                validate_storage_reference(reference)

    def test_metadata_rejects_portable_aliases_and_traversal(self):
        for root in ("../store", "/store", "a/../store", "a\\b", "NUL", "a."):
            with self.subTest(root=root), self.assertRaises(LifecycleError):
                validate_storage_metadata(
                    {
                        "schemaVersion": "agent-workflow-storage.v1",
                        "root": root,
                    }
                )

    def test_declared_hard_limits_are_not_relaxed(self):
        self.assertEqual(MAX_REACHABLE_OBJECTS, 4096)
        self.assertEqual(MAX_REACHABLE_BYTES, 64 * 1024 * 1024)
        self.assertEqual(MAX_RETAINED_BYTES, 128 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
