"""Count the entire public capture boundary, including delegated Git work."""

from __future__ import annotations

import ast
import json
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types
import unittest
from contextlib import ExitStack
from itertools import product
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.changesets import snapshot
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.task_transitions import _validate_task_write_scope

BASELINE = "ca4d5c12168c29193db5237b09d6c4b739a7c6d4"
REPOSITORY = Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _fixture(root: Path, count: int) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "ALK snapshot test")
    (root / "src").mkdir()
    for index in range(count):
        (root / f"src/{index:03}.bin").write_bytes(bytes([index % 256, 0, 255]) * 64)
    _git(root, "add", "src")
    _git(root, "commit", "-qm", "fixture")
    baseline = _git(root, "rev-parse", "HEAD")
    for index in range(count):
        (root / f"src/{index:03}.bin").write_bytes(b"changed\0" + bytes([index % 256]) * 64)
    return baseline


def _measure(module, root: Path, baseline: str) -> tuple[dict, dict]:
    children = []
    original = subprocess.Popen

    def counted(argv, *args, **kwargs):
        children.append(list(argv))
        return original(argv, *args, **kwargs)

    tracemalloc.start()
    started = time.perf_counter()
    try:
        with patch.object(subprocess, "Popen", counted):
            try:
                result = module.capture_task_change_set(root, baseline=baseline, write_paths=["src"])
                outcome = {"result": result}
            except LifecycleError as exc:
                outcome = {"errorCode": exc.code}
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return outcome, {"gitChildren": len(children), "argv": children, "wallSeconds": elapsed, "peakPythonBytes": peak}


def _historical_module(stack: ExitStack):
    """Isolate all three unchanged-source dependencies, outside measurement."""
    namespace = "agent_lifecycle._release219_reference"
    stack.enter_context(patch.dict(sys.modules, {namespace: types.ModuleType(namespace)}))
    for name in ("git_io", "git", "snapshot"):
        path = f"src/agent_lifecycle/changesets/{name}.py"
        source = subprocess.run(
            ["git", "show", f"{BASELINE}:{path}"], cwd=REPOSITORY, capture_output=True, check=True
        ).stdout
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in (
                "agent_lifecycle.changesets.git",
                "agent_lifecycle.changesets.git_io",
            ):
                node.module = namespace + "." + node.module.rsplit(".", 1)[1]
        module = types.ModuleType(namespace + "." + name)
        stack.enter_context(patch.dict(sys.modules, {module.__name__: module}))
        exec(compile(tree, path, "exec"), module.__dict__)
    return module


