from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli.dispatch import dispatch
from agent_lifecycle.cli.main import main
from agent_lifecycle.contracts import LifecycleError


class UnknownArgumentsTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_workflow_init_refuses_unknown_flags_before_dispatch_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "not-created" / "run.state.json"
            for extra in (["--dry-run"], ["--pakage-root", "."], ["unexpected-position"]):
                with self.subTest(extra=extra), patch("agent_lifecycle.cli.main.dispatch") as handler:
                    code, payload = self._run(
                        [
                            "workflow",
                            "init",
                            "--state",
                            str(state),
                            "--run-id",
                            "run",
                            "--package-id",
                            "package",
                            *extra,
                        ]
                    )
                self.assertEqual(code, 2)
                self.assertEqual(payload["code"], "cli-unrecognized-arguments")
                handler.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_other_command_families_refuse_unowned_arguments(self) -> None:
        for argv in (
            ["version", "--unexpected"],
            ["task", "compile", "--manifest", "absent.json", "--dry-run"],
            ["plan", "check", "--manifest", "absent.json", "positional"],
        ):
            with self.subTest(argv=argv), patch("agent_lifecycle.cli.main.dispatch") as handler:
                code, payload = self._run(list(argv))
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "cli-unrecognized-arguments")
            handler.assert_not_called()

    def test_unknown_argument_values_are_not_echoed(self) -> None:
        code, payload = self._run(["version", "--token=private-value", "private-position"])
        self.assertEqual(code, 2)
        self.assertNotIn("private-value", json.dumps(payload))
        self.assertNotIn("private-position", json.dumps(payload))
        self.assertEqual(payload["details"], {"argumentCount": 2})

    def test_direct_dispatch_cannot_bypass_the_same_guard(self) -> None:
        with (
            patch("agent_lifecycle.cli.dispatch.dispatch_contracts") as handler,
            self.assertRaises(LifecycleError) as raised,
        ):
            dispatch(argparse.Namespace(command="version"), ["--dry-run"])
        self.assertEqual(raised.exception.code, "cli-unrecognized-arguments")
        handler.assert_not_called()

    def test_start_delegates_to_its_existing_remainder_validator(self) -> None:
        code, payload = self._run(
            [
                "start",
                "--adapter",
                "codex",
                "--text",
                "bounded task",
                "--unexpected",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "start-argument-unknown")

    def test_neutrality_preserves_its_named_delegation(self) -> None:
        with patch("agent_lifecycle.neutrality.cli.main", return_value=0) as delegated:
            self.assertEqual(main(["neutrality", "scan", "--scope", "tracked-release"]), 0)
        delegated.assert_called_once_with(["scan", "--scope", "tracked-release"])

    def test_neutrality_rejects_unknown_arguments_in_its_own_parser(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["neutrality", "--unexpected"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
