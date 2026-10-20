"""TP01-TP08 exercise production composition on real temporary repositories."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, chdir
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.compiler import task_packets
from agent_lifecycle.contracts import LifecycleError, authority_io, canonical_bytes, canonical_digest
from agent_lifecycle.freeze.package_integrity import build_plan_lock_v2
from agent_lifecycle.workflow import initialization
from agent_lifecycle.workflow.plan_adoption import adopt_plan
from tests.planning.test_completeness import _manifest

FIXED_CLOCK = "2026-01-01T00:00:00Z"
STATE = Path("run.state.json")
PACKETS = Path("work/output/workflow/task-packets")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _bundle(root: Path, *, frozen: bool = True, checkpoint_policy: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "ALK unit test")
    (root / "source.py").write_text("value = 1\n")
    _git(root, "add", "source.py")
    _git(root, "commit", "-qm", "unit fixture")
    manifest = _manifest()
    manifest["package"]["artifactRoot"] = "work/output"
    manifest["baseRevision"] = {"sha": _git(root, "rev-parse", "HEAD")}
    manifest["workstreams"][0].update(owner="worker", reviewer="reviewer")
    manifest["status"] = "FROZEN" if frozen else "DRAFT"
    if checkpoint_policy is not None:
        manifest["contextCheckpointPolicy"] = checkpoint_policy
    report_path = "tasks/canonical-fixture/review.json"
    manifest["planFiles"] = sorted([*manifest["planFiles"], report_path])
    manifest["planReview"] = {
        "required": True,
        "report": report_path,
        "reviewedRevision": 1,
        "verdict": "READY_TO_FREEZE",
    }
    plan = root / "tasks/canonical-fixture/plan.manifest.json"
    plan.parent.mkdir(parents=True)
    plan.write_bytes(canonical_bytes(manifest) + b"\n")
    # This is a declared unit-test fixture, never native reviewer evidence.
    report = {
        "schemaVersion": "agent-plan-review.v1",
        "reviewId": "unit-review",
        "reviewer": {"id": "unit-reviewer", "runId": "unit", "surface": "unit", "independent": True},
        "packageId": "canonical-fixture",
        "planRevision": 1,
        "reviewedPlanHash": canonical_digest(manifest),
        "fullReview": True,
        "verdict": "READY_TO_FREEZE",
        "findings": [],
    }
    (root / report_path).write_bytes(canonical_bytes(report) + b"\n")
    if frozen:
        lock = build_plan_lock_v2(manifest, repository_root=root)
        (plan.parent / "plan.lock.json").write_bytes(canonical_bytes(lock) + b"\n")
    return plan


def _kwargs(root: Path, plan: Path) -> dict:
    return {
        "state_path": root / STATE,
        "manifest_path": plan,
        "run_id": "unit-run",
        "package_id": "canonical-fixture",
        "repository_root": root,
    }


def _apply(root: Path, plan: Path, *, digest: str | None = None) -> dict:
    args = _kwargs(root, plan)
    before = _inventory(root)
    original = authority_io._write_fd
    writes = 0

    def counted(*args, **kwargs):
        nonlocal writes
        writes += 1
        return original(*args, **kwargs)

    def trace(outcome):
        inventories = [
            {name: hashlib.sha256(data).hexdigest() for name, data in inventory.items()}
            for inventory in (before, _inventory(root))
        ]
        print(
            "TRANSACTION_TRACE="
            + json.dumps(
                {
                    "proofKind": "real-filesystem-unit-proof",
                    "nativeExecutionProof": False,
                    "targetBindingDigest": digest,
                    "outcome": outcome,
                    "fdWriteAttempts": writes,
                    "beforeFileHashes": inventories[0],
                    "afterFileHashes": inventories[1],
                },
                sort_keys=True,
            )
        )

    try:
        with patch.object(authority_io, "_write_fd", counted):
            if digest is None:
                digest = initialization.project_workflow_initialization(**args)["bindingDigest"]
            result = initialization.initialize_compiled_workflow(
                **args, projected_target_digest=digest, operation_id="unit-adopt"
            )
    except BaseException as exc:
        trace(exc.code if isinstance(exc, LifecycleError) else type(exc).__name__)
        raise
    trace("PASS")
    return result


def _inventory(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


class InitializationTransactionTests(unittest.TestCase):
    def test_enabled_canonical_checkpoint_policy_refuses_before_any_composed_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = {"enabled": True, "required": True, "milestoneEvents": ["plan-adopted"]}
            plan = _bundle(root, checkpoint_policy=policy)
            before = _inventory(root)
            with patch.object(authority_io, "_write_fd") as writes, self.assertRaises(LifecycleError) as refused:
                _apply(root, plan)
            self.assertEqual(refused.exception.code, "composition-policy-unsupported")
            self.assertEqual(writes.call_count, 0)
            self.assertEqual(before, _inventory(root))
            self.assertFalse((root / ".alk").exists())
            self.assertFalse((root / "work").exists())
            # The existing explicit route still supports this same policy.
            task_packets.compile_task_packets(plan, repository_root=root, write=True)
            initialization.initialize_workflow_state(
                root / STATE, run_id="unit-run", package_id="canonical-fixture", package_root="."
            )
            adopt_plan(
                root / STATE,
                manifest_path=plan,
                operation_id="explicit-policy-adopt",
                expected_revision=1,
                source_revision=_git(root, "rev-parse", "HEAD"),
                reset_tasks=False,
                start_mode="approval-required",
            )
            self.assertTrue(list((root / ".alk/context/checkpoints").glob("*.json")))
            self.assertEqual(json.loads((root / STATE).read_bytes())["planRevision"], 1)

    def test_nested_state_uses_the_real_repository_authority_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            plan = _bundle(root)
            with chdir(root):
                args = {**_kwargs(root, plan), "state_path": root / "runtime/run.state.json"}
                projected = initialization.project_workflow_initialization(**args)
                result = initialization.initialize_compiled_workflow(
                    **args, projected_target_digest=projected["bindingDigest"], operation_id="nested-adopt"
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(json.loads((root / "runtime/run.state.json").read_bytes())["packageRoot"], "..")

    def test_tp01_draft_projection_is_read_only_and_cannot_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root, frozen=False)
            before = _inventory(root)
            projected = initialization.project_workflow_initialization(**_kwargs(root, plan))
            self.assertEqual(projected["stage"], "PLANNING")
            with self.assertRaises(LifecycleError) as rejected:
                _apply(root, plan, digest=projected["bindingDigest"])
            self.assertEqual(rejected.exception.code, "plan-not-frozen")
            self.assertEqual(before, _inventory(root))

    def test_tp02_composition_matches_all_explicit_state_and_event_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as clocks:
            root = Path(tmp)
            plan = _bundle(root)
            for module in (initialization,):
                clocks.enter_context(patch.object(module, "now_iso", return_value=FIXED_CLOCK))
            for name in ("operation_kernel", "state", "plan_adoption", "events"):
                clocks.enter_context(
                    patch("agent_lifecycle.workflow." + name + ".now_iso", return_value=FIXED_CLOCK, create=True)
                )
            task_packets.compile_task_packets(plan, repository_root=root, write=True)
            initialization.initialize_workflow_state(
                root / STATE, run_id="unit-run", package_id="canonical-fixture", package_root="."
            )
            adopt_plan(
                root / STATE,
                manifest_path=plan,
                operation_id="unit-adopt",
                expected_revision=1,
                source_revision=_git(root, "rev-parse", "HEAD"),
                reset_tasks=False,
                start_mode="approval-required",
            )
            expected_state = (root / STATE).read_bytes()
            expected_events = (root / "events.jsonl").read_bytes()
            (root / STATE).unlink()
            (root / "events.jsonl").unlink()
            shutil.rmtree(root / "work")
            result = _apply(root, plan)
            self.assertFalse(result["executionAuthorized"])
            self.assertEqual((root / STATE).read_bytes(), expected_state)
            self.assertEqual((root / "events.jsonl").read_bytes(), expected_events)
            self.assertFalse(json.loads(expected_state)["authorization"]["granted"])

    def test_tp03_tp05_inspects_late_conflicts_without_earlier_writes(self) -> None:
        for occupied in (str(STATE), "events.jsonl", str(PACKETS / "index.json")):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan = _bundle(root)
                target = root / occupied
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"old run or other writer")
                before = _inventory(root)
                with self.assertRaises(LifecycleError) as rejected:
                    _apply(root, plan)
                self.assertEqual(rejected.exception.code, "execution-target-output-conflict")
                self.assertEqual(before, _inventory(root))

    def test_tp04_reuses_only_complete_exact_packet_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root)
            task_packets.compile_task_packets(plan, repository_root=root, write=True)
            before = {p: data for p, data in _inventory(root).items() if p.startswith(str(PACKETS))}
            _apply(root, plan)
            self.assertEqual(before, {p: data for p, data in _inventory(root).items() if p in before})

    def test_tp06_source_and_ignored_output_drift_refuse_before_writes(self) -> None:
        for name in ("source.py", "events.jsonl"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan = _bundle(root)
                (root / ".git/info/exclude").write_text("events.jsonl\n")
                projected = initialization.project_workflow_initialization(**_kwargs(root, plan))
                (root / name).write_bytes(b"changed after inspection")
                before = _inventory(root)
                with self.assertRaises(LifecycleError):
                    _apply(root, plan, digest=projected["bindingDigest"])
                self.assertEqual(before, _inventory(root))

    def test_tp07_alternate_output_and_symlink_parent_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            plan = _bundle(root)
            before = _inventory(root)
            with self.assertRaises(LifecycleError):
                initialization.project_workflow_initialization(**_kwargs(root, plan), output_dir=Path("alternate"))
            self.assertEqual(before, _inventory(root))
            (root / "work").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(LifecycleError):
                _apply(root, plan)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_tp08_clean_clone_cannot_authorize_occupied_actual_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clean, actual = Path(tmp) / "clean", Path(tmp) / "actual"
            plan = _bundle(clean)
            shutil.copytree(clean, actual)
            clean_projection = initialization.project_workflow_initialization(**_kwargs(clean, plan))
            (actual / "events.jsonl").write_bytes(b"actual old run")
            before = _inventory(actual)
            with self.assertRaises(LifecycleError):
                _apply(actual, actual / plan.relative_to(clean), digest=clean_projection["bindingDigest"])
            self.assertEqual(before, _inventory(actual))

    def test_state_or_event_failure_rolls_back_only_own_outputs(self) -> None:
        for failing in ("create_private_json", "create_authority_bytes", "adopt_plan"):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan = _bundle(root)
                projected = initialization.project_workflow_initialization(**_kwargs(root, plan))
                with (
                    patch.object(initialization, failing, side_effect=OSError("injected write failure")),
                    self.assertRaises(OSError),
                ):
                    _apply(root, plan, digest=projected["bindingDigest"])
                self.assertFalse((root / STATE).exists())
                self.assertFalse((root / "events.jsonl").exists())
                self.assertTrue((root / PACKETS / "index.json").is_file())

    def test_failure_before_and_after_every_real_write_leaves_no_partial_authority(self) -> None:
        original = authority_io._write_fd
        # packet, index, initial state, empty log, event append, state replace.
        for boundary in range(1, 7):
            for after_write in (False, True):
                with self.subTest(boundary=boundary, after=after_write), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    plan = _bundle(root)
                    projected = initialization.project_workflow_initialization(**_kwargs(root, plan))
                    writes = 0

                    def fail_selected(fd, data, *, boundary=boundary, after_write=after_write, **kwargs):
                        nonlocal writes
                        writes += 1
                        if writes == boundary and not after_write:
                            # The real primitive owns descriptor closure.
                            import os

                            os.close(fd)
                            raise OSError("injected before write")
                        result = original(fd, data, **kwargs)
                        if writes == boundary:
                            raise OSError("injected after write")
                        return result

                    with patch.object(authority_io, "_write_fd", fail_selected), self.assertRaises(LifecycleError):
                        _apply(root, plan, digest=projected["bindingDigest"])
                    self.assertEqual(writes, boundary)
                    self.assertFalse((root / STATE).exists())
                    self.assertFalse((root / "events.jsonl").exists())
                    packet_files = list((root / PACKETS).glob("*.json"))
                    self.assertEqual(len(packet_files), 0 if boundary <= 2 else 2)

    def test_competing_writer_is_retained_even_when_rollback_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root)

            def competitor(*_args, **_kwargs):
                (root / STATE).write_bytes(b"different writer data")
                raise OSError("failure after competing replacement")

            with patch.object(initialization, "adopt_plan", competitor), self.assertRaises(LifecycleError) as rejected:
                _apply(root, plan)
            self.assertEqual(rejected.exception.code, "workflow-initialization-rollback-conflict")
            self.assertEqual((root / STATE).read_bytes(), b"different writer data")

    def test_source_drift_between_packet_writes_is_rechecked_and_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root)
            original = task_packets._write_idempotent
            calls = 0

            def drift_after_first(*args, **kwargs):
                nonlocal calls
                result = original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    (root / "source.py").write_bytes(b"source changed between publications")
                return result

            with (
                patch.object(task_packets, "_write_idempotent", drift_after_first),
                self.assertRaises(LifecycleError) as rejected,
            ):
                _apply(root, plan)
            self.assertEqual(rejected.exception.code, "execution-target-changed")
            self.assertEqual(calls, 1)
            self.assertFalse((root / STATE).exists())
            self.assertEqual(list((root / PACKETS).glob("*.json")), [])

    def test_git_clean_ignored_packet_conflict_still_refuses_actual_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root)
            _git(root, "add", "tasks")
            _git(root, "commit", "-qm", "unit frozen bundle")
            (root / ".git/info/exclude").write_text("work/\n")
            occupied = root / PACKETS / "index.json"
            occupied.parent.mkdir(parents=True)
            occupied.write_bytes(b"ignored predecessor output")
            self.assertEqual(_git(root, "status", "--porcelain"), "")
            before = _inventory(root)
            with self.assertRaises(LifecycleError) as refused:
                _apply(root, plan)
            self.assertEqual(refused.exception.code, "execution-target-output-conflict")
            self.assertEqual(before, _inventory(root))

    def test_source_drift_after_event_append_refuses_state_publication_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _bundle(root)
            original = authority_io.append_authority_bytes

            def changed_after_append(*args, **kwargs):
                original(*args, **kwargs)
                (root / "source.py").write_bytes(b"changed before state replacement")

            with (
                patch("agent_lifecycle.workflow.events.append_authority_bytes", changed_after_append),
                self.assertRaises(LifecycleError) as refused,
            ):
                _apply(root, plan)
            self.assertEqual(refused.exception.code, "execution-target-changed")
            self.assertFalse((root / STATE).exists())
            self.assertFalse((root / "events.jsonl").exists())
            self.assertEqual((root / "source.py").read_bytes(), b"changed before state replacement")


if __name__ == "__main__":
    unittest.main()
