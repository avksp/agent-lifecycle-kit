from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest  # noqa: E402
from tools.live_hosts.common import CommandResult  # noqa: E402


RUNNER = ROOT / "adapters/gemini-cli/runner.py"


class GeminiCliRunnerTests(unittest.TestCase):
    def test_run_operation_returns_normalized_host_receipt(self) -> None:
        module = _load_runner()
        calls: list[tuple[list[str], Path | None, float]] = []

        def fake_runner(command: list[str], cwd: Path | None, timeout_seconds: float) -> CommandResult:
            calls.append((command, cwd, timeout_seconds))
            stdout = "\n".join(
                [
                    json.dumps({"type": "system", "session_id": "runner-session", "model": "GLM-5.2"}),
                    json.dumps(
                        {
                            "type": "result",
                            "duration_ms": 200,
                            "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
                        }
                    ),
                ]
            )
            return CommandResult(returncode=0, stdout=stdout, stderr="", wall_seconds=0.2)

        with tempfile.TemporaryDirectory() as tmp:
            request = HostOperationRequest(
                operation_id="gemini-runner-test",
                capability="launch",
                inputs={},
                outputs=[],
                constraints={"model": "glm-5.2"},
            ).to_json()

            receipt = module.run_operation(request, cwd=tmp, timeout_seconds=30, command_runner=fake_runner)

        parsed = HostOperationReceipt.from_json(receipt)
        self.assertEqual(parsed.operation_id, "gemini-runner-test")
        self.assertEqual(parsed.capability, "launch")
        self.assertEqual(parsed.status, "PASS")
        self.assertEqual(parsed.usage["billableTokens"], 16)
        self.assertEqual(parsed.usage["sessionId"], "runner-session")
        self.assertEqual(calls[0][0][calls[0][0].index("--model") + 1], "glm-5.2")
        self.assertIn("--skip-trust", calls[0][0])
        self.assertIn("--approval-mode", calls[0][0])
        self.assertNotIn("--safe-mode", calls[0][0])
        self.assertEqual(calls[0][2], 30)

    def test_run_operation_fails_closed_when_usage_is_missing(self) -> None:
        module = _load_runner()
        request = HostOperationRequest(
            operation_id="gemini-runner-missing-usage",
            capability="launch",
            inputs={},
            outputs=[],
            constraints={},
        ).to_json()

        with self.assertRaises(LifecycleError) as raised:
            module.run_operation(
                request,
                command_runner=lambda command, cwd, timeout_seconds: CommandResult(
                    returncode=0,
                    stdout=json.dumps({"type": "result", "duration_ms": 200}),
                    stderr="",
                    wall_seconds=0.2,
                ),
            )

        self.assertEqual(raised.exception.code, "adapter-usage-attestation-missing")


def _load_runner():
    spec = importlib.util.spec_from_file_location("gemini_cli_adapter_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise AssertionError("failed to load gemini-cli runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
