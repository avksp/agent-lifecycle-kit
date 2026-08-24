from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import canonical_digest
from tests.project.test_domain_language import _language


def _run(argv: list[str]) -> tuple[int, dict]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, json.loads(output.getvalue())


def _manifest(path: Path, revision: int, description: str) -> None:
    path.write_text(
        json.dumps(
            {
                "package": {"id": "sample"},
                "planRevision": revision,
                "status": "FROZEN",
                "baseRevision": {"ref": "main", "sha": "a" * 40},
                "specification": {"requirements": [{"id": "R1", "description": description}]},
                "workstreams": [],
                "acceptance": {"criteria": []},
                "validation": {},
            }
        ),
        encoding="utf-8",
    )


class DomainLanguageCommandTests(unittest.TestCase):
    def test_check_and_audit_commands_are_optional_read_only_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs/domain-language.json"
            source.parent.mkdir()
            language = _language(old_alias_status="DEPRECATED")
            source.write_text(json.dumps(language, ensure_ascii=False), encoding="utf-8")
            (root / "docs/terms.md").write_text("qualification receipt\n", encoding="utf-8")
            code, checked = _run(["project", "language", "check", "--project-root", str(root), "--file", str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(checked["status"], "PASS")

            code, audit = _run(
                [
                    "project",
                    "language",
                    "audit",
                    "--project-root",
                    str(root),
                    "--file",
                    str(source),
                    "--term-id",
                    "qualification",
                    "--changed-path",
                    "docs/terms.md",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(audit["status"], "DRIFT")
        self.assertTrue(audit["readOnly"])

    def test_plan_delta_can_bind_two_vocabulary_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before_plan = root / "before-plan.json"
            after_plan = root / "after-plan.json"
            before_language = root / "before-language.json"
            after_language = root / "after-language.json"
            _manifest(before_plan, 1, "before")
            _manifest(after_plan, 2, "after")
            before = _language()
            after = _language(revision=2, old_alias_status="DEPRECATED")
            after["terms"][0]["labels"]["en"] = "Capability qualification"
            after["languageDigest"] = canonical_digest(
                {key: value for key, value in after.items() if key != "languageDigest"}
            )
            before_language.write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
            after_language.write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")

            code, delta = _run(
                [
                    "plan",
                    "delta",
                    "--before",
                    str(before_plan),
                    "--after",
                    str(after_plan),
                    "--language-before",
                    str(before_language),
                    "--language-after",
                    str(after_language),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(delta["status"], "PASS")
        self.assertEqual(delta["termChanges"]["renamedTerms"][0]["kind"], "RENAME")
        self.assertTrue(delta["reviewRequired"])


if __name__ == "__main__":
    unittest.main()
