from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.neutrality.authority import (  # noqa: E402
    sign_deny_authority,
    signing_key_for_seed,
    trust_root_for_seed,
)
from agent_lifecycle.neutrality.canonical import canonical_bytes, write_json_create  # noqa: E402
from agent_lifecycle.neutrality.ed25519 import fingerprint, publickey_from_seed, sign, verify  # noqa: E402
from agent_lifecycle.neutrality.errors import NeutralityError  # noqa: E402
from agent_lifecycle.neutrality.paths import validate_output_paths  # noqa: E402
from agent_lifecycle.neutrality.policy import load_policy  # noqa: E402
from agent_lifecycle.neutrality.scanner import scan_repository  # noqa: E402


class NeutralityTests(unittest.TestCase):
    def test_ed25519_round_trip(self) -> None:
        seed = bytes(range(32))
        public_key = publickey_from_seed(seed)
        signature = sign(seed, b"message")
        self.assertTrue(verify(public_key, b"message", signature))
        self.assertFalse(verify(public_key, b"changed", signature))
        self.assertTrue(fingerprint(public_key).startswith("ed25519:"))

    def test_scan_detects_deny_literal_without_fragment_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("contains forbidden-origin-marker", encoding="utf-8")
            policy = _policy(root, deny_literals=[])
            report = scan_repository(
                workspace_root=root,
                policy=policy,
                deny_literals=["forbidden-origin-marker"],
                deny_regexes=[],
                scope="current-tree-complete",
                output_paths=[Path("out/report.json"), Path("out/receipt.json")],
            )
            serialized = canonical_bytes(report.to_json({"operationId": "op"})).decode("utf-8")
            self.assertEqual(report.findings[0].category, "deny-literal")
            self.assertNotIn("forbidden-origin-marker", serialized)

    def test_clean_scan_has_zero_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("portable", encoding="utf-8")
            report = scan_repository(
                workspace_root=root,
                policy=_policy(root),
                deny_literals=["absent-marker"],
                deny_regexes=[],
                scope="current-tree-complete",
                output_paths=[Path("out/report.json"), Path("out/receipt.json")],
            )
            self.assertEqual(report.to_json({"operationId": "op"})["counters"]["findings"], 0)

    def test_output_alias_conflict_fails_closed(self) -> None:
        with self.assertRaises(NeutralityError) as caught:
            validate_output_paths([Path("Out/report.json"), Path("out/report.json")])
        self.assertEqual(caught.exception.code, "neutrality-output-alias-conflict")

    def test_occupied_output_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir()
            (root / "out/report.json").write_text("occupied", encoding="utf-8")
            report = scan_repository(
                workspace_root=root,
                policy=_policy(root),
                deny_literals=[],
                deny_regexes=[],
                scope="current-tree-complete",
                output_paths=[Path("out/report.json"), Path("out/receipt.json")],
            )
            self.assertEqual(report.occupied_output_conflicts, 1)

    def test_malformed_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "policy.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(NeutralityError) as caught:
                load_policy(root / "policy.json")
            self.assertEqual(caught.exception.code, "neutrality-policy-schema-unsupported")

    def test_non_object_json_fails_with_stable_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "policy.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(NeutralityError) as caught:
                load_policy(root / "policy.json")
            self.assertEqual(caught.exception.code, "neutrality-json-object-required")

    def test_neutrality_error_uses_stable_branch_codes(self) -> None:
        cases = {
            "external authority path is inside a forbidden root": "neutrality-external-authority-forbidden-root",
            "deny authority signature verification failed": "neutrality-authority-signature-invalid",
            "authority is stale": "neutrality-authority-stale",
            "expected signer is not authorized by trust root": "neutrality-signer-unauthorized",
            "gate receipt planDigest binding mismatch": "neutrality-gate-binding-mismatch",
        }
        for message, code in cases.items():
            with self.subTest(message=message):
                self.assertEqual(NeutralityError(message).code, code)

    def test_authority_fixture_signatures_are_verifiable(self) -> None:
        seed = b"a" * 32
        now = datetime.now(UTC).replace(microsecond=0)
        deny = _deny(seed, now, literals=["x"])
        self.assertEqual(deny["signature"]["signerFingerprint"], fingerprint(publickey_from_seed(seed)))

    def test_authority_inside_workspace_is_rejected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime.now(UTC).replace(microsecond=0)
            seed = b"b" * 32
            _write_authority(root, seed, now, authority_root=root)
            result, payload = _run_cli_json(root, seed)
            self.assertNotEqual(result, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
            self.assertEqual(payload["code"], "neutrality-external-authority-forbidden-root")

    def test_bad_signature_is_rejected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = Path(tempfile.mkdtemp())
            now = datetime.now(UTC).replace(microsecond=0)
            seed = b"c" * 32
            paths = _write_authority(root, seed, now, authority_root=outside)
            deny = json.loads(paths["deny"].read_text(encoding="utf-8"))
            deny["denyLiterals"].append("tampered")
            paths["deny"].write_text(json.dumps(deny), encoding="utf-8")
            result = _run_cli(root, seed, env_paths=paths)
            self.assertNotEqual(result, 0)

    def test_stale_authority_is_rejected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = Path(tempfile.mkdtemp())
            seed = b"d" * 32
            now = datetime.now(UTC).replace(microsecond=0) - timedelta(days=3)
            paths = _write_authority(root, seed, now, authority_root=outside, validity=timedelta(hours=1))
            result = _run_cli(root, seed, env_paths=paths)
            self.assertNotEqual(result, 0)

    def test_fingerprint_mismatch_is_rejected_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = Path(tempfile.mkdtemp())
            now = datetime.now(UTC).replace(microsecond=0)
            seed = b"e" * 32
            paths = _write_authority(root, seed, now, authority_root=outside)
            result = _run_cli(root, b"f" * 32, env_paths=paths)
            self.assertNotEqual(result, 0)

    def test_cli_writes_signed_report_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = Path(tempfile.mkdtemp())
            now = datetime.now(UTC).replace(microsecond=0)
            seed = b"g" * 32
            paths = _write_authority(root, seed, now, authority_root=outside)
            result = _run_cli(root, seed, env_paths=paths)
            self.assertEqual(result, 0)
            self.assertTrue((root / "out/report.json").is_file())
            self.assertTrue((root / "out/receipt.json").is_file())

    def test_zip_entry_limit_breach_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "archive.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a.txt", "a")
                archive.writestr("b.txt", "b")
            policy = _policy(root, max_entries=1)
            report = scan_repository(
                workspace_root=root,
                policy=policy,
                deny_literals=[],
                deny_regexes=[],
                scope="current-tree-complete",
                output_paths=[Path("out/report.json"), Path("out/receipt.json")],
            )
            self.assertEqual(report.archive_limit_breaches, 1)

    def test_create_no_replace_prevents_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "out.json"
            write_json_create(target, {"ok": True})
            with self.assertRaises(FileExistsError):
                write_json_create(target, {"ok": False})

    def test_local_scan_command_writes_authorized_protocol_report(self) -> None:
        from agent_lifecycle.neutrality.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("portable", encoding="utf-8")
            _policy(root)
            _operation_request(root / "request.json", "out/report.json", "agent-neutrality-report.v1")
            cwd = Path.cwd()
            try:
                os.chdir(root)
                result = main(
                    [
                        "scan",
                        "--scope",
                        "current-tree-complete",
                        "--policy",
                        "policy.json",
                        "--operation-request",
                        "request.json",
                        "--report",
                        "out/report.json",
                        "--require-zero-findings",
                    ]
                )
            finally:
                os.chdir(cwd)
            self.assertEqual(result, 0)
            report = json.loads((root / "out/report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["schemaVersion"], "agent-neutrality-report.v1")
            self.assertEqual(report["counters"]["findings"], 0)

    def test_gate_produce_and_verify_round_trip(self) -> None:
        from agent_lifecycle.neutrality.gate import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = Path(tempfile.mkdtemp())
            now = datetime.now(UTC).replace(microsecond=0)
            seed = b"h" * 32
            paths = _write_authority(root, seed, now, authority_root=outside)
            (root / "policy").mkdir()
            (root / "policy/neutrality.policy.json").write_text(
                (root / "policy.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            previous = os.environ.copy()
            os.environ.update(
                {
                    "AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY": str(paths["deny"]),
                    "AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT": str(paths["trust"]),
                    "AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY": str(paths["signing"]),
                    "AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT": fingerprint(publickey_from_seed(seed)),
                }
            )
            try:
                base_args = [
                    "--profile",
                    "profile.json",
                    "--scope",
                    "current-tree-complete",
                    "--gate-id",
                    "neutrality-current-tree",
                    "--run-id",
                    "run",
                    "--package-id",
                    "package",
                    "--task-id",
                    "task",
                    "--attempt",
                    "1",
                    "--phase",
                    "pre-launch",
                    "--operation-id",
                    "operation",
                    "--plan-digest",
                    "0" * 64,
                    "--source-revision",
                    "source",
                    "--workspace-root",
                    str(root),
                    "--operation-output",
                    "gates/receipt.json",
                    "--receipt",
                    "gates/receipt.json",
                ]
                self.assertEqual(main(["produce", *base_args]), 0)
                del os.environ["AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY"]
                self.assertEqual(main(["verify", *base_args]), 0)
            finally:
                os.environ.clear()
                os.environ.update(previous)


def _policy(root: Path, *, deny_literals: list[str] | None = None, max_entries: int = 10) -> object:
    path = root / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-lifecycle-neutrality-policy.v1",
                "scan": {"maxFileBytes": 1000000, "maxObjectBytes": 1000000},
                "archives": {"maxEntriesPerArchive": max_entries, "maxExpandedBytesPerEntry": 1000000},
                "pathExcludes": ["^policy\\.json$"],
                "denyLiterals": deny_literals or [],
                "denyRegexes": [],
            }
        ),
        encoding="utf-8",
    )
    return load_policy(path)


def _operation_request(path: Path, output_path: str, schema_version: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-controller-validation-operation-request.v1",
                "claimsDigest": "0" * 64,
                "claims": {
                    "runId": "run",
                    "packageId": "package",
                    "taskId": "task",
                    "attempt": 1,
                    "operationId": "validation",
                    "commandId": "command",
                    "commandOperationId": "command-operation",
                    "planDigest": "0" * 64,
                    "sourceRevision": "source",
                    "projectionDigest": "1" * 64,
                    "protocolOutputs": [
                        {
                            "id": "report",
                            "role": "report",
                            "kind": "artifact",
                            "path": output_path,
                            "schemaVersion": schema_version,
                            "minBytes": 2,
                            "createNoReplace": True,
                        }
                    ],
                    "generatedAt": "2026-07-22T00:00:00Z",
                },
                "signerFingerprint": "0" * 64,
                "signatureDomain": "test",
                "signature": "",
            }
        ),
        encoding="utf-8",
    )


