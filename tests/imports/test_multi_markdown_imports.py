from __future__ import annotations

import contextlib
import errno
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_lifecycle.cli import main
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import _Directory, open_authority_read
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.imports import import_markdown_collection, spec_kit_profile, validate_import_result
from agent_lifecycle.imports.multi_markdown import collect_markdown_collection

DISCOVERY_OWNER = "agent_lifecycle.imports.multi_markdown."


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
            for index in range(100):
                (root / f"entry-{index}.md").write_text("- Requirement", encoding="utf-8")
            yielded = []
            real_scandir = os.scandir

            @contextmanager
            def observed(route):
                with real_scandir(route) as entries:

                    def candidates():
                        for entry in entries:
                            yielded.append(entry.name)
                            yield entry

                    yield candidates()

            with (
                patch(DISCOVERY_OWNER + "os.scandir", observed),
                patch("agent_lifecycle.imports.multi_markdown.open_authority_read") as reader,
            ):
                collection = collect_markdown_collection(root, max_files=2)
            reader.assert_not_called()
            self.assertEqual(len(yielded), 3)
            self.assertEqual(collection["files"], [])
            self.assertEqual(collection["blockers"][0]["code"], "markdown-collection-file-cap-exceeded")
            self.assertEqual(collection["blockers"][0]["fileCount"], 3)

    def assert_discovery_refused(self, source, limit=None, code="markdown-collection-discovery-limit-exceeded"):
        with (
            patch(DISCOVERY_OWNER + "open_authority_read") as reader,
            patch(DISCOVERY_OWNER + "import_planning_text") as planner,
            self.assertRaises(LifecycleError) as caught,
        ):
            import_markdown_collection(source)
        reader.assert_not_called()
        planner.assert_not_called()
        self.assertEqual(caught.exception.code, code)
        if limit is not None:
            self.assertEqual(caught.exception.details["limit"], limit)
        self.assertNotIn(str(source), json.dumps(caught.exception.to_json()))
        return caught.exception

    def test_all_entries_obey_exact_entry_cap_and_overflow_without_metadata_or_content_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(4096):
                (root / f"noise-{index}.txt").touch()
            exact = collect_markdown_collection(root, max_files=1)
            self.assertEqual(exact["blockers"][0]["code"], "markdown-collection-empty")
            (root / "one-more.txt").touch()
            yielded, inspected = [], []
            real_scandir = os.scandir
            real_metadata = _Directory.stat_child

            @contextmanager
            def observed(route):
                with real_scandir(route) as entries:

                    def candidates():
                        for entry in entries:
                            yielded.append(entry.name)
                            yield entry

                    yield candidates()

            def metadata(directory, name):
                if name.startswith("noise-") or name == "one-more.txt":
                    inspected.append(name)
                return real_metadata(directory, name)

            with (
                patch(DISCOVERY_OWNER + "os.scandir", observed),
                patch.object(_Directory, "stat_child", metadata),
            ):
                error = self.assert_discovery_refused(root, "entries")
            self.assertEqual(error.details["cap"], 4096)
            self.assertEqual(len(yielded), 4097)
            self.assertEqual(len(inspected), 4096)

    def test_empty_directories_obey_exact_directory_cap_including_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(255):
                (root / f"empty-{index}").mkdir()
            scanned = []
            real_scandir = os.scandir

            def observed(route):
                scanned.append(route)
                return real_scandir(route)

            with patch(DISCOVERY_OWNER + "os.scandir", observed):
                exact = collect_markdown_collection(root, max_files=1)
            self.assertEqual(exact["blockers"][0]["code"], "markdown-collection-empty")
            self.assertEqual(len(scanned), 256)
            (root / "one-more").mkdir()
            scanned.clear()
            with patch(DISCOVERY_OWNER + "os.scandir", observed):
                error = self.assert_discovery_refused(root, "directories")
            self.assertEqual(error.details["cap"], 256)
            self.assertLessEqual(len(scanned), 256)

    def test_nested_real_corpus_accepts_depth_32_and_refuses_depth_33(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leaf = root
            for _ in range(32):
                leaf = leaf / "d"
                leaf.mkdir()
            source = leaf / "requirement.md"
            source.write_text("- Preserve /api/v1/status and https://example.com/docs.", encoding="utf-8")
            (root / "a.md").write_text("- Review access.", encoding="utf-8")
            (leaf / "noise.txt").write_text("ignored", encoding="utf-8")
            first = import_markdown_collection(root, target_tokens=4096)
            second = import_markdown_collection(root, target_tokens=4096)
            self.assertEqual(validate_import_result(first)["status"], "PASS")
            self.assertEqual(first["importDigest"], second["importDigest"])
            self.assertEqual(first["candidatePlan"]["status"], "DRAFT")
            self.assertTrue(first["freezeBlocked"])
            self.assertEqual(
                [item["label"] for item in first["markdownCollection"]["files"]],
                ["a.md", source.relative_to(root).as_posix()],
            )
            (leaf / "too-deep").mkdir()
            error = self.assert_discovery_refused(root, "depth")
            self.assertEqual(error.details["cap"], 32)

    def test_deadline_is_checked_before_initial_metadata(self) -> None:
        source = Path("not-read")
        with (
            patch(DISCOVERY_OWNER + "time.monotonic", side_effect=[0.0, 5.0]),
            patch.object(Path, "lstat") as metadata,
        ):
            error = self.assert_discovery_refused(source, "seconds")
        metadata.assert_not_called()
        self.assertEqual(error.details["cap"], 5.0)

    def test_cooperative_deadline_is_checked_after_open_next_metadata_and_close(self) -> None:
        for boundary in ("open", "next", "metadata", "close"):
            with self.subTest(boundary=boundary):
                self._assert_cooperative_deadline(boundary)

    def _assert_cooperative_deadline(self, boundary) -> None:
        # Virtual time proves observation after each operation, not OS-call preemption.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.md").write_text("- Review", encoding="utf-8")
            now = [0.0]
            real_scandir = os.scandir
            real_metadata = _Directory.stat_child
            observed = []

            @contextmanager
            def delayed(route):
                with real_scandir(route) as entries:
                    if boundary == "open":
                        now[0] = 5.0

                    def candidates():
                        for entry in entries:
                            observed.append("next")
                            if boundary == "next":
                                now[0] = 5.0

                            yield entry

                    yield candidates()
                if boundary == "close":
                    now[0] = 5.0

            def metadata(directory, name):
                info = real_metadata(directory, name)
                if name == "entry.md":
                    observed.append("metadata")
                    if boundary == "metadata":
                        now[0] = 5.0
                return info

            with (
                patch(DISCOVERY_OWNER + "time.monotonic", side_effect=lambda: now[0]),
                patch(DISCOVERY_OWNER + "os.scandir", delayed),
                patch.object(_Directory, "stat_child", metadata),
            ):
                self.assert_discovery_refused(root, "seconds")
            if boundary == "open":
                self.assertEqual(observed, [])
            if boundary == "next":
                self.assertEqual(observed, ["next"])

    def test_empty_iterator_deadline_and_directory_release_are_checked(self) -> None:
        for boundary in ("empty-next", "directory-release"):
            with self.subTest(boundary=boundary):
                self._assert_empty_iterator_and_release(boundary)

    def _assert_empty_iterator_and_release(self, boundary) -> None:
        from agent_lifecycle.contracts.authority_io import hold_authority_directory

        with tempfile.TemporaryDirectory() as tmp:
            root, now = Path(tmp), [0.0]
            real_scandir = os.scandir

            @contextmanager
            def delayed_empty(route):
                with real_scandir(route) as entries:

                    def candidates():
                        yield from entries
                        if boundary == "empty-next":
                            now[0] = 5.0

                    yield candidates()

            @contextmanager
            def delayed_release(path):
                with hold_authority_directory(path) as held:
                    yield held
                if boundary == "directory-release":
                    now[0] = 5.0

            with (
                patch(DISCOVERY_OWNER + "time.monotonic", side_effect=lambda: now[0]),
                patch(DISCOVERY_OWNER + "os.scandir", delayed_empty),
                patch(DISCOVERY_OWNER + "hold_authority_directory", delayed_release),
            ):
                self.assert_discovery_refused(root, "seconds")

    def test_unreadable_directory_and_entry_metadata_fail_closed(self) -> None:
        for boundary in ("directory", "metadata"):
            with self.subTest(boundary=boundary):
                self._assert_unreadable_discovery(boundary)

    def _assert_unreadable_discovery(self, boundary) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.md").write_text("- Review", encoding="utf-8")
            real_scandir = os.scandir
            real_metadata = _Directory.stat_child

            @contextmanager
            def denied(route):
                if boundary == "directory":
                    raise PermissionError(errno.EACCES, "private path " + str(root))
                with real_scandir(route) as entries:
                    yield entries

            def metadata(directory, name):
                if boundary == "metadata" and name == "entry.md":
                    raise OSError(errno.EIO, "private path " + str(root))
                return real_metadata(directory, name)

            with (
                patch(DISCOVERY_OWNER + "os.scandir", denied),
                patch.object(_Directory, "stat_child", metadata),
            ):
                self.assert_discovery_refused(root, code="markdown-collection-discovery-unavailable")

    def test_reparse_metadata_is_refused_without_descending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "junction"
            child.mkdir()
            (child / "entry.md").write_text("- Review", encoding="utf-8")
            real_scandir = os.scandir
            real_metadata = _Directory.stat_child
            scanned = []

            @contextmanager
            def reparse(route):
                scanned.append(route)
                with real_scandir(route) as entries:
                    yield entries

            def metadata(directory, name):
                actual = real_metadata(directory, name)
                if name == "junction":
                    return SimpleNamespace(st_mode=actual.st_mode, st_file_attributes=0x400)
                return actual

            with (
                patch(DISCOVERY_OWNER + "os.scandir", reparse),
                patch.object(_Directory, "stat_child", metadata),
            ):
                self.assert_discovery_refused(root, code="authority-input-not-regular")
            self.assertEqual(len(scanned), 1)

    def test_queued_directory_replacement_is_detected_before_scanning(self) -> None:
        from agent_lifecycle.contracts.authority_io import hold_authority_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child, moved = root / "child", root / "moved"
            child.mkdir()
            (child / "original.md").write_text("- Review original", encoding="utf-8")
            replacements = []

            @contextmanager
            def replaced(path):
                if path == child:
                    child.rename(moved)
                    child.mkdir()
                    (child / "substitute.md").write_text("- Review substitute", encoding="utf-8")
                    replacements.append(True)
                with hold_authority_directory(path) as held:
                    yield held

            with patch(DISCOVERY_OWNER + "hold_authority_directory", replaced):
                self.assert_discovery_refused(root, code="authority-input-changed")
            self.assertEqual(replacements, [True])

    def test_cli_discovery_overflow_refuses_output_and_raw_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / "source", root / "result.json"
            source.mkdir()
            for index in range(5):
                (source / f"noise-{index}.txt").touch()
            stdout, stderr = StringIO(), StringIO()
            with (
                patch(DISCOVERY_OWNER + "_MAX_DISCOVERY_ENTRIES", 4),
                patch(DISCOVERY_OWNER + "open_authority_read") as reader,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = main(["import", "plan", "--source", str(source), "--out", str(output)])
            reader.assert_not_called()
            self.assertNotEqual(code, 0)
            self.assertFalse(output.exists())
            rendered = stdout.getvalue() + stderr.getvalue()
            self.assertIn("markdown-collection-discovery-limit-exceeded", rendered)
            self.assertNotIn(str(root), rendered)

    def test_cli_native_directory_links_are_refused_at_root_and_within_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, outside = root / "source", root / "outside"
            source.mkdir()
            outside.mkdir()
            marker = outside / "requirement.md"
            marker.write_text("- Review outside", encoding="utf-8")
            link = source / "route"
            if os.name == "nt":
                from tests.contracts.test_authority_io import _set_native_mount_point

                link.mkdir()
                _set_native_mount_point(link, outside)
            else:
                link.symlink_to(outside, target_is_directory=True)
            try:
                for selected in (source, link):
                    with self.subTest(root=selected == source):
                        output = root / "result.json"
                        stdout, stderr = StringIO(), StringIO()
                        with (
                            patch(DISCOVERY_OWNER + "open_authority_read") as reader,
                            contextlib.redirect_stdout(stdout),
                            contextlib.redirect_stderr(stderr),
                        ):
                            code = main(["import", "plan", "--source", str(selected), "--out", str(output)])
                        reader.assert_not_called()
                        self.assertNotEqual(code, 0)
                        self.assertFalse(output.exists())
                        rendered = stdout.getvalue() + stderr.getvalue()
                        self.assertIn("authority-input-not-regular", rendered)
                        self.assertNotIn(str(root), rendered)
                self.assertEqual(marker.read_text(encoding="utf-8"), "- Review outside")
            finally:
                if os.name == "nt":
                    link.rmdir()
                else:
                    link.unlink()

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
            original = source.read_bytes()
            write_errors = []

            @contextmanager
            def replace_during_read(path):
                with open_authority_read(path) as handle:

                    class Reader:
                        def read(self, size):
                            data = handle.read(size)
                            try:
                                source.write_text("- Changed after read", encoding="utf-8")
                            except OSError as error:
                                write_errors.append(error)
                                raise
                            return data

                    yield Reader()

            with (
                patch("agent_lifecycle.imports.multi_markdown.open_authority_read", replace_during_read),
                self.assertRaises(LifecycleError) as caught,
            ):
                collect_markdown_collection(source)
            if write_errors:
                self.assertEqual(len(write_errors), 1)
                error = write_errors[0]
                self.assertEqual(os.name, "nt")
                self.assertIsInstance(error, PermissionError)
                self.assertEqual(error.errno, errno.EACCES)
                winerror = getattr(error, "winerror", None)
                if winerror is not None:
                    self.assertIn(winerror, (5, 32, 33))
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(caught.exception.code, "authority-input-unavailable")
                observation = {"branch": "native-write-denied", "errno": error.errno, "winerror": winerror}
            else:
                self.assertEqual(source.read_bytes(), b"- Changed after read")
                self.assertNotEqual(source.read_bytes(), original)
                self.assertEqual(caught.exception.code, "authority-input-changed")
                observation = {"branch": "native-mutation-detected"}
            print("MULTI_MARKDOWN_NATIVE_MUTATION " + json.dumps(observation, sort_keys=True))

    def test_injected_post_read_descriptor_identity_change_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "entry.md"
            original = b"- Review"
            source.write_bytes(original)
            original_fstat = os.fstat
            read_descriptors = []
            injected = []

            def changed_stat(descriptor):
                actual = original_fstat(descriptor)
                if descriptor in read_descriptors:
                    changed = SimpleNamespace(
                        **{name: getattr(actual, name) for name in dir(actual) if name.startswith("st_")}
                    )
                    changed.st_size += 1
                    injected.append(descriptor)
                    return changed
                return actual

            @contextmanager
            def observe(path):
                with open_authority_read(path) as handle:

                    class Reader:
                        def read(self, size):
                            data = handle.read(size)
                            read_descriptors.append(handle.fileno())
                            return data

                    yield Reader()

            with (
                patch("agent_lifecycle.contracts.authority_io.os.fstat", changed_stat),
                patch("agent_lifecycle.imports.multi_markdown.open_authority_read", observe),
                self.assertRaises(LifecycleError) as caught,
            ):
                collect_markdown_collection(source)
            self.assertEqual(caught.exception.code, "authority-input-changed")
            self.assertEqual(len(read_descriptors), 1)
            self.assertEqual(injected, read_descriptors)
            self.assertEqual(source.read_bytes(), original)

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
