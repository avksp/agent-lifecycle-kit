from __future__ import annotations

import contextlib
from io import StringIO
import unittest

from agent_lifecycle.cli.parsers import build_parser


class RemovedRunnerCommandTests(unittest.TestCase):
    def test_each_removed_command_is_rejected(self) -> None:
        parser = build_parser()
        for command in ("start", "status", "transition", "stop", "resume"):
            with self.subTest(command=command), contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                parser.parse_args(["runner", command])
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