def _deny(seed: bytes, now: datetime, *, literals: list[str]) -> dict:
    return sign_deny_authority(
        seed,
        {
            "schemaVersion": "agent-neutrality-deny-authority.v1",
            "issuedAt": now.isoformat().replace("+00:00", "Z"),
            "expiresAt": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "denyLiterals": literals,
            "denyRegexes": [],
        },
    )


def _write_authority(
    root: Path,
    seed: bytes,
    now: datetime,
    *,
    authority_root: Path,
    validity: timedelta = timedelta(hours=1),
) -> dict[str, Path]:
    authority_root.mkdir(parents=True, exist_ok=True)
    expires = now + validity
    trust = trust_root_for_seed(seed, issued_at=now, expires_at=expires)
    signing_key = signing_key_for_seed(seed, issued_at=now, expires_at=expires)
    deny = _deny(seed, now, literals=["absent"])
    paths = {
        "trust": authority_root / "trust-root.json",
        "signing": authority_root / "signing-key.json",
        "deny": authority_root / "deny-authority.json",
    }
    for key, value in [("trust", trust), ("signing", signing_key), ("deny", deny)]:
        paths[key].write_text(json.dumps(value), encoding="utf-8")
    (root / "policy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "agent-lifecycle-neutrality-policy.v1",
                "scan": {"maxFileBytes": 1000000, "maxObjectBytes": 1000000},
                "archives": {"maxEntriesPerArchive": 10, "maxExpandedBytesPerEntry": 1000000},
                "pathExcludes": ["^policy\\.json$"],
                "denyLiterals": [],
                "denyRegexes": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "profile.json").write_text(
        json.dumps({"schemaVersion": "agent-lifecycle-neutrality-authority-profile.v3"}),
        encoding="utf-8",
    )
    return paths


