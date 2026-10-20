from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDES = (
    "docs/guides/code-review-workflows.md", "docs/guides/review-mesh-workflow.md",
    "docs/ru/code-review-workflows.md", "docs/ru/review-mesh-workflow.md",
)
PARSER = """import argparse,json
p=argparse.ArgumentParser()
p.add_argument('command', choices=['run'])
p.add_argument('message')
p.add_argument('--model',required=True)
p.add_argument('--format',choices=['json'],required=True)
p.add_argument('--title',required=True)
p.add_argument('--file',action='append',required=True)
p.add_argument('--standalone',action='store_true')
print(json.dumps(vars(p.parse_args())))
"""


class OpenCodeExampleTests(unittest.TestCase):
    def test_every_real_guide_example_reaches_an_inert_strict_cli_parser(self) -> None:
        titles = set()
        for guide in GUIDES:
            text = (ROOT / guide).read_text(encoding="utf-8")
            lines = text.splitlines()
            examples = []
            for start, line in enumerate(lines):
                if not line.startswith("python3 -c "):
                    continue
                end = start
                while lines[end].rstrip().endswith("\\"):
                    end += 1
                example = "\n".join(lines[start:end + 1])
                if "opencode run" in example:
                    examples.append(example)
            self.assertGreaterEqual(len(examples), 2, guide)
            families = set()
            for index, example in enumerate(examples):
                with self.subTest(guide=guide, index=index):
                    self.assertIn("timeout=120", example)
                    self.assertIn("uuid.uuid4()", example)
                    self.assertNotRegex(example, r"--file\s")
                    title = f"fixture-{guide}-{index}"
                    command = re.sub(r'--title "[^"\n]+"', f'--title "{title}"', example)
                    command = command.split("\n  >", 1)[0].replace("\\\n", " ").rstrip(" \\")
                    argv = shlex.split(command)
                    position = argv.index("opencode")
                    args = argv[position + 1:]
                    self.assertEqual(args[0], "run")
                    self.assertFalse(args[1].startswith("-"))
                    # A path containing spaces must stay one --file= argument.
                    args = ["--file=fixture with spaces.json" if item.startswith("--file=") else item for item in args]
                    result = subprocess.run([sys.executable, "-c", PARSER, *args], capture_output=True, text=True, timeout=2, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    parsed = json.loads(result.stdout)
                    self.assertIn("reviewer-output.v1", parsed["message"])
                    self.assertEqual(parsed["file"], ["fixture with spaces.json"])
                    self.assertNotIn(parsed["title"], titles)
                    titles.add(parsed["title"])
                    families.add(2 if parsed["standalone"] else 1)
            self.assertEqual(families, {1, 2}, guide)


if __name__ == "__main__":
    unittest.main()
