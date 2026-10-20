from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import ExitStack, chdir
from pathlib import Path
from unittest import mock

from tests.workflow.test_continuation_batch import _write_batch_bundle
from tests.workflow.test_transaction_projection import _bundle as _initialization_bundle
from tests.workflow.test_transaction_projection import _inventory
from tests.workflow.test_workflow_run import _write_bundle

from .helpers import _run_cli


class WorkflowContinueCliTests(unittest.TestCase):
    def test_composed_cli_guard_and_selector_refusals_leave_every_output_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            manifest = _initialization_bundle(root)
            args = [
                "workflow",
                "init",
                "--state",
                "run.state.json",
                "--manifest",
                str(manifest),
                "--run-id",
                "unit-run",
                "--package-id",
                "canonical-fixture",
            ]
            before = _inventory(root)
            cases = [
                (["--apply"], "initialization-projection-required"),
                (
                    ["--apply", "--projected-target-digest", "0" * 64, "--operation-id", "stale"],
                    "execution-target-changed",
                ),
                (["--projected-target-digest", "0" * 64], "initialization-option-conflict"),
                (["--packet-output-dir", "alternate"], "execution-target-selector-mismatch"),
            ]
            with chdir(root):
                for extra, expected in cases:
                    with self.subTest(extra=extra):
                        code, payload = _run_cli([*args, *extra])
                        self.assertEqual(code, 2)
                        self.assertEqual(payload["code"], expected)
                        self.assertEqual(before, _inventory(root))

    def test_local_only_option_cannot_silently_enable_an_unbounded_or_one_step_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root, phase="READY", task_status="READY")
            before = state.read_bytes()
            code, payload = _continue_args(manifest, state, operation_id="wrong-mode", extra=["--local-only"])
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "continuation-batch-option-conflict")
            self.assertEqual(state.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())

    def test_explicit_three_commands_and_composed_two_commands_have_identical_authority_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as clocks:
            root = Path(tmp).resolve()
            manifest = _initialization_bundle(root)
            source = json.loads(manifest.read_bytes())["baseRevision"]["sha"]
            for module in ("initialization", "operation_kernel", "plan_adoption", "state", "events"):
                clocks.enter_context(
                    mock.patch("agent_lifecycle.workflow." + module + ".now_iso", return_value="2026-01-01T00:00:00Z")
                )
            args = [
                "workflow",
                "init",
                "--state",
                "run.state.json",
                "--run-id",
                "unit-run",
                "--package-id",
                "canonical-fixture",
            ]
            with chdir(root):
                started = time.perf_counter()
                explicit = [
                    ["task", "compile", "--manifest", str(manifest), "--write"],
                    args,
                    [
                        "workflow",
                        "adopt-plan",
                        "--state",
                        "run.state.json",
                        "--manifest",
                        str(manifest),
                        "--operation-id",
                        "cli-parity-adopt",
                        "--expected-revision",
                        "1",
                        "--source-revision",
                        source,
                        "--start-mode",
                        "approval-required",
                    ],
                ]
                for argv in explicit:
                    code, result = _run_cli(argv)
                    self.assertEqual(code, 0, result)
                explicit_wall = time.perf_counter() - started
                state_bytes = (root / "run.state.json").read_bytes()
                event_bytes = (root / "events.jsonl").read_bytes()
                (root / "run.state.json").unlink()
                (root / "events.jsonl").unlink()
                shutil.rmtree(root / "work")
                started = time.perf_counter()
                code, projected = _run_cli([*args, "--manifest", str(manifest)])
                self.assertEqual(code, 0, projected)
                code, result = _run_cli(
                    [
                        *args,
                        "--manifest",
                        str(manifest),
                        "--apply",
                        "--projected-target-digest",
                        projected["bindingDigest"],
                        "--operation-id",
                        "cli-parity-adopt",
                    ]
                )
                composed_wall = time.perf_counter() - started
                self.assertEqual(code, 0, result)
                self.assertEqual((root / "run.state.json").read_bytes(), state_bytes)
                self.assertEqual((root / "events.jsonl").read_bytes(), event_bytes)
            print(
                "CLI_INITIALIZATION_PARITY="
                + json.dumps(
                    {
                        "explicitFacadeCalls": 3,
                        "projectionAndApplyFacadeCalls": 2,
                        "stateByteParity": True,
                        "eventByteParity": True,
                        "explicitWallSeconds": explicit_wall,
                        "composedWallSeconds": composed_wall,
                    }
                )
            )

    def test_composed_initialization_cli_projects_then_applies_without_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            manifest = _initialization_bundle(root)
            args = [
                "workflow",
                "init",
                "--state",
                "runtime/run.state.json",
                "--manifest",
                str(manifest),
                "--run-id",
                "unit-run",
                "--package-id",
                "canonical-fixture",
            ]
            before = _inventory(root)
            with chdir(root):
                code, projected = _run_cli(args)
                self.assertEqual(code, 0)
                self.assertEqual(before, _inventory(root))
                self.assertEqual(projected["stage"], "FROZEN")
                code, applied = _run_cli(
                    [
                        *args,
                        "--apply",
                        "--projected-target-digest",
                        projected["bindingDigest"],
                        "--operation-id",
                        "cli-initial-adoption",
                    ]
                )
            self.assertEqual(code, 0, applied)
            state = json.loads((root / "runtime/run.state.json").read_bytes())
            self.assertEqual(state["phase"], "AWAITING_AUTHORIZATION")
            self.assertEqual(state["packageRoot"], "..")
            self.assertFalse(state["authorization"]["granted"])
            self.assertFalse(applied["executionAuthorized"])

    def test_composed_initialization_cli_refuses_conflicting_target_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            manifest = _initialization_bundle(root)
            (root / "events.jsonl").write_bytes(b"old run")
            before = _inventory(root)
            with chdir(root):
                code, payload = _run_cli(
                    [
                        "workflow",
                        "init",
                        "--state",
                        "run.state.json",
                        "--manifest",
                        str(manifest),
                        "--run-id",
                        "unit-run",
                        "--package-id",
                        "canonical-fixture",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "execution-target-output-conflict")
            self.assertEqual(before, _inventory(root))

    def test_new_apply_options_cannot_silently_change_legacy_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, payload = _run_cli(
                [
                    "workflow",
                    "init",
                    "--state",
                    str(root / "state.json"),
                    "--run-id",
                    "run",
                    "--package-id",
                    "p",
                    "--apply",
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "initialization-manifest-required")
            self.assertFalse((root / "state.json").exists())

    def test_local_only_batch_cli_stops_before_worker_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, state = _write_bundle(root, phase="READY", task_status="READY")
            bundle = _write_batch_bundle(root)
            code, summary = _continue_args(
                manifest, state, operation_id=None, extra=[*_batch_args(manifest, bundle), "--local-only"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(summary["appliedCount"], 2)
            self.assertEqual(summary["stopReason"], "WAITING")
            self.assertFalse(summary["hostLaunchStarted"])

    def test_status_digest_display_keeps_full_underlying_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, state = _write_bundle(Path(tmp), phase="READY", task_status="READY")
            before = state.read_bytes()
            args = ["workflow", "status", "--state", str(state), "--full"]
            code, original = _run_cli(args)
            self.assertEqual(code, 0)
            code, rendered = _run_cli([*args, "--digest-prefix-length", "12"])
            self.assertEqual(code, 0)
            self.assertEqual(rendered["data"], original)
            self.assertFalse(rendered["prefixesUsableAsAuthority"])
            self.assertEqual(state.read_bytes(), before)

    def test_projection_is_default_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            before = state_path.read_bytes()

            code, payload = _continue_args(manifest_path, state_path, operation_id="project-start")

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "READY")
            self.assertEqual(payload["mode"], "PROJECT")
            self.assertEqual(payload["action"]["route"], "run-start")
            self.assertFalse(payload["stateWritten"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())

    def test_apply_requires_projection_guards_then_commits_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            _, projection = _continue_args(manifest_path, state_path, operation_id="apply-start")

            code, missing = _continue_args(
                manifest_path,
                state_path,
                operation_id="apply-start",
                extra=["--apply"],
            )
            self.assertEqual(code, 0)
            self.assertEqual(missing["status"], "INPUT_REQUIRED")
            self.assertFalse(missing["stateWritten"])

            code, applied = _continue_args(
                manifest_path,
                state_path,
                operation_id="apply-start",
                extra=[
                    "--apply",
                    "--projected-state-revision",
                    str(projection["action"]["stateRevision"]),
                    "--projected-action-digest",
                    projection["action"]["actionDigest"],
                ],
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(code, 0)
            self.assertEqual(applied["status"], "APPLIED")
            self.assertEqual(state["stateRevision"], 2)
            self.assertEqual([item["eventType"] for item in events], ["execution-started"])

    def test_explicit_out_writes_the_same_projection_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            out = root / "continuation.json"

            code, payload = _continue_args(
                manifest_path,
                state_path,
                operation_id="project-out",
                extra=["--out", str(out)],
            )

            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

    def test_stale_action_digest_blocks_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            before = state_path.read_bytes()

            code, payload = _continue_args(
                manifest_path,
                state_path,
                operation_id="stale-apply",
                extra=[
                    "--apply",
                    "--projected-state-revision",
                    "1",
                    "--projected-action-digest",
                    "f" * 64,
                ],
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(payload["blockers"][0]["code"], "continuation-projection-action-mismatch")
            self.assertFalse(payload["stateWritten"])
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "events.jsonl").exists())

    def test_global_progress_hook_does_not_intercept_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")

            with mock.patch.dict(os.environ, {"ALK_PROGRESS_HOOK": "stderr"}):
                code, payload = _continue_args(manifest_path, state_path, operation_id="project-with-env")

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "READY")
            self.assertEqual(payload["mode"], "PROJECT")
            self.assertFalse(payload["stateWritten"])

    def test_bounded_mode_applies_bundle_and_returns_persisted_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)

            code, summary = _continue_args(
                manifest_path,
                state_path,
                operation_id=None,
                extra=_batch_args(manifest_path, bundle_path),
            )

            receipt = json.loads((root / "work/batch-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(summary["schemaVersion"], "agent-workflow-continuation-batch-summary.v1")
            self.assertEqual(summary["stopReason"], "INPUT_REQUIRED")
            self.assertEqual(summary["appliedCount"], 2)
            self.assertEqual(receipt["schemaVersion"], "agent-workflow-continuation-batch-receipt.v1")
            self.assertEqual(receipt["receiptDigest"], summary["receiptDigest"])
            self.assertEqual(receipt["blockers"], summary["blockers"])
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["stateRevision"], 3)

    def test_bounded_and_one_step_flag_errors_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
            bundle_path = _write_batch_bundle(root)
            complete = _batch_args(manifest_path, bundle_path)
            cases = [
                (None, [], "continuation-one-step-operation-id-required"),
                (None, [item for item in complete if item != "--apply"], "continuation-batch-apply-required"),
                (None, ["--until-blocked", "--apply"], "continuation-batch-arguments-required"),
                (
                    None,
                    [
                        *complete[: complete.index("--max-transitions") + 1],
                        "0",
                        *complete[complete.index("--max-io-bytes") :],
                    ],
                    "continuation-batch-cap-invalid",
                ),
                ("singular-operation", complete, "continuation-batch-option-conflict"),
                (None, ["--input-bundle", bundle_path], "continuation-batch-option-conflict"),
            ]
            for operation_id, extra, expected_code in cases:
                with self.subTest(expected_code=expected_code, operation_id=operation_id):
                    code, payload = _continue_args(
                        manifest_path,
                        state_path,
                        operation_id=operation_id,
                        extra=extra,
                    )
                    self.assertEqual(code, 2)
                    self.assertEqual(payload["code"], expected_code)

    def test_bounded_mode_rejects_explicit_empty_singular_and_required_values(self) -> None:
        cases = [
            ("operation-id", "continuation-batch-option-conflict"),
            ("projected-action-digest", "continuation-batch-option-conflict"),
            ("lock", "continuation-batch-arguments-required"),
            ("input-bundle", "continuation-batch-arguments-required"),
            ("out", "continuation-batch-arguments-required"),
        ]
        for option, expected_code in cases:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, state_path = _write_bundle(root, phase="READY", task_status="READY")
                bundle_path = _write_batch_bundle(root)
                complete = _batch_args(manifest_path, bundle_path)
                before = state_path.read_bytes()
                operation_id = "" if option == "operation-id" else None
                extra = complete
                if option == "projected-action-digest":
                    extra = [*complete, "--projected-action-digest", ""]
                elif option in {"lock", "input-bundle", "out"}:
                    flag = f"--{option}"
                    value_index = complete.index(flag) + 1
                    extra = [*complete]
                    extra[value_index] = ""

                code, payload = _continue_args(
                    manifest_path,
                    state_path,
                    operation_id=operation_id,
                    extra=extra,
                )

                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], expected_code)
                self.assertEqual(state_path.read_bytes(), before)
                self.assertFalse((root / "events.jsonl").exists())
                self.assertFalse((root / "work/batch-receipt.json").exists())


def _continue_args(
    manifest_path: Path,
    state_path: Path,
    *,
    operation_id: str | None,
    extra: list[str] | None = None,
) -> tuple[int, dict]:
    args = [
        "workflow",
        "continue",
        "--state",
        str(state_path),
        "--manifest",
        str(manifest_path),
        "--expected-revision",
        "1",
        "--source-revision",
        "source",
        "--reason",
        "test guided continuation",
    ]
    if operation_id is not None:
        args.extend(["--operation-id", operation_id])
    return _run_cli([*args, *(extra or [])])


def _batch_args(manifest_path: Path, bundle_path: str) -> list[str]:
    return [
        "--until-blocked",
        "--apply",
        "--input-bundle",
        bundle_path,
        "--max-transitions",
        "8",
        "--max-io-bytes",
        "1048576",
        "--out",
        "work/batch-receipt.json",
        "--lock",
        str(manifest_path.parent / "plan.lock.json"),
    ]


if __name__ == "__main__":
    unittest.main()
