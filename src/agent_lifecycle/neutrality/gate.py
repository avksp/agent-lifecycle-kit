"""Controller-gate compatibility wrapper for neutrality scans."""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_lifecycle.neutrality.authority import RECEIPT_DOMAIN, load_authority_bundle
from agent_lifecycle.neutrality.canonical import canonical_bytes, load_json, sha256_hex, write_json_create
from agent_lifecycle.neutrality.ed25519 import verify as verify_signature
from agent_lifecycle.neutrality.errors import NeutralityError
from agent_lifecycle.neutrality.policy import load_policy
from agent_lifecycle.neutrality.scanner import scan_repository

POLICY_PATH = "policy/neutrality.policy.json"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "produce":
            return _produce(args)
        if args.command == "verify":
            return _verify(args)
    except NeutralityError as exc:
        print(f"neutrality-gate: {exc}", file=sys.stderr)
        return 2
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-lifecycle-neutrality-gate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("produce", "verify"):
        gate = subparsers.add_parser(command)
        gate.add_argument("--profile", required=True)
        gate.add_argument("--scope", required=True, choices=["current-tree-complete", "full-repository"])
        gate.add_argument("--gate-id", required=True)
        gate.add_argument("--run-id", required=True)
        gate.add_argument("--package-id", required=True)
        gate.add_argument("--task-id", required=True)
        gate.add_argument("--attempt", required=True, type=int)
        gate.add_argument("--phase", required=True)
        gate.add_argument("--operation-id", required=True)
        gate.add_argument("--plan-digest", required=True)
        gate.add_argument("--source-revision", required=True)
        gate.add_argument("--workspace-root", required=True)
        gate.add_argument("--operation-output", required=True)
        gate.add_argument("--receipt", required=True)
    return parser


