from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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


def _continue_args(
    manifest_path: Path,
    state_path: Path,
    *,
    operation_id: str,
    extra: list[str] | None = None,
) -> tuple[int, dict]:
    return _run_cli(
        [
            "workflow",
            "continue",
            "--state",
            str(state_path),
            "--manifest",
            str(manifest_path),
            "--operation-id",
            operation_id,
            "--expected-revision",
            "1",
            "--source-revision",
            "source",
            "--reason",
            "test guided continuation",
            *(extra or []),
        ]
    )


if __name__ == "__main__":
    unittest.main()
