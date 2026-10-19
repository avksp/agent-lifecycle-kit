"""The current CLI does not expose an unqualified protected closing command."""
import tempfile
import unittest
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli.main import main
from agent_lifecycle.adapter_sessions.launch_preflight import launch_from_local_profile
from agent_lifecycle.workflow.closing_window import PROTECTED_OPERATOR_CLAIM


class ClosingWindowCommandTests(unittest.TestCase):
    @staticmethod
    def _arguments(command, state, root):
        arguments = ["workflow", command, "--state", str(state), "--operation-id", "protected-request",
                     "--expected-revision", "1", "--source-revision", "source"]
        if command in {"adopt-plan", "continue"}:
            arguments += ["--manifest", str(root / "missing-manifest.json")]
        if command in {"finalize", "continue"}:
            arguments += ["--reason", "explicit request"]
        if command == "finalize":
            arguments += ["--final-audit", str(root / "missing-audit.json"), "--proof", str(root / "proof.json")]
        return arguments

    def test_explicit_protected_claim_refuses_before_reading_or_creating_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state.json"
            state.write_bytes(b"retained-invalid-json-is-not-execution-authority")
            for command in ("adopt-plan", "finalize", "continue"):
                with self.subTest(command=command):
                    out = StringIO()
                    with redirect_stdout(out), redirect_stderr(StringIO()):
                        code = main(self._arguments(command, state, root)
                                    + ["--requested-claim", PROTECTED_OPERATOR_CLAIM])
                    self.assertEqual(code, 2)
                    self.assertIn("UNSUPPORTED_OPERATOR_ROUTE", out.getvalue())
                    self.assertEqual(state.read_bytes(), b"retained-invalid-json-is-not-execution-authority")
                    self.assertEqual(sorted(p.name for p in root.iterdir()), ["state.json"])

    def test_explicit_ordinary_claim_keeps_existing_validation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state.json"
            state.write_bytes(b"invalid-json")
            for command in ("adopt-plan", "finalize", "continue"):
                outputs = []
                for extra in ([], ["--requested-claim", "ORDINARY_LIMITED"]):
                    out = StringIO()
                    with redirect_stdout(out), redirect_stderr(StringIO()):
                        code = main(self._arguments(command, state, root) + extra)
                    outputs.append((code, json.loads(out.getvalue())))
                with self.subTest(command=command):
                    self.assertEqual(outputs[0], outputs[1])
                    self.assertNotIn("UNSUPPORTED_OPERATOR_ROUTE", json.dumps(outputs[1]))

    def test_managed_protected_claim_refuses_before_profile_or_runner(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = launch_from_local_profile(
                profile_path=root / "missing-profile.json", operation="managedTask",
                adapter_id="codex", project_root=root, requested_claim=PROTECTED_OPERATOR_CLAIM,
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["hostLaunchStarted"])
            self.assertEqual(result["argv"], [])
            self.assertIn("UNSUPPORTED_OPERATOR_ROUTE", json.dumps(result))
            self.assertEqual(list(root.iterdir()), [])

    def test_unsupported_protected_commands_refuse_before_opening_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state.json"
            state.write_bytes(b"retained-original-bytes")
            before = state.read_bytes()
            for command in ("closing-window-start", "closing-window-activate"):
                with self.subTest(command=command), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main(["workflow", command, "--state", str(state)])
                    self.assertEqual(error.exception.code, 2)
                self.assertEqual(state.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in root.iterdir()), ["state.json"])
