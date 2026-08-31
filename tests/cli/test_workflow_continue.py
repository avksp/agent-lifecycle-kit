from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.workflow.test_continuation_batch import _write_batch_bundle
from tests.workflow.test_workflow_run import _write_bundle

from .helpers import _run_cli


class WorkflowContinueCliTests(unittest.TestCase):
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
