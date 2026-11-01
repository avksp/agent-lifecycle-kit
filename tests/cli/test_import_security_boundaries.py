from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.imports.dialect_profiles import external_dialect_profile
from agent_lifecycle.imports.external_dialects import import_external_dialect


class ImportSecurityBoundaryTests(unittest.TestCase):
    def test_cli_portable_paths_caps_and_unsafe_sources(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            source = root / "данные.json"
            source.write_text('{"steps":["small"]}', encoding="utf-8")
            parent_relative = Path(os.path.relpath(child)) / ".." / source.name
            cases = [
                (["plan"], source, 128, 0),
                (["external", "--family", "workflow"], source, 128, 0),
                (["external", "--family", "workflow"], parent_relative, 128, 0),
                (["plan"], source, 8, 2),
                (["external", "--family", "workflow"], source, 8, 2),
                (["external", "--family", "workflow"], root / "CON.json", 128, 2),
                (["external", "--family", "workflow"], root, 128, 2),
            ]
            for i, (command, path, cap, expected) in enumerate(cases):
                with self.subTest(command=command, path=path, cap=cap):
                    output = root / f"result-{i}.json"
                    stdout = StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(StringIO()):
                        code = main(
                            [
                                "import",
                                *command,
                                "--source",
                                str(path),
                                "--max-input-bytes",
                                str(cap),
                                "--out",
                                str(output),
                            ]
                        )
                    self.assertEqual(code, expected)
                    self.assertEqual(output.exists(), expected == 0)
                    if expected == 0:
                        self.assertEqual(json.loads(output.read_text())["status"], "PASS")
                    else:
                        self.assertNotIn(str(root), stdout.getvalue())

    def test_cli_refuses_fine_grained_token_and_cookie_without_output(self) -> None:
        values = ["github" + "_pat_" + "A" * 22 + "_" + "B" * 59, "Cookie: sid=opaque-one; csrf=opaque-two"]
        for value in values:
            for command, content in [
                (["plan"], "- " + value),
                (["external", "--family", "workflow"], json.dumps({"steps": [value]})),
            ]:
                with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                    source, output = Path(tmp) / "source.md", Path(tmp) / "output.json"
                    source.write_text(content, encoding="utf-8")
                    stdout, stderr = StringIO(), StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = main(["import", *command, "--source", str(source), "--out", str(output)])
                    self.assertEqual(code, 2)
                    self.assertFalse(output.exists())
                    self.assertIn("import-sensitive-content", stdout.getvalue())
                    for secret in (value, "opaque-one", "opaque-two"):
                        self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())

    def test_cli_refuses_secret_content_labels_and_nested_text_before_output(self) -> None:
        secret = "sk-proj-" + "f" * 32
        cases = [
            (["plan"], "source.md", "- Review " + secret),
            (["plan"], secret + ".md", "- Review requirement"),
            (["plan", "--dialect", "spec-kit"], "source.md", "- Review " + secret),
            (["external", "--family", "workflow"], "source.json", json.dumps({"steps": [secret]})),
            (["external", "--family", "agent"], secret + ".json", json.dumps({"role": "Reviewer"})),
            (["external", "--family", "agent"], "source.json", json.dumps({"metadata": {"note": secret}})),
            (
                ["external", "--family", "workflow", "--profile", secret],
                "source.json",
                json.dumps({"steps": ["Keep status endpoint"]}),
            ),
            (
                ["external", "--family", "agent", "--profile", secret],
                "source.json",
                json.dumps({"role": "Reviewer"}),
            ),
            (["security-findings"], "source.json", json.dumps({"findings": [{"description": secret}]})),
            (["security-findings"], secret + ".json", json.dumps({"findings": []})),
        ]
        for index, (command, name, content) in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                source, output = Path(tmp) / name, Path(tmp) / "result.json"
                source.write_text(content, encoding="utf-8")
                stdout, stderr = StringIO(), StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(["import", *command, "--source", str(source), "--out", str(output)])
                self.assertNotEqual(code, 0)
                self.assertFalse(output.exists())
                self.assertTrue(secret not in stdout.getvalue() + stderr.getvalue())
                self.assertIn("import-sensitive-content", stdout.getvalue() + stderr.getvalue())

    def test_api_refuses_secret_profile_inputs_before_profile_validation(self) -> None:
        secret = "sk-proj-" + "a" * 32
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.json"
            source.write_text(json.dumps({"steps": ["Keep status endpoint"]}), encoding="utf-8")
            for options in ({"family": "workflow", "profile_id": secret}, {"family": secret}):
                with self.assertRaises(LifecycleError) as caught:
                    import_external_dialect(source, **options)
                self.assertEqual(caught.exception.code, "import-sensitive-content")
                self.assertTrue(secret not in json.dumps(caught.exception.to_json()))

    def test_generated_profile_metadata_is_screened_before_validation(self) -> None:
        secret = "sk-proj-" + "b" * 32
        fields = ["schemaVersion", "dialectId", "dialectKind", "family", "profileId", "mapping"]
        for field in fields:
            with self.subTest(field=field):
                profile = external_dialect_profile("workflow")
                profile[field] = {"nested": [secret]} if field == "mapping" else secret
                with (
                    patch("agent_lifecycle.imports.external_dialects.external_dialect_profile", return_value=profile),
                    patch("agent_lifecycle.imports.external_dialects.validate_external_dialect_profile") as validator,
                    self.assertRaises(LifecycleError) as caught,
                ):
                    import_external_dialect(Path("unread-source.json"), family="workflow")
                validator.assert_not_called()
                self.assertEqual(caught.exception.code, "import-sensitive-content")
                self.assertTrue(secret not in json.dumps(caught.exception.to_json()))

    def test_benign_api_profile_preserves_metadata_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.json"
            source.write_text(json.dumps({"steps": ["Keep status endpoint"]}), encoding="utf-8")
            result = import_external_dialect(source, family="workflow", profile_id="review-team.v1")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["dialectProfile"]["profileId"], "review-team.v1")
            self.assertEqual(result["dialectProfile"]["dialectId"], "external-workflow-review-team.v1")
            self.assertEqual(result["candidatePlan"]["importState"]["sourceDigest"], result["source"]["digest"])
            self.assertTrue(result["freezeBlocked"])

    def test_benign_cli_import_preserves_requirements_provenance_and_draft_gates(self) -> None:
        cases = [
            (["plan"], "- Preserve /api/v1/status and https://example.com/docs."),
            (
                ["external", "--family", "workflow", "--profile", "review-team.v1"],
                json.dumps({"steps": ["Keep status endpoint"]}),
            ),
        ]
        for command, content in cases:
            with tempfile.TemporaryDirectory() as tmp:
                source, output = Path(tmp) / "source.md", Path(tmp) / "result.json"
                source.write_text(content, encoding="utf-8")
                with contextlib.redirect_stdout(StringIO()):
                    code = main(["import", *command, "--source", str(source), "--out", str(output)])
                self.assertEqual(code, 0)
                result = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["source"]["label"], "source.md")
                if command[0] == "external":
                    self.assertEqual(result["dialectProfile"]["profileId"], "review-team.v1")
                candidate = result["candidatePlan"]
                self.assertEqual(candidate["status"], "DRAFT")
                self.assertEqual(candidate["importState"]["sourceDigest"], result["source"]["digest"])
                self.assertTrue(candidate["importState"]["auditRequired"])
                self.assertTrue(candidate["importState"]["freezeBlocked"])
                self.assertTrue(candidate["specification"]["requirements"])


if __name__ == "__main__":
    unittest.main()
