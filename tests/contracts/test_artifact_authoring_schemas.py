from __future__ import annotations

import copy
import unittest

import jsonschema

from agent_lifecycle.contracts.artifact_authoring_schemas import (
    ARTIFACT_AUTHORING_SCHEMAS,
    AUTHORING_REQUEST,
    validate_authoring_request,
)
from agent_lifecycle.contracts.errors import LifecycleError


class AuthoringSchemaTests(unittest.TestCase):
    def test_published_shape_and_runtime_reject_same_closed_request_mutations(self):
        valid = {
            "schemaVersion": AUTHORING_REQUEST,
            "kind": "json",
            "value": {"note": "advisory"},
            "redactAdvisory": False,
        }
        schema = ARTIFACT_AUTHORING_SCHEMAS[AUTHORING_REQUEST]
        jsonschema.Draft202012Validator.check_schema(schema)
        self.assertEqual(validate_authoring_request(valid), valid)
        jsonschema.validate(valid, schema)
        for mutation in (
            {"schemaVersion": "unknown"},
            {"kind": "stdout"},
            {"value": []},
            {"redactAdvisory": 1},
            {"extra": True},
        ):
            value = {**copy.deepcopy(valid), **mutation}
            with self.subTest(mutation=mutation):
                with self.assertRaises(LifecycleError):
                    validate_authoring_request(value)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(value, schema)

    def test_byte_cap_rejects_before_output(self):
        with self.assertRaisesRegex(LifecycleError, "byte limit"):
            validate_authoring_request(
                {
                    "schemaVersion": AUTHORING_REQUEST,
                    "kind": "json",
                    "value": {"note": "x" * 262144},
                    "redactAdvisory": False,
                }
            )