def _produce(args: argparse.Namespace) -> int:
    workspace_root = Path(args.workspace_root).resolve()
    receipt_path = _receipt_path(workspace_root, args)
    if receipt_path.exists():
        raise NeutralityError("gate receipt path is already occupied")
    authority = _authority(workspace_root, signing=True)
    report = _scan(workspace_root, args, authority)
    _require_zero(report)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    claims = _claims(args, report, authority.authority_digest, generated_at)
    claims_digest = sha256_hex(canonical_bytes(claims))
    receipt = {
        "schemaVersion": "agent-controller-gate-receipt.v1",
        "gateId": args.gate_id,
        "runId": args.run_id,
        "packageId": args.package_id,
        "taskId": args.task_id,
        "attempt": args.attempt,
        "phase": args.phase,
        "operationId": args.operation_id,
        "planDigest": args.plan_digest,
        "sourceRevision": args.source_revision,
        "verdict": "PASS",
        "generatedAt": generated_at,
        "attestation": {
            "schemaVersion": "agent-controller-gate-attestation.v1",
            "algorithm": "Ed25519",
            "claimsDigest": claims_digest,
            "subjectDigest": report["digests"]["subjectDigest"],
            "scopeDigest": claims["scopeDigest"],
            "authorityDigest": authority.authority_digest,
            "signerFingerprint": _digest_fingerprint(authority.signer_fingerprint),
            "signature": base64.b64encode(
                bytes.fromhex(authority.sign_claims_digest(claims_digest))
            ).decode("ascii"),
        },
    }
    write_json_create(receipt_path, receipt)
    print(f"neutrality-gate: wrote {receipt_path.relative_to(workspace_root)}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    workspace_root = Path(args.workspace_root).resolve()
    receipt_path = _receipt_path(workspace_root, args)
    receipt = load_json(receipt_path.read_bytes())
    expected = {
        "schemaVersion": "agent-controller-gate-receipt.v1",
        "gateId": args.gate_id,
        "runId": args.run_id,
        "packageId": args.package_id,
        "taskId": args.task_id,
        "attempt": args.attempt,
        "phase": args.phase,
        "operationId": args.operation_id,
        "planDigest": args.plan_digest,
        "sourceRevision": args.source_revision,
        "verdict": "PASS",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise NeutralityError(f"gate receipt {key} binding mismatch")
    generated_at = receipt.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise NeutralityError("gate receipt generatedAt is missing")
    authority = _authority(workspace_root, signing=False)
    report = _scan(workspace_root, args, authority)
    _require_zero(report)
    claims = _claims(args, report, authority.authority_digest, generated_at)
    claims_digest = sha256_hex(canonical_bytes(claims))
    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict):
        raise NeutralityError("gate receipt attestation is missing")
    if (
        attestation.get("claimsDigest") != claims_digest
        or attestation.get("subjectDigest") != report["digests"]["subjectDigest"]
        or attestation.get("scopeDigest") != claims["scopeDigest"]
        or attestation.get("authorityDigest") != authority.authority_digest
        or attestation.get("signerFingerprint") != _digest_fingerprint(authority.signer_fingerprint)
    ):
        raise NeutralityError("gate receipt attestation binding mismatch")
    signature = base64.b64decode(str(attestation.get("signature")), validate=True)
    if not verify_signature(
        bytes.fromhex(authority.signer_public_key_hex),
        RECEIPT_DOMAIN + claims_digest.encode("ascii"),
        signature,
    ):
        raise NeutralityError("gate receipt signature verification failed")
    print("neutrality-gate: receipt verified")
    return 0


def _authority(workspace_root: Path, *, signing: bool):
    return load_authority_bundle(
        deny_authority_path=Path(_env("AGENT_LIFECYCLE_NEUTRALITY_DENY_AUTHORITY")),
        trust_root_path=Path(_env("AGENT_LIFECYCLE_NEUTRALITY_TRUST_ROOT")),
        signing_key_path=(
            Path(_env("AGENT_LIFECYCLE_NEUTRALITY_SIGNING_KEY")) if signing else None
        ),
        expected_signer_fingerprint=_env("AGENT_LIFECYCLE_NEUTRALITY_SIGNER_FINGERPRINT"),
        workspace_root=workspace_root,
        artifact_root=workspace_root / "plans" / "standalone-v1",
    )


def _scan(workspace_root: Path, args: argparse.Namespace, authority) -> dict[str, Any]:
    policy = load_policy(workspace_root / POLICY_PATH)
    receipt_path = _receipt_path(workspace_root, args).relative_to(workspace_root).as_posix()
    policy = replace(
        policy,
        path_excludes=policy.path_excludes + (re.compile(f"^{re.escape(receipt_path)}$"),),
    )
    profile = load_json((workspace_root / args.profile).read_bytes())
    report = scan_repository(
        workspace_root=workspace_root,
        policy=policy,
        deny_literals=authority.deny_literals,
        deny_regexes=authority.deny_regexes,
        scope=args.scope,
        output_paths=[],
    ).to_json(
        {
            "schemaVersion": "agent-neutrality-gate-operation.v1",
            "gateId": args.gate_id,
            "runId": args.run_id,
            "packageId": args.package_id,
            "taskId": args.task_id,
            "attempt": args.attempt,
            "phase": args.phase,
            "operationId": args.operation_id,
            "planDigest": args.plan_digest,
            "sourceRevision": args.source_revision,
            "profileDigest": sha256_hex(canonical_bytes(profile)),
        }
    )
    return report


def _claims(
    args: argparse.Namespace,
    report: dict[str, Any],
    authority_digest: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-neutrality-controller-gate-claims.v1",
        "gateId": args.gate_id,
        "runId": args.run_id,
        "packageId": args.package_id,
        "taskId": args.task_id,
        "attempt": args.attempt,
        "phase": args.phase,
        "operationId": args.operation_id,
        "planDigest": args.plan_digest,
        "sourceRevision": args.source_revision,
        "scope": report["scope"],
        "scopeDigest": sha256_hex(canonical_bytes({"scope": report["scope"]})),
        "subjectDigest": report["digests"]["subjectDigest"],
        "workingTreeDigest": report["digests"]["workingTreeDigest"],
        "gitObjectSetDigest": report["digests"]["gitObjectSetDigest"],
        "zeroCounters": report["counters"],
        "authorityDigest": authority_digest,
        "receiptPath": args.receipt,
        "generatedAt": generated_at,
        "verdict": "PASS",
    }


def _require_zero(report: dict[str, Any]) -> None:
    if any(int(value) != 0 for value in report["counters"].values()):
        raise NeutralityError("neutrality gate counters are non-zero")


def _receipt_path(workspace_root: Path, args: argparse.Namespace) -> Path:
    if args.operation_output != args.receipt:
        raise NeutralityError("operation output must match receipt for controller gate v1")
    path = Path(args.receipt)
    if path.is_absolute():
        raise NeutralityError("gate receipt must be repository-relative")
    resolved = (workspace_root / path).resolve()
    if not resolved.is_relative_to(workspace_root):
        raise NeutralityError("gate receipt escapes workspace")
    return resolved


def _digest_fingerprint(value: str) -> str:
    if value.startswith("ed25519:"):
        return value.split(":", 1)[1]
    return value


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NeutralityError(f"required environment variable is not set: {name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
