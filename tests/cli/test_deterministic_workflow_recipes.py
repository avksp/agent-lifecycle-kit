from __future__ import annotations

import json
import re
import shlex
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from tests.cli.helpers import _run_cli
from tests.workflow.test_continuation_batch import _write_batch_bundle
from tests.workflow.test_workflow_run import _write_bundle

ROOT = Path(__file__).resolve().parents[2]
GUIDE = Path("guides/lifecycle-cookbook.md")


def _commands(language: str = "en") -> list[list[str]]:
    directory = ROOT / "docs" if language == "en" else ROOT / "docs/ru"
    text = (directory / GUIDE).read_text(encoding="utf-8")
    text = text.split("<!-- deterministic-workflow-recipes:begin -->", 1)[1].split(
        "<!-- deterministic-workflow-recipes:end -->", 1
    )[0]
    blocks = re.findall(r"```sh\n(.*?)\n```", text, flags=re.DOTALL)
    return [shlex.split(block.replace("\\\n", " "))[1:] for block in blocks]


def _replace(argv: list[str], option: str, value: str) -> list[str]:
    result = list(argv)
    result[result.index(option) + 1] = value
    return result


def _continue_command(root: Path) -> tuple[list[str], Path]:
    manifest, state = _write_bundle(root, phase="READY", task_status="READY")
    bundle = _write_batch_bundle(root)
    argv = _commands()[2]
    values = {
        "--state": str(state),
        "--manifest": str(manifest),
        "--lock": str(manifest.parent / "plan.lock.json"),
        "--expected-revision": "1",
        "--source-revision": "source",
        "--input-bundle": bundle,
    }
    for option, value in values.items():
        argv = _replace(argv, option, value)
    return argv, state


class DeterministicWorkflowRecipeTests(unittest.TestCase):
    def test_bilingual_commands_create_and_inspect_the_same_canonical_artifact(self) -> None:
        commands = _commands()
        self.assertEqual(commands, _commands("ru"))
        self.assertEqual(len(commands), 3)
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            Path("advisory.json").write_text('{"z":2, "a":1}', encoding="utf-8")
            code, created = _run_cli(commands[0])
            self.assertEqual(code, 0, created)
            artifact = Path("work/advisory.canonical.json")
            self.assertEqual(artifact.read_bytes(), b'{"a":1,"z":2}\n')
            self.assertFalse(created["authoritative"])
            code, inspected = _run_cli(commands[1])
            self.assertEqual(code, 0, inspected)
            self.assertEqual(json.loads(inspected["display"]), {"a": 1, "z": 2})
            self.assertEqual(artifact.read_bytes(), b'{"a":1,"z":2}\n')

    def test_recipe_refuses_missing_input_escape_and_output_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "project"
            root.mkdir()
            with chdir(root):
                command = _commands()[0]
                code, _ = _run_cli(command)
                self.assertEqual(code, 2)
                self.assertFalse(Path("work").exists())
                Path("advisory.json").write_text("{}", encoding="utf-8")
                code, result = _run_cli(_replace(command, "--out", "../escape.json"))
                self.assertEqual(code, 2, result)
                self.assertFalse((parent / "escape.json").exists())
                code, result = _run_cli(command)
                self.assertEqual(code, 0, result)
                output = Path("work/advisory.canonical.json")
                original = output.read_bytes()
                code, _ = _run_cli(command)
                self.assertEqual(code, 2)
                self.assertEqual(output.read_bytes(), original)

    def test_documented_local_chain_stops_before_the_external_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            command, state = _continue_command(root)
            with chdir(root):
                code, result = _run_cli(command)
            self.assertEqual(code, 0, result)
            self.assertEqual(result["appliedCount"], 2)
            self.assertEqual(result["stopReason"], "WAITING")
            self.assertFalse(result["hostLaunchStarted"])
            current = json.loads(state.read_bytes())
            self.assertEqual(current["phase"], "RUNNING")
            self.assertEqual(current["tasks"][0]["status"], "RUNNING")
            self.assertTrue((root / "work/continuation-receipt.json").is_file())

    def test_missing_bundle_and_stale_revision_do_not_mutate_authority(self) -> None:
        cases = (
            ("--input-bundle", "missing.json", "repository-file-missing"),
            ("--expected-revision", "99", "state-revision-mismatch"),
        )
        for option, value, blocker in cases:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                command, state = _continue_command(root)
                original = state.read_bytes()
                with chdir(root):
                    code, result = _run_cli(_replace(command, option, value))
                self.assertEqual(code, 0, result)
                self.assertEqual(result["status"], "STOPPED")
                self.assertEqual(result["stopReason"], "BLOCKED")
                self.assertEqual(result["appliedCount"], 0)
                self.assertEqual(result["blockers"][0]["code"], blocker)
                self.assertFalse(result["modelCallsStarted"])
                self.assertFalse(result["hostLaunchStarted"])
                self.assertEqual(state.read_bytes(), original)
                self.assertFalse((root / "events.jsonl").exists())

    def test_canonical_recipe_section_and_topic_entry_links_are_bilingual(self) -> None:
        self.assertEqual(_commands(), _commands("ru"))
        self.assertEqual(len(_commands()), 3)
        for directory in (ROOT / "docs", ROOT / "docs/ru"):
            book = (directory / GUIDE).read_text(encoding="utf-8")
            topic = (directory / "guides/deterministic-workflow-recipes.md").read_text(encoding="utf-8")
            self.assertIn("lifecycle-cookbook.md#deterministic-workflow-recipes", topic)
            self.assertIn('<a id="deterministic-workflow-recipes"></a>', book)
            self.assertNotIn("```sh", topic)
            self.assertNotIn("](deterministic-workflow-recipes.md)", book)


if __name__ == "__main__":
    unittest.main()
