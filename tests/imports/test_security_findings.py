from __future__ import annotations

import errno
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.imports.security_findings import (
    export_security_findings_sarif,
    import_security_findings,
    validate_security_finding_import,
)


class SecurityFindingImportTests(unittest.TestCase):
    def test_normalized_import_is_untrusted_and_validated(self) -> None:
        payload = import_security_findings(
            {
                "sourceRevision": "source-1",
                "findings": [{"id": "SEC-1", "title": "issue", "severity": "HIGH", "path": "src/a.py"}],
            },
            expected_source_revision="source-1",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["trusted"])
        self.assertEqual(
            validate_security_finding_import(payload, expected_source_revision="source-1")["status"], "PASS"
        )

    def test_stale_and_private_imports_fail_closed(self) -> None:
        payload = import_security_findings(
            {
                "sourceRevision": "old",
                "findings": [{"title": "issue", "severity": "HIGH", "path": "/tmp/private.py"}],
            },
            expected_source_revision="current",
        )
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("security-analysis-source-revision-mismatch", codes)
        self.assertIn("security-analysis-private-locator", codes)

    def test_sarif_export_does_not_claim_trust(self) -> None:
        payload = import_security_findings(
            {"sourceRevision": "source-1", "findings": [{"title": "issue", "severity": "LOW", "path": "src/a.py"}]},
            expected_source_revision="source-1",
        )
        sarif = export_security_findings_sarif(payload["findings"])
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertFalse(sarif["runs"][0]["results"][0]["properties"]["alkTrusted"])

    def test_file_cap_boundary_and_oversized_error_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.json"
            data = json.dumps({"sourceRevision": "source-1", "findings": []}).encode()
            path.write_bytes(data)
            self.assertEqual(import_security_findings(path, max_input_bytes=len(data))["status"], "PASS")
            with self.assertRaises(LifecycleError) as caught:
                import_security_findings(path, max_input_bytes=len(data) - 1)
            self.assertEqual(caught.exception.code, "security-analysis-import-too-large")

    def test_actual_descriptor_read_is_bounded_and_identity_change_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.json"
            path.write_text('{"findings":[]}', encoding="utf-8")
            original = path.read_bytes()
            cap = 64
            reads = []
            write_errors = []

            @contextmanager
            def observe(source, **kwargs):
                with open_authority_read(source, **kwargs) as handle:

                    class Reader:
                        def fileno(self):
                            return handle.fileno()

                        def read(self, size):
                            data = handle.read(size)
                            reads.append((size, len(data)))
                            try:
                                path.write_text('{"findings":[],"changed":true}', encoding="utf-8")
                            except OSError as error:
                                write_errors.append(error)
                                raise
                            return data

                    yield Reader()

            with (
                patch("agent_lifecycle.contracts.authority_io.open_authority_read", observe),
                self.assertRaises(LifecycleError) as caught,
            ):
                import_security_findings(path, max_input_bytes=cap)
            if write_errors:
                self.assertEqual(len(write_errors), 1)
                error = write_errors[0]
                self.assertEqual(os.name, "nt")
                self.assertIsInstance(error, PermissionError)
                self.assertEqual(error.errno, errno.EACCES)
                winerror = getattr(error, "winerror", None)
                if winerror is not None:
                    self.assertIn(winerror, (5, 32, 33))
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(caught.exception.code, "authority-input-unavailable")
                observation = {"branch": "native-write-denied", "errno": error.errno, "winerror": winerror}
            else:
                self.assertEqual(path.read_bytes(), b'{"findings":[],"changed":true}')
                self.assertNotEqual(path.read_bytes(), original)
                self.assertEqual(caught.exception.code, "authority-input-changed")
                observation = {"branch": "native-mutation-detected"}
            print("SECURITY_FINDINGS_NATIVE_MUTATION " + json.dumps(observation, sort_keys=True))
            self.assertEqual(reads[0][0], cap + 1)
            self.assertLessEqual(sum(actual for _, actual in reads), cap + 1)

    def test_injected_post_read_descriptor_identity_change_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.json"
            original = b'{"findings":[]}'
            path.write_bytes(original)
            cap = 64
            original_fstat = os.fstat
            read_descriptors = []
            reads = []
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
            def observe(source, **kwargs):
                with open_authority_read(source, **kwargs) as handle:

                    class Reader:
                        def fileno(self):
                            return handle.fileno()

                        def read(self, size):
                            data = handle.read(size)
                            reads.append((size, len(data)))
                            read_descriptors.append(handle.fileno())
                            return data

                    yield Reader()

            with (
                patch("agent_lifecycle.contracts.authority_io.os.fstat", changed_stat),
                patch("agent_lifecycle.contracts.authority_io.open_authority_read", observe),
                self.assertRaises(LifecycleError) as caught,
            ):
                import_security_findings(path, max_input_bytes=cap)
            self.assertEqual(caught.exception.code, "authority-input-changed")
            self.assertEqual(len(read_descriptors), 1)
            self.assertEqual(injected, read_descriptors)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(reads[0][0], cap + 1)
            self.assertLessEqual(sum(actual for _, actual in reads), cap + 1)

    def test_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real.json"
            target.write_text("{}", encoding="utf-8")
            link = Path(tmp) / "link.json"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(LifecycleError) as caught:
                import_security_findings(link)
            self.assertEqual(caught.exception.code, "authority-input-not-regular")

    def test_nested_secrets_and_revision_labels_are_refused_without_echo(self) -> None:
        secret = "sk-" + "d" * 24
        for payload, revision in [
            ({"findings": [{"description": secret}]}, "source-1"),
            ({"findings": [], "metadata": {"password": "opaque"}}, "source-1"),
            ({"findings": []}, secret),
        ]:
            with self.assertRaises(LifecycleError) as caught:
                import_security_findings(payload, source_revision=revision)
            self.assertEqual(caught.exception.code, "import-sensitive-content")
            self.assertTrue(secret not in str(caught.exception))


if __name__ == "__main__":
    unittest.main()
