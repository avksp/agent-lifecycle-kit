from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.imports import import_markdown_collection, spec_kit_profile, validate_import_result


class MultiMarkdownImportTests(unittest.TestCase):
    def test_markdown_collection_schema_is_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}
        schema = get_schema("agent-markdown-source-collection.v1")

        self.assertIn("agent-markdown-source-collection.v1", schema_ids)
        self.assertIn("files", schema["required"])
        self.assertIn("collectionDigest", schema["required"])
        self.assertEqual(schema["properties"]["ordering"]["const"], "lexical-relative-posix")

    def test_directory_import_is_deterministic_and_redacts_path_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b-plan.md").write_text("# Plan\n\n- Validate second file.\n", encoding="utf-8")
            (root / "a-requirements.md").write_text("# Requirements\n\n- Review first file.\n", encoding="utf-8")

            first = import_markdown_collection(root, dialect_profile=spec_kit_profile(), target_tokens=4096)
            second = import_markdown_collection(root, dialect_profile=spec_kit_profile(), target_tokens=4096)
            collection = first["markdownCollection"]

            self.assertEqual(validate_import_result(first)["status"], "PASS")
            self.assertEqual(first["importDigest"], second["importDigest"])
            self.assertEqual(collection["sourceKind"], "directory")
            self.assertEqual([item["label"] for item in collection["files"]], ["a-requirements.md", "b-plan.md"])
            self.assertFalse(any(str(root) in item["label"] for item in collection["files"]))
            self.assertEqual(first["candidatePlan"]["status"], "DRAFT")

    def test_directory_import_fails_closed_when_cap_is_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "large.md").write_text("# Large\n\n- " + ("x" * 128), encoding="utf-8")

            result = import_markdown_collection(root, max_input_bytes=32)
            validation = validate_import_result(result)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("markdown-collection-input-cap-exceeded", {item["code"] for item in result["blockers"]})
            self.assertEqual(validation["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
