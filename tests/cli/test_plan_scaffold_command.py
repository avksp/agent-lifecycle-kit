from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from tests.cli.helpers import _run_cli


class PlanScaffoldCommandTests(unittest.TestCase):
    def test_full_package_roundtrip_and_refusals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tasks").mkdir()
            package = root / "tasks/demo"
            args = [
                "plan",
                "scaffold",
                "--repository-root",
                str(root),
                "--out",
                "tasks/demo",
                "--artifact-root",
                "work/demo",
                "--author",
                "author",
                "--owner",
                "owner",
                "--base-ref",
                "main",
                "--base-sha",
                "1" * 40,
            ]
            code, receipt = _run_cli(args)
            self.assertEqual(code, 0, receipt)
            self.assertEqual(receipt["status"], "DRAFT")
            self.assertFalse(receipt["authorityClaimed"])
            self.assertFalse(receipt["modelCallsStarted"])
            self.assertEqual(
                {p.name for p in package.iterdir()},
                {
                    "plan.manifest.json",
                    "specification.md",
                    "00-developer-overview.md",
                    "acceptance-criteria.md",
                    "review-request.md",
                },
            )
            baseline = {p.name: p.read_bytes() for p in package.iterdir()}
            code, refusal = _run_cli(args)
            self.assertEqual((code, refusal["code"]), (2, "scaffold-output-exists"))
            self.assertEqual({p.name: p.read_bytes() for p in package.iterdir()}, baseline)
            manifest = package / "plan.manifest.json"
            code, result = _run_cli(["plan", "check", "--manifest", str(manifest)])
            self.assertEqual(code, 2)
            [blocked] = [b for b in result["details"]["blockers"] if b["code"] == "scaffold-placeholders-unfilled"]
            self.assertEqual(blocked["context"]["names"], receipt["placeholders"])
            content = manifest.read_text(encoding="utf-8")
            for marker in receipt["placeholders"]:
                content = content.replace(marker, marker.removeprefix("ALK_FILL_").lower())
            manifest.write_text(json.dumps(json.loads(content)), encoding="utf-8")
            code, result = _run_cli(["plan", "check", "--manifest", str(manifest)])
            self.assertEqual(code, 0, result)
            code, result = _run_cli(["plan", "verify", "--manifest", str(manifest), "--repository-root", str(root)])
            self.assertEqual(code, 0, result)
            moved = root / "tasks/moved"
            shutil.copytree(package, moved)
            code, result = _run_cli(
                ["plan", "verify", "--manifest", str(moved / manifest.name), "--repository-root", str(root)]
            )
            self.assertEqual(code, 2)
            [error] = result["details"]["verification"]["blockers"]
            self.assertEqual(error["code"], "plan-manifest-path-mismatch")
            self.assertIn("tasks/moved/plan.manifest.json", str(error))
            self.assertIn("tasks/demo", str(error))
            self.assertFalse((root / "work").exists())

    def test_hidden_and_escaping_destinations_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".git").mkdir()
            for out in (".git/plan", "../outside"):
                with self.subTest(out=out):
                    code, _ = _run_cli(
                        [
                            "plan",
                            "scaffold",
                            "--repository-root",
                            str(root),
                            "--out",
                            out,
                            "--artifact-root",
                            "work/demo",
                            "--author",
                            "author",
                            "--owner",
                            "owner",
                            "--base-ref",
                            "main",
                            "--base-sha",
                            "1" * 40,
                        ]
                    )
                    self.assertEqual(code, 2)
            self.assertEqual(list((root / ".git").iterdir()), [])

    def test_scaffold_refuses_without_atomic_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tasks").mkdir()
            with patch(
                "agent_lifecycle.contracts.authority_io._directory_no_replace",
                side_effect=LifecycleError("authority-directory-publish-unavailable", "unsupported filesystem"),
            ):
                code, receipt = _run_cli(
                    [
                        "plan",
                        "scaffold",
                        "--repository-root",
                        str(root),
                        "--out",
                        "tasks/demo",
                        "--artifact-root",
                        "work/demo",
                        "--author",
                        "author",
                        "--owner",
                        "owner",
                        "--base-ref",
                        "main",
                        "--base-sha",
                        "1" * 40,
                    ]
                )
            self.assertEqual((code, receipt["code"]), (2, "authority-directory-publish-unavailable"))
            self.assertEqual(list((root / "tasks").iterdir()), [])
