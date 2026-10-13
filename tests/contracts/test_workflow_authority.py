"""D-AUTH shapes bind identities without granting signature or native authority."""

from __future__ import annotations

import hashlib
import unittest
from copy import deepcopy

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.ed25519 import sign
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.workflow_authority import (
    validate_initial_authority_inputs,
    validate_selected_grant_envelope,
    verify_signed_authority_snapshot,
    verify_signed_window_grant,
)
from agent_lifecycle.contracts.workflow_authority_schemas import (
    AUTHORITY_DECISION_V1,
    AUTHORITY_INPUT_BUNDLE_V1,
    AUTHORITY_SNAPSHOT_V1,
    BOOTSTRAP_PIN_V1,
    ISSUER_PERMISSION_V1,
    WINDOW_GRANT_V1,
    validate_authority_decision_shape,
    validate_authority_input_bundle,
    validate_authority_snapshot_shape,
    validate_bootstrap_pin,
    validate_window_grant_shape,
)
from agent_lifecycle.neutrality.ed25519 import fingerprint, publickey_from_seed


def _pin() -> dict:
    public_key = publickey_from_seed(bytes(range(32)))
    return {
        "schemaVersion": BOOTSTRAP_PIN_V1, "authorityDomain": "authority:run",
        "rootId": "root", "rootGeneration": "generation:1",
        "rootPublicKeyHex": public_key.hex(), "rootFingerprint": fingerprint(public_key),
        "bindingId": "binding", "runId": "run", "budgetScopeId": "budget:run",
        "journalIdentity": "journal", "expectedInitialSnapshotDigest": "a" * 64,
        "clockPolicy": "QUALIFIED_HOST_UTC_NONDECREASING",
        "qualificationRef": {"path": "proof/qualification.json", "sha256": "b" * 64, "bytes": 12},
        "trustMode": "QUALIFIED_LOCAL_OPERATOR",
    }


def _grant() -> dict:
    return {
        "schemaVersion": WINDOW_GRANT_V1, "authorityDomain": "authority:run",
        "rootId": "root", "rootGeneration": "generation:1",
        "issuerId": "issuer", "issuerGeneration": "generation:1",
        "nonce": "a" * 64,
        "scope": {
            "runId": "run", "packageId": "package", "budgetScopeId": "budget:run",
            "journalIdentity": "journal", "bindingId": "binding",
            "originalPlanDigest": "b" * 64, "effectivePlanDigest": "c" * 64,
            "sourceRevision": "source", "evidenceSubjectDigest": "d" * 64,
        },
        "permission": "closing.activate", "closingWindowId": "window",
        "windowIntentDigest": "e" * 64, "expectedWorkflowRevision": 2,
        "originalAuthorizationDigest": "f" * 64, "originalDeadlineDigest": "1" * 64,
        "originalBlockerDigest": "2" * 64,
        "allowedActions": ["read-evidence", "final-audit", "finalize"],
        "allowedWritesDigest": "3" * 64, "resourceApprovalDigest": "4" * 64,
        "validFrom": "2026-09-23T01:00:00.000000Z",
        "expiresAt": "2026-09-23T02:00:00.000000Z",
        "issuedUnderEpoch": 1, "issuedUnderSnapshotDigest": "5" * 64,
        "signature": {"algorithm": "Ed25519", "signerFingerprint": "ed25519:" + "6" * 64,
                      "valueHex": "7" * 128},
    }


def _issuer() -> dict:
    public_key = publickey_from_seed(bytes(range(1, 33)))
    return {
        "issuerId": "issuer", "issuerGeneration": "generation:1",
        "publicKeyHex": public_key.hex(), "fingerprint": fingerprint(public_key),
        "validFrom": "2026-09-23T00:00:00.000000Z",
        "expiresAt": "2026-09-23T03:00:00.000000Z",
        "scope": _grant()["scope"], "permissions": ["closing.activate"],
        "allowedActions": ["read-evidence", "final-audit", "finalize"],
        "resourceApprovalDigest": "4" * 64, "allowedWritesDigest": "3" * 64,
    }


