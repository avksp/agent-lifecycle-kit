"""Public synthetic keys test exact signed subjects, never real operator custody."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.ed25519 import fingerprint, publickey_from_seed, sign
from agent_lifecycle.contracts.operator_signature import (
    MAX_SIGNATURE_BYTES,
    build_operator_payload,
    expected_operator_decision,
    operator_signing_message,
    verify_operator_envelope,
    verify_operator_subject,
)
from agent_lifecycle.contracts.operator_signature_schemas import (
    ENVELOPE,
    POLICY,
    ROOT,
    operator_authority_marker,
    require_operator_authority,
    validate_operator_envelope,
    validate_operator_payload,
    validate_operator_policy,
)

SEED = bytes(range(32))
NOW = "2026-11-17T01:00:00.000000Z"
START = "2020-01-01T00:00:00.000000Z"
END = "2090-01-01T00:00:00.000000Z"


def policy(mode="required"):
    key = publickey_from_seed(SEED)
    return {
        "schemaVersion": POLICY,
        "mode": mode,
        "trustRoot": {
            "schemaVersion": ROOT,
            "rootId": "public-test-root",
            "keys": [
                {
                    "publicKeyHex": key.hex(),
                    "fingerprint": fingerprint(key),
                    "validFrom": "2000-01-01T00:00:00.000000Z",
                    "expiresAt": "2100-01-01T00:00:00.000000Z",
                }
            ],
        },
    }


def manifest(mode="required"):
    selected = policy(mode)
    value = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package", "artifactRoot": "work"},
        "baseRevision": {"sha": "source", "ref": "test"},
        "packageIntegrity": {"required": True, "lockSchemaVersion": "agent-plan-lock.v2"},
        "operatorSignaturePolicy": selected,
    }
    if mode == "required":
        value["operatorSignatureAuthority"] = operator_authority_marker(selected)
    return value


def state(mode="required", phase="AWAITING_AUTHORIZATION"):
    selected = policy(mode)
    value = {
        "schemaVersion": "agent-workflow-state.v7" if mode == "required" else "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "stateRevision": 1,
        "planRevision": 1,
        "planDigest": "a" * 64,
        "sourceRevision": "source",
        "phase": phase,
        "startMode": "approval-required",
        "packageRoot": ".",
        "eventLog": "events.jsonl",
        "tasks": [],
        "operationLedger": {},
        "authorization": {"required": True, "granted": False},
        "budgets": {},
        "storage": {"schemaVersion": "agent-workflow-storage.v1", "root": "run.state.json.storage"},
        "operatorSignaturePolicy": selected,
    }
    if mode == "required":
        value["operatorSignatureAuthority"] = operator_authority_marker(selected)
    return value


def envelope(container, kind="freeze", *, operation_id=None, subject=None, **changes):
    payload = build_operator_payload(
        container,
        kind,
        operation_id=operation_id,
        subject=subject,
        signer_fingerprint=container["operatorSignaturePolicy"]["trustRoot"]["keys"][0]["fingerprint"],
        valid_from=START,
        expires_at=END,
    )
    payload.update(changes)
    return {
        "schemaVersion": ENVELOPE,
        "payload": payload,
        "signatureHex": sign(SEED, operator_signing_message(payload)).hex(),
    }


NEGATIVE_CASES = ("missing", "flipped", "expired-key", "unpinned", "wrong-domain", "other-plan", "replaced-root")


def negative_case(container, kind, case, *, operation_id=None, subject=None):
    selected = deepcopy(container)
    args = {"operation_id": operation_id, "subject": subject}
    if case == "expired-key":
        selected["operatorSignaturePolicy"]["trustRoot"]["keys"][0]["expiresAt"] = "2024-01-01T00:00:00.000000Z"
        if "operatorSignatureAuthority" in selected:
            selected["operatorSignatureAuthority"] = operator_authority_marker(selected["operatorSignaturePolicy"])
        return selected, envelope(
            selected, kind, **args, validFrom="2022-01-01T00:00:00.000000Z", expiresAt="2023-01-01T00:00:00.000000Z"
        )
    signed = envelope(selected, kind, **args)
    if case == "missing":
        return selected, None
    if case == "flipped":
        raw = bytearray.fromhex(signed["signatureHex"])
        raw[-1] ^= 1
        signed["signatureHex"] = raw.hex()
    if case == "unpinned":
        signed = envelope(selected, kind, **args, signerFingerprint="ed25519:" + "b" * 64)
    if case == "wrong-domain":
        wrong = "accept" if kind != "accept" else "freeze"
        message = ("agent-lifecycle-operator-" + wrong + "-v1\0").encode("ascii") + canonical_digest(
            signed["payload"]
        ).encode("ascii")
        signed["signatureHex"] = sign(SEED, message).hex()
    if case == "other-plan":
        signed = envelope(selected, kind, **args, planDigest="b" * 64)
    if case == "replaced-root":
        selected["operatorSignaturePolicy"]["trustRoot"]["rootId"] = "replacement-after-signing"
        if "operatorSignatureAuthority" in selected:
            selected["operatorSignatureAuthority"] = operator_authority_marker(selected["operatorSignaturePolicy"])
    return selected, signed


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class OperatorSignatureContractsTests(unittest.TestCase):
    def test_explicit_null_is_not_a_policy_or_authority_marker(self):
        from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state

        for field in ("operatorSignaturePolicy", "operatorSignatureAuthority"):
            value = manifest("advisory")
            value[field] = None
            with self.subTest(manifestField=field), self.assertRaises(LifecycleError):
                require_operator_authority(value)
            value = state("advisory")
            value[field] = None
            with self.subTest(stateField=field), self.assertRaises(LifecycleError):
                validate_workflow_state(value)

    def test_public_file_boundary_rejects_duplicate_oversized_symlink_and_nonregular_input(self):
        m = manifest()
        signed = envelope(m)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "signature.json"
            invalid_json = (b'{"schemaVersion":"duplicate","schemaVersion":"duplicate"}', b"[1]", b"{")
            for raw in (*invalid_json, b" " * (MAX_SIGNATURE_BYTES + 1)):
                target.write_bytes(raw)
                before = inventory(root)
                with self.assertRaises(LifecycleError):
                    verify_operator_subject(m, "freeze", root=root, signature_path="signature.json", observed_at=NOW)
                self.assertEqual(before, inventory(root))
            target.write_bytes(canonical_bytes(signed))
            alias = root / "alias.json"
            try:
                alias.symlink_to(target)
            except OSError:
                pass
            else:
                with self.assertRaises(LifecycleError):
                    verify_operator_subject(m, "freeze", root=root, signature_path="alias.json", observed_at=NOW)
            (root / "directory").mkdir()
            for path in ("directory", "../signature.json", str(target.absolute())):
                with self.subTest(path=path), self.assertRaises(LifecycleError):
                    verify_operator_subject(m, "freeze", root=root, signature_path=path, observed_at=NOW)

    def test_three_decisions_bind_exact_public_subject_and_no_native_permission(self):
        for kind in ("freeze", "authorize", "accept"):
            with self.subTest(kind=kind):
                container = manifest() if kind == "freeze" else state()
                args = {} if kind == "freeze" else {"operation_id": "operation", "subject": {"decision": kind}}
                expected = expected_operator_decision(container, kind, **args)
                signed = envelope(container, kind, **args)
                result = verify_operator_envelope(policy(), signed, expected, observed_at=NOW)
                self.assertTrue(result["signatureVerified"])
                self.assertFalse(result["nativePermissionGranted"])
                self.assertFalse(result["keyCustodyVerified"])
                self.assertEqual(result["rootSelectionStrength"], "Declared")
                self.assertEqual(result["payloadDigest"], canonical_digest(signed["payload"]))
                independent = ("agent-lifecycle-operator-" + kind + "-v1\0").encode("ascii") + canonical_digest(
                    signed["payload"]
                ).encode("ascii")
                self.assertEqual(operator_signing_message(signed["payload"]), independent)

    def test_all_static_bindings_refuse_transplant_without_claim_promotion(self):
        container = state()
        args = {"operation_id": "operation", "subject": {"decision": "ALLOW"}}
        signed = envelope(container, "authorize", **args)
        original = expected_operator_decision(container, "authorize", **args)
        for field in ("packageId", "planDigest", "sourceRevision", "runId", "operationId", "subjectDigest"):
            with self.subTest(field=field):
                expected = {**original, field: "b" * 64}
                result = verify_operator_envelope(policy(), signed, expected, observed_at=NOW)
                self.assertFalse(result["signatureVerified"])
                self.assertEqual(result["claimStrength"], "Declared")
        for field in ("planRevision", "expectedStateRevision"):
            expected = {**original, field: original[field] + 1}
            self.assertFalse(verify_operator_envelope(policy(), signed, expected, observed_at=NOW)["signatureVerified"])

    def test_bit_flip_and_wrong_domain_and_unpinned_signer_refuse(self):
        m = manifest()
        expected = expected_operator_decision(m, "freeze")
        original = envelope(m)
        mutated = deepcopy(original)
        signature = bytearray.fromhex(mutated["signatureHex"])
        signature[0] ^= 1
        mutated["signatureHex"] = signature.hex()
        wrong_domain = deepcopy(original)
        wrong_domain["signatureHex"] = sign(
            SEED, b"agent-lifecycle-operator-authorize-v1\0" + canonical_digest(original["payload"]).encode("ascii")
        ).hex()
        unpinned = envelope(m, signerFingerprint="ed25519:" + "b" * 64)
        for signed in ({}, mutated, wrong_domain, unpinned):
            with self.subTest(signed=signed.keys()):
                self.assertFalse(
                    verify_operator_envelope(policy(), signed, expected, observed_at=NOW)["signatureVerified"]
                )

    def test_expired_future_and_replaced_root_are_distinct_validly_signed_inputs(self):
        m = manifest()
        expected = expected_operator_decision(m, "freeze")
        for start, end in (
            ("2022-01-01T00:00:00.000000Z", "2023-01-01T00:00:00.000000Z"),
            ("2030-01-01T00:00:00.000000Z", "2031-01-01T00:00:00.000000Z"),
        ):
            signed = envelope(m, validFrom=start, expiresAt=end)
            self.assertFalse(verify_operator_envelope(policy(), signed, expected, observed_at=NOW)["signatureVerified"])
        changed = policy()
        changed["trustRoot"]["rootId"] = "replacement-with-same-key"
        self.assertFalse(verify_operator_envelope(changed, envelope(m), expected, observed_at=NOW)["signatureVerified"])
        expired = manifest()
        expired["operatorSignaturePolicy"]["trustRoot"]["keys"][0]["expiresAt"] = "2024-01-01T00:00:00.000000Z"
        expired["operatorSignatureAuthority"] = operator_authority_marker(expired["operatorSignaturePolicy"])
        old_signed = envelope(expired, validFrom="2022-01-01T00:00:00.000000Z", expiresAt="2023-01-01T00:00:00.000000Z")
        self.assertFalse(
            verify_operator_envelope(
                expired["operatorSignaturePolicy"],
                old_signed,
                expected_operator_decision(expired, "freeze"),
                observed_at=NOW,
            )["signatureVerified"]
        )

    def test_key_and_decision_expiry_have_distinct_safe_diagnostics(self):
        value = manifest()
        signed = envelope(value)
        results = [
            verify_operator_envelope(
                value["operatorSignaturePolicy"],
                signed,
                expected_operator_decision(value, "freeze"),
                observed_at=stamp,
            )
            for stamp in ("2095-01-01T00:00:00.000000Z", "2101-01-01T00:00:00.000000Z")
        ]
        self.assertEqual({r["reason"] for r in results}, {"operator-signature-invalid"})
        self.assertIn("decision", results[0]["reasonDetail"])
        self.assertIn("key", results[1]["reasonDetail"])
        self.assertNotEqual(results[0]["reasonDetail"], results[1]["reasonDetail"])
        self.assertTrue(all(not r["nativePermissionGranted"] for r in results))

    def test_strict_shapes_reject_ambiguous_secret_and_malformed_fields(self):
        for mode in ([], {}, True, 1, "unknown"):
            invalid = policy()
            invalid["mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(LifecycleError):
                validate_operator_policy(invalid)
        for update in ({"privateKey": None}, {"unexpected": 1}):
            invalid = {**envelope(manifest()), **update}
            with self.assertRaises(LifecycleError):
                validate_operator_envelope(invalid)
        for change in (
            {"planRevision": True},
            {"runId": "must-be-null"},
            {"signerFingerprint": "bad"},
            {"decisionKind": []},
        ):
            invalid = {**envelope(manifest())["payload"], **change}
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_operator_payload(invalid)
        invalid = policy()
        invalid["trustRoot"]["keys"] *= 2
        with self.assertRaises(LifecycleError):
            validate_operator_policy(invalid)

    def test_required_integrity_marker_and_format_cannot_be_erased(self):
        for key in ("packageIntegrity", "operatorSignatureAuthority"):
            invalid = manifest()
            invalid.pop(key)
            with self.subTest(key=key), self.assertRaises(LifecycleError):
                require_operator_authority(invalid)
        invalid = manifest()
        invalid["packageIntegrity"]["lockSchemaVersion"] = "agent-plan-lock.v1"
        with self.assertRaises(LifecycleError):
            require_operator_authority(invalid)
        for key in ("operatorSignaturePolicy", "operatorSignatureAuthority"):
            invalid = state()
            invalid.pop(key)
            with self.subTest(key=key), self.assertRaises(LifecycleError):
                require_operator_authority(invalid, state=True)
        invalid = state()
        invalid["schemaVersion"] = "agent-workflow-state.v5"
        with self.assertRaises(LifecycleError):
            require_operator_authority(invalid, state=True)

    def test_off_is_absence_and_does_not_select_a_root(self):
        self.assertIsNone(require_operator_authority({}))
        self.assertIsNone(
            require_operator_authority({"operatorSignaturePolicy": {"schemaVersion": POLICY, "mode": "off"}})
        )
        with self.assertRaises(LifecycleError):
            require_operator_authority({"operatorSignatureAuthority": operator_authority_marker(policy())})


if __name__ == "__main__":
    unittest.main()
