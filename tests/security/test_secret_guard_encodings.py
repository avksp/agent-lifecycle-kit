"""Tracked-file security boundaries, using synthetic credentials only."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.security import test_release_security as guard


class SecretGuardEncodingTests(unittest.TestCase):
    def check_guard(self, raw: bytes, *, refused: bool, name: str = "probe.py") -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(raw)
            with patch.object(guard, "ROOT", root), patch.object(guard, "_git_ls_files", return_value=[name]):
                check = (
                    guard.ReleaseSecurityTests().test_tracked_text_files_do_not_contain_local_paths_or_secret_markers
                )
                if refused:
                    with self.assertRaises(AssertionError) as caught:
                        check()
                    # Neither the fixture credential nor an offending source line may escape.
                    self.assertNotIn("A" * 24, str(caught.exception))
                    self.assertNotIn("opaque-fixture-value", str(caught.exception))
                else:
                    check()

    def test_utf8_and_bom_preserve_known_token_refusal(self) -> None:
        text = "# sk-" + "A" * 24
        for codec in ("utf-8", "utf-8-sig"):
            with self.subTest(codec=codec):
                self.check_guard(text.encode(codec), refused=True)

    def test_utf16_with_either_bom_refuses_known_token(self) -> None:
        text = "# sk-" + "A" * 24
        for bom, codec in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
            with self.subTest(codec=codec):
                self.check_guard(bom + text.encode(codec), refused=True)

    def test_opaque_sensitive_literal_is_refused_without_echo(self) -> None:
        text = 'DB_PASSWORD = "opaque-fixture-value"'
        for codec in ("utf-8", "utf-16"):
            with self.subTest(codec=codec):
                self.check_guard(text.encode(codec), refused=True)

    def test_environment_reference_and_benign_literal_are_not_credentials(self) -> None:
        self.check_guard(b'import os\nDB_PASSWORD = os.environ["DB_PASSWORD"]\nfeature = "enabled"', refused=False)

    def test_public_field_labels_do_not_exempt_other_values(self) -> None:
        self.check_guard(b'CREDENTIAL_PROXY_KEY = "credentialProxy"', refused=True)
        self.check_guard(b'CREDENTIAL_PROXY_KEY = "opaque-fixture-value"', refused=True)
        for name in ("PASSWORD_KEY", "SECRET_KEY"):
            self.check_guard(f'{name} = "{name[:-4].lower()}"'.encode(), refused=True)
        path = "src/agent_lifecycle/host_protocol/sandbox_receipts.py"
        self.check_guard(b'CREDENTIAL_PROXY_KEY = "credentialProxy"', refused=False, name=path)
        self.check_guard(b'CREDENTIAL_PROXY_KEY = "opaque-fixture-value"', refused=True, name=path)

    def test_literal_credentials_in_python_binding_forms(self) -> None:
        forms = [
            'config = {"DB_PASSWORD": "opaque-fixture-value"}',
            'config["DB_PASSWORD"] = "opaque-fixture-value"',
            'connect(DB_PASSWORD="opaque-fixture-value")',
            'client.password = "opaque-fixture-value"',
            'def connect(password="opaque-fixture-value"): pass',
            '(password := "opaque-fixture-value")',
        ]
        for form in forms:
            with self.subTest(form=forms.index(form)):
                self.check_guard(form.encode(), refused=True)

    def test_unquoted_config_and_shared_markers_refuse(self) -> None:
        values = [
            "DB_PASSWORD=opaque-fixture-value",
            "DB_PASSWORD=$opaque-fixture-value",
            "Authorization: Bearer opaque-fixture-value",
            "-----BEGIN EC PRIVATE KEY-----\nsynthetic\n-----END EC PRIVATE KEY-----",
        ]
        for value in values:
            with self.subTest(case=values.index(value)):
                self.check_guard(value.encode(), refused=True, name="probe.txt")

    def test_json_array_and_scalar_strings_use_shared_marker_policy(self) -> None:
        marker = "Bearer " + "array-fixture-value"
        for value in ([marker], {"nested": [marker]}, [[marker]], marker):
            with self.subTest(shape=type(value).__name__):
                self.check_guard(json.dumps(value).encode(), refused=True, name="probe.json")
        self.check_guard(
            json.dumps(["ordinary", {"value": "enabled"}, 1, None]).encode(), refused=False, name="probe.json"
        )

    def test_hyphenated_sensitive_config_labels_follow_shared_policy(self) -> None:
        for label in ("session" + "-token", "client" + "-secret"):
            self.check_guard(f"{label}: opaque-fixture-value".encode(), refused=True, name="probe.txt")
            self.check_guard(f"{label}=${{ENV_VALUE}}".encode(), refused=False, name="probe.env")

    def test_public_oidc_permission_exception_is_exact(self) -> None:
        label = "id" + "-token"
        path = ".github/workflows/publish.yml"
        self.check_guard(f"{label}: write".encode(), refused=False, name=path)
        self.check_guard(f"{label}: opaque-fixture-value".encode(), refused=True, name=path)
        self.check_guard(f"{label}: write".encode(), refused=True, name="other.yml")

    def test_dynamic_bindings_are_not_literal_credentials(self) -> None:
        values = [
            'config = {"DB_PASSWORD": os.environ["DB_PASSWORD"]}',
            'config["DB_PASSWORD"] = read_password()',
            "connect(DB_PASSWORD=read_password())",
        ]
        for value in values:
            self.check_guard(value.encode(), refused=False)
        self.check_guard(b"DB_PASSWORD=${DATABASE_PASSWORD}", refused=False, name="probe.env")
        self.check_guard(b'DB_PASSWORD="${DATABASE_PASSWORD}"', refused=False, name="probe.env")

    def test_shared_redacted_marker_is_exact(self) -> None:
        self.check_guard(b'DB_PASSWORD="<redacted>"', refused=False)
        self.check_guard(b'DB_PASSWORD="<redacted>opaque-fixture-value"', refused=True)

    def test_broken_json_does_not_hide_a_literal_credential(self) -> None:
        self.check_guard(b'{"DB_PASSWORD": "opaque-fixture-value"} trailing', refused=True, name="probe.json")

    def test_fixture_exception_is_bound_to_path_key_and_value(self) -> None:
        name = "tests/benchmarks/fixtures/redaction-leak.json"
        fixture = (guard.ROOT / name).read_bytes()
        self.check_guard(fixture, refused=False, name=name)
        self.check_guard(fixture, refused=True, name="other.json")
        self.check_guard(b'{"api_key": "opaque-fixture-value"}', refused=True, name=name)
        other_key = json.dumps({"password": json.loads(fixture)["api_key"]}).encode()
        self.check_guard(other_key, refused=True, name=name)

    def test_literal_exceptions_cannot_disable_existing_token_rules(self) -> None:
        value = "sk-" + "A" * 24
        exception = ("probe.py", "api_key", hashlib.sha256(value.encode()).hexdigest())
        with patch.object(guard, "INTENTIONAL_LITERAL_FIXTURES", {exception}):
            self.check_guard(f'api_key="{value}"'.encode(), refused=True)

    def test_oversize_text_is_not_silently_skipped(self) -> None:
        self.check_guard(b"#" + b"x" * (2 * 1024 * 1024), refused=True)

    def test_malformed_supported_text_refuses(self) -> None:
        self.check_guard(b"\xff\xfe\x00", refused=True)

    def test_binary_and_bomless_utf16_remain_explicitly_outside_text_claim(self) -> None:
        self.check_guard(b"\x00\x01binary payload", refused=False, name="probe.bin")
        self.check_guard(("# sk-" + "A" * 24).encode("utf-16-le"), refused=False)


if __name__ == "__main__":
    unittest.main()