def _signed(document: dict, seed: bytes, domain: bytes) -> dict:
    value = deepcopy(document)
    key = publickey_from_seed(seed)
    unsigned = {name: item for name, item in value.items() if name != "signature"}
    message = domain + canonical_digest(unsigned).encode("ascii")
    value["signature"] = {"algorithm": "Ed25519", "signerFingerprint": fingerprint(key),
                          "valueHex": sign(seed, message).hex()}
    return value


class WorkflowAuthoritySchemaTests(unittest.TestCase):
    def test_authority_decision_kinds_are_closed_records_not_grants(self) -> None:
        value = {
            "schemaVersion": AUTHORITY_DECISION_V1, "decisionId": "decision",
            "bindingId": "binding", "journalIdentity": "journal", "authorityDomain": "authority:run",
            "rootFingerprint": _pin()["rootFingerprint"], "issuerId": "issuer",
            "issuerGeneration": "generation:1", "nonce": "a" * 64,
            "grantDigest": "b" * 64, "currentSnapshotDigest": "c" * 64,
            "authorityEpoch": 1, "operationId": "op", "requestDigest": "d" * 64,
            "expectedWorkflowRevision": 2, "authorizedAt": "2026-09-23T01:00:00.000000Z",
            "expiresAt": "2026-09-23T02:00:00.000000Z", "permission": "closing.activate",
            "windowIntentDigest": "e" * 64, "resourceApprovalDigest": "f" * 64,
            "allowedWritesDigest": "0" * 64, "decisionKind": "ACTIVATION",
            "claimId": None, "action": None, "clockObservationDigest": "1" * 64,
        }
        self.assertEqual(get_schema(AUTHORITY_DECISION_V1)["$id"], AUTHORITY_DECISION_V1)
        self.assertIs(validate_authority_decision_shape(value), value)
        for kind, claim_id, action in (
            ("CLAIM", "claim-1", "report"),
            ("PRODUCE_PROOF", None, "finalize"),
            ("FINALIZE", None, "finalize"),
        ):
            self.assertEqual(validate_authority_decision_shape({
                **value, "decisionKind": kind, "claimId": claim_id, "action": action,
            })["decisionKind"], kind)
        for invalid in (
            {**value, "decisionKind": "ACTIVATION", "action": "report"},
            {**value, "decisionKind": "CLAIM", "claimId": None, "action": "report"},
            {**value, "decisionKind": "FINALIZE", "claimId": "claim-1", "action": "finalize"},
            {**value, "authorityEpoch": True},
            {**value, "expiresAt": "2026-09-23T00:00:00.000000Z"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LifecycleError):
                validate_authority_decision_shape(invalid)

    def test_authority_input_bundle_is_closed_data_only(self) -> None:
        ref = {"path": "authority/grant.json", "sha256": "a" * 64, "bytes": 120}
        bundle = {
            "schemaVersion": AUTHORITY_INPUT_BUNDLE_V1, "bindingId": "binding",
            "pinDigest": "b" * 64, "grantRef": ref,
            "issuanceSnapshotDigest": "c" * 64, "expectedCurrentEpoch": 2,
            "windowRequestRef": ref, "resourceApprovalRef": ref,
            "allowedWritesRef": ref, "deadlineInputRef": ref,
        }
        self.assertEqual(get_schema(AUTHORITY_INPUT_BUNDLE_V1)["$id"], AUTHORITY_INPUT_BUNDLE_V1)
        self.assertIs(validate_authority_input_bundle(bundle), bundle)
        for invalid in (
            {**bundle, "operatorQualified": True},
            {**bundle, "expectedCurrentEpoch": True},
            {**bundle, "pinDigest": "B" * 64},
            {**bundle, "grantRef": {**ref, "bytes": 0}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LifecycleError):
                validate_authority_input_bundle(invalid)

    def test_initial_inputs_bind_independent_pin_and_exact_artifacts_without_grant(self) -> None:
        qualification = b"operator evidence"
        snapshot = _signed({
            "schemaVersion": AUTHORITY_SNAPSHOT_V1, "authorityDomain": "authority:run",
            "rootId": "root", "rootGeneration": "generation:1", "bindingId": "binding",
            "journalIdentity": "journal", "epoch": 0, "previousSnapshotDigest": None,
            "validFrom": "2026-09-23T00:00:00.000000Z", "expiresAt": "2026-09-24T00:00:00.000000Z",
            "activeIssuers": [_issuer()], "revokedIssuers": [], "revokedGrants": [],
        }, bytes(range(32)), b"agent-lifecycle-workflow-authority-snapshot-v1\x00")
        pin = {
            **_pin(), "expectedInitialSnapshotDigest": canonical_digest(snapshot),
            "qualificationRef": {"path": "proof/qualification.json",
                                 "sha256": hashlib.sha256(qualification).hexdigest(),
                                 "bytes": len(qualification)},
        }
        pin_raw = canonical_bytes(pin)
        ref = {"path": "proof/pin.json", "sha256": hashlib.sha256(pin_raw).hexdigest(),
               "bytes": len(pin_raw)}
        binding = {
            "schemaVersion": "agent-workflow-journal-binding.v1", "bindingId": "binding", "runId": "run",
            "packageId": "package", "budgetScopeId": "budget:run", "canonicalStatePath": "state.json",
            "journalPath": "/qualified/journal.db", "journalIdentity": "journal",
            "storageProtocolVersion": "5", "workflowProtocolVersion": "1", "planDigest": "a" * 64,
            "sourceRevision": "source", "adoptionEpoch": "epoch-1", "authorityMode": "JOURNAL_REQUIRED",
            "workflowAuthorityPinRef": ref, "resourceInventoryRef": ref, "deadlineInventoryRef": ref,
        }
        expected_binding = canonical_digest(binding)
        expected_pin = canonical_digest(pin)
        result = validate_initial_authority_inputs(
            binding, expected_binding, expected_pin, pin_raw, qualification, snapshot,
            observed_at="2026-09-23T01:00:00.000000Z",
        )
        self.assertEqual(result["status"], "DATA_CANDIDATE")
        self.assertFalse(result["bootstrapQualified"])
        self.assertFalse(result["nativePermissionGranted"])
        for selected_pin, selected_qualification, selected_snapshot in (
            ("0" * 64, qualification, snapshot),
            (expected_pin, b"task-selected evidence", snapshot),
            (expected_pin, qualification, {**snapshot, "epoch": 1}),
        ):
            with self.subTest(selected_pin=selected_pin, selected_snapshot=selected_snapshot["epoch"]), \
                    self.assertRaises(LifecycleError):
                validate_initial_authority_inputs(
                    binding, expected_binding, selected_pin, pin_raw, selected_qualification,
                    selected_snapshot, observed_at="2026-09-23T01:00:00.000000Z",
                )

    def test_da03_signed_snapshot_and_grant_are_crypto_only(self) -> None:
        root_seed = bytes(range(32))
        issuer_seed = bytes(range(1, 33))
        snapshot = _signed({
            "schemaVersion": AUTHORITY_SNAPSHOT_V1, "authorityDomain": "authority:run",
            "rootId": "root", "rootGeneration": "generation:1", "bindingId": "binding",
            "journalIdentity": "journal", "epoch": 0, "previousSnapshotDigest": None,
            "validFrom": "2026-09-23T00:00:00.000000Z", "expiresAt": "2026-09-23T04:00:00.000000Z",
            "activeIssuers": [_issuer()], "revokedIssuers": [], "revokedGrants": [],
        }, root_seed, b"agent-lifecycle-workflow-authority-snapshot-v1\x00")
        pin = {**_pin(), "expectedInitialSnapshotDigest": canonical_digest(snapshot)}
        self.assertIs(validate_authority_snapshot_shape(snapshot), snapshot)
        self.assertEqual(get_schema(AUTHORITY_SNAPSHOT_V1)["$id"], AUTHORITY_SNAPSHOT_V1)
        checked = verify_signed_authority_snapshot(pin, snapshot, observed_at="2026-09-23T01:30:00.000000Z")
        self.assertTrue(checked["signatureVerified"])
        self.assertFalse(checked["nativePermissionGranted"])
        grant = _grant()
        grant["issuedUnderEpoch"] = 0
        grant["issuedUnderSnapshotDigest"] = canonical_digest(snapshot)
        grant = _signed(grant, issuer_seed, b"agent-lifecycle-workflow-closing-grant-v1\x00")
        checked = verify_signed_window_grant(
            pin, snapshot, snapshot, grant, expected_scope=grant["scope"],
            observed_at="2026-09-23T01:30:00.000000Z",
        )
        self.assertTrue(checked["signatureVerified"])
        self.assertFalse(checked["nonceConsumed"])
        for changed in ({"windowIntentDigest": "0" * 64}, {"issuedUnderEpoch": 1}):
            with self.subTest(changed=changed), self.assertRaises(LifecycleError):
                verify_signed_window_grant(
                    pin, snapshot, snapshot, {**grant, **changed}, expected_scope=grant["scope"],
                    observed_at="2026-09-23T01:30:00.000000Z",
                )
        successor = _signed({**snapshot, "epoch": 1, "previousSnapshotDigest": canonical_digest(snapshot),
                             "revokedGrants": [{"issuerId": "issuer", "issuerGeneration": "generation:1",
                                                "nonce": grant["nonce"]}]},
                            root_seed, b"agent-lifecycle-workflow-authority-snapshot-v1\x00")
        with self.assertRaises(LifecycleError):
            verify_signed_window_grant(pin, snapshot, successor, grant, expected_scope=grant["scope"],
                                       observed_at="2026-09-23T01:30:00.000000Z")

    def test_da02_pin_key_and_fingerprint_match_but_do_not_prove_bootstrap(self) -> None:
        pin = _pin()
        self.assertEqual(get_schema(BOOTSTRAP_PIN_V1)["$id"], BOOTSTRAP_PIN_V1)
        self.assertIs(validate_bootstrap_pin(pin), pin)
        with self.assertRaises(LifecycleError):
            validate_bootstrap_pin({**pin, "rootFingerprint": "ed25519:" + "0" * 64})
        with self.assertRaises(LifecycleError):
            validate_bootstrap_pin({**pin, "trustMode": "SELF_ASSERTED"})

    def test_da04_grant_has_exact_scope_actions_and_finite_interval(self) -> None:
        grant = _grant()
        self.assertEqual(get_schema(WINDOW_GRANT_V1)["$id"], WINDOW_GRANT_V1)
        self.assertIs(validate_window_grant_shape(grant), grant)
        for change in (
            {"allowedActions": ["finalize", "*"]},
            {"allowedActions": ["finalize", "finalize"]},
            {"expectedWorkflowRevision": True},
            {"expiresAt": grant["validFrom"]},
            {"permission": "task.start"},
        ):
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_window_grant_shape({**grant, **change})
        changed = {**grant, "scope": {**grant["scope"], "wildcard": "*"}}
        with self.assertRaises(LifecycleError):
            validate_window_grant_shape(changed)

    def test_da04_selected_envelope_cannot_expand_issuer_scope_or_approval(self) -> None:
        pin, issuer, grant = _pin(), _issuer(), _grant()
        self.assertEqual(get_schema(ISSUER_PERMISSION_V1)["$id"], ISSUER_PERMISSION_V1)
        grant["signature"]["signerFingerprint"] = issuer["fingerprint"]
        result = validate_selected_grant_envelope(pin, issuer, grant, grant["scope"], "5" * 64)
        self.assertEqual(result["disposition"], "DATA_CANDIDATE")
        for key in ("signatureVerified", "rootSelectionVerified", "currentSnapshotVerified",
                    "nonceConsumed", "nativePermissionGranted"):
            self.assertIs(result[key], False)
        for changed in (
            {"resourceApprovalDigest": "9" * 64},
            {"allowedActions": ["read-evidence", "final-audit", "finalize", "accounting-closeout"]},
            {"expiresAt": "2026-09-23T04:00:00.000000Z"},
        ):
            with self.subTest(changed=changed), self.assertRaises(LifecycleError):
                validate_selected_grant_envelope(pin, issuer, {**grant, **changed}, grant["scope"], "5" * 64)
        with self.assertRaises(LifecycleError):
            validate_selected_grant_envelope(pin, issuer, grant, {**grant["scope"], "runId": "other"}, "5" * 64)
