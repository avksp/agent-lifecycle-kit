"""Bounded public-CLI consumer; fixture bootstrap is explicitly UNIT_ONLY.

ALK_EXTERNAL_CONSUMER_EXECUTABLE selects a source/editable or wheel-installed
console script. Consumer subprocesses use a disposable cwd and no PYTHONPATH.
ALK_EXTERNAL_CONSUMER_RECEIPTS optionally retains exact subprocess observations.
No fixture attestation represents a live host, reviewer or qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((Path(__file__).parent / "fixtures/external-consumer-cases.json").read_text(encoding="utf-8"))
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_EXECUTABLE_BYTES = 32 * 1024 * 1024
MAX_STATE_BYTES = 1024 * 1024
MAX_EVENT_BYTES = 4 * 1024 * 1024
MAX_EVENT_LINE_BYTES = 65536
MAX_EVENT_COUNT = 1024
RUNTIME_SECONDS = 20
CLEANUP_SECONDS = 2


class ConsumerRefusal(ValueError):
    """The external client's contract mapping forbids a mutation."""


class PublicCliConsumer:
    """Generic caller: only stdlib, public argv and public JSON artifacts."""

    def __init__(self, executable: str, cwd: Path) -> None:
        self.executable = str(Path(executable).absolute())
        self.cwd = cwd.resolve()
        self.calls: list[dict] = []
        self.qualified = False
        self._unknown_effect = False
        self._cleanup_confirmed = True

    def _unknown(self, message: str) -> ConsumerRefusal:
        self.qualified = False
        self._unknown_effect = True
        return ConsumerRefusal("UNKNOWN: " + message)

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        total = 0
        try:
            with Path(self.executable).open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EXECUTABLE_BYTES:
                    raise ConsumerRefusal("executable fingerprint exceeds consumer limit")
                while chunk := stream.read(min(65536, MAX_EXECUTABLE_BYTES + 1 - total)):
                    total += len(chunk)
                    if total > MAX_EXECUTABLE_BYTES:
                        raise ConsumerRefusal("executable fingerprint exceeds consumer limit")
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ConsumerRefusal("executable changed during fingerprinting")
        except OSError as exc:
            raise ConsumerRefusal("executable fingerprint unavailable") from exc
        return digest.hexdigest()

    def _capture(self, command: list[str], env: dict[str, str]) -> tuple:
        try:
            child = subprocess.Popen(
                command,
                cwd=self.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=False,
            )
        except OSError:
            return None, b"", b"", False, "process creation failed"
        deadline = time.monotonic() + RUNTIME_SECONDS
        cap = MAX_OUTPUT_BYTES
        buffers = [bytearray(), bytearray()]
        closed = [False, False]
        faults: list[str] = []
        fault = threading.Event()

        def drain(index, pipe):
            try:
                while len(buffers[index]) <= cap:
                    chunk = pipe.read(min(8192, cap + 1 - len(buffers[index])))
                    if not chunk:
                        return
                    buffers[index].extend(chunk)
                    if len(buffers[index]) > cap:
                        faults.append("output exceeds consumer limit")
                        fault.set()
                        return
            except (OSError, ValueError):
                faults.append("pipe reader failed")
                fault.set()
            finally:
                try:
                    pipe.close()
                    closed[index] = True
                except OSError:
                    faults.append("pipe close unconfirmed")
                    fault.set()

        threads = [
            threading.Thread(target=drain, args=(i, pipe), daemon=True, name=f"alk-consumer-{uuid.uuid4()}")
            for i, pipe in enumerate((child.stdout, child.stderr))
        ]
        reason = ""
        try:
            for thread in threads:
                thread.start()
            while True:
                if fault.is_set():
                    reason = faults[0]
                    break
                if child.poll() is not None and not any(t.is_alive() for t in threads):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "runtime deadline exceeded"
                    break
                fault.wait(min(0.01, remaining))
        except (OSError, RuntimeError):
            reason = "process supervision failed"
        cleanup_deadline = time.monotonic() + CLEANUP_SECONDS
        if child.poll() is None:
            try:
                child.kill()
            except OSError:
                reason = reason or "child stop unconfirmed"
        try:
            child.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired):
            reason = reason or "child exit unconfirmed"
        for index, thread in enumerate(threads):
            if thread.ident is not None:
                thread.join(max(0, cleanup_deadline - time.monotonic()))
            else:
                try:
                    (child.stdout, child.stderr)[index].close()
                    closed[index] = True
                except OSError:
                    pass
        clean = child.returncode is not None and all(closed) and not any(t.is_alive() for t in threads)
        if faults:
            reason = reason or faults[0]
        if not clean:
            reason = reason or "reader cleanup unconfirmed"
        return child.returncode, bytes(buffers[0]), bytes(buffers[1]), clean, reason

    def call(self, args: list[str]) -> tuple[int, dict]:
        if self._unknown_effect or not self._cleanup_confirmed:
            raise ConsumerRefusal("UNKNOWN: reconcile/dispose before another call")
        if len(args) > 96 or sum(map(len, args)) > 16384:
            raise ConsumerRefusal("argv exceeds consumer limit")
        fingerprint = self._fingerprint()
        env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
            if key in os.environ
        }
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
        command = [self.executable, *args]
        started = datetime.now(UTC).isoformat()
        code, out, err, clean, reason = self._capture(command, env)
        self._cleanup_confirmed = clean
        payload = None
        if not reason:
            try:
                payload = json.loads(out.decode("utf-8"))
                err.decode("utf-8")
                if not isinstance(payload, dict):
                    reason = "expected a JSON object"
            except (ValueError, RecursionError):
                reason = "invalid UTF-8/JSON output"
        record = {
            "commandId": str(uuid.uuid4()),
            "argv": command,
            "cwd": str(self.cwd),
            "env": env,
            "executableSha256": fingerprint,
            "startedAt": started,
            "finishedAt": datetime.now(UTC).isoformat(),
            "exitCode": code,
            "stdout": out.decode("utf-8", errors="replace"),
            "stderr": err.decode("utf-8", errors="replace"),
            "stdoutSha256": hashlib.sha256(out).hexdigest(),
            "stderrSha256": hashlib.sha256(err).hexdigest(),
            "stdoutBytesRead": len(out),
            "stderrBytesRead": len(err),
            "cleanupConfirmed": clean,
            "outcome": "UNKNOWN" if reason else "RECEIVED",
            "unknownReason": reason or None,
            "evidenceBoundary": "UNIT_ONLY",
            "providerTokens": None,
            "providerUSD": None,
        }
        self.calls.append(record)
        if reason:
            self._unknown(reason)
        if receipt_path := os.environ.get("ALK_EXTERNAL_CONSUMER_RECEIPTS"):
            try:
                with Path(receipt_path).open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError as exc:
                record["outcome"] = "UNKNOWN"
                raise self._unknown("receipt persistence failed") from exc
        if reason:
            raise self._unknown(reason)
        return code, payload

    def negotiate(self, *, versions: tuple[str, ...], schema: str) -> dict:
        self.qualified = False
        code, receipt = self.call(["version"])
        if code != 0 or receipt.get("schemaVersion") != schema or receipt.get("version") not in versions:
            raise ConsumerRefusal("unsupported version/schema; mutation refused")
        self.qualified = True
        return receipt

    def continue_args(self, operation: str, *, revision: int = 1) -> list[str]:
        return [
            "workflow",
            "continue",
            "--state",
            "run.state.json",
            "--manifest",
            "plans/package/plan.manifest.json",
            "--lock",
            "plans/package/plan.lock.json",
            "--operation-id",
            operation,
            "--expected-revision",
            str(revision),
            "--source-revision",
            "source",
            "--reason",
            "UNIT_ONLY external consumer conformance",
        ]

    def apply(self, args: list[str], projection: dict) -> tuple[int, dict]:
        if not self.qualified:
            raise ConsumerRefusal("negotiate before mutation")
        if projection.get("schemaVersion") != CASES["continuationSchema"]:
            raise ConsumerRefusal("unsupported receipt schema")
        action = projection.get("action", {})
        if action.get("schemaVersion") != CASES["actionSchema"] or action.get("route") != "run-start":
            raise ConsumerRefusal("unsupported action")
        return self.call(
            [
                *args,
                "--apply",
                "--projected-state-revision",
                str(action["stateRevision"]),
                "--projected-action-digest",
                action["actionDigest"],
            ]
        )

    def _read_artifact(self, name: str, cap: int) -> bytes:
        relative = Path(name)
        if not name or relative.is_absolute() or relative.drive or ".." in relative.parts or "\\" in name:
            raise ConsumerRefusal("artifact must be a contained relative path")
        path = self.cwd
        identities = []
        for part in relative.parts:
            path = path / part
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ConsumerRefusal("artifact path contains a symlink/reparse point")
            identities.append((path, info.st_dev, info.st_ino, info.st_mode))
        if not identities or not stat.S_ISREG(info.st_mode):
            raise ConsumerRefusal("artifact is not regular")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
                raise ConsumerRefusal("artifact exceeds consumer limit or is not regular")
            data = stream.read(cap + 1)
            after = os.fstat(stream.fileno())
        if len(data) > cap or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ConsumerRefusal("artifact changed or exceeded consumer limit")
        for item, device, inode, mode in identities:
            now = item.lstat()
            if (now.st_dev, now.st_ino, now.st_mode) != (device, inode, mode):
                raise ConsumerRefusal("artifact path changed")
        if identities[-1][1:3] != (before.st_dev, before.st_ino):
            raise ConsumerRefusal("artifact identity changed")
        return data

    def reconcile_run_start(self, operation: str, projection: dict) -> dict:
        """Read bounded native authority; never dispatch a second mutation."""
        try:
            state_bytes = self._read_artifact("run.state.json", MAX_STATE_BYTES)
            state = json.loads(state_bytes)
            if not isinstance(state, dict) or state.get("schemaVersion") not in (
                "agent-workflow-state.v3",
                "agent-workflow-state.v4",
                "agent-workflow-state.v5",
            ):
                raise ConsumerRefusal("unsupported state shape/schema")
            events = self._read_artifact(state["eventLog"], MAX_EVENT_BYTES)
            if self._read_artifact("run.state.json", MAX_STATE_BYTES) != state_bytes:
                raise ConsumerRefusal("state changed during reconciliation")
            action = projection["action"]
            if type(action["stateRevision"]) is not int or type(state["stateRevision"]) is not int:
                raise ConsumerRefusal("invalid revision shape")
            expected = action["stateRevision"] + 1
            match = None
            stream = BytesIO(events)
            for _index in range(MAX_EVENT_COUNT):
                line = stream.readline(MAX_EVENT_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_EVENT_LINE_BYTES:
                    raise ConsumerRefusal("event line exceeds consumer limit")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ConsumerRefusal("invalid event shape")
                if event.get("operationId") == operation:
                    if match is not None:
                        raise ConsumerRefusal("operation has no unique committed event")
                    match = event
            if stream.read(1):
                raise ConsumerRefusal("event count exceeds consumer limit")
            if match is None:
                raise ConsumerRefusal("operation has no unique committed event")
            if (
                match.get("schemaVersion") != "agent-workflow-event.v1"
                or match.get("runId") != state["runId"]
                or match.get("packageId") != state["packageId"]
                or type(match.get("stateRevision")) is not int
                or match["stateRevision"] != expected
                or state["stateRevision"] != expected
                or match.get("eventType") != "execution-started"
                or state["phase"] != "RUNNING"
                or state["planDigest"] != action["planDigest"]
                or state["sourceRevision"] != action["sourceRevision"]
            ):
                raise ConsumerRefusal("state/event/request bindings disagree")
            if not self._cleanup_confirmed:
                raise ConsumerRefusal("effect matched but resource cleanup remains unconfirmed; dispose caller")
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise self._unknown(
                "reconciliation unavailable: "
                + (str(exc) if isinstance(exc, ConsumerRefusal) else "invalid/missing bounded artifact")
            ) from exc
        self._unknown_effect = False
        self.qualified = False
        return match


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


class ConsumerEnvironmentTests(unittest.TestCase):
    def test_safe_ambient_windows_home_is_preserved_without_source_or_secret_environment(self) -> None:
        home_names = ("USERPROFILE", "HOMEDRIVE", "HOMEPATH")
        forbidden = ("PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for homes in (
                {"USERPROFILE": r"C:\Users\unit-only", "HOMEDRIVE": "C:", "HOMEPATH": r"\Users\unit-only"},
                {},
            ):
                captured = {}

                actual_popen = subprocess.Popen

                def observed_popen(command, captured=captured, actual_popen=actual_popen, **kwargs):
                    captured.update(kwargs["env"])
                    return actual_popen(command, **kwargs)

                ambient = {
                    "PATH": os.defpath,
                    "SYSTEMROOT": r"C:\Windows",
                    "TEMP": directory,
                    "TMP": directory,
                    **homes,
                    **dict.fromkeys(forbidden, "unit-only-placeholder"),
                }
                with (
                    self.subTest(homePresent=bool(homes)),
                    patch.dict(os.environ, ambient, clear=True),
                    patch(
                        "tests.cli.test_external_consumer_contract.subprocess.Popen", side_effect=observed_popen
                    ) as run,
                ):
                    code, payload = PublicCliConsumer(sys.executable, root).call(
                        [
                            "-c",
                            "import json; print(json.dumps({'schemaVersion':'agent-lifecycle-version.v1','version':'2.35.0'}))",
                        ]
                    )
                self.assertEqual(code, 0)
                self.assertEqual(payload["version"], "2.35.0")
                run.assert_called_once()
                self.assertEqual({name: captured[name] for name in home_names if name in captured}, homes)
                self.assertTrue(set(forbidden).isdisjoint(captured))
                self.assertEqual(captured["PYTHONDONTWRITEBYTECODE"], "1")
                self.assertEqual(captured["PYTHONNOUSERSITE"], "1")


class ConsumerBoundedIoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        self.consumer = PublicCliConsumer(sys.executable, self.root)
        self.children = []
        self.reads = {"stdout": [], "stderr": []}
        self.capture_fds = []
        original = subprocess.Popen
        reads = self.reads

        class ObservedPipe:
            def __init__(self, raw, name):
                self.raw, self.name = raw, name

            def read(self, size):
                data = self.raw.read(size)
                reads[self.name].append((size, len(data)))
                return data

            def close(self):
                self.raw.close()

        def observed(command, **kwargs):
            child = original(command, **kwargs)
            self.children.append(child)
            for name in ("stdout", "stderr"):
                raw = getattr(child, name)
                if raw is not None:
                    setattr(child, name, ObservedPipe(raw, name))
                target = kwargs.get(name)
                if hasattr(target, "fileno"):
                    descriptor = os.dup(target.fileno())
                    self.capture_fds.append(descriptor)
                    self.addCleanup(os.close, descriptor)
            return child

        self.enterContext(patch("tests.cli.test_external_consumer_contract.subprocess.Popen", side_effect=observed))

    def assert_clean(self) -> None:
        self.assertTrue(self.children)
        self.assertTrue(all(child.returncode is not None for child in self.children))
        self.assertFalse(any(t.name.startswith("alk-consumer-") for t in threading.enumerate()))

    def test_floods_stop_during_execution_with_bounded_reads_and_no_capture_files(self) -> None:
        for streams in ((1,), (2,), (1, 2)):
            with (
                self.subTest(streams=streams),
                patch("tests.cli.test_external_consumer_contract.MAX_OUTPUT_BYTES", 1024),
            ):
                marker = self.root / "natural-completion"
                marker.unlink(missing_ok=True)
                self.reads["stdout"].clear()
                self.reads["stderr"].clear()
                script = (
                    "import os,time,threading,pathlib; "
                    f"threads=[threading.Thread(target=os.write,args=(fd,b'x'*8192)) for fd in {streams!r}]; "
                    "[t.start() for t in threads]; [t.join() for t in threads]; "
                    "time.sleep(2); pathlib.Path('natural-completion').write_text('done')"
                )
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.call(["-c", script])
                self.assertFalse(marker.exists(), "overflow must stop the child before natural completion")
                self.assertEqual(sum(os.fstat(fd).st_size for fd in self.capture_fds), 0)
                for name in ("stdout", "stderr"):
                    self.assertLessEqual(sum(size for _request, size in self.reads[name]), 1025)
                    self.assertLessEqual(len(self.consumer.calls[-1][name].encode()), 1025)
                self.assertTrue(any(self.reads.values()))
                self.assertEqual(self.consumer.calls[-1]["outcome"], "UNKNOWN")
                self.assert_clean()
                self.consumer = PublicCliConsumer(sys.executable, self.root)

    def test_both_pipes_drain_concurrently_without_deadlock(self) -> None:
        script = (
            "import os,threading; "
            "a=threading.Thread(target=os.write,args=(1,b'{\"data\":\"'+b'x'*100000+b'\"}')); "
            "b=threading.Thread(target=os.write,args=(2,b'e'*100000)); "
            "a.start(); b.start(); a.join(); b.join()"
        )
        code, payload = self.consumer.call(["-c", script])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["data"]), 100000)
        self.assertEqual(sum(n for _size, n in self.reads["stderr"]), 100000)
        self.assert_clean()

    def test_timeout_reaps_child_and_blocks_redispatch(self) -> None:
        with (
            patch("tests.cli.test_external_consumer_contract.RUNTIME_SECONDS", 0.1, create=True),
            self.assertRaises(ConsumerRefusal),
        ):
            self.consumer.call(["-c", "import time; time.sleep(2); print('{}')"])
        self.assertEqual(self.consumer.calls[-1]["outcome"], "UNKNOWN")
        self.assertTrue(self.consumer.calls[-1]["cleanupConfirmed"])
        with self.assertRaises(ConsumerRefusal):
            self.consumer.call(["-c", "print('{}')"])
        with self.assertRaises(ConsumerRefusal):
            self.consumer.negotiate(versions=("2.37.0",), schema=CASES["versionSchema"])
        self.assertEqual(len(self.children), 1)
        self.assert_clean()

    def test_invalid_output_is_recorded_unknown_without_blind_retry(self) -> None:
        for raw in (b"\xff", b"not-json", b"[]"):
            with self.subTest(raw=raw):
                self.consumer = PublicCliConsumer(sys.executable, self.root)
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.call(["-c", f"import os; os.write(1,{raw!r})"])
                self.assertEqual(self.consumer.calls[-1]["outcome"], "UNKNOWN")
                self.assertTrue(self.consumer.calls[-1]["cleanupConfirmed"])
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.call(["-c", "print('{}')"])
                self.assertEqual(len(self.consumer.calls), 1)
                self.assert_clean()

    def test_executable_fingerprint_is_bounded_before_spawn(self) -> None:
        with (
            patch("tests.cli.test_external_consumer_contract.MAX_EXECUTABLE_BYTES", 8, create=True),
            self.assertRaises(ConsumerRefusal),
        ):
            self.consumer.call(["-c", "print('{}')"])
        self.assertEqual(self.children, [])
        self.assertEqual(self.consumer.calls, [])


class ConsumerReconciliationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        self.consumer = PublicCliConsumer(sys.executable, self.root)
        self.state = {
            "schemaVersion": "agent-workflow-state.v4",
            "runId": "unit-run",
            "packageId": "unit-package",
            "phase": "RUNNING",
            "stateRevision": 2,
            "sourceRevision": "unit-source",
            "planDigest": "d" * 64,
            "eventLog": "events.jsonl",
        }
        self.event = {
            "schemaVersion": "agent-workflow-event.v1",
            "runId": "unit-run",
            "packageId": "unit-package",
            "operationId": "unit-op",
            "stateRevision": 2,
            "eventType": "execution-started",
        }
        self.projection = {"action": {"stateRevision": 1, "planDigest": "d" * 64, "sourceRevision": "unit-source"}}
        self.write_authority()

    def write_authority(self) -> None:
        (self.root / "run.state.json").write_text(json.dumps(self.state), encoding="utf-8")
        (self.root / "events.jsonl").write_text(json.dumps(self.event) + "\n", encoding="utf-8")

    def test_oversized_state_event_line_and_count_remain_unknown(self) -> None:
        cases = (
            ("MAX_STATE_BYTES", 32, json.dumps(self.state), json.dumps(self.event) + "\n"),
            ("MAX_EVENT_BYTES", 32, json.dumps(self.state), json.dumps(self.event) + "\n"),
            ("MAX_EVENT_LINE_BYTES", 32, json.dumps(self.state), json.dumps(self.event) + "\n"),
            ("MAX_EVENT_COUNT", 1, json.dumps(self.state), json.dumps(self.event) + "\n{}\n"),
        )
        for limit, cap, state, events in cases:
            with (
                self.subTest(limit=limit),
                patch("tests.cli.test_external_consumer_contract." + limit, cap, create=True),
            ):
                (self.root / "run.state.json").write_text(state, encoding="utf-8")
                (self.root / "events.jsonl").write_text(events, encoding="utf-8")
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.reconcile_run_start("unit-op", self.projection)
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.call(["-c", "print('{}')"])
                self.assertFalse(self.consumer.calls)
                self.consumer = PublicCliConsumer(sys.executable, self.root)

    def test_traversal_and_malformed_artifacts_remain_unknown(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            target = Path(outside) / "events.jsonl"
            target.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
            for path in (str(target), "../" + Path(outside).name + "/events.jsonl"):
                with self.subTest(path=path):
                    self.state["eventLog"] = path
                    self.write_authority()
                    with self.assertRaises(ConsumerRefusal):
                        self.consumer.reconcile_run_start("unit-op", self.projection)
        self.state["eventLog"] = "events.jsonl"
        self.write_authority()
        for invalid in (b"\xff", b"[]", b"null", b"{broken"):
            with self.subTest(invalid=invalid):
                (self.root / "events.jsonl").write_bytes(invalid)
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.reconcile_run_start("unit-op", self.projection)
        self.assertFalse(self.consumer.calls)

    def test_symlink_artifact_is_refused(self) -> None:
        target = self.root / "real-events.jsonl"
        target.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
        link = self.root / "events.jsonl"
        link.unlink()
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"OS does not permit creating the test symlink: {exc}")
        with self.assertRaises(ConsumerRefusal):
            self.consumer.reconcile_run_start("unit-op", self.projection)
        self.assertFalse(self.consumer.calls)

    def test_effect_reconciliation_requires_renegotiation(self) -> None:
        with self.assertRaises(ConsumerRefusal):
            self.consumer.call(["-c", "print('bad-json')"])
        self.assertEqual(self.consumer.reconcile_run_start("unit-op", self.projection), self.event)
        self.assertEqual(self.consumer.call(["-c", "print('{}')"]), (0, {}))
        with self.assertRaises(ConsumerRefusal):
            self.consumer.apply([], self.projection)
        self.assertEqual(len(self.consumer.calls), 2)

    def test_effect_match_does_not_clear_unconfirmed_reader_cleanup(self) -> None:
        # The real pipe closes; an injected OS close-report failure prevents certification.
        actual_popen = subprocess.Popen

        class UnconfirmedClose:
            def __init__(self, raw):
                self.raw = raw

            def read(self, size):
                return self.raw.read(size)

            def close(self):
                self.raw.close()
                raise OSError("controlled close-report failure")

        def observed(command, **kwargs):
            child = actual_popen(command, **kwargs)
            child.stdout = UnconfirmedClose(child.stdout)
            return child

        with (
            patch("tests.cli.test_external_consumer_contract.subprocess.Popen", side_effect=observed),
            self.assertRaises(ConsumerRefusal),
        ):
            self.consumer.call(["-c", "print('{}')"])
        self.assertFalse(self.consumer.calls[-1]["cleanupConfirmed"])
        with self.assertRaises(ConsumerRefusal):
            self.consumer.reconcile_run_start("unit-op", self.projection)
        with self.assertRaises(ConsumerRefusal):
            self.consumer.call(["-c", "print('{}')"])
        with self.assertRaises(ConsumerRefusal):
            self.consumer.negotiate(versions=("2.37.0",), schema=CASES["versionSchema"])
        self.assertEqual(len(self.consumer.calls), 1)
        self.assertFalse(any(t.name.startswith("alk-consumer-") for t in threading.enumerate()))


class ExternalConsumerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = os.environ.get("ALK_EXTERNAL_CONSUMER_EXECUTABLE") or shutil.which("agent-lifecycle")
        if not cls.executable:
            raise RuntimeError("install the source package or set ALK_EXTERNAL_CONSUMER_EXECUTABLE")

    def setUp(self) -> None:
        # The private helper belongs solely to disposable test setup. It is
        # never imported by PublicCliConsumer or a consumer subprocess.
        from tests.workflow.test_workflow_run import _write_bundle

        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        _write_bundle(self.root, phase="READY", task_status="READY")
        self.consumer = PublicCliConsumer(self.executable, self.root)
        self.consumer.negotiate(versions=tuple(CASES["testedVersions"]), schema=CASES["versionSchema"])

    def project(self, operation: str) -> tuple[list[str], dict]:
        args = self.consumer.continue_args(operation)
        code, receipt = self.consumer.call(args)
        self.assertEqual(code, 0)
        self.assertEqual(receipt["schemaVersion"], CASES["continuationSchema"])
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["mode"], "PROJECT")
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["action"]["schemaVersion"], CASES["actionSchema"])
        state = json.loads((self.root / "run.state.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["action"]["planDigest"], state["planDigest"])
        self.assertEqual(receipt["action"]["sourceRevision"], state["sourceRevision"])
        self.assertEqual(receipt["action"]["operationId"], operation)
        self.assertEqual(receipt["action"]["stateRevision"], state["stateRevision"])
        return args, receipt

    def test_readonly_projection(self) -> None:
        before = _inventory(self.root)
        self.project("readonly-projection")
        self.assertEqual(_inventory(self.root), before)

    def test_guarded_action(self) -> None:
        args, projection = self.project("guarded-action")
        code, applied = self.consumer.apply(args, projection)
        self.assertEqual(code, 0)
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(applied["mode"], "APPLY")
        self.assertTrue(applied["stateWritten"])
        self.assertFalse(applied["modelCallsStarted"])
        self.assertFalse(applied["hostLaunchStarted"])
        event = self.consumer.reconcile_run_start("guarded-action", projection)
        for key, value in applied["appliedEvent"].items():
            self.assertEqual(event[key], value)

    def test_stale_guards(self) -> None:
        args, projection = self.project("stale-guards")
        before = _inventory(self.root)
        for revision, digest, expected in (
            (0, projection["action"]["actionDigest"], CASES["cases"][2]["codes"][0]),
            (1, "f" * 64, CASES["cases"][2]["codes"][1]),
        ):
            with self.subTest(expected=expected):
                code, receipt = self.consumer.call(
                    [
                        *args,
                        "--apply",
                        "--projected-state-revision",
                        str(revision),
                        "--projected-action-digest",
                        digest,
                    ]
                )
                self.assertEqual(code, 0)
                self.assertEqual(receipt["status"], "BLOCKED")
                self.assertEqual(receipt["blockers"][0]["code"], expected)
                self.assertFalse(receipt["stateWritten"])
                self.assertEqual(_inventory(self.root), before)

    def test_missing_required_input(self) -> None:
        args, _ = self.project("missing-input")
        before = _inventory(self.root)
        code, receipt = self.consumer.call([*args, "--apply"])
        self.assertEqual(code, 0)  # Exit zero alone is explicitly insufficient.
        self.assertEqual(receipt["status"], "INPUT_REQUIRED")
        self.assertTrue(receipt["requiredInputs"])
        self.assertFalse(receipt["stateWritten"])
        self.assertEqual(_inventory(self.root), before)

    def test_unattested_usage(self) -> None:
        decision = {
            "schemaVersion": "agent-lifecycle-model-route-decision.v1",
            "operationId": "route-op",
            "phase": "task-implementation",
            "sddTier": "S1",
            "routingPolicy": "balanced",
            "modelClass": "standard-code",
            "allowedFallbackModelClasses": ["strong-reasoning"],
            "targetContextWindow": "8k",
            "requiresUsageReceipt": True,
            "maxBillableTokens": 120000,
            "reasonCodes": ["tier-s1"],
            "profileDigest": "a" * 64,
            "decisionDigest": "b" * 64,
        }
        usage = {
            "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
            "operationId": "route-op",
            "host": "codex",
            "modelClass": "standard-code",
            "providerModelHash": "redacted",
            "routeDecisionDigest": "b" * 64,
            "usage": {
                "inputTokens": 1,
                "outputTokens": 1,
                "billableTokens": 2,
                "cumulativeContextBytes": 10,
                "toolCalls": 0,
                "wallSeconds": 1,
            },
            "attestation": {"source": "host", "status": "MISSING"},
        }
        self.write_json("decision.json", decision)
        self.write_json("usage.json", usage)
        self.refused(
            ["model", "usage-check", "--receipt", "usage.json", "--route-decision", "decision.json"],
            "model-usage-validation-failed",
        )

    def test_critical_model_route(self) -> None:
        self.write_json("routing.json", json.loads((ROOT / "profiles/model-routing-profile.v1.json").read_bytes()))
        self.write_json(
            "host.json",
            {
                "schemaVersion": "agent-lifecycle-host-model-profile.v1",
                "host": "unit-only",
                "profileId": "unqualified-compact",
                "bindings": {
                    "local-compact": {
                        "providerModel": "fixture-compact",
                        "contextWindow": "8k",
                        "capabilities": ["text", "json"],
                        "jsonReliability": "best-effort",
                        "toolUse": "unsupported",
                        "allowedForTiers": ["S0"],
                        "allowedForPhases": ["triage"],
                        "usageAccounting": "host-attested",
                        "dataPolicy": "local-only",
                        "calibrationStatus": "PASSED",
                    }
                },
            },
        )
        self.write_json(
            "request.json",
            {
                "schemaVersion": "agent-lifecycle-model-route-request.v1",
                "operationId": "critical-route",
                "phase": "final-audit",
                "sddTier": "S2",
                "riskFlags": {},
                "capabilityRequirements": ["text", "json", "tool-use", "deep-review"],
                "targetContextWindow": "8k",
                "routingPolicy": "local-only",
                "budgetClass": "normal",
                "userPolicy": {"localModelsAllowed": True, "cloudModelsAllowed": False},
            },
        )
        self.refused(
            ["model", "route", "--profile", "routing.json", "--host-profile", "host.json", "--request", "request.json"],
            "model-route-unsupported",
        )

    def test_lost_reply_reconciles_without_second_mutation(self) -> None:
        args, projection = self.project("lost-reply")
        self.consumer.apply(args, projection)  # Deliberately discard the reply.
        before = _inventory(self.root)
        self.consumer.reconcile_run_start("lost-reply", projection)
        self.consumer.reconcile_run_start("lost-reply", projection)  # Repeated delivery.
        code, receipt = self.consumer.call(self.consumer.continue_args("observe-after-lost-reply", revision=2))
        self.assertEqual(code, 0)
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertEqual(_inventory(self.root), before)
        self.assertEqual(sum("--apply" in call["argv"] for call in self.consumer.calls), 1)
        self.assertEqual(len((self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_incompatible_version_or_schema_refuses_before_mutation(self) -> None:
        args, projection = self.project("incompatible-contract")
        before = _inventory(self.root)
        for versions, schema in (
            (("0.0.0",), CASES["versionSchema"]),
            (tuple(CASES["testedVersions"]), "unknown-version-schema.v99"),
        ):
            with self.subTest(versions=versions, schema=schema):
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.negotiate(versions=versions, schema=schema)
                with self.assertRaises(ConsumerRefusal):
                    self.consumer.apply(args, projection)
        self.assertFalse(any("--apply" in call["argv"] for call in self.consumer.calls))
        self.assertEqual(_inventory(self.root), before)

    def write_json(self, name: str, payload: dict) -> None:
        (self.root / name).write_text(json.dumps(payload), encoding="utf-8")

    def refused(self, args: list[str], expected: str) -> None:
        before = _inventory(self.root)
        code, receipt = self.consumer.call(args)
        self.assertEqual(code, 2)
        self.assertEqual(receipt["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(receipt["code"], expected)
        self.assertEqual(_inventory(self.root), before)


if __name__ == "__main__":
    unittest.main()
