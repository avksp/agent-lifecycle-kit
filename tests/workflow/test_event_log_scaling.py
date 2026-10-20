"""Full replay remains bounded per line and validates the entire journal."""

from __future__ import annotations

import json
import tempfile
import time
import tracemalloc
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import DuplicateJsonMemberError
from agent_lifecycle.workflow import events
from agent_lifecycle.workflow.operation_kernel import _last_event


def _line(index: int) -> bytes:
    return (
        json.dumps(
            {
                "schemaVersion": "agent-workflow-event.v1",
                "stateRevision": index,
                "operationId": f"op-{index}",
                "payload": "x" * 512,
            }
        ).encode()
        + b"\n"
    )


class EventLogScalingTests(unittest.TestCase):
    def test_complete_replay_measurements_include_all_bytes_and_last_identity(self) -> None:
        measurements = []
        for size in (1_000, 10_000):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                path.write_bytes(b"".join(_line(index) for index in range(1, size + 1)))
                total = 0
                original = events.open_authority_read

                class Counted:
                    def __init__(self, stream):
                        self.stream = stream

                    def readline(self, limit):
                        nonlocal total
                        value = self.stream.readline(limit)
                        total += len(value)
                        return value

                @contextmanager
                def counted(*args, original=original, **kwargs):
                    with original(*args, **kwargs) as stream:
                        yield Counted(stream)

                tracemalloc.start()
                started = time.perf_counter()
                try:
                    with patch.object(events, "open_authority_read", counted):
                        last = _last_event(path)
                    wall = time.perf_counter() - started
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertEqual(total, path.stat().st_size)
                self.assertEqual(last["operationId"], f"op-{size}")
                self.assertEqual(last["stateRevision"], size)
                measurements.append(
                    {
                        "events": size,
                        "readBytes": total,
                        "wallSeconds": wall,
                        "peakPythonBytes": peak,
                        "lastOperationId": last["operationId"],
                    }
                )
        print("EVENT_REPLAY_MEASUREMENTS=" + json.dumps(measurements, sort_keys=True))

    def test_early_middle_and_tail_corruption_cannot_authorize_last_event(self) -> None:
        for index in (0, 499, 999):
            for bad in (b"{broken\n", b'{"stateRevision":4,"stateRevision":5}\n', _line(1), _line(2000)):
                # A high revision at the last line is valid. Use a regression
                # there instead, retaining every corruption position.
                replacement = (
                    _line(2) if (index == 999 and bad == _line(2000)) or (index == 0 and bad == _line(1)) else bad
                )
                with self.subTest(index=index, bad=replacement), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "events.jsonl"
                    lines = [_line(value) for value in range(1, 1001)]
                    lines[index] = replacement
                    path.write_bytes(b"".join(lines))
                    with self.assertRaises((LifecycleError, DuplicateJsonMemberError)):
                        _last_event(path)


if __name__ == "__main__":
    unittest.main()