class SnapshotScalingTests(unittest.TestCase):
    def test_rename_and_copy_keep_protected_source_in_authoritative_ownership_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = _fixture(root, 2)
            (root / "src/000.bin").rename(root / "src/renamed.bin")
            (root / "src/copy.bin").write_bytes((root / "src/001.bin").read_bytes())
            observed, measured = _measure(snapshot, root, base)
            self.assertIn("src/000.bin", observed["result"]["allChangedFiles"])
            self.assertIn("src/renamed.bin", observed["result"]["allChangedFiles"])
            self.assertIn("src/copy.bin", observed["result"]["allChangedFiles"])
            self.assertLessEqual(measured["gitChildren"], 8)
            state = {"manifestPath": "plan.json", "writePolicy": {"readOnly": ["src/000.bin"]}}
            task = {"id": "worker", "writes": ["src/renamed.bin", "src/copy.bin", "src/001.bin"]}
            with self.assertRaises(LifecycleError) as refused:
                _validate_task_write_scope(
                    state,
                    task,
                    observed["result"],
                    changed_files=observed["result"]["allChangedFiles"],
                    repository_root=root,
                )
            self.assertEqual(refused.exception.code, "task-ownership-violation")
            self.assertEqual(refused.exception.details["ownership"]["blockers"][0]["path"], "src/000.bin")

    def test_whole_capture_two_twenty_sixty_files_uses_at_most_eight_children(self) -> None:
        measurements = []
        for count in (2, 20, 60):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                base = _fixture(root, count)
                observed, measured = _measure(snapshot, root, base)
                self.assertIn("result", observed)
                self.assertEqual(observed["result"]["changedFileCount"], count)
                self.assertLessEqual(measured["gitChildren"], 8)
                measurements.append({"files": count, **measured})
        print("SNAPSHOT_MEASUREMENTS=" + json.dumps(measurements, sort_keys=True))

    @unittest.skipUnless((REPOSITORY / ".git").exists(), "source archive has no historical Git oracle")
    def test_release219_full_result_and_failure_parity_on_same_fixtures(self) -> None:
        probe = subprocess.run(["git", "cat-file", "-e", BASELINE], cwd=REPOSITORY, capture_output=True)
        if probe.returncode:
            self.skipTest("shallow checkout lacks accepted 2.19 source; current capture gate still runs")
        measurements = []
        with ExitStack() as stack:
            historical = _historical_module(stack)
            for count in (2, 20, 60):
                with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base = _fixture(root, count)
                    before, old = _measure(historical, root, base)
                    after, new = _measure(snapshot, root, base)
                    self.assertEqual(after, before)
                    self.assertLessEqual(new["gitChildren"], 8)
                    measurements.append({"files": count, "accepted219": old, "current": new})
            for failure, count in product(("oversized", "missing-object"), (2, 20, 60)):
                with (
                    self.subTest(failure=failure, files=count),
                    tempfile.TemporaryDirectory() as tmp,
                    ExitStack() as limits,
                ):
                    root = Path(tmp)
                    base = _fixture(root, count)
                    if failure == "oversized":
                        for module in (historical, snapshot):
                            limits.enter_context(patch.object(module, "MAX_GIT_OBJECT_BYTES", 100))
                    else:
                        object_id = _git(root, "rev-parse", base + ":src/000.bin")
                        object_path = root / ".git/objects" / object_id[:2] / object_id[2:]
                        object_path.chmod(object_path.stat().st_mode | stat.S_IWRITE)
                        object_path.unlink()
                    before, old = _measure(historical, root, base)
                    after, new = _measure(snapshot, root, base)
                    self.assertIn("errorCode", before)
                    self.assertEqual(after, before)
                    self.assertLessEqual(new["gitChildren"], 8)
                    measurements.append({"failure": failure, "fixtureFiles": count, "accepted219": old, "current": new})
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                base = _fixture(root, 2)
                (root / "src/000.bin").rename(root / "src/renamed.bin")
                (root / "src/copy.bin").write_bytes((root / "src/001.bin").read_bytes())
                before, old = _measure(historical, root, base)
                after, new = _measure(snapshot, root, base)
                self.assertEqual(after, before)
                self.assertLessEqual(new["gitChildren"], 8)
                measurements.append({"case": "rename-and-copy", "accepted219": old, "current": new})
            for failure, count in product(("malformed-metadata", "blob-drift", "batch-failure"), (2, 20, 60)):
                with self.subTest(failure=failure, files=count), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base = _fixture(root, count)
                    outcomes = []
                    for module in (historical, snapshot):
                        original = module._git_bytes
                        original_process = snapshot.BoundedProcess

                        def corrupted(cwd, argv, *, original=original, failure=failure, **kwargs):
                            if failure == "malformed-metadata" and argv[1] == "ls-tree":
                                return b"malformed\0"
                            if failure == "batch-failure" and argv[1:3] == ["cat-file", "blob"]:
                                argv = ["git", "cat-file", "--invalid-option"]
                            data = original(cwd, argv, **kwargs)
                            if failure == "blob-drift" and argv[1:3] == ["cat-file", "blob"]:
                                data = data[:-1]
                            return data

                        def failed_batch(_argv, *, original_process=original_process, **kwargs):
                            return original_process(["git", "cat-file", "--invalid-option"], **kwargs)

                        with ExitStack() as faults:
                            faults.enter_context(patch.object(module, "_git_bytes", corrupted))
                            if module is snapshot and failure == "batch-failure":
                                faults.enter_context(patch.object(module, "BoundedProcess", failed_batch))
                            if module is snapshot and failure == "blob-drift":
                                original_parser = module._parse_baseline_row

                                def drifted(*args, original_parser=original_parser):
                                    name, (mode, oid, size) = original_parser(*args)
                                    return name, (mode, oid, size + 1)

                                faults.enter_context(patch.object(module, "_parse_baseline_row", drifted))
                            outcome, measured = _measure(module, root, base)
                        outcomes.append(outcome)
                        self.assertLessEqual(measured["gitChildren"], 8)
                        measurements.append(
                            {
                                "failure": failure,
                                "fixtureFiles": count,
                                "version": module.__name__,
                                **measured,
                                **outcome,
                            }
                        )
                    self.assertEqual(outcomes[0], outcomes[1])
                    self.assertIn("errorCode", outcomes[0])
        print("SNAPSHOT_COMPARISON=" + json.dumps(measurements, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
