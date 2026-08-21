from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    canonical_bytes,
    load_json_object,
    read_json_object,
    write_json_create_private,
    write_json_create,
)


class CanonicalSecurityTests(unittest.TestCase):
    def test_json_input_is_bounded_and_unicode_is_preserved(self) -> None:
        self.assertEqual(load_json_object('{"message":"Привет"}'.encode("utf-8"))["message"], "Привет")
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
