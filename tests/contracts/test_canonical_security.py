from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import traceback
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    canonical_bytes,
    canonical_digest,
    load_json_object,
    read_json_object,
    write_json_create,
    write_json_create_private,
)


class CanonicalSecurityTests(unittest.TestCase):
    def test_duplicate_members_are_rejected_without_input_in_diagnostics(self) -> None:
        payloads = (
            b'{"actor":"worker","actor":"reviewer"}',
            b'{"nested":{"actor":1,"actor":2}}',
            b'{"list":[{"actor":1,"a\\u0063tor":2}]}',
            b'{"/private/sensitive-key":"sensitive-value","/private/sensitive-key":false}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                try:
                    load_json_object(payload)
                except LifecycleError as exc:
                    self.assertEqual(exc.code, "invalid-json")
                    self.assertEqual(exc.message, "JSON input is invalid")
                    self.assertIsNone(exc.__cause__)
                    self.assertTrue(exc.__suppress_context__)
                    diagnostic = "".join(traceback.format_exception(exc)) + json.dumps(exc.to_json())
                    self.assertNotIn("sensitive-key", diagnostic)
                    self.assertNotIn("sensitive-value", diagnostic)
                    self.assertNotIn("duplicate JSON member", diagnostic)
                else:
                    self.fail("ambiguous JSON was accepted")

    def test_distinct_members_preserve_canonical_bytes_and_digest(self) -> None:
        value = load_json_object(b'{"z":[{"a":1},{"a":2}],"a":true}')
        self.assertEqual(canonical_bytes(value), b'{"a":true,"z":[{"a":1},{"a":2}]}')
        expected = hashlib.sha256(b'{"a":true,"z":[{"a":1},{"a":2}]}').hexdigest()
        self.assertEqual(canonical_digest(value), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            write_json_create(path, value)
            self.assertEqual(path.read_bytes(), b'{"a":true,"z":[{"a":1},{"a":2}]}\n')

    def test_parser_error_chain_does_not_echo_invalid_utf8_payload(self) -> None:
        payload = b'{"/private/sensitive-key":"sensitive-value\xff"}'
        try:
            load_json_object(payload)
        except LifecycleError as exc:
            self.assertEqual(exc.code, "invalid-json")
            diagnostic = "".join(traceback.format_exception(exc))
            self.assertNotIn("UnicodeDecodeError", diagnostic)
            self.assertNotIn("sensitive-key", diagnostic)
            self.assertNotIn("sensitive-value", diagnostic)
        else:
            self.fail("invalid UTF-8 was accepted")

    def test_duplicate_file_read_preserves_input_and_creates_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            payload = b'{"stateRevision":1,"stateRevision":2}'
            path.write_bytes(payload)
            with self.assertRaises(LifecycleError) as raised:
                read_json_object(path)
            self.assertEqual(raised.exception.code, "invalid-json")
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_json_input_is_bounded_and_unicode_is_preserved(self) -> None:
        self.assertEqual(load_json_object('{"message":"Привет"}'.encode())["message"], "Привет")
        with self.assertRaisesRegex(LifecycleError, "byte limit") as raised:
            load_json_object(b'{"value":"' + b"x" * MAX_JSON_INPUT_BYTES + b'"}')
        self.assertEqual(raised.exception.code, "json-input-too-large")

    def test_json_depth_syntax_non_object_and_nonfinite_values_fail_structured(self) -> None:
        nested: dict[str, object] = {"leaf": True}
        for _ in range(MAX_JSON_NESTING + 1):
            nested = {"child": nested}
        with self.assertRaises(LifecycleError) as raised:
            load_json_object(json.dumps(nested).encode("utf-8"))
        self.assertEqual(raised.exception.code, "json-input-depth-exceeded")

        for payload, code in ((b"{", "invalid-json"), (b"[]", "invalid-json-object")):
            with self.subTest(code=code), self.assertRaises(LifecycleError) as raised:
                load_json_object(payload)
            self.assertEqual(raised.exception.code, code)

        with self.assertRaises(LifecycleError) as raised:
            canonical_bytes({"value": float("nan")})
        self.assertEqual(raised.exception.code, "json-output-invalid")

    def test_read_json_object_does_not_read_beyond_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversized.json"
            path.write_bytes(b"{" + b"x" * (MAX_JSON_INPUT_BYTES + 1))
            with self.assertRaises(LifecycleError) as raised:
                read_json_object(path)
        self.assertEqual(raised.exception.code, "json-input-too-large")
        self.assertNotIn(tmp, str(raised.exception))

    @unittest.skipUnless(os.name != "nt", "POSIX mode contract only")
    def test_private_json_writer_uses_exact_owner_only_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            old_umask = os.umask(0)
            try:
                write_json_create_private(root / "state.json", {"status": "PASS"})
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), PRIVATE_DIRECTORY_MODE)
            self.assertEqual(stat.S_IMODE((root / "state.json").stat().st_mode), PRIVATE_FILE_MODE)

    @unittest.skipUnless(os.name != "nt", "POSIX mode contract only")
    def test_alk_json_writer_applies_private_contract_to_qualification_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alk_root = Path(tmp) / ".alk"
            path = alk_root / "context" / "checkpoints" / "qualification.json"
            old_umask = os.umask(0)
            try:
                write_json_create(path, {"status": "PASS"})
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(alk_root.stat().st_mode), PRIVATE_DIRECTORY_MODE)
            self.assertEqual(stat.S_IMODE((alk_root / "context").stat().st_mode), PRIVATE_DIRECTORY_MODE)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), PRIVATE_DIRECTORY_MODE)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), PRIVATE_FILE_MODE)


if __name__ == "__main__":
    unittest.main()
