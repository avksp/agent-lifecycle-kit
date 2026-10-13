"""Closed reviewer records reject malformed or ambiguous proof inputs."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.reviewer_identity_schemas import (
    ATTESTATION_V1,
    CLAIMS_V1,
    TRUST_ROOT_V1,
    parse_reviewer_utc,
    validate_reviewer_attestation_shape,
    validate_reviewer_trust_root,
)
from agent_lifecycle.contracts.schemas import get_schema

FIXTURE = Path(__file__).resolve().parents[1] / "review/fixtures/reviewer_provenance.v1.json"


class ReviewerIdentitySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["authority"], "TEST_AUTHORITY_ONLY")
        self.root = fixture["context"]["trustRoot"]
        self.proof = fixture["attestation"]

    def test_public_test_fixture_is_closed_and_registered(self) -> None:
        self.assertEqual(validate_reviewer_trust_root(self.root), self.root)
        self.assertEqual(validate_reviewer_attestation_shape(self.proof), self.proof)
        for schema_id in (TRUST_ROOT_V1, CLAIMS_V1, ATTESTATION_V1):
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)
        self.assertFalse(get_schema(TRUST_ROOT_V1)["properties"]["authorizedIssuers"]["items"]["additionalProperties"])
        self.assertFalse(get_schema(ATTESTATION_V1)["properties"]["signer"]["additionalProperties"])

    def test_root_rejects_unknown_duplicate_and_oversized_identity(self) -> None:
        for mutation in (
            lambda root: root.update(extra=True),
            lambda root: root["authorizedIssuers"].append(copy.deepcopy(root["authorizedIssuers"][0])),
            lambda root: root["authorizedIssuers"][0]["actorIds"].append("reviewer"),
            lambda root: root["authorizedIssuers"][0].update(actorIds=["é" * 65]),
            lambda root: root.update(revision=True),
        ):
            with self.subTest(mutation=mutation):
                root = copy.deepcopy(self.root)
                mutation(root)
                with self.assertRaises(LifecycleError):
                    validate_reviewer_trust_root(root)

    def test_attestation_rejects_unknown_fields_bad_calendar_and_signature(self) -> None:
        for field, value in (
            ("extra", True),
            ("signature", "0" * 127),
            ("claims.issuedAt", "2026-02-30T00:00:00Z"),
            ("claims.phase", "implementation-audit"),
            ("claims.actorId", "é" * 65),
            ("signer.algorithm", "RSA"),
        ):
            with self.subTest(field=field):
                proof = copy.deepcopy(self.proof)
                target = proof
                names = field.split(".")
                for name in names[:-1]:
                    target = target[name]
                target[names[-1]] = value
                with self.assertRaises(LifecycleError):
                    validate_reviewer_attestation_shape(proof)
        with self.assertRaises(LifecycleError):
            parse_reviewer_utc("2026-09-23T02:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
