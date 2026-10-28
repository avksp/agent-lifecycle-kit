"""Real native consumers refuse damaged reachable history before mutation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import canonical_bytes, canonical_digest
from agent_lifecycle.workflow.initialization import migrate_workflow_state
from tests.workflow.test_state_storage import state_fixture

RUNTIME = Path(__file__).resolve().parents[2]


def observe(value):
    target = os.environ.get("WS03_OBSERVATIONS")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")


def native(root, command, *options, expected=0):
    argv = [sys.executable, "-B", "-m", "agent_lifecycle", "workflow", command, *map(str, options)]
    started = time.monotonic()
    child = subprocess.run(
        argv,
        cwd=root,
        env=dict(os.environ, PYTHONPATH=str(RUNTIME / "src")),
        capture_output=True,
        text=True,
        timeout=120,
    )
    observe(
        {
            "kind": "native-cli",
            "argv": argv,
            "exitCode": child.returncode,
            "expectedExit": expected,
            "wallSeconds": time.monotonic() - started,
            "stdout": child.stdout,
            "stderr": child.stderr,
        }
    )
    if child.returncode != expected:
        raise AssertionError(child.stdout + child.stderr)
    return child


def small_state(root):
    state = state_fixture()
    # This leaf is reachable only through old, currently unselected history.
    state["priorSnapshots"][0]["tasks"][0]["ownershipReceipt"]["historicalOnly"] = True
    state.update(
        stateRevision=1,
        phase="RUNNING",
        eventLog="events.jsonl",
        packageRoot=".",
        authorization={"required": False, "granted": True},
    )
    path = root / "state.json"
    path.write_bytes(canonical_bytes(state) + b"\n")
    return path


class NativeHistoryFailureTests(unittest.TestCase):
    def test_real_native_consumer_rejects_complete_negative_matrix(self):
        variants = (
            "missing",
            "tamper",
            "truncated",
            "oversized",
            "noncanonical",
            "bytes",
            "sha",
            "kind",
            "lineage",
            "count",
            "cycle",
            "alias",
            "traversal",
            "symlink",
            "reparse-spelling",
        )
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                path = small_state(root)
                migrate_workflow_state(
                    path,
                    operation_id="migrate",
                    expected_revision=1,
                    source_revision="source",
                    target_schema="agent-workflow-state.v5",
                )
                state = json.loads(path.read_bytes())
                snapshot = state["priorSnapshots"][0]
                snapshot_path = root / state["storage"]["root"] / snapshot["path"]
                body = json.loads(snapshot_path.read_bytes())
                reference = body["tasks"][0]["ownershipReceipt"]
                leaf = root / state["storage"]["root"] / reference["path"]
                if variant in {"missing", "tamper", "truncated", "oversized", "noncanonical", "symlink"}:
                    data = leaf.read_bytes()
                    if variant == "missing":
                        leaf.unlink()
                    elif variant == "symlink":
                        outside = root / "outside.json"
                        outside.write_bytes(data)
                        leaf.unlink()
                        leaf.symlink_to(outside)
                    else:
                        leaf.write_bytes(
                            {
                                "tamper": data.replace(b"PASS", b"FAIL"),
                                "truncated": data[:-3],
                                "oversized": b"x" * 1_048_577,
                                "noncanonical": data + b" ",
                            }[variant]
                        )
                else:
                    if variant == "bytes":
                        reference["bytes"] += 1
                    elif variant == "sha":
                        reference["sha256"] = "f" * 64
                        reference["path"] = "objects/" + "f" * 64 + ".json"
                    elif variant == "kind":
                        reference["kind"] = "result-change-set-evidence"
                    elif variant == "lineage":
                        reference["lineage"]["taskId"] = "OTHER"
                    elif variant == "count":
                        reference["itemCounts"]["entries"] += 1
                    elif variant == "cycle":
                        body["tasks"][0]["ownershipReceipt"] = deepcopy(snapshot)
                    else:
                        reference["path"] = {
                            "alias": "objects/./" + leaf.name,
                            "traversal": "../" + leaf.name,
                            "reparse-spelling": "objects\\" + leaf.name,
                        }[variant]
                    data = canonical_bytes(body) + b"\n"
                    snapshot["sha256"] = canonical_digest(body)
                    snapshot["bytes"] = len(data)
                    snapshot["path"] = "objects/" + snapshot["sha256"] + ".json"
                    (root / state["storage"]["root"] / snapshot["path"]).write_bytes(data)
                    path.write_bytes(canonical_bytes(state) + b"\n")
                before = path.read_bytes(), (root / "events.jsonl").read_bytes()
                child = native(
                    root,
                    "task-start",
                    "--state",
                    path,
                    "--task",
                    "T",
                    "--operation-id",
                    "must-refuse",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--reason",
                    "negative fixture",
                    expected=2,
                )
                code = json.loads(child.stdout)["code"]
                if variant in {"truncated", "oversized"}:
                    self.assertEqual(
                        code, {"truncated": "invalid-json", "oversized": "authority-input-too-large"}[variant]
                    )
                else:
                    self.assertTrue(code.startswith("workflow-storage"), code)
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)
                observe(
                    {
                        "kind": "negative-history",
                        "variant": variant,
                        "coldUnselectedHistory": True,
                        "expected": "refusal without authority write",
                        "actual": "refused",
                        "stateSha256": hashlib.sha256(before[0]).hexdigest(),
                    }
                )

    def test_two_real_readers_and_serialized_competing_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = small_state(root)

            def migrate():
                argv = [
                    sys.executable,
                    "-B",
                    "-m",
                    "agent_lifecycle",
                    "workflow",
                    "state-migrate",
                    "--state",
                    str(path),
                    "--target-schema",
                    "agent-workflow-state.v5",
                    "--operation-id",
                    "competing-migrate",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                ]
                child = subprocess.run(
                    argv,
                    cwd=root,
                    env=dict(os.environ, PYTHONPATH=str(RUNTIME / "src")),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                observe(
                    {
                        "kind": "competing-native-writer",
                        "argv": argv,
                        "exitCode": child.returncode,
                        "stdout": child.stdout,
                        "stderr": child.stderr,
                    }
                )
                return child.returncode, child.stdout

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: migrate(), range(2)))
            self.assertEqual(sorted(code for code, _ in outcomes), [0, 2])
            refused = next(output for code, output in outcomes if code == 2)
            self.assertEqual(json.loads(refused)["code"], "state-revision-mismatch")
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            with ThreadPoolExecutor(max_workers=2) as pool:
                readers = list(pool.map(lambda _: native(root, "status", "--state", path), range(2)))
            self.assertEqual(readers[0].stdout, readers[1].stdout)
            self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)

    @unittest.skipUnless(os.name == "nt", "Native Windows FSCTL reparse proof requires Windows")
    def test_native_reparse_storage_directory_refuses_without_redirected_write(self):
        from tests.contracts.test_authority_io import _set_native_mount_point

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = small_state(root)
            migrate_workflow_state(
                path,
                operation_id="migrate",
                expected_revision=1,
                source_revision="source",
                target_schema="agent-workflow-state.v5",
            )
            state = json.loads(path.read_bytes())
            directory = root / state["storage"]["root"] / "objects"
            outside = root / "outside"
            directory.rename(outside)
            directory.mkdir()
            protected = {p.name: p.read_bytes() for p in outside.iterdir()}
            before = path.read_bytes(), (root / "events.jsonl").read_bytes()
            try:
                _set_native_mount_point(directory, outside)
                native(
                    root,
                    "task-start",
                    "--state",
                    path,
                    "--task",
                    "T",
                    "--operation-id",
                    "must-refuse",
                    "--expected-revision",
                    2,
                    "--source-revision",
                    "source",
                    "--reason",
                    "fixture-only native reparse refusal",
                    expected=2,
                )
                self.assertEqual({p.name: p.read_bytes() for p in outside.iterdir()}, protected)
                self.assertEqual((path.read_bytes(), (root / "events.jsonl").read_bytes()), before)
            finally:
                if directory.lstat().st_file_attributes & 0x400:
                    directory.rmdir()


if __name__ == "__main__":
    unittest.main()
