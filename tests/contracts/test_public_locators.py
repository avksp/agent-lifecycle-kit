from __future__ import annotations

import unittest

from agent_lifecycle.contracts.public_locators import (
    MAX_PUBLIC_LOCATOR_BYTES,
    PUBLIC_LOCATOR_SCHEMA,
    normalize_public_locator,
    validate_public_locator,
)


class PublicLocatorTests(unittest.TestCase):
    def test_normalizes_scheme_host_default_port_and_preserves_evidence_path(self) -> None:
        value = "HTTPS://EXAMPLE.COM:443/docs/reference?section=one#intro"

        self.assertEqual(
            normalize_public_locator(value),
            "https://example.com/docs/reference?section=one#intro",
        )

    def test_normalizes_ipv6_and_idna_hosts(self) -> None:
        self.assertEqual(normalize_public_locator("http://[2001:0DB8:0:0::1]:80/a"), "http://[2001:db8::1]/a")
        self.assertEqual(
            normalize_public_locator("https://BÜCHER.example/guide"), "https://xn--bcher-kva.example/guide"
        )

    def test_rejects_unsafe_schemes_credentials_and_invalid_hosts(self) -> None:
        values = {
            "ftp://example.com/file": "public-locator-scheme-unsupported",
            "file:///" + "Users/private/source.md": "public-locator-scheme-unsupported",
            "https://user:password@example.com/private": "public-locator-credentials-forbidden",
            "https:///missing-host": "public-locator-host-required",
            "https://example.com:bad/path": "public-locator-port-invalid",
        }

        for value, code in values.items():
            with self.subTest(value=value):
                result = validate_public_locator(value)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["blockers"][0]["code"], code)

    def test_rejects_control_characters_and_overlong_values(self) -> None:
        control = validate_public_locator("https://example.com/a\nsecret")
        overlong = validate_public_locator("https://example.com/" + "a" * MAX_PUBLIC_LOCATOR_BYTES)

        self.assertEqual(control["blockers"][0]["code"], "public-locator-control-character")
        self.assertEqual(overlong["blockers"][0]["code"], "public-locator-too-large")

    def test_success_report_is_a_registered_contract(self) -> None:
        result = validate_public_locator("https://example.com/reference")

        self.assertEqual(result["schemaVersion"], PUBLIC_LOCATOR_SCHEMA)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["host"], "example.com")
        self.assertFalse(result["productionPromotionClaimed"])


if __name__ == "__main__":
    unittest.main()
