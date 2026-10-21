from __future__ import annotations

import json
import unittest
from copy import deepcopy
from urllib.parse import quote

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.review_mesh import (
    build_review_mesh_assignment,
    build_review_mesh_profile,
    build_review_mesh_result,
    import_review_mesh_result,
    validate_review_mesh_assignment,
    validate_review_mesh_profile,
    validate_review_mesh_result,
)
from agent_lifecycle.review_mesh.results import project_review_result_for_optimization


class ReviewMeshResultImportTests(unittest.TestCase):
    def test_same_recovered_response_is_imported_once_without_new_charge_or_voice(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        first = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        second = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw,
                                           existing_results=[first])
        self.assertIs(first, second)
        self.assertEqual(first["budgetUsage"], second["budgetUsage"])
        self.assertEqual(first["resultDigest"], second["resultDigest"])
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw,
                                      existing_results=[first, first])
        changed = deepcopy(raw)
        changed["findings"] = []
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=changed,
                                      existing_results=[first])

    def test_raw_session_claim_cannot_supply_separate_provenance(self) -> None:
        from tests.review_mesh.test_contracts import session_review_inputs

        profile, assignment, context = session_review_inputs()
        raw = _raw_output()
        raw["sessionUsage"] = context["receipt"]
        raw["qualification"] = context["qualification"]
        raw["budgetUsage"] = {key: context["receipt"]["usage"][key] for key in raw["budgetUsage"]}
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw,
                                           session_usage_context=context)
        self.assertEqual(result["sessionBudgetBasis"], "CUMULATIVE_PROVIDER_SESSION")

    def test_import_encoded_bearer_plus_does_not_expose_a_credential_suffix(self) -> None:
        for marker in ["Bearer prefix+opaque-auth-secret", "Bearer prefix++opaque-auth-secret", "public+topic", "public topic+tail"]:
            for encoding, safe in [(1, ""), (2, ""), (3, ""), (1, "+"), (2, "+"), (3, "+")]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(marker=marker, encoding=encoding, location=location, safe=safe):
                        profile, assignment = _profile_and_assignment()
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
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "encoded-bearer-plus", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            if not marker.startswith("Bearer "):
                                self.assertEqual(message, text)
                                continue
                            self.assertNotIn("opaque-auth-secret", message)
                            self.assertNotIn("outer-secret", message)
                            self.assertIn("keep=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_decoded_common_secrets_without_losing_failed_command(self) -> None:
        markers = [("Bearer opaque-auth-secret", "opaque-auth-secret"),
                   ("sk-abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
                   ("-----BEGIN " + "PRIVATE KEY-----\nprivate-key-body\n-----END PRIVATE KEY-----", "private-key-body"),
                   ("-----BEGIN " + "PRIVATE KEY-----\nhttps://safe.invalid/public\nprivate-key-body\n-----END PRIVATE KEY-----",
                    "private-key-body")]
        for marker, secret in markers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(marker=marker, encoding=encoding, location=location):
                        profile, assignment = _profile_and_assignment()
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
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "encoded-common-secret", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            self.assertNotIn(secret, message)
                            self.assertNotIn("outer-secret", message)
                            self.assertIn("keep=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_invalid_nested_uri_refusal_retains_no_credential_tail(self) -> None:
        for whitespace in ["/ ", "/" + chr(34), "?" + chr(39), "#<", "#>"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        profile, assignment = _profile_and_assignment()
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
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "decoded-uri-authority", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, message)
                            self.assertIn("keep=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_decoded_uri_authority_delimiters_without_losing_failed_command(self) -> None:
        for whitespace in [chr(34), chr(39), "<", ">"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        profile, assignment = _profile_and_assignment()
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
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "decoded-uri-authority", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, message)
                            self.assertIn("keep=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_decoded_uri_authority_whitespace_without_losing_failed_command(self) -> None:
        for whitespace in [" ", "\t", "\n"]:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "fragment", "routed-fragment"]:
                    with self.subTest(whitespace=repr(whitespace), encoding=encoding, location=location):
                        profile, assignment = _profile_and_assignment()
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
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "decoded-uri-authority", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, message)
                            self.assertIn("keep=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_mixed_container_uri_without_losing_failed_command(self) -> None:
        containers = ['["first-secret","https://safe.invalid/public","second-secret"]',
                      '{"first":"first-secret","url":"https://safe.invalid/public","second":"second-secret"}']
        for container in containers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "routed-fragment"]:
                    for key in ["credentials", "%2563redentials"]:
                        with self.subTest(container=container, encoding=encoding, location=location, key=key):
                            profile, assignment = _profile_and_assignment()
                            encoded = container
                            for _ in range(encoding):
                                encoded = quote(encoded, safe=",:/")
                            suffix = "/report;" + key + "=" + encoded + "?next=home"
                            if location == "query":
                                suffix = "/?" + key + "=" + encoded + "&next=home"
                            elif location == "routed-fragment":
                                suffix = "/#/report;" + key + "=" + encoded + "?next=home"
                            text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                            raw = _raw_output()
                            raw["findings"][0]["message"] = text
                            raw["commandOutcomes"] = [{"commandId": "mixed-container-uri", "status": "FAIL", "exitCode": 7,
                                                       "stderr": text}]
                            before = deepcopy(raw)
                            result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                            for message in [result["findings"][0]["message"],
                                            result["crossCheckReceipt"]["findings"][0]["message"],
                                            result["commandOutcomes"][0]["stderr"]]:
                                for secret in ["first-secret", "second-secret", "outer-secret"]:
                                    self.assertNotIn(secret, message)
                                self.assertIn("next=home", message)
                                self.assertTrue(message.startswith("before "))
                                self.assertTrue(message.endswith(" after"))
                            self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                            self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                            self.assertEqual(raw, before)

    def test_import_redacts_encoded_sensitive_containers_without_losing_failed_command(self) -> None:
        containers = ['["first-secret","second-secret"]',
                      '{"first":"first-secret","second":"second-secret"}',
                      '["first-secret","https://safe.invalid/public","second-secret"]']
        for container in containers:
            for encoding in [1, 2, 3]:
                for location in ["path", "query", "routed-fragment"]:
                    with self.subTest(container=container, encoding=encoding, location=location):
                        profile, assignment = _profile_and_assignment()
                        encoded = container
                        for _ in range(encoding):
                            encoded = quote(encoded, safe=",")
                        suffix = "/report;credentials=" + encoded + "?next=home"
                        if location == "query":
                            suffix = "/?credentials=" + encoded + "&next=home"
                        elif location == "routed-fragment":
                            suffix = "/#/report;credentials=" + encoded + "?next=home"
                        text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "encoded-container", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            for secret in ["first-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, message)
                            self.assertIn("next=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_mixed_sensitive_assignments_without_losing_failed_command(self) -> None:
        for location in ["/?", "/#/public?"]:
            for encoding in [2, 3]:
                for order in ["encoded-first", "literal-first"]:
                    with self.subTest(location=location, encoding=encoding, order=order):
                        profile, assignment = _profile_and_assignment()
                        key = "%74oken"
                        for _ in range(encoding - 1):
                            key = quote(key, safe="")
                        encoded = key + "=plain-secret"
                        literal = "password=second-secret"
                        component = encoded + ";" + literal if order == "encoded-first" else literal + ";" + encoded
                        text = "before https://alice:outer-secret@example.invalid" + location + component + "&next=home after"
                        raw = _raw_output()
                        raw["findings"][0]["message"] = text
                        raw["commandOutcomes"] = [{"commandId": "mixed-secrets", "status": "FAIL", "exitCode": 7,
                                                   "stderr": text}]
                        before = deepcopy(raw)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        for message in [result["findings"][0]["message"],
                                        result["crossCheckReceipt"]["findings"][0]["message"],
                                        result["commandOutcomes"][0]["stderr"]]:
                            for secret in ["plain-secret", "second-secret", "outer-secret"]:
                                self.assertNotIn(secret, message)
                            self.assertIn("next=home", message)
                            self.assertTrue(message.startswith("before "))
                            self.assertTrue(message.endswith(" after"))
                        self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                        self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                        self.assertEqual(raw, before)

    def test_import_redacts_multiply_encoded_query_keys_without_losing_failed_command(self) -> None:
        for location in ["/?", "/#/public?"]:
            for encoding in [2, 3]:
                with self.subTest(location=location, encoding=encoding):
                    profile, assignment = _profile_and_assignment()
                    key = "%74oken"
                    for _ in range(encoding - 1):
                        key = quote(key, safe="")
                    text = "before https://alice:outer-secret@example.invalid" + location + key + "=plain-secret&next=home after"
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "encoded-query", "status": "FAIL", "exitCode": 7,
                                               "stderr": text}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertNotIn("plain-secret", message)
                        self.assertNotIn("outer-secret", message)
                        self.assertIn("next=home", message)
                        self.assertTrue(message.startswith("before "))
                        self.assertTrue(message.endswith(" after"))
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)

    def test_import_redacts_mixed_nested_url_spans_without_losing_failed_command(self) -> None:
        for location in ["path", "query", "routed-fragment"]:
            for encoding in [1, 2]:
                with self.subTest(location=location, encoding=encoding):
                    profile, assignment = _profile_and_assignment()
                    encoded = "https://bob:inner-secret%20suffix@other.invalid/public"
                    for _ in range(encoding):
                        encoded = quote(encoded, safe="")
                    component = encoded + "/https://safe.invalid/public"
                    suffix = "/proxy/" + component
                    if location == "query":
                        suffix = "/?next=" + component
                    elif location == "routed-fragment":
                        suffix = "/#/proxy/" + component + "?next=public"
                    text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "mixed-url", "status": "FAIL", "exitCode": 7,
                                               "stderr": text}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertNotIn("inner-secret", message)
                        self.assertNotIn("outer-secret", message)
                        self.assertIn("other.invalid/public", message)
                        self.assertIn("safe.invalid/public", message)
                        self.assertTrue(message.startswith("before "))
                        self.assertTrue(message.endswith(" after"))
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)

    def test_import_redacts_nested_url_paths_and_routed_prefix_without_losing_failed_command(self) -> None:
        for location in ["path", "routed-fragment"]:
            for encoding in [0, 1, 2]:
                with self.subTest(location=location, encoding=encoding):
                    profile, assignment = _profile_and_assignment()
                    nested = "https://bob:inner-secret@other.invalid/public"
                    for _ in range(encoding):
                        nested = quote(nested, safe="")
                    suffix = "/proxy/" + nested if location == "path" else "/#/proxy/" + nested + "?next=safe"
                    text = "before https://alice:outer-secret@example.invalid" + suffix + " after"
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "nested-path", "status": "FAIL", "exitCode": 7,
                                               "stderr": text}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertNotIn("inner-secret", message)
                        self.assertNotIn("outer-secret", message)
                        self.assertIn("other.invalid/public", message)
                        self.assertTrue(message.startswith("before "))
                        self.assertTrue(message.endswith(" after"))
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)

    def test_import_redacts_nested_url_credentials_without_losing_failed_command(self) -> None:
        for separator in ["?next=", "#next="]:
            for encoding in [0, 1, 2]:
                with self.subTest(separator=separator, encoding=encoding):
                    profile, assignment = _profile_and_assignment()
                    nested = "https://bob:inner-secret@other.invalid/public"
                    for _ in range(encoding):
                        nested = quote(nested, safe="")
                    text = "before https://alice:outer-secret@example.invalid/" + separator + nested + " after"
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "nested-url", "status": "FAIL", "exitCode": 7,
                                               "stderr": text}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertNotIn("inner-secret", message)
                        self.assertNotIn("outer-secret", message)
                        self.assertIn("other.invalid/public", message)
                        self.assertTrue(message.startswith("before "))
                        self.assertTrue(message.endswith(" after"))
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)

    def test_import_validates_json_values_before_sensitive_key_redaction(self) -> None:
        for value in [("api_key=plain-secret",), {"nested": [("plain-secret",)]}, {"plain-secret"}]:
            with self.subTest(value=value):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["details"] = {"credentials": value}
                before = deepcopy(raw)
                with self.assertRaises(LifecycleError) as error:
                    import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(error.exception.code, "review-mesh-import-invalid")
                self.assertEqual(raw, before)

    def test_import_rejects_non_string_keys_before_redaction_and_binding_comparison(self) -> None:
        for key in [1, True, None, 1.5]:
            for location in ["finding", "sensitive-value", "bound-profile", "bound-subject"]:
                with self.subTest(key=key, location=location):
                    profile, assignment = _profile_and_assignment()
                    raw = _raw_output()
                    if location == "finding":
                        raw["findings"][0]["details"] = {key: "same"}
                    elif location == "sensitive-value":
                        raw["findings"][0]["details"] = {"credentials": {key: "same"}}
                    elif location == "bound-profile":
                        profile["provenance"] = {key: "same"}
                    else:
                        assignment["subject"]["provenance"] = {key: "same"}
                        assignment["assignmentDigest"] = canonical_digest(
                            {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                        )
                        json_key = json.loads(json.dumps({key: "same"}))
                        raw["bindings"] = {"subject": {"provenance": json_key}}
                    before = deepcopy((profile, assignment, raw))
                    with self.assertRaises(LifecycleError) as error:
                        import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    self.assertEqual(error.exception.code, "review-mesh-import-invalid")
                    self.assertEqual((profile, assignment, raw), before)

    def test_import_rejects_nested_non_json_containers_without_mutating_raw_or_bound_metadata(self) -> None:
        for value in [("api_key=plain-secret",), {"nested": [("api_key=plain-secret",)]}, {"api_key=plain-secret"}]:
            with self.subTest(value=value):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["details"] = value
                before = deepcopy(raw)
                with self.assertRaises(LifecycleError) as error:
                    import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(error.exception.code, "review-mesh-import-invalid")
                self.assertEqual(raw, before)
        profile, assignment = _profile_and_assignment()
        assignment["subject"]["details"] = ("api_key=plain-secret",)
        assignment["assignmentDigest"] = canonical_digest(
            {key: value for key, value in assignment.items() if key != "assignmentDigest"}
        )
        before = deepcopy(assignment)
        with self.assertRaises(LifecycleError) as error:
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        self.assertEqual(error.exception.code, "review-mesh-import-invalid")
        self.assertEqual(assignment, before)

    def test_import_authentication_semicolons_redact_signature_and_preserve_failed_command(self) -> None:
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            with self.subTest(key=key):
                profile, assignment = _profile_and_assignment()
                text = ("before " + key + ": AWS4-HMAC-SHA256 "
                        "Credential=EXAMPLE/20261009/us-east-1/s3/aws4_request, "
                        "SignedHeaders=host;x-amz-date, Signature=" + "e" * 64 + "; outcome=failed")
                raw = _raw_output()
                raw["findings"][0]["message"] = text
                raw["commandOutcomes"] = [{"commandId": "signed-auth", "status": "FAIL", "exitCode": 7,
                                           "stderr": text}]
                before = deepcopy(raw)
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                for message in [result["findings"][0]["message"],
                                result["crossCheckReceipt"]["findings"][0]["message"],
                                result["commandOutcomes"][0]["stderr"]]:
                    self.assertEqual(message, "before " + key + ": [REDACTED]; outcome=failed")
                self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                self.assertEqual(raw, before)

    def test_import_folded_authentication_redacts_both_findings_and_failed_commands(self) -> None:
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            for gap in ["\n ", "\r\n ", "\r\n\t", "\t", "\u2003"]:
                with self.subTest(key=key, gap=gap):
                    profile, assignment = _profile_and_assignment()
                    text = ("before " + key + ": Digest username*=UTF-8''alice," + gap
                            + 'nonce="nonce-secret",' + gap + 'response="opaque-auth-secret"; outcome=failed')
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "folded-auth", "status": "FAIL", "exitCode": 7,
                                               "stderr": text}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertEqual(message, "before " + key + ": [REDACTED]; outcome=failed")
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)

    def test_import_authentication_headers_protect_all_outputs_and_bound_metadata(self) -> None:
        credential = "opaque-auth-secret"
        for key in ["Authorization", "Proxy-Authorization", "proxy_authorization"]:
            for value in ["Basic " + credential, "Negotiate " + credential,
                          'Digest username="alice", nonce="nonce-secret", response="' + credential + '"']:
                with self.subTest(key=key, value=value):
                    profile, assignment = _profile_and_assignment()
                    text = "before " + key + ": " + value + "; outcome=failed"
                    raw = _raw_output()
                    raw["findings"][0]["message"] = text
                    raw["commandOutcomes"] = [{"commandId": "auth-check", "status": "FAIL",
                                               "exitCode": 7, "stderr": text, key: value}]
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for message in [result["findings"][0]["message"],
                                    result["crossCheckReceipt"]["findings"][0]["message"],
                                    result["commandOutcomes"][0]["stderr"]]:
                        self.assertNotIn(credential, message)
                        self.assertNotIn("nonce-secret", message)
                        self.assertIn("before ", message)
                        self.assertIn("; outcome=failed", message)
                    self.assertEqual(result["commandOutcomes"][0][key], "[REDACTED]")
                    self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                    self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                    self.assertEqual(raw, before)
                    assignment["subject"]["locator"] = text
                    assignment["assignmentDigest"] = canonical_digest(
                        {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                    )
                    original = deepcopy(assignment)
                    with self.assertRaises(LifecycleError):
                        import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
                    self.assertEqual(assignment, original)

    def test_import_redacts_basic_authorization_in_findings_and_command_diagnostics(self) -> None:
        credential = "dXNlcjpwYXNz"
        for header in ["Authorization: Basic ", "authorization=basic\t", "Authorization : BASIC "]:
            with self.subTest(header=header):
                profile, assignment = _profile_and_assignment()
                text = "before " + header + credential + "; outcome=failed"
                raw = _raw_output()
                raw["findings"][0]["message"] = text
                raw["commandOutcomes"] = [{"commandId": "basic-auth-check", "status": "FAIL",
                                           "exitCode": 7, "stderr": text}]
                before = deepcopy(raw)
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                messages = [result["findings"][0]["message"],
                            result["crossCheckReceipt"]["findings"][0]["message"],
                            result["commandOutcomes"][0]["stderr"]]
                for message in messages:
                    self.assertNotIn(credential, message)
                    self.assertIn("before ", message)
                    self.assertIn("; outcome=failed", message)
                self.assertEqual(result["commandOutcomes"][0]["status"], "FAIL")
                self.assertEqual(result["commandOutcomes"][0]["exitCode"], 7)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(raw, before)

    def test_import_redacts_hash_router_secrets_and_refuses_them_in_bound_metadata(self) -> None:
        for key in ["token", "password", "%74oken"]:
            with self.subTest(key=key):
                profile, assignment = _profile_and_assignment()
                text = f"https://example.invalid/#/reset?{key}=plain-secret&next=home"
                raw = _raw_output()
                raw["findings"][0]["message"] = text
                before = deepcopy(raw)
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                for finding in [result["findings"][0], result["crossCheckReceipt"]["findings"][0]]:
                    self.assertNotIn("plain-secret", finding["message"])
                    self.assertIn("next=home", finding["message"])
                self.assertEqual(raw, before)
                assignment["subject"]["locator"] = text
                assignment["assignmentDigest"] = canonical_digest(
                    {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                )
                original = deepcopy(assignment)
                with self.assertRaises(LifecycleError):
                    import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
                self.assertEqual(assignment, original)

    def test_numeric_result_validator_requires_declared_nonempty_string_phase(self) -> None:
        profile, assignment = _profile_and_assignment()
        original = build_review_mesh_result(
            profile=profile, assignment=assignment, budget_usage=_raw_output()["budgetUsage"], status="FAIL",
        )
        self.assertEqual(validate_review_mesh_result(original, profile=profile)["status"], "PASS")
        for mutation in ["ABSENT", "", None, False, 1, [], {}]:
            with self.subTest(phase=mutation):
                result = deepcopy(original)
                if mutation == "ABSENT":
                    del result["phase"]
                else:
                    result["phase"] = mutation
                _repair_result_digests(result)
                validation = validate_review_mesh_result(result, profile=profile)
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn("review-mesh-result-phase-missing", {r["code"] for r in validation["blockers"]})

    def test_bound_profile_reviewer_class_applies_to_assignment_result_and_import(self) -> None:
        profile = build_review_mesh_profile(reviewer_model_classes=["specialist-review"], independence_required=False)
        assignment = build_review_mesh_assignment(
            profile=profile, assignment_id="RM-specialist-only", subject={"taskId": "TASK-1"},
            reviewer={"role": "reviewer", "modelClass": "specialist-review"},
        )
        self.assertEqual(validate_review_mesh_assignment(assignment, profile=profile)["status"], "PASS")
        original = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        self.assertEqual(validate_review_mesh_result(original, profile=profile)["status"], "PASS")
        excluded = deepcopy(assignment)
        excluded["reviewer"]["modelClass"] = "strong-reasoning"
        excluded["assignmentDigest"] = canonical_digest({k: v for k, v in excluded.items() if k != "assignmentDigest"})
        validation = validate_review_mesh_assignment(excluded, profile=profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-assignment-reviewer-class-not-profile", {r["code"] for r in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=excluded, reviewer_output=_raw_output())
        result = deepcopy(original)
        result["reviewer"]["modelClass"] = "strong-reasoning"
        result["crossCheckReceipt"]["reviewer"]["modelClass"] = "strong-reasoning"
        _repair_result_digests(result)
        validation = validate_review_mesh_result(result, profile=profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-mesh-result-reviewer-class-not-profile", {r["code"] for r in validation["blockers"]})

    def test_import_redacts_every_serialized_sensitive_container_member(self) -> None:
        for value in ['["first-secret","second-secret"]',
                      '{"first":"first-secret","nested":["second-secret"]}',
                      '["first-secret",\n"second-secret"]',
                      '["first-secret", "second-secret"']:
            with self.subTest(value=value):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["message"] = "credentials=" + value
                before = deepcopy(raw)
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                for finding in [result["findings"][0], result["crossCheckReceipt"]["findings"][0]]:
                    self.assertNotIn("first-secret", finding["message"])
                    self.assertNotIn("second-secret", finding["message"])
                self.assertEqual(raw, before)

    def test_numeric_import_independence_relabel_never_validates_or_projects_as_proven(self) -> None:
        profile = build_review_mesh_profile(independence_required=True)
        assignment = build_review_mesh_assignment(
            profile=profile, assignment_id="RM-relabel-import",
            subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True,
                     "hostIdentityHash": "a" * 64, "modelIdentityHash": "b" * 64},
            reviewer={"role": "reviewer", "modelClass": "strong-reasoning",
                      "hostIdentityHash": "c" * 64, "modelIdentityHash": "d" * 64}, blocking=True,
        )
        raw = {**_raw_output(), "status": "PASS", "findings": []}
        original = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        for remove_markers in [(), ("import",), ("roundParticipation",), ("import", "roundParticipation")]:
            for keep_blocker in ["both", "result", "receipt"]:
                with self.subTest(remove_markers=remove_markers, keep_blocker=keep_blocker):
                    result = deepcopy(original)
                    result["independence"]["status"] = "INDEPENDENT"
                    result["crossCheckReceipt"]["independence"]["status"] = "INDEPENDENT"
                    for marker in remove_markers:
                        del result[marker]
                    if keep_blocker == "result":
                        result["crossCheckReceipt"]["blockers"] = []
                    elif keep_blocker == "receipt":
                        result["blockers"] = []
                    _repair_result_digests(result)
                    validation = validate_review_mesh_result(result, profile=profile)
                    self.assertEqual(validation["status"], "FAIL")
                    self.assertIn("review-mesh-result-import-independence-not-proven",
                                  {item["code"] for item in validation["blockers"]})
                    self.assertEqual(project_review_result_for_optimization(result)["independenceStatus"], "NOT_PROVEN")
        ordinary = build_review_mesh_result(
            profile=profile, assignment=assignment, budget_usage=raw["budgetUsage"], status="PASS", findings=[],
        )
        self.assertEqual(validate_review_mesh_result(ordinary, profile=profile)["status"], "PASS")
        self.assertEqual(project_review_result_for_optimization(ordinary)["independenceStatus"], "INDEPENDENT")

    def test_import_redacts_url_matrix_secrets_in_both_finding_copies(self) -> None:
        for authority in ["example.invalid", "alice:login-secret@example.invalid"]:
            for path in ["/report;api_key=plain-secret", "/report;%61pi_key=plain-secret"]:
                with self.subTest(authority=authority, path=path):
                    profile, assignment = _profile_and_assignment()
                    raw = _raw_output()
                    raw["findings"][0]["message"] = "https://" + authority + path
                    before = deepcopy(raw)
                    result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    for finding in [result["findings"][0], result["crossCheckReceipt"]["findings"][0]]:
                        self.assertNotIn("plain-secret", finding["message"])
                        self.assertNotIn("login-secret", finding["message"])
                    self.assertEqual(raw, before)

    def test_import_rejects_contradictory_bound_assignment_identities(self) -> None:
        for key, subject_value, top_value in [
            ("taskId", "TASK-1", "TASK-2"), ("attempt", 1, True),
            ("planRevision", 1, 1.0), ("sourceDigest", "a" * 64, "b" * 64),
        ]:
            for provide_bindings in [False, True]:
                with self.subTest(key=key, provide_bindings=provide_bindings):
                    profile, assignment = _profile_and_assignment()
                    assignment["subject"][key] = subject_value
                    assignment[key] = top_value
                    assignment["assignmentDigest"] = canonical_digest(
                        {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                    )
                    raw = _raw_output()
                    if provide_bindings:
                        raw[key] = top_value
                        raw["subject"] = {key: subject_value}
                    before = deepcopy(assignment)
                    with self.assertRaises(LifecycleError) as error:
                        import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                    self.assertEqual(error.exception.code, "review-mesh-import-invalid")
                    self.assertEqual(assignment, before)
        profile, assignment = _profile_and_assignment()
        assignment["taskId"] = assignment["subject"]["taskId"]
        assignment["assignmentDigest"] = canonical_digest(
            {k: v for k, v in assignment.items() if k != "assignmentDigest"}
        )
        raw = _raw_output()
        raw["taskId"] = assignment["taskId"]
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["subject"]["taskId"], result["import"]["bindings"]["taskId"])

    def test_import_redacts_nested_string_assignments_in_both_finding_copies(self) -> None:
        for text in ['payload={"api_key":"plain-secret"}',
                     'outer={"payload":{"db_token":"plain-secret"}}',
                     r'payload="{\"api_key\":\"plain secret\"}"']:
            with self.subTest(text=text):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["message"] = text
                before = deepcopy(raw)
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                for finding in [result["findings"][0], result["crossCheckReceipt"]["findings"][0]]:
                    self.assertNotIn("plain-secret", finding["message"])
                    self.assertNotIn("plain secret", finding["message"])
                    self.assertIn("payload", finding["message"])
                    self.assertIn("[REDACTED]", finding["message"])
                self.assertGreater(result["redaction"]["secretLikeMarkersRedacted"], 0)
                self.assertEqual(raw, before)

    def test_import_unicode_paths_require_permission_and_are_redacted(self) -> None:
        for path in ["/секреты/ключи", "/秘密/鍵", "/🔐/данные", r"C:\секреты\ключи"]:
            with self.subTest(path=path):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["message"] = path
                before = deepcopy(raw)
                with self.assertRaises(LifecycleError) as error:
                    import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(error.exception.code, "review-mesh-local-path-leakage")
                result = import_review_mesh_result(
                    profile=profile, assignment=assignment, reviewer_output=raw, allow_local_evidence_refs=True,
                )
                self.assertEqual(result["findings"][0]["message"], "[LOCAL_PATH]")
                self.assertEqual(result["crossCheckReceipt"]["findings"][0]["message"], "[LOCAL_PATH]")
                self.assertEqual(result["redaction"]["localPathsRedacted"], 1)
                self.assertEqual(raw, before)

    def test_import_rejects_nested_secrets_and_unicode_paths_in_bound_metadata(self) -> None:
        for field in ["subject", "reviewer"]:
            for text in ['payload={"api_key":"plain-secret"}', "/секреты/ключи", "/秘密/鍵"]:
                for allow_local in [False, True]:
                    with self.subTest(field=field, text=text, allow_local=allow_local):
                        profile, assignment = _profile_and_assignment()
                        assignment[field]["annotation"] = text
                        assignment["assignmentDigest"] = canonical_digest(
                            {key: value for key, value in assignment.items() if key != "assignmentDigest"}
                        )
                        before = deepcopy(assignment)
                        with self.assertRaises(LifecycleError) as error:
                            import_review_mesh_result(
                                profile=profile, assignment=assignment, reviewer_output=_raw_output(),
                                allow_local_evidence_refs=allow_local,
                            )
                        self.assertNotIn(text, str(error.exception))
                        self.assertEqual(assignment, before)

    def test_import_preserves_literal_url_tokens_in_original_finding(self) -> None:
        profile, assignment = _profile_and_assignment()
        text = "__alk_http_url_0__ __alk_http_url_1__ https://example.invalid/a http://example.invalid/b"
        raw = _raw_output()
        raw["findings"][0]["message"] = text
        before = deepcopy(raw)
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["findings"][0]["message"], text)
        self.assertEqual(result["crossCheckReceipt"]["findings"][0]["message"], text)
        self.assertEqual(result["redaction"]["status"], "PASS")
        self.assertEqual(raw, before)

    def test_import_preserves_validated_binding_values_without_content_normalization(self) -> None:
        for field in ["subject", "reviewer"]:
            for identity in ["HTTPS://EXAMPLE.COM:443/review#Finding", "<redacted>", "<local-path>"]:
                for top_level in [False, True]:
                    with self.subTest(field=field, identity=identity, top_level=top_level):
                        profile, assignment = _profile_and_assignment()
                        assignment[field]["locator"] = identity
                        assignment["assignmentDigest"] = canonical_digest(
                            {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                        )
                        raw = {**_raw_output(), "bindings": {field: {"locator": identity}}}
                        if top_level:
                            raw[field] = {"locator": identity}
                        before = deepcopy((profile, assignment, raw))
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        self.assertEqual(result["import"]["bindings"][field], {"locator": identity})
                        self.assertEqual(result[field]["locator"], identity)
                        self.assertEqual((profile, assignment, raw), before)

    def test_import_redacts_parseable_url_with_missing_authority(self) -> None:
        for url in [
            "https:///alice:plain-secret@example.invalid/private",
            "https://alice:first-secret@/bob:plain-secret@example.invalid/private",
            "http://alice:first-secret@:8080/bob:plain-secret@example.invalid/private",
            "https://alice:first-secret@example.invalid:bad-port/bob:plain-secret@example.invalid/private",
        ]:
            with self.subTest(url=url):
                profile, assignment = _profile_and_assignment()
                raw = _raw_output()
                raw["findings"][0]["message"] = url
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(result["findings"][0]["message"], "[REDACTED]")
                self.assertNotIn("plain-secret", json.dumps(result))

    def test_import_rejects_sensitive_bound_profile_metadata_without_rebinding(self) -> None:
        for nested in [False, True]:
            for identifier in [
                "api_key=plain-secret",
                "https://[invalid/?api_key=plain-secret",
                "/" + "Users/example/private",
            ]:
                for allow_local in [False, True]:
                    with self.subTest(nested=nested, identifier=identifier, allow_local=allow_local):
                        profile, assignment = _profile_and_assignment()
                        target = profile["crossCheckProfile"] if nested else profile
                        target["profileId"] = identifier
                        target["profileDigest"] = canonical_digest(
                            {k: v for k, v in target.items() if k != "profileDigest"}
                        )
                        profile["profileDigest"] = canonical_digest(
                            {k: v for k, v in profile.items() if k != "profileDigest"}
                        )
                        assignment = build_review_mesh_assignment(
                            profile=profile,
                            assignment_id="unsafe-profile",
                            subject=assignment["subject"],
                            reviewer=assignment["reviewer"],
                            blocking=True,
                        )
                        before = deepcopy((profile, assignment))
                        self.assertEqual(validate_review_mesh_profile(profile)["status"], "PASS")
                        with self.assertRaises(LifecycleError) as raised:
                            import_review_mesh_result(
                                profile=profile,
                                assignment=assignment,
                                reviewer_output=_raw_output(),
                                allow_local_evidence_refs=allow_local,
                            )
                        self.assertIn(
                            raised.exception.code, {"review-mesh-import-invalid", "review-mesh-local-path-leakage"}
                        )
                        self.assertNotIn("plain-secret", str(raised.exception))
                        self.assertEqual((profile, assignment), before)

    def test_import_preserves_recursive_binding_types_and_supported_subsets(self) -> None:
        for field in ["subject", "reviewer"]:
            for original, changed in [
                ({"planRevision": 1}, {"planRevision": True}),
                ([{"planRevision": 1}], [{"planRevision": True}]),
                ({"revisions": [1]}, {"revisions": [True]}),
            ]:
                for top_level in [False, True]:
                    with self.subTest(field=field, original=original, top_level=top_level):
                        profile, assignment = _profile_and_assignment()
                        assignment[field]["provenance"] = original
                        assignment["assignmentDigest"] = canonical_digest(
                            {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                        )
                        raw = {**_raw_output(), "bindings": {field: {"provenance": changed}}}
                        if top_level:
                            raw[field] = {"provenance": original}
                        before = deepcopy((assignment, raw))
                        with self.assertRaises(LifecycleError) as raised:
                            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        self.assertEqual(raised.exception.code, "review-mesh-import-invalid")
                        self.assertEqual((assignment, raw), before)
                        raw["bindings"][field]["provenance"] = deepcopy(original)
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        self.assertEqual(result["import"]["bindings"][field], {"provenance": original})
                        self.assertEqual(result[field]["provenance"], original)

    def test_import_rejects_conflicting_profile_live_call_policies(self) -> None:
        for outer, nested in [(False, True), (True, False)]:
            for usage in [{}, _raw_output()["budgetUsage"]]:
                with self.subTest(outer=outer, nested=nested, usage=usage):
                    profile, assignment = _profile_and_assignment()
                    profile["liveCallsAllowed"] = outer
                    profile["crossCheckProfile"]["liveCallsAllowed"] = nested
                    cross = profile["crossCheckProfile"]
                    cross["profileDigest"] = canonical_digest({k: v for k, v in cross.items() if k != "profileDigest"})
                    profile["profileDigest"] = canonical_digest(
                        {k: v for k, v in profile.items() if k != "profileDigest"}
                    )
                    validation = validate_review_mesh_profile(profile)
                    self.assertIn("review-mesh-live-calls-not-cross-check", {b["code"] for b in validation["blockers"]})
                    assignment["profileDigest"] = profile["profileDigest"]
                    assignment["assignmentDigest"] = canonical_digest(
                        {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                    )
                    with self.assertRaises(LifecycleError):
                        import_review_mesh_result(
                            profile=profile,
                            assignment=assignment,
                            reviewer_output={**_raw_output(), "budgetUsage": usage, "liveCallsStarted": True},
                        )

    def test_import_rejects_assignment_cap_changes_after_digest_repair(self) -> None:
        for field in ["maxInvocations", "maxInputTokens", "maxOutputTokens", "maxWallSeconds"]:
            for changed in [0, 1_000_000]:
                with self.subTest(field=field, changed=changed):
                    profile, assignment = _profile_and_assignment()
                    assignment["budgetCap"][field] = changed
                    assignment["assignmentDigest"] = canonical_digest(
                        {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                    )
                    validation = validate_review_mesh_assignment(assignment, profile=profile)
                    self.assertIn(
                        "review-mesh-assignment-budget-cap-not-profile", {b["code"] for b in validation["blockers"]}
                    )
                    with self.assertRaises(LifecycleError):
                        import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())

    def test_import_rejects_unsafe_dictionary_keys_without_colliding_fields(self) -> None:
        for key in ["api_key=plain-secret", "/" + "Users/example/private.txt", "https://[invalid/?api_key=plain-secret"]:
            for allow_local in [False, True]:
                with self.subTest(key=key, allow_local=allow_local):
                    profile, assignment = _profile_and_assignment()
                    raw = _raw_output()
                    raw["findings"][0]["details"] = {key: "diagnostic", "[REDACTED]": "existing field"}
                    before = deepcopy(raw)
                    with self.assertRaises(LifecycleError) as raised:
                        import_review_mesh_result(
                            profile=profile,
                            assignment=assignment,
                            reviewer_output=raw,
                            allow_local_evidence_refs=allow_local,
                        )
                    self.assertEqual(raised.exception.code, "review-mesh-import-invalid")
                    self.assertNotIn("plain-secret", str(raised.exception))
                    self.assertEqual(raw, before)

    def test_import_rejects_sensitive_bound_metadata_without_rebinding_identity(self) -> None:
        for field in ["subject", "reviewer"]:
            for metadata in [
                {"token": "plain-secret"},
                {"annotation": "api_key=plain-secret"},
                {"path": "/" + "Users/example/private.txt"},
            ]:
                for allow_local in [False, True]:
                    with self.subTest(field=field, metadata=metadata, allow_local=allow_local):
                        profile, assignment = _profile_and_assignment()
                        assignment[field].update(metadata)
                        assignment["assignmentDigest"] = canonical_digest(
                            {k: v for k, v in assignment.items() if k != "assignmentDigest"}
                        )
                        before = deepcopy(assignment)
                        raw = {**_raw_output(), field: metadata}
                        with self.assertRaises(LifecycleError) as raised:
                            import_review_mesh_result(
                                profile=profile,
                                assignment=assignment,
                                reviewer_output=raw,
                                allow_local_evidence_refs=allow_local,
                            )
                        self.assertNotIn("plain-secret", str(raised.exception))
                        self.assertEqual(assignment, before)

    def test_import_numeric_receipt_cap_substitution_fails_after_both_digests_repaired(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = {**_raw_output(), "status": "PASS", "findings": []}
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "PASS")
        value = profile["budgetCap"]["maxInputTokens"] + 1
        result["budgetUsage"]["inputTokens"] = value
        result["crossCheckReceipt"]["budgetUsage"]["inputTokens"] = value
        result["crossCheckReceipt"]["budgetCap"]["maxInputTokens"] = value
        _repair_result_digests(result)
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")

    def test_import_malformed_url_credential_is_redacted(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["findings"][0]["message"] = "https://[invalid/?api_key=plain-secret"
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertNotIn("plain-secret", json.dumps(result))
        self.assertEqual(result["findings"][0]["message"], "[REDACTED]")
        self.assertEqual(result["redaction"]["status"], "REDACTED")

    def test_import_unknown_usage_does_not_excuse_forbidden_live_call(self) -> None:
        for allowed in [False, True]:
            profile = build_review_mesh_profile(independence_required=False, live_calls_allowed=allowed)
            assignment = build_review_mesh_assignment(
                profile=profile,
                assignment_id="RM-live-policy",
                subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
                reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
                blocking=True,
            )
            for usage in [{}, {"inputTokens": 1}]:
                with self.subTest(allowed=allowed, usage=usage):
                    raw = {**_raw_output(), "liveCallsStarted": True, "budgetUsage": usage}
                    if allowed:
                        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        self.assertTrue(result["liveCallsStarted"])
                        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")
                    else:
                        with self.assertRaises(LifecycleError):
                            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                        result = build_review_mesh_result(
                            profile=profile,
                            assignment=assignment,
                            budget_usage={key: usage.get(key) for key in _raw_output()["budgetUsage"]},
                            live_calls_started=True,
                        )
                        self.assertIn("cross-check-live-call-not-allowed", {b["code"] for b in result["blockers"]})
                        validation = validate_review_mesh_result(result, profile=profile)
                        self.assertIn("cross-check-live-call-not-allowed", {b["code"] for b in validation["blockers"]})

    def test_import_unknown_resource_does_not_excuse_known_cap_overrun(self) -> None:
        profile, assignment = _profile_and_assignment()
        cap_fields = {
            "invocations": "maxInvocations",
            "inputTokens": "maxInputTokens",
            "outputTokens": "maxOutputTokens",
            "wallSeconds": "maxWallSeconds",
        }
        for field, cap_field in cap_fields.items():
            with self.subTest(field=field):
                raw = _raw_output()
                raw["budgetUsage"] = {key: None for key in cap_fields}
                raw["budgetUsage"][field] = profile["budgetCap"][cap_field]
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(result["budgetUsage"], raw["budgetUsage"])
                validation = validate_review_mesh_result(result, profile=profile)
                self.assertEqual(validation["status"], "FAIL")
                self.assertEqual({b["code"] for b in validation["blockers"]}, {"review-mesh-result-usage-unavailable"})
                raw["budgetUsage"][field] += 1
                with self.assertRaises(LifecycleError):
                    import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                overrun = build_review_mesh_result(
                    profile=profile,
                    assignment=assignment,
                    budget_usage=raw["budgetUsage"],
                    status="FAIL",
                )
                self.assertIn("cross-check-budget-cap-exceeded", {b["code"] for b in overrun["blockers"]})
                validation = validate_review_mesh_result(overrun, profile=profile)
                self.assertIn("cross-check-budget-cap-exceeded", {b["code"] for b in validation["blockers"]})

    def test_import_redacts_nested_secret_keys_and_schema_metadata(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["schemaVersion"] = "api_key=plain-secret"
        raw["findings"][0]["details"] = {
            "password": "plain-secret",
            "nested": [{"client-secret": "plain-secret"}],
            "line": 7,
        }
        raw["commandOutcomes"] = [
            {"commandId": "check-1", "status": "FAIL", "exitCode": 7, "credentials": {"value": "plain-secret"}}
        ]
        before = deepcopy(raw)
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertNotIn("plain-secret", json.dumps(result))
        self.assertEqual(result["findings"][0]["details"]["line"], 7)
        self.assertEqual(result["findings"][0]["details"]["password"], "[REDACTED]")
        self.assertEqual(result["commandOutcomes"][0]["credentials"], "[REDACTED]")
        self.assertEqual(result["import"]["schemaVersion"], "api_key=[REDACTED]")
        self.assertEqual(result["redaction"]["secretLikeMarkersRedacted"], 4)
        self.assertEqual(raw, before)

    def test_result_validator_rejects_omitted_usage_after_digest_repair(self) -> None:
        profile, assignment = _profile_and_assignment()
        original = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        for field in original["budgetUsage"]:
            for layers in ["outer", "nested", "both"]:
                with self.subTest(field=field, layers=layers):
                    result = deepcopy(original)
                    if layers in {"outer", "both"}:
                        del result["budgetUsage"][field]
                    if layers in {"nested", "both"}:
                        del result["crossCheckReceipt"]["budgetUsage"][field]
                    _repair_result_digests(result)
                    self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")

    def test_result_validator_joins_status_identity_and_findings(self) -> None:
        profile, assignment = _profile_and_assignment()
        original = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        mutations = {
            "status": "PASS",
            "subject": {**original["subject"], "taskId": "OTHER"},
            "reviewer": {**original["reviewer"], "role": "OTHER"},
            "findings": [],
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                result = deepcopy(original)
                result[field] = value
                _repair_result_digests(result)
                validation = validate_review_mesh_result(result, profile=profile)
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn(f"review-mesh-result-{field}-mismatch", {b["code"] for b in validation["blockers"]})

    def test_result_validator_rejects_failed_or_malformed_commands_after_digest_repair(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["commandOutcomes"] = [{"commandId": "check-1", "status": "FAIL", "exitCode": 7}]
        original = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(validate_review_mesh_result(original, profile=profile)["status"], "PASS")
        for status_layers in ["outer", "both"]:
            with self.subTest(status_layers=status_layers):
                result = deepcopy(original)
                result["status"] = "PASS"
                if status_layers == "both":
                    result["crossCheckReceipt"]["status"] = "PASS"
                _repair_result_digests(result)
                self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")
        for commands in [
            None,
            {},
            [None],
            raw["commandOutcomes"] * 2,
            [{"commandId": "check-1", "status": "PASS", "exitCode": 7}],
            [{"commandId": "check-1", "status": "FAIL", "exitCode": True}],
            [{"commandId": "check-1", "status": "WAIVED", "exitCode": 7}],
        ]:
            with self.subTest(commands=commands):
                result = deepcopy(original)
                result["commandOutcomes"] = commands
                _repair_result_digests(result)
                self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")

    def test_import_distinct_identity_hashes_do_not_prove_independence(self) -> None:
        profile = build_review_mesh_profile(independence_required=True)
        assignment = build_review_mesh_assignment(
            profile=profile,
            assignment_id="RM-independent-import",
            subject={
                "taskId": "TASK-1",
                "reviewMeshBlockingOptIn": True,
                "hostIdentityHash": "a" * 64,
                "modelIdentityHash": "b" * 64,
            },
            reviewer={
                "role": "reviewer",
                "modelClass": "strong-reasoning",
                "hostIdentityHash": "c" * 64,
                "modelIdentityHash": "d" * 64,
            },
            blocking=True,
        )
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=_raw_output())
        self.assertEqual(result["independence"]["status"], "NOT_PROVEN")
        self.assertEqual(result["crossCheckReceipt"]["independence"]["status"], "NOT_PROVEN")
        self.assertEqual(project_review_result_for_optimization(result)["independenceStatus"], "NOT_PROVEN")
        self.assertIsNone(result["independentEvidence"])
        self.assertFalse(result["roundParticipation"]["eligible"])
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "FAIL")
        # A readable proof gap does not excuse an unrelated resource violation.
        raw = _raw_output()
        raw["budgetUsage"]["inputTokens"] = profile["budgetCap"]["maxInputTokens"] + 1
        with self.assertRaises(LifecycleError):
            import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)

    def test_import_lossless_findings_and_nested_bindings(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["subject"] = {"taskId": assignment["subject"]["taskId"]}
        raw["bindings"] = {"assignmentId": assignment["assignmentId"], "subject": dict(raw["subject"])}
        before = deepcopy(raw)
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["findings"], raw["findings"])
        self.assertEqual(result["subject"], assignment["subject"])
        self.assertEqual(result["import"]["bindings"], raw["bindings"])
        self.assertEqual(raw, before)
        raw["bindings"]["subject"] = {"reviewMeshBlockingOptIn": True}
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["import"]["bindings"]["subject"], assignment["subject"])

    def test_import_retains_failed_command_and_never_waives_it(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["status"] = "PASS"
        raw["commandOutcomes"] = [{"commandId": "check-1", "status": "FAIL", "exitCode": 7, "stderr": "check failed"}]
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["commandOutcomes"], raw["commandOutcomes"])
        self.assertEqual(result["findings"], raw["findings"])
        for mutation in [
            {"status": "WAIVED"},
            {"status": {}},
            {"commandOutcomes": [{"commandId": "check-1", "status": "PASS", "exitCode": 7}]},
            {"commandOutcomes": [{"commandId": "check-1", "status": "WAIVED", "exitCode": 7}]},
            {"commandOutcomes": [{"commandId": "check-1", "status": "FAIL", "exitCode": True}]},
            {"commandOutcomes": [{"commandId": "check-1", "status": "FAIL", "exitCode": "7"}]},
            {"commandOutcomes": [None]},
            {"commandOutcomes": {}},
            {"commandOutcomes": [{"commandId": "check-1", "status": "FAIL"}]},
            {"commandOutcomes": raw["commandOutcomes"] * 2},
        ]:
            with self.subTest(mutation=mutation), self.assertRaises(LifecycleError):
                import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output={**raw, **mutation})

    def test_import_rejects_wrong_containers_and_values(self) -> None:
        profile, assignment = _profile_and_assignment()
        invalid = [None, [], "raw", *({**_raw_output(), "findings": value} for value in [None, {}, "raw", [1], [None]])]
        invalid.extend({**_raw_output(), "budgetUsage": value} for value in [None, 0, [], {"costUsd": 1}])
        invalid.extend({**_raw_output(), "budgetUsage": {"inputTokens": value}} for value in [True, -1, "10", 1.5, {}])
        invalid.extend({**_raw_output(), "liveCallsStarted": value} for value in [None, 0, "false"])
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(LifecycleError):
                import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)

    def test_import_rejects_conflicting_top_and_nested_bindings(self) -> None:
        profile, assignment = _profile_and_assignment()
        for bindings in [
            {"subject": {"taskId": "OTHER"}},
            {"taskId": "OTHER"},
            {"assignmentId": "OTHER"},
            {"bindings": {"assignmentId": "OTHER"}},
            {"bindings": {"subject": {"taskId": "OTHER"}}},
            {"assignmentId": assignment["assignmentId"], "bindings": {"assignmentId": "OTHER"}},
            {"bindings": {"unboundIdentity": "invented"}},
            {"bindings": []},
            {"subject": []},
        ]:
            with self.subTest(bindings=bindings), self.assertRaises(LifecycleError):
                import_review_mesh_result(
                    profile=profile, assignment=assignment, reviewer_output={**_raw_output(), **bindings}
                )

    def test_import_unknown_usage_stays_null_and_fails_native_validation(self) -> None:
        profile, assignment = _profile_and_assignment()
        for usage in [None, {}, {"inputTokens": 0}, {"inputTokens": None, "invocations": 1}]:
            raw = _raw_output()
            raw.pop("budgetUsage")
            if usage is not None:
                raw["budgetUsage"] = usage
            with self.subTest(usage=usage):
                result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
                self.assertEqual(
                    result["budgetUsage"], {key: (usage or {}).get(key) for key in _raw_output()["budgetUsage"]}
                )
                self.assertEqual(result["budgetUsageStatus"], "UNAVAILABLE")
                self.assertIsNone(result["crossCheckReceipt"])
                self.assertEqual(result["findings"], raw["findings"])
                validation = validate_review_mesh_result(result, profile=profile)
                self.assertEqual(validation["status"], "FAIL")
                self.assertIn("review-mesh-result-usage-unavailable", {b["code"] for b in validation["blockers"]})
                # Relabeling or deleting the unknown marker never makes null a measured zero.
                for marker in [None, "OBSERVED"]:
                    forged = deepcopy(result)
                    if marker is None:
                        forged.pop("budgetUsageStatus")
                    else:
                        forged["budgetUsageStatus"] = marker
                    forged["resultDigest"] = canonical_digest({k: v for k, v in forged.items() if k != "resultDigest"})
                    self.assertEqual(validate_review_mesh_result(forged, profile=profile)["status"], "FAIL")

    def test_import_observed_zero_remains_distinct_from_unknown(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = _raw_output()
        raw["budgetUsage"] = {key: 0 for key in raw["budgetUsage"]}
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertEqual(result["budgetUsage"], raw["budgetUsage"])
        self.assertIsInstance(result["crossCheckReceipt"], dict)
        self.assertNotIn("budgetUsageStatus", result)
        self.assertEqual(validate_review_mesh_result(result, profile=profile)["status"], "PASS")

    def test_import_never_grants_quorum_or_independence(self) -> None:
        profile, assignment = _profile_and_assignment()
        raw = {**_raw_output(), "independent": True, "quorumSatisfied": True, "roundParticipation": {"eligible": True}}
        result = import_review_mesh_result(profile=profile, assignment=assignment, reviewer_output=raw)
        self.assertFalse(result["roundParticipation"]["eligible"])
        self.assertIsNone(result["independentEvidence"])

    def test_import_result_redacts_secret_like_markers_without_raw_output(self) -> None:
        profile, assignment = _profile_and_assignment()

        result = import_review_mesh_result(
            profile=profile,
            assignment=assignment,
            reviewer_output={
                "schemaVersion": "reviewer-output.test",
                "status": "FAIL",
                "budgetUsage": {"invocations": 1, "inputTokens": 100, "outputTokens": 20, "wallSeconds": 3},
                "findings": [
                    {
                        "id": "F1",
                        "severity": "MEDIUM",
                        "status": "open",
                        "message": "token " + "sk-" + "abcdefghijklmnopqrstuv",
                    }
                ],
            },
        )

        self.assertEqual(result["schemaVersion"], "agent-review-mesh-result.v1")
        self.assertEqual(result["redaction"]["status"], "REDACTED")
        self.assertEqual(result["redaction"]["secretLikeMarkersRedacted"], 1)
        self.assertFalse(result["import"]["rawOutputStored"])
        self.assertIn("[REDACTED]", result["findings"][0]["message"])
        self.assertFalse(result["roundParticipation"]["eligible"])
        self.assertEqual(
            result["roundParticipation"]["reasonCode"],
            "review-verdict-and-terminal-job-required",
        )

    def test_import_result_rejects_local_absolute_paths_by_default(self) -> None:
        profile, assignment = _profile_and_assignment()

        with self.assertRaises(LifecycleError) as raised:
            import_review_mesh_result(
                profile=profile,
                assignment=assignment,
                reviewer_output={
                    "budgetUsage": {"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
                    "findings": [
                        {"id": "F1", "severity": "LOW", "status": "open", "message": "/Us" + "ers/example/private.txt"}
                    ],
                },
            )

        self.assertEqual(raised.exception.code, "review-mesh-local-path-leakage")

    def test_import_result_can_redact_explicit_local_evidence_refs(self) -> None:
        profile, assignment = _profile_and_assignment()

        result = import_review_mesh_result(
            profile=profile,
            assignment=assignment,
            reviewer_output={
                "budgetUsage": {"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
                "findings": [
                    {"id": "F1", "severity": "LOW", "status": "open", "message": "/Vo" + "lumes/Work/evidence.json"}
                ],
            },
            allow_local_evidence_refs=True,
        )

        self.assertEqual(result["redaction"]["localPathsRedacted"], 1)
        self.assertIn("[LOCAL_PATH]", result["findings"][0]["message"])

    def test_import_result_normalizes_public_locator_in_finding(self) -> None:
        profile, assignment = _profile_and_assignment()

        result = import_review_mesh_result(
            profile=profile,
            assignment=assignment,
            reviewer_output={
                "budgetUsage": {"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
                "findings": [
                    {
                        "id": "F1",
                        "severity": "LOW",
                        "status": "open",
                        "message": "HTTPS://EXAMPLE.COM:443/review#Finding",
                    }
                ],
            },
        )

        self.assertEqual(result["findings"][0]["message"], "https://example.com/review#Finding")
        self.assertEqual(result["redaction"]["status"], "PASS")


def _profile_and_assignment() -> tuple[dict, dict]:
    profile = build_review_mesh_profile(independence_required=False)
    assignment = build_review_mesh_assignment(
        profile=profile,
        assignment_id="RM-1",
        subject={"taskId": "TASK-1", "reviewMeshBlockingOptIn": True},
        reviewer={"role": "reviewer", "modelClass": "strong-reasoning"},
        blocking=True,
    )
    return profile, assignment


def _raw_output() -> dict:
    return {
        "schemaVersion": "reviewer-output.test",
        "status": "FAIL",
        "budgetUsage": {"invocations": 1, "inputTokens": 10, "outputTokens": 4, "wallSeconds": 1},
        "findings": [
            {"id": "F1", "severity": "MEDIUM", "status": "open", "message": "First finding", "details": {"line": 7}},
            {"id": "F2", "severity": "LOW", "status": "open", "message": "Second finding"},
        ],
    }


def _repair_result_digests(result: dict) -> None:
    cross = result["crossCheckReceipt"]
    cross["receiptDigest"] = canonical_digest({k: v for k, v in cross.items() if k != "receiptDigest"})
    result["resultDigest"] = canonical_digest({k: v for k, v in result.items() if k != "resultDigest"})


if __name__ == "__main__":
    unittest.main()
