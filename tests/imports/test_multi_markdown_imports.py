from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.imports import import_markdown_collection, spec_kit_profile, validate_import_result
from agent_lifecycle.imports.multi_markdown import collect_markdown_collection


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

    def test_file_enumeration_stops_at_cap_plus_one_without_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "entry.md"
            source.write_text("- Requirement", encoding="utf-8")
            yielded = []

            def candidates(_pattern):
                for index in range(100):
                    yielded.append(index)
                    yield source

            with (
                patch.object(Path, "rglob", side_effect=candidates),
                patch("agent_lifecycle.imports.multi_markdown.open_authority_read") as reader,
            ):
                collection = collect_markdown_collection(root, max_files=2)
            reader.assert_not_called()
            self.assertEqual(yielded, [0, 1, 2])
            self.assertEqual(collection["files"], [])
            self.assertEqual(collection["blockers"][0]["code"], "markdown-collection-file-cap-exceeded")
            self.assertEqual(collection["blockers"][0]["fileCount"], 3)

    def test_aggregate_reads_stop_at_byte_cap_plus_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.md", "b.md", "c.md"):
                (root / name).write_bytes(b"x" * 20)
            reads = []

            @contextmanager
            def observe(path):
                with open_authority_read(path) as handle:

                    class Reader:
                        def read(self, size):
                            data = handle.read(size)
                            reads.append((path.name, size, len(data)))
                            return data

                    yield Reader()

            with patch("agent_lifecycle.imports.multi_markdown.open_authority_read", observe):
                result = collect_markdown_collection(root, max_input_bytes=30)
            self.assertEqual(reads, [("a.md", 31, 20), ("b.md", 11, 11)])
            self.assertEqual(result["totalInputBytes"], 31)
            self.assertEqual(result["_combinedText"], "")
            self.assertEqual(result["blockers"][0]["code"], "markdown-collection-input-cap-exceeded")

    def test_exact_byte_cap_allows_empty_remaining_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_bytes(b"- Review")
            (root / "b.md").write_bytes(b"")
            collection = collect_markdown_collection(root, max_input_bytes=8, max_files=2)
            self.assertEqual(collection["blockers"], [])
            self.assertEqual(collection["totalInputBytes"], 8)
            self.assertEqual(collection["fileCount"], 2)

    def test_identity_change_during_content_read_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "entry.md"
            source.write_text("- Review", encoding="utf-8")

            @contextmanager
            def replace_during_read(path):
                with open_authority_read(path) as handle:

                    class Reader:
                        def read(self, size):
                            data = handle.read(size)
                            source.write_text("- Changed after read", encoding="utf-8")
                            return data

                    yield Reader()

            with (
                patch("agent_lifecycle.imports.multi_markdown.open_authority_read", replace_during_read),
                self.assertRaises(LifecycleError) as caught,
            ):
                collect_markdown_collection(source)
            self.assertEqual(caught.exception.code, "authority-input-changed")

    def test_file_and_directory_links_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            (real / "a.md").write_text("- Review", encoding="utf-8")
            for name, target in (("file.md", real / "a.md"), ("directory", real)):
                link = root / name
                try:
                    link.symlink_to(target, target_is_directory=target.is_dir())
                except OSError:
                    self.skipTest("symlinks unavailable")
                with self.assertRaises(LifecycleError):
                    collect_markdown_collection(link)
            with self.assertRaises(LifecycleError):
                collect_markdown_collection(root / "directory" / "a.md")
            with self.assertRaises(LifecycleError):
                collect_markdown_collection(root)

    def test_secret_labels_and_contents_are_never_collected(self) -> None:
        secret = "gh" + "p_" + "e" * 24
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, text in ((secret + ".md", "- Review"), ("safe.md", "- " + secret)):
                source = root / name
                source.write_text(text, encoding="utf-8")
                with self.assertRaises(LifecycleError) as caught:
                    collect_markdown_collection(source)
                self.assertEqual(caught.exception.code, "import-sensitive-content")
                self.assertTrue(secret not in str(caught.exception))
                source.unlink()


if __name__ == "__main__":
    unittest.main()
