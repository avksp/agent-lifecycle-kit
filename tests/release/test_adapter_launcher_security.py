from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AdapterLauncherSecurityValidatorTests(unittest.TestCase):
    def test_delegated_bound_removals_are_rejected_on_actual_source(self) -> None:
        from tools.release.validate_adapter_launcher_security import _boundary_blockers

        base = ROOT / "src/agent_lifecycle/adapter_sessions"
        mutations = (
            ("codex_exact_prompt.py", "total <= 4_194_304", "True"),
            ("codex_exact_prompt.py", "len(raw) <= _APP_SERVER_MAX_REQUEST_BYTES", "True"),
            (
                "codex_exact_prompt.py",
                "_APP_SERVER_TIMEOUT_SECONDS = 15.0",
                "_APP_SERVER_TIMEOUT_SECONDS = float('inf')",
            ),
            ("codex_exact_prompt.py", "process.wait(timeout=2)", "process.wait()"),
            ("codex_exact_prompt.py", "total=total", "total=0"),
            ("codex_exact_prompt.py", 'message["result"], total', 'message["result"], 0'),
            (
                "codex_exact_prompt.py",
                'stdin = _validated_cast("IO[bytes]", process.stdin)',
                'stdin = _validated_cast("IO[bytes]", process.stdout)',
            ),
            (
                "codex_exact_prompt.py",
                'stdin = _validated_cast("IO[bytes]", process.stdin)',
                '_validated_cast = lambda *_args: None\n        stdin = _validated_cast("IO[bytes]", process.stdin)',
            ),
            ("codex_input_diagnostics.py", "total <= limit", "True"),
            ("codex_input_diagnostics.py", "deadline - time.monotonic()", "15.0"),
            (
                "process.py",
                "    def write() -> None:\n        with failure:\n"
                "            _write_stdin(process, inputs.input_bytes)",
                "    _write_stdin(process, inputs.input_bytes)\n    def write() -> None:\n        pass",
            ),
            ("process.py", "    writer.start()", "    write()\n    writer.start()"),
            ("process.py", 'raise RuntimeError("process capture threads did not terminate")', "pass"),
            (
                "process.py",
                "    if any(reader.is_alive() for reader in readers):\n"
                '        raise RuntimeError("process capture threads did not terminate")\n'
                "    capture.finish(process, readers, grace_seconds)",
                "    capture.finish(process, readers, grace_seconds)\n"
                "    if any(reader.is_alive() for reader in readers):\n"
                '        raise RuntimeError("process capture threads did not terminate")',
            ),
            ("process.py", "writer.join(min(0.02, remaining))", "writer.join()"),
            ("process.py", "if cancelled or remaining <= 0:", "if False:"),
            ("process.py", "state.readers.append(writer)", "pass"),
            ("process.py", 'name="alk-process-stdin", daemon=True', 'name="alk-process-stdin", daemon=False'),
            ("process.py", "or not readers_done", 'or (name != "stdin" and not readers_done)'),
            ("process.py", "remaining = deadline - time.monotonic()", "remaining = 10.0"),
            ("process.py", "_CaptureState(output_limit)", "_CaptureState(1000000000)"),
            ("process.py", "time.monotonic() >= deadline", "False"),
            ("process.py", "deadline_monotonic_ns=deadline_ns", "deadline_monotonic_ns=None"),
        )
        for name, old, new in mutations:
            with self.subTest(file=name, removed=old):
                path = base / name
                source = path.read_text()
                self.assertEqual(_boundary_blockers(path, source), [])
                self.assertIn(old, source)
                blockers = _boundary_blockers(path, source.replace(old, new))
                self.assertIn("adapter-unbounded-process-route", {row["code"] for row in blockers})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = (base / "process.py").read_text()
            capture = (base / "process_capture.py").read_text()
            self.assertIn("chunk[:remaining]", capture)
            (root / "process_capture.py").write_text(capture.replace("chunk[:remaining]", "chunk"))
            blockers = _boundary_blockers(root / "process.py", process)
            self.assertIn("adapter-unbounded-process-route", {row["code"] for row in blockers})

    def test_ordinary_stalled_stdin_obeys_process_deadline(self) -> None:
        from agent_lifecycle.adapter_sessions.process import run_process

        started = time.monotonic()
        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            env=dict(os.environ),
            timeout_seconds=0.1,
            cleanup_grace_seconds=0.1,
            stdin_text="x" * 2_000_000,
        )
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(result["timedOut"])
        self.assertNotEqual(result["status"], "PASS")

    def test_current_launcher_sources_pass_security_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "adapter-launcher-security.json"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    "src/agent_lifecycle/adapter_sessions",
                    "--paths",
                    "src/agent_lifecycle/cli/adapter.py",
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                check=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(payload["schemaVersion"], "agent-adapter-launcher-security-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["requiredInvariants"]["argvArrays"])
        self.assertFalse(payload["requiredInvariants"]["nativeConfigWrites"])

    def test_validator_rejects_shell_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad_launcher.py"
            evidence = root / "evidence.json"
            bad.write_text("subprocess.run(['echo'], shell = (True))\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("adapter-launcher-shell-policy", {item["code"] for item in payload["blockers"]})

    def test_validator_rejects_generic_launcher_process_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "launcher.py"
            evidence = root / "evidence.json"
            bad.write_text("def launch_from_descriptor():\n    return run_process([])\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adapter-generic-launch-process-route", {item["code"] for item in payload["blockers"]})

    def test_validator_rejects_popen_outside_bounded_process_helper(self) -> None:
        payload, result = self._validate_source(
            "bad.py",
            "import subprocess\ndef launch(argv):\n    return subprocess.Popen(argv, shell=False)\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adapter-unbounded-process-route", {item["code"] for item in payload["blockers"]})

    def test_validator_rejects_unbounded_process_helper(self) -> None:
        payload, result = self._validate_source(
            "process.py",
            "import subprocess\n"
            "def _run_bounded_process(argv, env, timeout_seconds, max_input_bytes, max_output_bytes):\n"
            "    process = subprocess.Popen(argv, shell=False, env=env)\n"
            "    return process.wait()\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adapter-unbounded-process-route", {item["code"] for item in payload["blockers"]})

    def test_validator_rejects_unbounded_git_identity_subprocess(self) -> None:
        payload, result = self._validate_source(
            "launcher.py",
            "import subprocess\n"
            "adapter_generic_launch_disabled = 'adapter-generic-launch-disabled'\n"
            "def _git_bytes(root, args):\n"
            "    return subprocess.run(['sh', '-c', 'git status'], shell=False)\n",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adapter-git-identity-process-route", {item["code"] for item in payload["blockers"]})

    def _validate_source(self, name: str, source: str) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / name
            evidence = root / "evidence.json"
            bad.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_adapter_launcher_security.py"),
                    "--paths",
                    str(bad),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))
        return payload, result


if __name__ == "__main__":
    unittest.main()