def _run_cli(root: Path, seed: bytes, env_paths: dict[str, Path] | None = None) -> int:
    return _run_cli_json(root, seed, env_paths=env_paths)[0]


def _run_cli_json(root: Path, seed: bytes, env_paths: dict[str, Path] | None = None) -> tuple[int, dict]:
    from agent_lifecycle.neutrality.cli import main

    if env_paths is None:
        env_paths = {
            "trust": root / "trust-root.json",
            "signing": root / "signing-key.json",
            "deny": root / "deny-authority.json",
        }
    previous = os.environ.copy()
    os.environ.update(
        {
            "AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY": str(env_paths["deny"]),
            "AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT": str(env_paths["trust"]),
            "AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY": str(env_paths["signing"]),
            "AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT": fingerprint(publickey_from_seed(seed)),
        }
    )
    cwd = Path.cwd()
    stdout = StringIO()
    try:
        os.chdir(root)
        with redirect_stdout(stdout):
            result = main(
                [
                    "bootstrap",
                    "--profile",
                    "profile.json",
                    "--scope",
                    "current-tree-complete",
                    "--policy",
                    "policy.json",
                    "--run-id",
                    "run",
                    "--package-id",
                    "package",
                    "--task-id",
                    "task",
                    "--attempt",
                    "1",
                    "--phase",
                    "task",
                    "--operation-id",
                    "operation",
                    "--plan-digest",
                    "0" * 64,
                    "--source-revision",
                    "source",
                    "--deny-authority-env",
                    "AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY",
                    "--trust-root-env",
                    "AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT",
                    "--signing-key-env",
                    "AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY",
                    "--expected-signer-fingerprint-env",
                    "AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT",
                    "--primary-output",
                    "out/report.json",
                    "--receipt",
                    "out/receipt.json",
                    "--create-no-replace",
                    "--require-zero-findings",
                ]
            )
        text = stdout.getvalue().strip()
        payload = json.loads(text) if text.startswith("{") else {}
        return result, payload
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(previous)


if __name__ == "__main__":
    unittest.main()
