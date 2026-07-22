"""Command line interface for neutrality operations."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_lifecycle.neutrality.authority import load_authority_bundle
from agent_lifecycle.neutrality.canonical import canonical_bytes, load_json, sha256_hex, write_json_create
from agent_lifecycle.neutrality.errors import NeutralityError
from agent_lifecycle.neutrality.policy import load_policy
from agent_lifecycle.neutrality.receipt import build_claims, build_receipt, verify_existing_receipt
from agent_lifecycle.neutrality.scanner import scan_repository


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "bootstrap":
            return _bootstrap(args)
        if args.command == "scan":
            return _scan(args)
        if args.command == "verify-receipt":
            return _verify_receipt(args)
    except NeutralityError as exc:
        print(f"neutrality: {exc}", file=sys.stderr)
        return 2
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-lifecycle-neutrality")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="scan and publish a signed neutrality receipt")
    _add_common_lifecycle_args(bootstrap)
    bootstrap.add_argument("--profile", required=True)
    bootstrap.add_argument("--scope", required=True, choices=["full-repository", "current-tree-complete"])
    bootstrap.add_argument("--policy", required=True)
    bootstrap.add_argument("--validation-operation-id", required=False)
    bootstrap.add_argument("--command-id", required=False)
    bootstrap.add_argument("--primary-output", required=True)
    bootstrap.add_argument("--receipt", required=True)
    bootstrap.add_argument("--operation-request", required=False)
    bootstrap.add_argument("--deny-authority-env", required=True)
    bootstrap.add_argument("--trust-root-env", required=True)
    bootstrap.add_argument("--signing-key-env", required=True)
    bootstrap.add_argument("--expected-signer-fingerprint-env", required=True)
    bootstrap.add_argument("--create-no-replace", action="store_true")
    bootstrap.add_argument("--require-zero-findings", action="store_true")

    scan = subparsers.add_parser("scan", help="run a local unsigned neutrality scan")
    scan.add_argument("--scope", required=True, choices=["full-repository", "current-tree-complete"])
    scan.add_argument("--policy", required=True)
    scan.add_argument("--report", required=False)
    scan.add_argument("--operation-request", required=False)
    scan.add_argument("--require-zero-findings", action="store_true")

    verify_parser = subparsers.add_parser("verify-receipt", help="verify an existing signed receipt")
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.add_argument("--primary-output", required=True)
    verify_parser.add_argument("--trust-root", required=True)
    verify_parser.add_argument("--expected-signer-fingerprint", required=True)
    return parser


def _add_common_lifecycle_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--source-revision", required=True)


def _bootstrap(args: argparse.Namespace) -> int:
    workspace_root = Path.cwd().resolve()
    artifact_root = workspace_root / "plans" / "standalone-v1"
    primary_path = _relative_output_path(workspace_root, args.primary_output)
    receipt_path = _relative_output_path(workspace_root, args.receipt)
    operation = _operation_bindings(args)

    if args.create_no_replace and primary_path.exists() and receipt_path.exists():
        if verify_existing_receipt(
            receipt_path=receipt_path,
            primary_path=primary_path,
            expected_operation=operation,
            trust_root_path=_env_path(args.trust_root_env),
            expected_signer_fingerprint=_env_value(args.expected_signer_fingerprint_env),
        ):
            print("neutrality: existing same-operation receipt verified")
            return 0
        raise NeutralityError("existing output paths do not match this operation")
    if args.create_no_replace and (primary_path.exists() or receipt_path.exists()):
        raise NeutralityError("operation output path is occupied before publication")

    policy = load_policy(Path(args.policy))
    profile = load_json(Path(args.profile).read_bytes())
    if profile.get("schemaVersion") != "agent-lifecycle-neutrality-authority-profile.v3":
        raise NeutralityError("unsupported neutrality authority profile schemaVersion")
    authority = load_authority_bundle(
        deny_authority_path=_env_path(args.deny_authority_env),
        trust_root_path=_env_path(args.trust_root_env),
        signing_key_path=_env_path(args.signing_key_env),
        expected_signer_fingerprint=_env_value(args.expected_signer_fingerprint_env),
        workspace_root=workspace_root,
        artifact_root=artifact_root,
    )
    report = scan_repository(
        workspace_root=workspace_root,
        policy=policy,
        deny_literals=authority.deny_literals,
        deny_regexes=authority.deny_regexes,
        scope=args.scope,
        output_paths=[primary_path.relative_to(workspace_root), receipt_path.relative_to(workspace_root)],
    ).to_json(operation)

    if args.require_zero_findings and report["counters"]["findings"] != 0:
        raise NeutralityError("neutrality findings are non-zero")

    claims = build_claims(
        operation=operation,
        report=report,
        authority_digest=authority.authority_digest,
        primary_path=primary_path.relative_to(workspace_root).as_posix(),
        receipt_path=receipt_path.relative_to(workspace_root).as_posix(),
        policy=policy.raw,
        profile=profile,
    )
    report["claimsDigest"] = sha256_hex(canonical_bytes(claims))
    report_bytes = write_json_create(primary_path, report)
    receipt = build_receipt(
        operation=operation,
        claims=claims,
        primary_sha256=sha256_hex(report_bytes),
        primary_bytes=len(report_bytes),
        signer_fingerprint=authority.signer_fingerprint,
        signature=authority.sign_claims_digest(sha256_hex(canonical_bytes(claims))),
    )
    write_json_create(receipt_path, receipt)
    print(f"neutrality: wrote {primary_path.relative_to(workspace_root)} and {receipt_path.relative_to(workspace_root)}")
    return 0


def _scan(args: argparse.Namespace) -> int:
    workspace_root = Path.cwd().resolve()
    report_path = _relative_output_path(workspace_root, args.report) if args.report else None
    operation = _operation_from_request(args.operation_request)
    policy = load_policy(Path(args.policy))
    relative_outputs = [report_path.relative_to(workspace_root)] if report_path else []
    report = scan_repository(
        workspace_root=workspace_root,
        policy=policy,
        deny_literals=[],
        deny_regexes=[],
        scope=args.scope,
        output_paths=relative_outputs,
    ).to_json(operation)

    if args.require_zero_findings and any(int(value) != 0 for value in report["counters"].values()):
        raise NeutralityError("neutrality scan counters are non-zero")
    if report_path is not None:
        _require_protocol_output(
            request_path=args.operation_request,
            output_path=report_path.relative_to(workspace_root).as_posix(),
            schema_version="agent-neutrality-report.v1",
        )
        write_json_create(report_path, report)
        print(f"neutrality: wrote local scan report {report_path.relative_to(workspace_root)}")
    else:
        sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0


def _verify_receipt(args: argparse.Namespace) -> int:
    if not verify_existing_receipt(
        receipt_path=Path(args.receipt),
        primary_path=Path(args.primary_output),
        expected_operation=None,
        trust_root_path=Path(args.trust_root),
        expected_signer_fingerprint=args.expected_signer_fingerprint,
    ):
        raise NeutralityError("receipt verification failed")
    print("neutrality: receipt verified")
    return 0


def _operation_bindings(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-neutrality-operation.v1",
        "runId": args.run_id,
        "packageId": args.package_id,
        "taskId": args.task_id,
        "attempt": args.attempt,
        "phase": args.phase,
        "operationId": args.operation_id,
        "validationOperationId": args.validation_operation_id,
        "commandId": args.command_id,
        "planDigest": args.plan_digest,
        "sourceRevision": args.source_revision,
        "verifiedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _operation_from_request(request_path: str | None) -> dict[str, Any]:
    if request_path is None:
        return {
            "schemaVersion": "agent-local-neutrality-operation.v1",
            "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
    request = load_json(Path(request_path).read_bytes())
    claims = request.get("claims")
    if not isinstance(claims, dict):
        raise NeutralityError("operation request claims are missing")
    keys = [
        "runId",
        "packageId",
        "taskId",
        "attempt",
        "operationId",
        "commandId",
        "commandOperationId",
        "planDigest",
        "sourceRevision",
        "projectionDigest",
        "generatedAt",
    ]
    operation = {
        "schemaVersion": "agent-local-neutrality-operation.v1",
        "requestClaimsDigest": request.get("claimsDigest"),
    }
    operation.update({key: claims.get(key) for key in keys})
    return operation


def _require_protocol_output(
    *,
    request_path: str | None,
    output_path: str,
    schema_version: str,
) -> None:
    if request_path is None:
        return
    request = load_json(Path(request_path).read_bytes())
    claims = request.get("claims")
    outputs = claims.get("protocolOutputs") if isinstance(claims, dict) else None
    if not isinstance(outputs, list):
        raise NeutralityError("operation request protocolOutputs are missing")
    for item in outputs:
        if (
            isinstance(item, dict)
            and item.get("path") == output_path
            and item.get("schemaVersion") == schema_version
            and item.get("createNoReplace") is True
        ):
            return
    raise NeutralityError("requested report path is not authorized by operation request")


def _relative_output_path(workspace_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise NeutralityError("operation outputs must be repository-relative paths")
    resolved = (workspace_root / path).resolve()
    if not resolved.is_relative_to(workspace_root):
        raise NeutralityError("operation output escapes workspace")
    return resolved


def _env_path(name: str) -> Path:
    return Path(_env_value(name))


def _env_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NeutralityError(f"required environment variable is not set: {name}")
    return value
