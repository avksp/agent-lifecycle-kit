from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol.inspection import CommandRun, inspect_adapter_descriptor

ROOT = Path(__file__).resolve().parents[2]


class HostProtocolInspectionTests(unittest.TestCase):
    def test_opencode_inspection_detects_safe_cli_capabilities_without_live_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path = root / "adapters/opencode/adapter.descriptor.json"
            descriptor_path.parent.mkdir(parents=True)
            descriptor = json.loads((ROOT / "adapters/opencode/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            shutil.copyfile(ROOT / "adapters/opencode/inspection_profile.py", descriptor_path.parent / "inspection_profile.py")
            (root / "opencode.json").write_text(
                json.dumps({"plugin": ["./adapters/opencode/plugins/agent-lifecycle-kit.js"]}),
                encoding="utf-8",
            )
            (descriptor_path.parent / "opencode.json").write_text(
                json.dumps({"plugin": ["./plugins/agent-lifecycle-kit.js"]}),
                encoding="utf-8",
            )

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                self.assertEqual(timeout_seconds, 3.0)
                if command[1:] == ["--version"]:
                    return CommandRun(0, "opencode 1.18.9\n", "")
                if command[1:] == ["auth", "--help"]:
                    return CommandRun(0, "Usage: opencode auth login logout\n", "")
                if command[1:] == ["run", "--help"]:
                    return CommandRun(0, "Usage: opencode run --format json --dir DIR --auto --model MODEL\n", "")
                if command[1:] == ["export", "--help"]:
                    return CommandRun(0, "Usage: opencode export\n", "")
                if command[1:] == ["stats", "--help"]:
                    return CommandRun(0, "Usage: opencode stats\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin="/tmp/fake-opencode",
                project_root=root,
                timeout_seconds=3.0,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["schemaVersion"], "agent-host-adapter-inspection.v1")
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "opencode")
            self.assertEqual(payload["maturity"], "VERIFIED")
            self.assertFalse(payload["liveCallsStarted"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertEqual(payload["capabilities"]["hostVersion"], "opencode 1.18.9")
            self.assertEqual(payload["capabilities"]["headlessExecution"]["status"], "SUPPORTED")
            self.assertEqual(payload["capabilities"]["permissionMode"]["autoApproveFlag"], "--auto")
            self.assertTrue(payload["capabilities"]["usageAttestation"]["requiresLiveReceipt"])
            self.assertEqual(payload["capabilities"]["authState"]["status"], "NOT_DISCLOSED")
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-opencode")
            self.assertEqual(len(calls), 5)
            self.assertFalse(any(str(root) in json.dumps(check) for check in payload["checks"]))

    def test_opencode_inspection_fails_closed_when_required_run_flags_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path = root / "adapters/opencode/adapter.descriptor.json"
            descriptor_path.parent.mkdir(parents=True)
            descriptor = json.loads((ROOT / "adapters/opencode/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            shutil.copyfile(ROOT / "adapters/opencode/inspection_profile.py", descriptor_path.parent / "inspection_profile.py")
            (root / "opencode.json").write_text(
                json.dumps({"plugin": ["./adapters/opencode/plugins/agent-lifecycle-kit.js"]}),
                encoding="utf-8",
            )
            (descriptor_path.parent / "opencode.json").write_text(
                json.dumps({"plugin": ["./plugins/agent-lifecycle-kit.js"]}),
                encoding="utf-8",
            )

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                if command[1:] == ["--version"]:
                    return CommandRun(0, "opencode 1.18.9\n", "")
                if command[1:] == ["auth", "--help"]:
                    return CommandRun(0, "Usage: opencode auth login logout\n", "")
                if command[1:] == ["run", "--help"]:
                    return CommandRun(0, "Usage: opencode run\n", "")
                return CommandRun(0, "Usage: ok\n", "")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin="opencode",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "FAIL")
            codes = {item["code"] for item in payload["blockers"]}
            self.assertIn("opencode-headless-run-unavailable", codes)
            run_check = next(item for item in payload["checks"] if item["name"] == "opencode-run-help")
            self.assertIn("--format", run_check["details"]["missingMarkers"])

    def test_hermes_inspection_detects_safe_cli_and_projection_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path = root / "adapters/hermes/adapter.descriptor.json"
            descriptor_path.parent.mkdir(parents=True)
            descriptor = json.loads((ROOT / "adapters/hermes/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            shutil.copyfile(ROOT / "adapters/hermes/inspection_profile.py", descriptor_path.parent / "inspection_profile.py")
            shutil.copyfile(ROOT / "adapters/hermes/hermes.registry.json", descriptor_path.parent / "hermes.registry.json")
            shutil.copyfile(ROOT / "adapters/hermes/slash-commands.json", descriptor_path.parent / "slash-commands.json")
            shutil.copyfile(ROOT / "skills.sh.json", root / "skills.sh.json")

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                if command[1:] == ["--version"]:
                    return CommandRun(0, "Hermes Agent v0.19.0 (2026.7.20)\nInstall directory: /tmp/redacted\n", "")
                if command[1:] == ["--help"]:
                    return CommandRun(0, "usage: hermes --oneshot --usage-file --model --provider --yolo --safe-mode skills auth status\n", "")
                if command[1:] == ["chat", "--help"]:
                    return CommandRun(0, "usage: hermes chat --query --model --provider --toolsets --skills --yolo --safe-mode\n", "")
                if command[1:] == ["skills", "--help"]:
                    return CommandRun(0, "usage: hermes skills install list check\n", "")
                if command[1:] == ["auth", "--help"]:
                    return CommandRun(0, "usage: hermes auth status list logout\n", "")
                if command[1:] == ["status", "--help"]:
                    return CommandRun(0, "usage: hermes status --all redacted\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin="/tmp/fake-hermes",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "hermes")
            self.assertEqual(payload["maturity"], "VERIFIED")
            self.assertEqual(payload["capabilities"]["hostVersion"], "Hermes Agent v0.19.0 (2026.7.20)")
            self.assertEqual(payload["capabilities"]["headlessExecution"]["command"], "--oneshot")
            self.assertEqual(payload["capabilities"]["usageAttestation"]["source"], "usage-file")
            self.assertEqual(payload["capabilities"]["skillDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["authState"]["status"], "NOT_DISCLOSED")
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-hermes")
            self.assertEqual(len(calls), 6)
            self.assertFalse(any(str(root) in json.dumps(check) for check in payload["checks"]))

    def test_cursor_inspection_redacts_account_and_model_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path = root / "adapters/cursor/adapter.descriptor.json"
            descriptor_path.parent.mkdir(parents=True)
            descriptor = json.loads((ROOT / "adapters/cursor/adapter.descriptor.json").read_text(encoding="utf-8"))
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            shutil.copyfile(ROOT / "adapters/cursor/inspection_profile.py", descriptor_path.parent / "inspection_profile.py")
            root_plugin = root / ".cursor-plugin"
            root_plugin.mkdir()
            shutil.copyfile(ROOT / ".cursor-plugin/plugin.json", root_plugin / "plugin.json")
            adapter_plugin = descriptor_path.parent / ".cursor-plugin"
            adapter_plugin.mkdir()
            shutil.copyfile(ROOT / "adapters/cursor/.cursor-plugin/plugin.json", adapter_plugin / "plugin.json")

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                if command[1:] == ["agent", "--version"]:
                    return CommandRun(0, "2026.07.23-e383d2b\n", "")
                if command[1:] == ["agent", "--help"]:
                    return CommandRun(
                        0,
                        "Usage: cursor agent --print --output-format stream-json --model --force --yolo --auto-review --workspace --plugin-dir status models about\n",
                        "",
                    )
                if command[1:] == ["agent", "status", "--help"]:
                    return CommandRun(0, "Usage: cursor agent status --format json\n", "")
                if command[1:] == ["agent", "about", "--help"]:
                    return CommandRun(0, "Usage: cursor agent about --format json\n", "")
                if command[1:] == ["agent", "about"]:
                    return CommandRun(
                        0,
                        "About Cursor CLI\nCLI Version 2026.07.23-e383d2b\nSubscription Tier   Free\nUser Email user@example.com\n",
                        "",
                    )
                if command[1:] == ["agent", "models"]:
                    return CommandRun(0, "Available models\na - Model A\nb - Model B\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin="/tmp/fake-cursor",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "cursor")
            self.assertEqual(payload["maturity"], "EXPERIMENTAL")
            self.assertEqual(payload["capabilities"]["hostVersion"], "2026.07.23-e383d2b")
            self.assertEqual(payload["capabilities"]["subscriptionConstraints"]["tier"], "Free")
            self.assertFalse(payload["capabilities"]["subscriptionConstraints"]["boundedSmokeCanPromote"])
            self.assertEqual(payload["capabilities"]["authState"]["status"], "LOGGED_IN_REDACTED")
            self.assertTrue(payload["capabilities"]["modelCatalog"]["modelNamesRedacted"])
            self.assertEqual(payload["capabilities"]["modelCatalog"]["modelCount"], 2)
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-cursor")
            self.assertEqual(len(calls), 6)
            rendered_checks = json.dumps(payload["checks"])
            self.assertNotIn("user@example.com", rendered_checks)
            self.assertFalse(str(root) in rendered_checks)

    def test_gemini_cli_inspection_detects_safe_cli_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/gemini-cli"
            shutil.copytree(ROOT / "adapters/gemini-cli", adapter_root)
            descriptor = json.loads((adapter_root / "adapter.descriptor.json").read_text(encoding="utf-8"))

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                if command[1:] == ["--version"]:
                    return CommandRun(0, "0.46.0\n", "")
                if command[1:] == ["--help"]:
                    return CommandRun(
                        0,
                        "Usage: gemini --prompt --output-format stream-json --model --yolo --approval-mode --sandbox --worktree skills mcp extensions\n",
                        "",
                    )
                if command[1:] == ["skills", "--help"]:
                    return CommandRun(0, "gemini skills list install enable disable\n", "")
                if command[1:] == ["extensions", "--help"]:
                    return CommandRun(0, "gemini extensions install validate list\n", "")
                if command[1:] == ["mcp", "--help"]:
                    return CommandRun(0, "gemini mcp add list enable disable\n", "")
                if command[1:] == ["gemma", "--help"]:
                    return CommandRun(0, "gemini gemma setup start status\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=adapter_root / "adapter.descriptor.json",
                host_bin="/tmp/fake-gemini",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "gemini-cli")
            self.assertEqual(payload["maturity"], "EXPERIMENTAL")
            self.assertEqual(payload["capabilities"]["hostVersion"], "0.46.0")
            self.assertEqual(payload["capabilities"]["headlessExecution"]["command"], "--prompt")
            self.assertEqual(payload["capabilities"]["usageAttestation"]["status"], "UNPROVEN")
            self.assertEqual(payload["capabilities"]["skillDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["localModelRouting"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["authState"]["status"], "NOT_PROBED")
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-gemini")
            self.assertEqual(len(calls), 6)
            self.assertFalse(str(root) in json.dumps(payload["checks"]))

    def test_qwen_code_inspection_detects_safe_cli_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/qwen-code"
            shutil.copytree(ROOT / "adapters/qwen-code", adapter_root)
            descriptor = json.loads((adapter_root / "adapter.descriptor.json").read_text(encoding="utf-8"))

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                if command[1:] == ["--version"]:
                    return CommandRun(0, "0.21.0\n", "")
                if command[1:] == ["--help"]:
                    return CommandRun(
                        0,
                        (
                            "Usage: qwen --prompt --output-format stream-json --model --fallback-model "
                            "--safe-mode --sandbox --continue --resume mcp extensions sessions serve\n"
                        ),
                        "",
                    )
                if command[1:] == ["extensions", "--help"]:
                    return CommandRun(0, "qwen extensions install uninstall list update disable enable\n", "")
                if command[1:] == ["mcp", "--help"]:
                    return CommandRun(0, "qwen mcp add remove list reconnect approve reject\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=adapter_root / "adapter.descriptor.json",
                host_bin="/tmp/fake-qwen",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "qwen-code")
            self.assertEqual(payload["maturity"], "VERIFIED")
            self.assertEqual(payload["capabilities"]["hostVersion"], "0.21.0")
            self.assertEqual(payload["capabilities"]["headlessExecution"]["command"], "--prompt")
            self.assertEqual(payload["capabilities"]["usageAttestation"]["status"], "UNPROVEN")
            self.assertEqual(payload["capabilities"]["resourceCaps"]["status"], "NOT_DISCOVERED")
            self.assertEqual(payload["capabilities"]["extensionDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["mcpDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["authState"]["status"], "NOT_PROBED")
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-qwen")
            self.assertEqual(len(calls), 4)
            self.assertFalse(str(root) in json.dumps(payload["checks"]))

    def test_kimi_code_inspection_detects_safe_cli_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/kimi-code"
            shutil.copytree(ROOT / "adapters/kimi-code", adapter_root)
            descriptor = json.loads((adapter_root / "adapter.descriptor.json").read_text(encoding="utf-8"))

            calls: list[list[str]] = []

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                calls.append(command)
                if command[1:] == ["--version"]:
                    return CommandRun(0, "0.30.0\n", "")
                if command[1:] == ["--help"]:
                    return CommandRun(
                        0,
                        (
                            "Usage: kimi --prompt --output-format stream-json --model --yolo --auto "
                            "--skills-dir --session --continue --plan export provider acp login doctor\n"
                        ),
                        "",
                    )
                if command[1:] == ["provider", "--help"]:
                    return CommandRun(0, "kimi provider add remove list catalog\n", "")
                if command[1:] == ["export", "--help"]:
                    return CommandRun(0, "kimi export sessionId --output --yes\n", "")
                if command[1:] == ["acp", "--help"]:
                    return CommandRun(0, "Run kimi-code as an Agent Client Protocol server over stdio --login\n", "")
                if command[1:] == ["doctor", "--help"]:
                    return CommandRun(0, "kimi doctor config tui\n", "")
                return CommandRun(1, "", "unexpected command")

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=adapter_root / "adapter.descriptor.json",
                host_bin="/tmp/fake-kimi",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["host"], "kimi-code")
            self.assertEqual(payload["maturity"], "EXPERIMENTAL")
            self.assertEqual(payload["capabilities"]["hostVersion"], "0.30.0")
            self.assertEqual(payload["capabilities"]["headlessExecution"]["command"], "--prompt")
            self.assertEqual(payload["capabilities"]["usageAttestation"]["status"], "UNPROVEN")
            self.assertEqual(payload["capabilities"]["permissionMode"]["autoFlag"], "--auto")
            self.assertEqual(payload["capabilities"]["skillDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["providerDiscovery"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["agentProtocol"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["resultExport"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["configurationValidation"]["status"], "DISCOVERED")
            self.assertEqual(payload["capabilities"]["hostCommands"]["binary"], "fake-kimi")
            self.assertEqual(len(calls), 6)
            self.assertFalse(str(root) in json.dumps(payload["checks"]))

    def test_kimi_code_inspection_fails_closed_when_binary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter_root = root / "adapters/kimi-code"
            shutil.copytree(ROOT / "adapters/kimi-code", adapter_root)
            descriptor = json.loads((adapter_root / "adapter.descriptor.json").read_text(encoding="utf-8"))

            def fake_runner(command: list[str], timeout_seconds: float) -> CommandRun:
                raise FileNotFoundError(command[0])

            payload = inspect_adapter_descriptor(
                descriptor,
                descriptor_path=adapter_root / "adapter.descriptor.json",
                host_bin="/tmp/fake-kimi-code",
                project_root=root,
                command_runner=fake_runner,
            )

            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["host"], "kimi-code")
            self.assertEqual(payload["maturity"], "EXPERIMENTAL")
            self.assertFalse(payload["liveCallsStarted"])
            self.assertFalse(payload["productionPromotionClaimed"])
            self.assertEqual(payload["capabilities"]["hostCommands"]["status"], "BINARY_MISSING")
            self.assertIsNone(payload["capabilities"]["hostVersion"])
            self.assertIn("kimi-code-binary-unavailable", {item["code"] for item in payload["blockers"]})
            self.assertFalse(str(root) in json.dumps(payload["checks"]))

    def test_generic_inspection_can_skip_host_commands(self) -> None:
        descriptor = json.loads((ROOT / "adapters/codex/adapter.descriptor.json").read_text(encoding="utf-8"))

        payload = inspect_adapter_descriptor(
            descriptor,
            descriptor_path=ROOT / "adapters/codex/adapter.descriptor.json",
            skip_host_commands=True,
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["host"], "codex")
        self.assertEqual(payload["capabilities"]["hostCommands"]["status"], "SKIPPED")
        self.assertEqual(next(item for item in payload["checks"] if item["name"] == "host-command-discovery")["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
