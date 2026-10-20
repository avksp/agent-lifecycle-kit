from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.neutrality.errors import NeutralityError
from agent_lifecycle.neutrality.git_objects import _pretty_object, iter_git_objects
from agent_lifecycle.neutrality.policy import load_policy


class GitTreeFormatTests(unittest.TestCase):
    @staticmethod
    def git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=root, input=input_bytes, capture_output=True,
            timeout=5, check=True,
        ).stdout

    def test_pretty_bytes_match_native_git_for_both_object_widths_and_quoting_modes(self) -> None:
        names = [b"plain", b"space name", b"tab\tname", b"line\nname", b'quote"name',
                 b"back\\slash", b"bell\x07name", "日本語".encode(), b"nonutf8-\xff"]
        for object_format in ("sha1", "sha256"):
            with self.subTest(object_format=object_format), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                initialized = subprocess.run(
                    ["git", "init", "--object-format=" + object_format], cwd=root,
                    capture_output=True, timeout=5,
                )
                if initialized.returncode and object_format == "sha256":
                    continue  # The release contract makes this format conditional on Git support.
                self.assertEqual(initialized.returncode, 0)
                self.git(root, "config", "user.email", "alk@example.invalid")
                self.git(root, "config", "user.name", "ALK fixture")
                blob = self.git(root, "hash-object", "-w", "--stdin", input_bytes=b"fixture\n").strip()
                entries = b"".join(b"100644 blob " + blob + b"\t" + name + b"\0" for name in names)
                tree = self.git(root, "mktree", "-z", input_bytes=entries).strip()
                commit = self.git(root, "commit-tree", tree.decode(), "-m", "fixture").strip()
                self.git(root, "update-ref", "refs/heads/fixture", commit.decode())
                policy_file = root / "policy.json"
                policy_file.write_text(json.dumps({
                    "schemaVersion": "agent-lifecycle-neutrality-policy.v1", "scan": {},
                    "archives": {}, "pathExcludes": [], "localArtifactRoots": [],
                    "denyLiterals": [], "denyRegexes": [],
                }))
                raw = self.git(root, "cat-file", "tree", tree.decode())
                for quote_paths in (True, False):
                    with self.subTest(quote_paths=quote_paths):
                        self.git(root, "config", "core.quotepath", str(quote_paths).lower())
                        expected = self.git(root, "cat-file", "-p", tree.decode())
                        self.assertEqual(_pretty_object(raw, "tree", len(tree) // 2, quote_paths), expected)
                        real_popen = subprocess.Popen
                        children: list[subprocess.Popen] = []

                        def capture(*args, child_list=children, launch=real_popen, **kwargs):
                            child = launch(*args, **kwargs)
                            child_list.append(child)
                            return child

                        with patch("agent_lifecycle.changesets.git_io.subprocess.Popen", side_effect=capture):
                            actual = dict(iter_git_objects(root, load_policy(policy_file)))
                        self.assertEqual(actual[tree.decode()], expected)
                        self.assertEqual(len(children), 3)
                        self.assertTrue(all(child.poll() is not None for child in children))

    def test_malformed_tree_width_modes_and_names_fail_explicitly(self) -> None:
        for data, width in [(b"100644 short\0" + b"x" * 19, 20),
                            (b"100644 \0" + b"x" * 20, 20),
                            (b"000000 name\0" + b"x" * 20, 20), (b"", 24)]:
            with self.subTest(width=width, size=len(data)), self.assertRaises(NeutralityError):
                _pretty_object(data, "tree", width)

    def test_quoted_name_expansion_is_bounded_while_rendering(self) -> None:
        data = b"100644 " + b"\xff" * 1000 + b"\0" + b"x" * 20
        with self.assertRaises(NeutralityError):
            _pretty_object(data, "tree", max_bytes=len(data))


if __name__ == "__main__":
    unittest.main()
