"""Bounded public operator decisions through existing authority readers/writers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, load_json_object
from agent_lifecycle.contracts.operator_signature import (
    build_operator_payload,
    operator_observed_at,
    operator_signing_message,
    verify_operator_subject,
)
from agent_lifecycle.contracts.operator_signature_schemas import VALIDATION, operator_error
from agent_lifecycle.contracts.ownership_paths import require_output_footprint
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file


def _read(root: Path, name: str) -> dict[str, Any]:
    return load_json_object(
        read_stable_repository_file(root, name, max_bytes=MAX_JSON_INPUT_BYTES, label="operator public input"),
        label="operator public input",
    )


def _inputs(args: argparse.Namespace) -> tuple[Path, dict[str, Any], dict[str, Any] | None, set[str]]:
    root = Path.cwd().resolve()
    if args.kind == "freeze":
        if not args.manifest or args.state or args.subject or args.operation_id:
            raise operator_error("Freeze needs only a manifest, not state, subject or operation flags")
        name = normalize_repo_path(args.manifest)
        return root, _read(root, name), None, {name}
    if not args.state or args.manifest or not args.subject or not args.operation_id:
        raise operator_error("A native decision needs state, subject and operation ID")
    from agent_lifecycle.workflow.artifacts import package_root
    from agent_lifecycle.workflow.state import load_state

    state_name = normalize_repo_path(args.state)
    # The actual central loader validates required-only format and both markers.
    read_stable_repository_file(root, state_name, max_bytes=MAX_JSON_INPUT_BYTES, label="operator state")
    state_path = root / state_name
    value = load_state(state_path)
    package = package_root(state_path, value)
    subject_name = normalize_repo_path(args.subject)
    try:
        contained_state = state_path.relative_to(package).as_posix()
    except ValueError:
        raise operator_error("State must be inside its declared package root") from None
    return package, value, _read(package, subject_name), {contained_state, subject_name}


def _write_result(
    root: Path, name: str | None, result: dict[str, Any], container: dict[str, Any], inputs: set[str]
) -> None:
    if name is None:
        return
    output = normalize_repo_path(name)
    protected = {".git", ".alk", ".codex", ".claude", ".github", *inputs}
    if "runId" in container:
        for field in ("eventLog", "manifestPath"):
            if isinstance(container.get(field), str):
                protected.add(normalize_repo_path(container[field]))
        storage = container.get("storage")
        if isinstance(storage, dict) and isinstance(storage.get("root"), str):
            protected.add(normalize_repo_path(storage["root"]))
        policy = container.get("writePolicy", {})
        if isinstance(policy, dict):
            for field in ("readOnly", "forbiddenWrites"):
                protected.update(normalize_repo_path(p) for p in policy.get(field, []) if isinstance(p, str))
        manifest_name = container.get("manifestPath")
        if isinstance(manifest_name, str):
            require_output_footprint(_read(root, normalize_repo_path(manifest_name)), [output], repository_root=root)
    else:
        require_output_footprint(container, [output], repository_root=root)
    folded = output.casefold()
    if any(folded == p.casefold() or folded.startswith(p.casefold().rstrip("/") + "/") for p in protected):
        raise operator_error("Public output overlaps a protected input or authority path")
    if folded.endswith((".state.json", ".lock.json", "plan.manifest.json", "events.jsonl")):
        raise operator_error("Public output cannot use a native authority filename")
    try:
        create_authority_bytes(root / output, canonical_bytes(result) + b"\n", root=root)
    except FileExistsError:
        raise LifecycleError("operator-signature-output-exists", "Public output is create-only") from None


def dispatch_operator_signatures(args: argparse.Namespace) -> dict[str, Any]:
    root, container, subject, inputs = _inputs(args)
    common = {"operation_id": args.operation_id, "subject": subject}
    if args.operator_signature_command == "request":
        payload = build_operator_payload(
            container,
            args.kind,
            signer_fingerprint=args.signer_fingerprint,
            valid_from=args.valid_from,
            expires_at=args.expires_at,
            **common,
        )
        result = {
            "schemaVersion": "agent-operator-signature-request.v1",
            "payload": payload,
            "signingMessageHex": operator_signing_message(payload).hex(),
            "nativePermissionGranted": False,
            "authorityClaimed": False,
        }
    else:
        signature = normalize_repo_path(args.signature)
        inputs.add(signature)
        result = verify_operator_subject(
            container,
            args.kind,
            root=root,
            signature_path=signature,
            observed_at=operator_observed_at(),
            **common,
        ) or {
            "schemaVersion": VALIDATION,
            "status": "OFF",
            "mode": "off",
            "signatureVerified": False,
            "nativePermissionGranted": False,
        }
    _write_result(root, args.out, result, container, inputs)
    return result
