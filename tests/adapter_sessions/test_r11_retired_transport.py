"""Disabled live transport refuses before IO; historical replay stays readable."""

from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.adapter_sessions import bootstrap_r11
from agent_lifecycle.adapter_sessions import source_review_support as support
from agent_lifecycle.adapter_sessions import source_review_transcript as transcript
from agent_lifecycle.contracts import LifecycleError, canonical_bytes

METHODS = ("__init__", "record", "send_bootstrap", "receive", "bootstrap_reply")
REFUSAL = {
    "schemaVersion": "agent-lifecycle-error.v1",
    "code": "r11-experimental-disabled",
    "message": "Experimental R11 review route is disabled; use ordinary independent audit",
    "details": {},
}


class RetiredR11TransportTests(unittest.TestCase):
    def test_every_disabled_entry_refuses_before_process_filesystem_or_stream_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reader, writer, observer = Mock(), Mock(), Mock()
            pipe = object.__new__(support._R11AppServerPipe)
            pipe.reader, pipe.writer = reader, writer
            calls = {
                "__init__": lambda: support._R11AppServerPipe(root, {}, reader, writer),
                "record": lambda: pipe.record("SESSION", b"archive"),
                "send_bootstrap": lambda: pipe.send_bootstrap({"method": "thread/start"}),
                "receive": lambda: pipe.receive(observer),
                "bootstrap_reply": lambda: pipe.bootstrap_reply(1, None),
            }
            before = dict(pipe.__dict__)
            with ExitStack() as stack:
                # Actual process, file and stream boundaries; a regression raises
                # AssertionError instead of dispatching anything on this host.
                forbidden = [
                    stack.enter_context(patch(target, side_effect=AssertionError("disabled entry reached IO")))
                    for target in (
                        "subprocess.Popen",
                        "subprocess.run",
                        "os.read",
                        "os.write",
                        "pathlib.Path.mkdir",
                        "pathlib.Path.open",
                        "builtins.open",
                    )
                ]
                for name, call in calls.items():
                    with self.subTest(entry=name), self.assertRaises(LifecycleError) as caught:
                        call()
                    self.assertEqual(REFUSAL, caught.exception.to_json())
                    self.assertEqual(before, pipe.__dict__)
                    for boundary in forbidden:
                        boundary.assert_not_called()
                self.assertEqual([], reader.mock_calls)
                self.assertEqual([], writer.mock_calls)
                self.assertEqual([], observer.mock_calls)
            self.assertEqual([], list(root.iterdir()))

    def test_compatibility_signatures_and_no_unreachable_method_tails(self):
        expected = {
            "__init__": ["self", "root", "binding", "reader", "writer"],
            "record": ["self", "kind", "raw"],
            "send_bootstrap": ["self", "value"],
            "receive": ["self", "transcript"],
            "bootstrap_reply": ["self", "ident", "thread_id"],
        }
        for name, parameters in expected.items():
            with self.subTest(method=name):
                signature = inspect.signature(getattr(support._R11AppServerPipe, name))
                self.assertEqual(parameters, list(signature.parameters))
        self.assertIsNone(inspect.signature(support._R11AppServerPipe.receive).parameters["transcript"].default)
        tree = ast.parse(inspect.getsource(support._R11AppServerPipe))
        methods = [node for node in tree.body[0].body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(list(METHODS), [node.name for node in methods])
        for method in methods:
            with self.subTest(method=method.name):
                self.assertEqual(2, len(method.body))
                self.assertIsInstance(method.body[0], ast.Assign)
                self.assertEqual("_compatibility_arguments", method.body[0].targets[0].id)
                self.assertIsInstance(method.body[-1], ast.Raise)

    def test_historical_readers_and_reexports_preserve_exact_record_bytes(self):
        self.assertIs(bootstrap_r11._R11AppServerPipe, support._R11AppServerPipe)
        self.assertIs(bootstrap_r11._R11PreparationReplay, support._R11PreparationReplay)
        self.assertIs(bootstrap_r11._r11_host_records, support._r11_host_records)
        self.assertIs(bootstrap_r11.SourceReviewTranscript, transcript.SourceReviewTranscript)
        self.assertIs(bootstrap_r11._r11_reassemble_transcript, transcript._r11_reassemble_transcript)
        payload = canonical_bytes({"fixture": "historical-only"})
        record = {
            "sequence": 0,
            "monotonicNs": 2,
            "kind": "SESSION",
            "offset": 0,
            "bytes": len(payload),
            "rawHex": payload.hex(),
        }
        snapshot = {"host-wire/00000000.json": canonical_bytes(record)}
        before = dict(snapshot)
        groups = support._r11_host_records(snapshot, 1, 3)
        self.assertEqual(payload, groups[0]["raw"])
        self.assertEqual(before, snapshot)
        replay = support._R11PreparationReplay(
            [
                {"kind": "SESSION", "raw": payload},
                {"kind": "RECEIVED_CHUNK", "raw": canonical_bytes({"id": 1, "result": {"archived": True}}) + b"\n"},
            ],
            {"fixture": "historical-only"},
        )
        with patch("subprocess.Popen", side_effect=AssertionError("historical replay launched a process")) as process:
            self.assertEqual({"archived": True}, replay.bootstrap_reply(1, None))
        process.assert_not_called()
