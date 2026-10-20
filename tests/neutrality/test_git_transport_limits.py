from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.changesets.git_io import BoundedProcess
from agent_lifecycle.contracts.performance_limits import DEFAULT_PERFORMANCE_LIMITS
from agent_lifecycle.neutrality.errors import NeutralityError
from agent_lifecycle.neutrality.git_objects import iter_git_objects
from agent_lifecycle.neutrality.policy import load_policy

_FAKE_GIT = r'''
import os, sys, time
mode, role = sys.argv[1:]
oid = "a" * 40
if role == "inventory":
    if mode == "inventory-stall":
        os.write(1, b"a" * 10); time.sleep(5)
    elif mode == "inventory-overflow":
        os.write(1, b"a" * 4096); time.sleep(5)
    else:
        print(oid + " file", flush=True)
        raise SystemExit(9 if mode == "inventory-nonzero" else 0)
else:
    sys.stdin.readline()
    if mode == "header-stall":
        os.write(1, (oid + " blob ").encode()); time.sleep(5)
    elif mode == "header-overflow":
        os.write(1, b"a" * 1000); time.sleep(5)
    elif mode == "stderr-overflow":
        os.write(2, b"e" * 100000); time.sleep(5)
    elif mode == "missing-object":
        print(oid + " missing", flush=True)
    elif mode == "oversized-object":
        print(oid + " blob 513", flush=True); time.sleep(5)
    elif mode in ("short-body", "body-stall"):
        os.write(1, (oid + " blob 10\n").encode() + b"ab")
        if mode == "body-stall": time.sleep(5)
    else:
        delimiter = b"X" if mode == "bad-delimiter" else b"\n"
        os.write(1, (oid + " blob 3\n").encode() + b"abc" + delimiter)
        if mode == "batch-nonzero": raise SystemExit(9)
        if mode == "trailing-data": os.write(1, b"unexpected")
        sys.stdin.read()
'''


class GitTransportLimitTests(unittest.TestCase):
    def test_malformed_short_oversized_stalled_and_failed_helpers_never_finish_a_scan(self) -> None:
        modes = ["inventory-stall", "inventory-overflow", "header-stall", "header-overflow",
                 "stderr-overflow", "missing-object", "oversized-object", "short-body",
                 "body-stall", "bad-delimiter", "batch-nonzero", "inventory-nonzero", "trailing-data"]
        limits = replace(
            DEFAULT_PERFORMANCE_LIMITS, max_full_scan_wall_seconds=1,
            max_git_inventory_bytes=512, max_git_object_bytes=512,
            max_git_expanded_bytes=512, max_git_batch_framing_bytes=1024,
        )
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script = root / "fake_git.py"
                script.write_text(_FAKE_GIT)
                policy_file = root / "policy.json"
                policy_file.write_text(json.dumps({
                    "schemaVersion": "agent-lifecycle-neutrality-policy.v1", "scan": {},
                    "archives": {}, "pathExcludes": [], "localArtifactRoots": [],
                    "denyLiterals": [], "denyRegexes": [],
                }))
                children = []

                def helper(argv, fixture_mode=mode, script_path=script, child_list=children, **kwargs):
                    role = "inventory" if argv[1] == "rev-list" else "batch"
                    transport = BoundedProcess([sys.executable, str(script_path), fixture_mode, role], **kwargs)
                    child_list.append(transport.process)
                    return transport

                started = time.monotonic()
                with (
                    patch("agent_lifecycle.neutrality.git_objects._quote_paths", return_value=True),
                    patch("agent_lifecycle.neutrality.git_objects.DEFAULT_PERFORMANCE_LIMITS", limits),
                    patch("agent_lifecycle.neutrality.git_objects.BoundedProcess", side_effect=helper),
                    self.assertRaises(NeutralityError),
                ):
                    list(iter_git_objects(root, load_policy(policy_file)))
                self.assertLess(time.monotonic() - started, 2.5)
                self.assertEqual(len(children), 2)
                self.assertTrue(all(child.poll() is not None for child in children))
                self.assertTrue(all(child.stdout.closed and child.stderr.closed for child in children))


if __name__ == "__main__":
    unittest.main()
