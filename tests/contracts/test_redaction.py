from __future__ import annotations

import unittest
from urllib.parse import quote

from agent_lifecycle.contracts.redaction import (
    LOCAL_PATH_REDACTION,
    REDACTED_VALUE,
    contains_local_absolute_path,
    redact_text,
    redact_text_with_stats,
    redact_value,
)


class ReceiptRedactionTests(unittest.TestCase):
    def test_additional_provider_tokens_are_redacted_without_assignment_labels(self) -> None:
        tokens = [
            "glpat-" + "A" * 24,
            "npm_" + "B" * 36,
            "sk_live_" + "C" * 24,
            "sk_test_" + "D" * 24,
            "rk_live_" + "E" * 24,
            "rk_test_" + "F" * 24,
            "hf_" + "G" * 34,
            "AIza" + "H" * 35,
        ]
        for token in tokens:
            for value in [token, "diagnostic: " + token + " end"]:
                with self.subTest(prefix=token[:8], embedded=value != token):
                    redacted, changed, stats = redact_text_with_stats(value)
                    self.assertTrue(changed)
                    self.assertEqual(redacted, value.replace(token, REDACTED_VALUE))
                    self.assertEqual(stats["secretLikeMarkersRedacted"], 1)

    def test_additional_provider_tokens_are_redacted_inside_encoded_public_urls(self) -> None:
        tokens = ["glpat-" + "A" * 24, "npm_" + "B" * 36,
                  "sk_live_" + "C" * 24, "hf_" + "D" * 34, "AIza" + "E" * 35]
        for token in tokens:
            for encoding in [0, 1, 2, 3]:
                encoded = token
                for _ in range(encoding):
                    encoded = "".join(f"%{byte:02X}" for byte in encoded.encode())
                for suffix in ["/item/" + encoded, "/?note=" + encoded, "/#note=" + encoded]:
                    with self.subTest(prefix=token[:8], encoding=encoding, suffix=suffix[:10]):
                        redacted, changed, stats = redact_text_with_stats("https://example.invalid" + suffix)
                        self.assertTrue(changed)
                        self.assertNotIn(token, redacted)
                        self.assertNotIn(encoded, redacted)
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_signed_query_values_are_private_but_public_parameters_survive(self) -> None:
        keys = ["sig", "Signature", "X-Amz-Signature", "X-Amz-Credential",
                "X-Amz-Security-Token", "X-Goog-Signature", "X-Goog-Credential",
                "AWSAccessKeyId", "GoogleAccessId"]
        for key in keys:
            for component in ["?", "#", "#/report?"]:
                for encoding in [0, 1, 2, 3]:
                    encoded_key = key
                    for _ in range(encoding):
                        encoded_key = "".join(f"%{byte:02X}" for byte in encoded_key.encode())
                    with self.subTest(key=key, component=component, encoding=encoding):
                        value = "https://example.invalid/report" + component + encoded_key + "=opaque-value&keep=home"
                        redacted, changed, stats = redact_text_with_stats(value)
                        self.assertTrue(changed)
                        self.assertNotIn("opaque-value", redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertIn("example.invalid/report", redacted)
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_public_signatures_publishable_keys_and_benign_query_keys_are_preserved(self) -> None:
        for value in ["pk_live_" + "A" * 24, "pk_test_" + "B" * 24,
                      "https://example.invalid/report?signature_version=4&signed=yes&algorithm=sha256",
                      "https://example.invalid/glpat-guide?topic=npm&model=hf-transformers",
                      "glpat-short npm-short hf-short AIza-short"]:
            with self.subTest(value=value):
                redacted, changed, stats = redact_text_with_stats(value)
                self.assertEqual(redacted, value)
                self.assertFalse(changed)
                self.assertEqual(stats["secretLikeMarkersRedacted"], 0)
        value = {"signature": "public-verification-bytes", "sig": "public-verification-bytes"}
        self.assertEqual(redact_value(value), (value, False))

    def test_encoded_bearer_plus_keeps_the_complete_credential_private(self) -> None:
        for marker in ["Bearer prefix+opaque-auth-secret", "Bearer prefix++opaque-auth-secret", "public+topic", "public topic+tail"]:
            for encoding, safe in [(1, ""), (2, ""), (3, ""), (1, "+"), (2, "+"), (3, "+")]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(marker=marker, encoding=encoding, location=location, safe=safe):
                        encoded = marker
                        for _ in range(encoding):
                            encoded = quote(encoded, safe=safe)
                        suffix = "/note/" + encoded + "?keep=home"
                        if location == "query":
                            suffix = "/?note=" + encoded + "&keep=home"
                        elif location == "fragment":
                            suffix = "/#note=" + encoded + "&keep=home"
                        elif location == "routed-fragment":
                            suffix = "/#/note/" + encoded + "?keep=home"
                        authority = "alice:outer-secret@example.invalid" if marker.startswith("Bearer ") else "example.invalid"
                        text = "before https://" + authority + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        if not marker.startswith("Bearer "):
                            self.assertEqual(redacted, text)
                            self.assertFalse(changed)
                            continue
                        self.assertTrue(changed)
                        self.assertNotIn("opaque-auth-secret", redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_decoded_uri_components_apply_all_common_secret_recognizers(self) -> None:
        markers = [("Bearer opaque-auth-secret", "opaque-auth-secret"),
                   ("sk-abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
                   ("-----BEGIN " + "PRIVATE KEY-----\nprivate-key-body\n-----END PRIVATE KEY-----", "private-key-body"),
                   ("-----BEGIN " + "PRIVATE KEY-----\nhttps://safe.invalid/public\nprivate-key-body\n-----END PRIVATE KEY-----",
                    "private-key-body")]
        for marker, secret in markers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(marker=marker, encoding=encoding, location=location):
                        encoded = marker
                        for _ in range(encoding):
                            encoded = quote(encoded, safe="")
                        suffix = "/note/" + encoded + "?keep=home"
                        if location == "query":
                            suffix = "/?note=" + encoded + "&keep=home"
                        elif location == "fragment":
                            suffix = "/#note=" + encoded + "&keep=home"
                        elif location == "routed-fragment":
                            suffix = "/#/note/" + encoded + "?keep=home"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        self.assertNotIn(secret, redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        for value in ["public topic", "sk-short", "-----BEGIN PUBLIC KEY-----\npublic\n-----END PUBLIC KEY-----"]:
            text = "https://example.invalid/?note=" + quote(value, safe="") + "&keep=home"
            redacted, changed, _stats = redact_text_with_stats(text)
            self.assertEqual(redacted, text)
            self.assertFalse(changed)

    def test_invalid_nested_uri_refusal_cannot_retain_decoded_credential_tail(self) -> None:
        for whitespace in ["/ ", "/" + chr(34), "?" + chr(39), "#<", "#>"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        encoded = "https://bob:first-secret" + whitespace + "second-secret@other.invalid/public"
                        for _ in range(encoding):
                            encoded = quote(encoded, safe="")
                        suffix = "/proxy/" + encoded + "?keep=home"
                        if location == "query":
                            suffix = "/?next=" + encoded + "&keep=home"
                        elif location == "fragment":
                            suffix = "/#next=" + encoded + "&keep=home"
                        elif location == "routed-fragment":
                            suffix = "/#/proxy/" + encoded + "?keep=home"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        for secret in ["first-secret", "second-secret", "outer-secret"]:
                            self.assertNotIn(secret, redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        for delimiter in [chr(34), chr(39), "<", ">"]:
            value = "https://safe.invalid/public" + delimiter + "topic"
            text = "https://example.invalid/?next=" + quote(value, safe="") + "&keep=home"
            redacted, changed, _stats = redact_text_with_stats(text)
            self.assertEqual(redacted, text)
            self.assertFalse(changed)

    def test_decoding_uri_authority_delimiters_cannot_leave_credential_tail(self) -> None:
        for whitespace in [chr(34), chr(39), "<", ">"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        encoded = "https://bob:first-secret" + whitespace + "second-secret@other.invalid/public"
                        for _ in range(encoding):
                            encoded = quote(encoded, safe="")
                        suffix = "/proxy/" + encoded + "?keep=home"
                        if location == "query":
                            suffix = "/?next=" + encoded + "&keep=home"
                        elif location == "fragment":
                            suffix = "/#next=" + encoded + "&keep=home"
                        elif location == "routed-fragment":
                            suffix = "/#/proxy/" + encoded + "?keep=home"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        for secret in ["first-secret", "second-secret", "outer-secret"]:
                            self.assertNotIn(secret, redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        for delimiter in [chr(34), chr(39), "<", ">"]:
            value = "https://safe.invalid/public" + delimiter + "topic"
            text = "https://example.invalid/?next=" + quote(value, safe="") + "&keep=home"
            redacted, changed, _stats = redact_text_with_stats(text)
            self.assertEqual(redacted, text)
            self.assertFalse(changed)

    def test_decoding_uri_authority_whitespace_cannot_leave_credential_tail(self) -> None:
        for whitespace in [" ", "\t", "\n"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        encoded = "https://bob:first-secret" + whitespace + "second-secret@other.invalid/public"
                        for _ in range(encoding):
                            encoded = quote(encoded, safe="")
                        suffix = "/proxy/" + encoded + "?keep=home"
                        if location == "query":
                            suffix = "/?next=" + encoded + "&keep=home"
                        elif location == "fragment":
                            suffix = "/#next=" + encoded + "&keep=home"
                        elif location == "routed-fragment":
                            suffix = "/#/proxy/" + encoded + "?keep=home"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        for secret in ["first-secret", "second-secret", "outer-secret"]:
                            self.assertNotIn(secret, redacted)
                        self.assertIn("keep=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        for value in ["https://safe.invalid/public topic", "public topic"]:
            text = "https://example.invalid/?next=" + quote(value, safe="") + "&keep=home"
            redacted, changed, _stats = redact_text_with_stats(text)
            self.assertEqual(redacted, text)
            self.assertFalse(changed)

    def test_mixed_encoded_container_and_literal_uri_redacts_complete_component(self) -> None:
        containers = ['["first-secret","https://safe.invalid/public","second-secret"]',
                      '{"first":"first-secret","url":"https://safe.invalid/public","second":"second-secret"}']
        for container in containers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "routed-fragment"]:
                    for key in ["credentials", "%2563redentials"]:
                        with self.subTest(container=container, encoding=encoding, location=location, key=key):
                            encoded = container
                            for _ in range(encoding):
                                encoded = quote(encoded, safe=",:/")
                            suffix = "/report;" + key + "=" + encoded + "?next=home"
                            if location == "query":
                                suffix = "/?" + key + "=" + encoded + "&next=home"
                            elif location == "routed-fragment":
                                suffix = "/#/report;" + key + "=" + encoded + "?next=home"
                            text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                            redacted, changed, stats = redact_text_with_stats(text)
                            self.assertTrue(changed)
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, redacted)
                            self.assertIn("next=home", redacted)
                            self.assertTrue(redacted.startswith("before "))
                            self.assertTrue(redacted.endswith(" after"))
                            self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        safe = "https://example.invalid/report;topic=%5B%22public%22,%22https://safe.invalid/public%22%5D?next=home"
        redacted, changed, _stats = redact_text_with_stats(safe)
        self.assertEqual(redacted, safe)
        self.assertFalse(changed)

    def test_encoded_sensitive_containers_preserve_complete_value_boundary(self) -> None:
        containers = ['["first-secret","second-secret"]',
                      '{"first":"first-secret","second":"second-secret"}',
                      '["first-secret","https://safe.invalid/public","second-secret"]']
        for container in containers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "routed-fragment"]:
                    for outer in ["example.invalid", "alice:outer-secret@example.invalid"]:
                        with self.subTest(container=container, encoding=encoding, location=location, outer=outer):
                            encoded = container
                            for _ in range(encoding):
                                encoded = quote(encoded, safe=",")
                            suffix = "/report;credentials=" + encoded + "?next=home"
                            if location == "query":
                                suffix = "/?credentials=" + encoded + "&next=home"
                            elif location == "routed-fragment":
                                suffix = "/#/report;credentials=" + encoded + "?next=home"
                            text = "before https://" + outer + suffix + " after"
                            redacted, changed, stats = redact_text_with_stats(text)
                            self.assertTrue(changed)
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, redacted)
                            self.assertIn("next=home", redacted)
                            self.assertTrue(redacted.startswith("before "))
                            self.assertTrue(redacted.endswith(" after"))
                            self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_mixed_sensitive_assignments_do_not_stop_decoding_remaining_encoded_keys(self) -> None:
        for location in ["/?", "/#/public?"]:
            for encoding in [2, 3]:
                for order in ["encoded-first", "literal-first"]:
                    with self.subTest(location=location, encoding=encoding, order=order):
                        key = "%74oken"
                        for _ in range(encoding - 1):
                            key = quote(key, safe="")
                        encoded = key + "=plain-secret"
                        literal = "password=second-secret"
                        component = encoded + ";" + literal if order == "encoded-first" else literal + ";" + encoded
                        text = "before https://alice:outer-secret@example.invalid" + location + component + "&next=home after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        for secret in ["plain-secret", "second-secret", "outer-secret"]:
                            self.assertNotIn(secret, redacted)
                        self.assertIn("next=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_multiply_encoded_sensitive_query_keys_are_redacted_and_safe_keys_preserved(self) -> None:
        for outer in ["example.invalid", "alice:outer-secret@example.invalid"]:
            for location in ["/?", "/#/public?"]:
                for encoding in [2, 3]:
                    with self.subTest(outer=outer, location=location, encoding=encoding):
                        key = "%74oken"
                        for _ in range(encoding - 1):
                            key = quote(key, safe="")
                        text = "before https://" + outer + location + key + "=plain-secret&next=home after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        self.assertNotIn("plain-secret", redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("next=home", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        safe = "https://example.invalid/?%2574opic=public&next=home"
        redacted, changed, stats = redact_text_with_stats(safe)
        self.assertEqual(redacted, safe)
        self.assertFalse(changed)
        self.assertEqual(stats["secretLikeMarkersRedacted"], 0)

    def test_mixed_literal_and_encoded_nested_urls_do_not_hide_credentials(self) -> None:
        for location in ["path", "query", "routed-fragment"]:
            for encoding in [1, 2]:
                for order in ["encoded-first", "literal-first"]:
                    with self.subTest(location=location, encoding=encoding, order=order):
                        encoded = "https://bob:inner-secret%20suffix@other.invalid/public"
                        for _ in range(encoding):
                            encoded = quote(encoded, safe="")
                        safe = "https://safe.invalid/public"
                        component = encoded + "/" + safe if order == "encoded-first" else safe + "/" + encoded
                        suffix = "/proxy/" + component
                        if location == "query":
                            suffix = "/?next=" + component
                        elif location == "routed-fragment":
                            suffix = "/#/proxy/" + component + "?next=public"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        self.assertNotIn("inner-secret", redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("other.invalid/public", redacted)
                        self.assertIn("safe.invalid/public", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_nested_url_path_credentials_and_work_limits_preserve_surrounding_diagnostics(self) -> None:
        for outer in ["example.invalid", "alice:outer-secret@example.invalid"]:
            for location in ["path", "routed-fragment"]:
                for encoding in [0, 1, 2]:
                    with self.subTest(outer=outer, location=location, encoding=encoding):
                        nested = "https://bob:inner-secret@other.invalid/public"
                        for _ in range(encoding):
                            nested = quote(nested, safe="")
                        suffix = "/proxy/" + nested if location == "path" else "/#/proxy/" + nested + "?next=safe"
                        text = "before https://" + outer + suffix + " after"
                        redacted, changed, stats = redact_text_with_stats(text)
                        self.assertTrue(changed)
                        self.assertNotIn("inner-secret", redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("other.invalid/public", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        for limit in ["depth", "decoding"]:
            with self.subTest(limit=limit):
                nested = "https://bob:deep-secret@other.invalid/public"
                for _ in range(12):
                    nested = "https://safe.invalid/proxy/" + nested if limit == "depth" else quote(nested, safe="")
                text = "before https://example.invalid/proxy/" + nested + " after"
                redacted, changed, stats = redact_text_with_stats(text)
                self.assertTrue(changed)
                self.assertNotIn("deep-secret", redacted)
                self.assertTrue(redacted.startswith("before "))
                self.assertTrue(redacted.endswith(" after"))
                self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_nested_url_credentials_are_redacted_in_literal_and_encoded_queries(self) -> None:
        for outer in ["example.invalid", "alice:outer-secret@example.invalid"]:
            for separator in ["?next=", "#next="]:
                for encoding in [0, 1, 2]:
                    with self.subTest(outer=outer, separator=separator, encoding=encoding):
                        nested = "https://bob:inner-secret@other.invalid/public"
                        for _ in range(encoding):
                            nested = quote(nested, safe="")
                        original = "before https://" + outer + "/" + separator + nested + " after"
                        redacted, changed, stats = redact_text_with_stats(original)
                        self.assertTrue(changed)
                        self.assertNotIn("inner-secret", redacted)
                        self.assertNotIn("outer-secret", redacted)
                        self.assertIn("other.invalid/public", redacted)
                        self.assertTrue(redacted.startswith("before "))
                        self.assertTrue(redacted.endswith(" after"))
                        self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_authentication_parameters_with_semicolons_redact_complete_signature(self) -> None:
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            for signed_headers in ["host;x-amz-date", "host;x-amz-date;x-amz-content-sha256"]:
                with self.subTest(key=key, signed_headers=signed_headers):
                    signature = "e" * 64
                    value = ("AWS4-HMAC-SHA256 Credential=EXAMPLE/20261009/us-east-1/s3/aws4_request, "
                             + "SignedHeaders=" + signed_headers + ", Signature=" + signature)
                    original = "before " + key + ": " + value + "; outcome=failed"
                    redacted, changed, stats = redact_text_with_stats(original)
                    self.assertTrue(changed)
                    self.assertEqual(redacted, "before " + key + ": " + REDACTED_VALUE + "; outcome=failed")
                    self.assertEqual(stats["secretLikeMarkersRedacted"], 1)
                    self.assertEqual(redact_value({"message": original})[0]["message"], redacted)

    def test_folded_authentication_parameters_redact_complete_continuations(self) -> None:
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            for gap in ["\n ", "\r\n ", "\r\n\t", "\t", "\u2003"]:
                for placement in ["after-comma", "before-comma", "around-equals", "after-scheme"]:
                    with self.subTest(key=key, gap=gap, placement=placement):
                        value = "Digest username*=UTF-8''alice, nonce=\"nonce-secret\", response=\"opaque-auth-secret\""
                        if placement == "after-comma":
                            value = value.replace(", ", "," + gap)
                        elif placement == "before-comma":
                            value = value.replace(", ", gap + ", ")
                        elif placement == "around-equals":
                            value = value.replace("=", gap + "=" + gap)
                        else:
                            value = value.replace("Digest ", "Digest" + gap)
                        original = "before " + key + ": " + value + "; outcome=failed"
                        redacted, changed, stats = redact_text_with_stats(original)
                        self.assertTrue(changed)
                        self.assertEqual(redacted, "before " + key + ": " + REDACTED_VALUE + "; outcome=failed")
                        self.assertEqual(stats["secretLikeMarkersRedacted"], 1)
                        self.assertEqual(redact_value({"message": original})[0]["message"], redacted)

    def test_authentication_headers_redact_proxy_opaque_and_digest_credentials(self) -> None:
        credential = "opaque-auth-secret"
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            for value in ["Basic " + credential, "Negotiate " + credential,
                          "CustomScheme " + credential,
                          'Digest username="alice", nonce="nonce-secret", response="' + credential + '"']:
                with self.subTest(key=key, value=value):
                    original = "before " + key + ": " + value + "; outcome=failed"
                    redacted, changed, stats = redact_text_with_stats(original)
                    self.assertTrue(changed)
                    self.assertNotIn(credential, redacted)
                    self.assertNotIn("nonce-secret", redacted)
                    self.assertEqual(redacted, "before " + key + ": " + REDACTED_VALUE + "; outcome=failed")
                    self.assertEqual(stats["secretLikeMarkersRedacted"], 1)
                    nested, changed = redact_value({"safe": "diagnostic", key: value})
                    self.assertTrue(changed)
                    self.assertEqual(nested, {"safe": "diagnostic", key: REDACTED_VALUE})

    def test_basic_authorization_redacts_complete_credential_and_preserves_diagnostics(self) -> None:
        credential = "dXNlcjpwYXNz"
        for header in ["Authorization: Basic ", "authorization=basic\t",
                       '"Authorization": "Basic ', "Authorization : BASIC "]:
            with self.subTest(header=header):
                quote = '"' if header.endswith('"Basic ') else ""
                original = "before " + header + credential + quote + "; outcome=failed"
                redacted, changed, stats = redact_text_with_stats(original)
                self.assertTrue(changed)
                self.assertNotIn(credential, redacted)
                self.assertIn("before ", redacted)
                self.assertIn("; outcome=failed", redacted)
                self.assertEqual(stats["secretLikeMarkersRedacted"], 1)
        safe = "before authentication=Basic challenge; outcome=failed"
        self.assertEqual(redact_text_with_stats(safe)[0], safe)

    def test_hash_router_parameters_redact_secrets_and_preserve_safe_pairs(self) -> None:
        for key in ["token", "password", "%74oken"]:
            for authority in ["example.invalid", "alice:login-secret@example.invalid"]:
                with self.subTest(key=key, authority=authority):
                    url = f"https://{authority}/#/reset?{key}=plain-secret&next=home"
                    redacted, changed, stats = redact_text_with_stats(url)
                    self.assertTrue(changed)
                    self.assertNotIn("plain-secret", redacted)
                    self.assertNotIn("login-secret", redacted)
                    self.assertIn("next=home", redacted)
                    self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
        encoded = "https://example.invalid/#%2Freset%3Ftoken%3Dplain-secret"
        self.assertNotIn("plain-secret", redact_text_with_stats(encoded)[0])
        safe = "https://example.invalid/#/route?page=2&next=home"
        self.assertEqual(redact_text_with_stats(safe)[0], safe)

    def test_sensitive_serialized_containers_redact_every_member(self) -> None:
        for value in ['["first-secret","second-secret"]',
                      '{"first":"first-secret","nested":["second-secret"]}',
                      '["first-secret", {"nested": ["second-secret"]}]',
                      '["first-secret",\n"second-secret"]']:
            with self.subTest(value=value):
                redacted, changed, stats = redact_text_with_stats("credentials=" + value + "; outcome=failed")
                self.assertTrue(changed)
                self.assertNotIn("first-secret", redacted)
                self.assertNotIn("second-secret", redacted)
                self.assertIn("outcome=failed", redacted)
                self.assertEqual(stats["secretLikeMarkersRedacted"], 1)
        for value in ['["first-secret", "second-secret"', "['first-secret','second-secret']",
                      '{"first":"first-secret",\n"second":"second-secret"']:
            with self.subTest(ambiguous=value):
                redacted, changed, _stats = redact_text_with_stats("credentials=" + value)
                self.assertTrue(changed)
                self.assertNotIn("first-secret", redacted)
                self.assertNotIn("second-secret", redacted)

    def test_url_path_assignments_redact_with_and_without_userinfo(self) -> None:
        for authority in ["example.invalid", "alice:login-secret@example.invalid"]:
            for path in ["/report;api_key=plain-secret", "/api_key=plain-secret",
                         "/report;%61pi_key=plain-secret", "/report;api_key%3Dplain-secret"]:
                with self.subTest(authority=authority, path=path):
                    redacted, changed, stats = redact_text_with_stats("https://" + authority + path)
                    self.assertTrue(changed)
                    self.assertNotIn("plain-secret", redacted)
                    self.assertNotIn("login-secret", redacted)
                    self.assertGreater(stats["secretLikeMarkersRedacted"], 0)
                    self.assertEqual(stats["localPathsRedacted"], 0)
        safe = "https://example.invalid/report;page=2/a%2Fb+c"
        self.assertEqual(redact_text_with_stats(safe)[0], safe)

    def test_nested_assignments_do_not_hide_inner_secrets(self) -> None:
        for original, expected, count in [
            ('payload={"api_key":"plain-secret"}', 'payload={"api_key":"<redacted>"}', 1),
            ('outer={"payload":{"db-password":"plain-secret"}}',
             'outer={"payload":{"db-password":"<redacted>"}}', 1),
            ('payload={"api_key":"first-secret","db_token":"second-secret"}',
             'payload={"api_key":"<redacted>","db_token":"<redacted>"}', 2),
            (r'payload="{\"api_key\":\"plain secret\"}"',
             r'payload="{\"api_key\":\"<redacted>\"}"', 1),
        ]:
            with self.subTest(original=original):
                redacted, changed, stats = redact_text_with_stats(original)
                self.assertEqual(redacted, expected)
                self.assertTrue(changed)
                self.assertEqual(stats["secretLikeMarkersRedacted"], count)
                self.assertEqual(stats["localPathsRedacted"], 0)
        for safe in ['payload={"message":"safe"}', "notpassword=safe",
                     "payload=some_api_key_identifier", "notes=plain-secret"]:
            with self.subTest(safe=safe):
                self.assertEqual(redact_text_with_stats(safe), (
                    safe, False, {"secretLikeMarkersRedacted": 0, "localPathsRedacted": 0},
                ))

    def test_unicode_absolute_paths_are_detected_and_fully_redacted(self) -> None:
        for path in ["/секреты/ключи", "/秘密/鍵", "/🔐/данные", "/re\u0301sume\u0301/cle\u0301",
                     r"C:\секреты\ключи", r"\секреты\ключи", r"\\сервер\секреты\ключи"]:
            with self.subTest(path=path):
                self.assertTrue(contains_local_absolute_path(path))
                redacted, changed, stats = redact_text_with_stats(path)
                self.assertEqual(redacted, LOCAL_PATH_REDACTION)
                self.assertTrue(changed)
                self.assertEqual(stats["localPathsRedacted"], 1)
        for safe in ["секреты/ключи", "résumé/clé", "https://example.invalid/секреты/ключи"]:
            with self.subTest(safe=safe):
                self.assertFalse(contains_local_absolute_path(safe))
                self.assertEqual(redact_text_with_stats(safe)[2]["localPathsRedacted"], 0)

    def test_literal_url_tokens_survive_without_recursive_restoration(self) -> None:
        for original, expected in [
            ("__alk_http_url_0__ https://example.invalid/report", "__alk_http_url_0__ https://example.invalid/report"),
            (
                "__alk_http_url_0__ __alk_http_url_1__ https://example.invalid/a http://example.invalid/b",
                "__alk_http_url_0__ __alk_http_url_1__ https://example.invalid/a http://example.invalid/b",
            ),
            (
                "__alk_http_url_0__ https://example.invalid/__alk_http_url_1__",
                "__alk_http_url_0__ https://example.invalid/__alk_http_url_1__",
            ),
            (
                "__alk_http_url_0__ https://example.invalid/__alk_http_url_%32__ https://example.invalid/end",
                "__alk_http_url_0__ https://example.invalid/__alk_http_url_%32__ https://example.invalid/end",
            ),
        ]:
            with self.subTest(original=original):
                redacted, changed, stats = redact_text_with_stats(original)
                self.assertEqual(redacted, expected)
                self.assertEqual(changed, original != expected)
                self.assertEqual(stats, {"secretLikeMarkersRedacted": 0, "localPathsRedacted": 0})

    def test_malformed_http_url_does_not_restore_embedded_credentials(self) -> None:
        for url in [
            "https://[invalid/?api_key=plain-secret",
            "http://[invalid/?access_token=plain-secret",
            "https://user:plain-secret@[invalid]/path",
            "https:///alice:plain-secret@example.invalid/private",
            "http:///?api_key=plain-secret",
            "https://example.invalid:bad-port/private?api_key=plain-secret",
            "https://alice:first-secret@/bob:plain-secret@example.invalid/private",
            "http://alice:first-secret@:8080/bob:plain-secret@example.invalid/private",
            "https://alice:first-secret@example.invalid:bad-port/bob:plain-secret@example.invalid/private",
            "http://alice:first-secret@?next=/bob:plain-secret@example.invalid/private",
        ]:
            with self.subTest(url=url):
                redacted, changed, stats = redact_text_with_stats("Before " + url + " after")
                self.assertTrue(changed)
                self.assertEqual(redacted, "Before " + REDACTED_VALUE + " after")
                self.assertNotIn("plain-secret", redacted)
                self.assertGreater(stats["secretLikeMarkersRedacted"], 0)

    def test_valid_userinfo_authority_retains_safe_dns_and_ipv6_locations(self) -> None:
        for host in ["example.invalid", "example.invalid:8443", "[2001:db8::1]:8443"]:
            with self.subTest(host=host):
                url = f"https://alice:plain-secret@{host}/public?search=safe#intro"
                redacted, changed, stats = redact_text_with_stats(url)
                self.assertEqual(redacted, f"https://{REDACTED_VALUE}@{host}/public?search=safe#intro")
                self.assertTrue(changed)
                self.assertEqual(stats["secretLikeMarkersRedacted"], 1)

    def test_redact_text_covers_assignment_bearer_private_key_and_local_path(self) -> None:
        local_path = "/" + "Users/operator/private.log"
        value = (
            "API_KEY=top-secret Authorization: Bearer token-value "
            '{"session-token": "session-secret"} '
            "-----BEGIN " + "PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY----- " + local_path
        )

        redacted, applied = redact_text(value)

        self.assertTrue(applied)
        self.assertNotIn("top-secret", redacted)
        self.assertNotIn("token-value", redacted)
        self.assertNotIn("session-secret", redacted)
        self.assertNotIn("private-material", redacted)
        self.assertNotIn(local_path, redacted)
        self.assertIn(REDACTED_VALUE, redacted)

    def test_redact_value_preserves_safe_values_and_tracks_no_change(self) -> None:
        redacted, applied = redact_value({"inputTokens": 12, "message": "safe", "items": ["ok"]})

        self.assertFalse(applied)
        self.assertEqual(redacted, {"inputTokens": 12, "message": "safe", "items": ["ok"]})

    def test_redact_value_redacts_nested_sensitive_keys(self) -> None:
        redacted, applied = redact_value(
            {"nested": {"refresh_token": "secret"}, "path": "C:\\Users\\operator\\secret.txt"}
        )

        self.assertTrue(applied)
        self.assertEqual(redacted["nested"]["refresh_token"], REDACTED_VALUE)
        self.assertEqual(redacted["path"], REDACTED_VALUE)

    def test_redact_value_redacts_common_posix_roots(self) -> None:
        paths = [
            "/" + "Volumes/Work/repo/private.txt",
            "/root/.ssh/id_rsa",
            "/opt/data/private.txt",
            "/etc/passwd",
            "/var/log/private.log",
        ]

        redacted, applied = redact_value({"paths": paths})

        self.assertTrue(applied)
        self.assertEqual(redacted["paths"], [REDACTED_VALUE] * len(paths))

    def test_redact_value_redacts_windows_unc_paths(self) -> None:
        paths = [
            r"\\corp-filesvr\eng\secret\roadmap.md",
            r"\\filesvr/share/secret",
            r"\\?\C:\Users\operator\secret.txt",
            r"C:\Users/operator\secret.txt",
            r"C:\foo/bar\baz",
            r"\Windows\System32\drivers",
            r"file:///etc/passwd",
        ]

        redacted, applied = redact_value({"paths": paths})

        self.assertTrue(applied)
        self.assertEqual(redacted["paths"], [REDACTED_VALUE] * len(paths))

    def test_redact_text_covers_standalone_provider_token_formats(self) -> None:
        values = [
            "sk-" + "proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature-material",
            "gh" + "p_1234567890abcdefghijklmnopqrstuvwxyzAB",
            "xo" + "xb-123456789012-1234567890123-AbCdEfGhIjKlMnOp",
            "AKIA" + "IOSFODNN7EXAMPLE",
        ]
        redacted, applied = redact_text(" ".join(values))

        self.assertTrue(applied)
        for value in values:
            self.assertNotIn(value, redacted)
        self.assertGreaterEqual(redacted.count(REDACTED_VALUE), len(values))

    def test_redact_text_preserves_public_http_urls(self) -> None:
        public_path = "/" + "Users/public"
        value = "See https://github.com/avksp/agent-lifecycle-kit and http://example.com" + public_path

        redacted, applied, stats = redact_text_with_stats(value)

        self.assertFalse(applied)
        self.assertEqual(redacted, value)
        self.assertEqual(stats["secretLikeMarkersRedacted"], 0)
        self.assertEqual(stats["localPathsRedacted"], 0)

    def test_redact_text_redacts_url_credentials_and_sensitive_query_values(self) -> None:
        value = "https://user:password@example.com/path?api_key=supersecret123&safe=1"

        redacted, applied = redact_text(value)

        self.assertTrue(applied)
        self.assertEqual(redacted, "https://<redacted>@example.com/path?api_key=<redacted>&safe=1")
        self.assertNotIn("password", redacted)
        self.assertNotIn("supersecret123", redacted)

    def test_redact_text_keeps_non_sensitive_url_query_values(self) -> None:
        value = "https://example.com/path?search=public&redirect=https%3A%2F%2Fexample.com"

        redacted, applied = redact_text(value)

        self.assertFalse(applied)
        self.assertEqual(redacted, value)

    def test_redact_text_normalizes_safe_url_host_without_touching_path(self) -> None:
        value = "See HTTPS://EXAMPLE.COM:443/docs/reference?section=one#intro"

        redacted, applied = redact_text(value)

        self.assertTrue(applied)
        self.assertEqual(redacted, "See https://example.com/docs/reference?section=one#intro")


if __name__ == "__main__":
    unittest.main()
