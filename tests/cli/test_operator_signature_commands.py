"""Real public CLI decisions using known synthetic keys, without key custody claims."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_bytes
from agent_lifecycle.contracts.ed25519 import sign
from agent_lifecycle.contracts.operator_signature_schemas import ENVELOPE, POLICY
from tests.contracts.test_operator_signature import END, SEED, START, inventory, manifest
from tests.planning.test_operator_signature_verify import prepare_package
from tests.workflow.test_operator_signature_gates import native_fixture

SOURCE = Path(__file__).resolve().parents[2] / "src"


class OperatorSignatureCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(value) + b"\n")

    def cli(self, *argv, success=True):
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "agent_lifecycle", *argv],
            cwd=self.root,
            env=dict(os.environ, PYTHONPATH=str(SOURCE), PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0 if success else 2, (argv, proc.stdout, proc.stderr))
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout)

    def request(self, kind, *inputs, out=None):
        value = manifest()
        fingerprint = value["operatorSignaturePolicy"]["trustRoot"]["keys"][0]["fingerprint"]
        return self.cli(
            "operator-signature",
            "request",
            "--kind",
            kind,
            *inputs,
            "--signer-fingerprint",
            fingerprint,
            "--valid-from",
            START,
            "--expires-at",
            END,
            *(["--out", out] if out else []),
        )

    def test_public_freeze_request_and_verify_are_inert_and_reconstruct_signed_bytes(self):
        self.write("manifest.json", manifest())
        before = inventory(self.root)
        requested = self.request("freeze", "--manifest", "manifest.json")
        self.assertFalse(requested["nativePermissionGranted"])
        self.assertFalse(requested["authorityClaimed"])
        self.assertEqual(before, inventory(self.root))
        self.write(
            "signature.json",
            {
                "schemaVersion": ENVELOPE,
                "payload": requested["payload"],
                "signatureHex": sign(SEED, bytes.fromhex(requested["signingMessageHex"])).hex(),
            },
        )
        before = inventory(self.root)
        verified = self.cli(
            "operator-signature",
            "verify",
            "--kind",
            "freeze",
            "--manifest",
            "manifest.json",
            "--signature",
            "signature.json",
        )
        self.assertTrue(verified["signatureVerified"])
        self.assertFalse(verified["nativePermissionGranted"])
        self.assertFalse(verified["keyCustodyVerified"])
        self.assertEqual(before, inventory(self.root))

    def test_state_requests_cover_authorize_and_accept_then_actual_native_cli_still_checks_signature(self):
        for kind in ("authorize", "accept"):
            with self.subTest(kind=kind):
                _path, subject = native_fixture(self.root, kind)
                inputs = ["--state", "run.state.json", "--subject", subject, "--operation-id", "operation"]
                requested = self.request(kind, *inputs)
                self.assertEqual(requested["payload"]["expectedStateRevision"], 1)
                result = self.cli(
                    "operator-signature",
                    "verify",
                    "--kind",
                    kind,
                    *inputs,
                    "--signature",
                    subject + ".operator-signature.json",
                )
                self.assertTrue(result["signatureVerified"])
                # Read-only verification does not consume the native operation.
                args = [
                    "workflow",
                    "finalize" if kind == "accept" else "authorize",
                    "--state",
                    "run.state.json",
                    "--operation-id",
                    "operation",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "Synthetic public CLI",
                ]
                args += (
                    ["--final-audit", subject, "--proof", "proof.json"] if kind == "accept" else ["--receipt", subject]
                )
                self.assertEqual(self.cli(*args)["phase"], "COMPLETE" if kind == "accept" else "READY")
                # Each subcase starts a distinct synthetic workspace journal.
                for p in sorted(self.root.rglob("*"), reverse=True):
                    if p.is_file() or p.is_symlink():
                        p.unlink()
                    elif p.is_dir():
                        p.rmdir()

    def test_actual_canonical_freeze_cli_binds_public_signature(self):
        _m, name, review = prepare_package(self.root)
        result = self.cli("plan", "lock-create", "--manifest", name, "--review", review)
        lock = json.loads((self.root / result["lockPath"]).read_bytes())
        self.assertTrue(lock["operatorSignature"]["signatureVerified"])

    def test_required_invalid_verify_is_exit_two_with_zero_protected_writes(self):
        self.write("manifest.json", manifest())
        self.write("invalid.json", {})
        before = inventory(self.root)
        failed = self.cli(
            "operator-signature",
            "verify",
            "--kind",
            "freeze",
            "--manifest",
            "manifest.json",
            "--signature",
            "invalid.json",
            "--out",
            "diagnostic.json",
            success=False,
        )
        self.assertEqual(failed["code"], "operator-signature-invalid")
        self.assertEqual(before, inventory(self.root))

    def test_advisory_reports_invalid_and_off_never_requires_a_signature_file(self):
        self.write("manifest.json", manifest("advisory"))
        result = self.cli(
            "operator-signature",
            "verify",
            "--kind",
            "freeze",
            "--manifest",
            "manifest.json",
            "--signature",
            "missing.json",
            "--out",
            "diagnostic.json",
        )
        self.assertEqual(result["status"], "INVALID")
        self.assertFalse(result["signatureVerified"])
        value = manifest("advisory")
        value["operatorSignaturePolicy"] = {"schemaVersion": POLICY, "mode": "off"}
        self.write("manifest.json", value)
        result = self.cli(
            "operator-signature",
            "verify",
            "--kind",
            "freeze",
            "--manifest",
            "manifest.json",
            "--signature",
            "still-missing.json",
        )
        self.assertEqual(result["status"], "OFF")

    def test_output_is_create_only_and_cannot_enter_frozen_or_native_authority(self):
        self.write("manifest.json", manifest())
        self.request("freeze", "--manifest", "manifest.json", out="public/request.json")
        fingerprint = manifest()["operatorSignaturePolicy"]["trustRoot"]["keys"][0]["fingerprint"]
        for name in (
            "public/request.json",
            ".git/config",
            "plans/package/request.json",
            "run.state.json",
            "events.jsonl",
            "manifest.json",
        ):
            before = inventory(self.root)
            self.cli(
                "operator-signature",
                "request",
                "--kind",
                "freeze",
                "--manifest",
                "manifest.json",
                "--signer-fingerprint",
                fingerprint,
                "--valid-from",
                START,
                "--expires-at",
                END,
                "--out",
                name,
                success=False,
            )
            self.assertEqual(before, inventory(self.root))

    def test_public_schema_registry_and_native_v7_are_discoverable(self):
        for name in ("policy", "authority", "request", "validation"):
            schema = self.cli("schema", "show", "agent-operator-signature-" + name + ".v1")
            self.assertIn("$id", schema)
        for schema_id in (
            "agent-operator-trust-root.v1",
            "agent-operator-decision.v1",
            "agent-operator-signature.v1",
            "agent-workflow-state.v7",
        ):
            self.assertEqual(self.cli("schema", "show", schema_id)["$id"], schema_id)


if __name__ == "__main__":
    unittest.main()
