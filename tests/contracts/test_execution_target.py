"""Actual filesystem observations, independent of workflow implementation."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.execution_target import (
    discard_created_output,
    inspect_execution_target,
    require_execution_target_digest,
)


def _inspect(root: Path, outputs: list[dict] | None = None) -> dict:
    return inspect_execution_target(
        root,
        source_identity={"revision": "unit-fixture"},
        plan_identity={"packageId": "fixture"},
        source_paths=["source.py"],
        outputs=outputs or [{"path": "state.json"}],
        state_path="state.json",
        event_log="events.jsonl",
        stage="PLANNING",
    )


class ExecutionTargetTests(unittest.TestCase):
    def test_read_only_binding_identifies_actual_checkout_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            root, other = Path(first), Path(second)
            for directory in (root, other):
                (directory / "source.py").write_bytes(b"original")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            observed = _inspect(root)
            require_execution_target_digest(observed["bindingDigest"], _inspect(root))
            self.assertFalse(observed["authorityClaimed"])
            self.assertFalse(observed["productionPromotionClaimed"])
            self.assertNotEqual(observed["targetId"], _inspect(other)["targetId"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            (root / "source.py").write_bytes(b"changed")
            with self.assertRaises(LifecycleError) as stale:
                require_execution_target_digest(observed["bindingDigest"], _inspect(root))
            self.assertEqual(stale.exception.code, "execution-target-changed")

    def test_complete_output_inventory_precedes_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "last.json").write_bytes(b"other writer")
            with self.assertRaises(LifecycleError) as conflict:
                _inspect(root, [{"path": "first.json"}, {"path": "last.json"}])
            destinations = conflict.exception.details["destinations"]
            self.assertEqual([d["disposition"] for d in destinations], ["ABSENT", "INCOMPATIBLE"])
            self.assertFalse((root / "first.json").exists())
            self.assertEqual((root / "last.json").read_bytes(), b"other writer")

    def test_exact_output_reuse_is_explicit_and_wrong_bytes_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packet.json").write_bytes(b"packet")
            spec = {
                "path": "packet.json",
                "expectedSha256": hashlib.sha256(b"packet").hexdigest(),
                "expectedBytes": 6,
                "allowExisting": True,
            }
            self.assertEqual(_inspect(root, [spec])["outputs"][0]["disposition"], "EXACT_MATCH")
            for change in ({"allowExisting": False}, {"expectedSha256": "0" * 64}):
                with self.subTest(change=change), self.assertRaises(LifecycleError):
                    _inspect(root, [{**spec, **change}])

    def test_output_alias_and_source_symlink_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "alias").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(LifecycleError) as alias:
                _inspect(root, [{"path": "alias/new.json"}])
            self.assertEqual(alias.exception.code, "execution-target-output-conflict")
            self.assertFalse((Path(outside) / "new.json").exists())
            (root / "source.py").symlink_to(Path(outside) / "source.py")
            with self.assertRaises(LifecycleError):
                _inspect(root)

    def test_rollback_never_deletes_changed_writer_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "owned.json"
            target.write_bytes(b"competitor")
            self.assertFalse(discard_created_output(root, target.name, [b"ours"]))
            self.assertEqual(target.read_bytes(), b"competitor")
            target.write_bytes(b"ou")
            self.assertTrue(discard_created_output(root, target.name, [b"ours"], allow_partial=True))
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
