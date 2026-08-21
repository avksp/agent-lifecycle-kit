"""Validate bounded JSON, strict Ed25519 decoding and private local storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, load_json_object
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    MAX_JSON_NESTING,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    write_json_create_private,
)

VALIDATION_SCHEMA = "agent-input-privacy-validation.v1"


def validate_input_privacy(
    *,
    canonical_path: Path,
    ed25519_path: Path,
    session_store_path: Path,
    planning_session_path: Path,
    checkpoint_store_path: Path,
    workflow_state_path: Path,
) -> dict[str, Any]:
    """Run bounded static and runtime checks without model, network or host calls."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    source_paths = [
        ("canonical-json", canonical_path, ("MAX_JSON_INPUT_BYTES", "MAX_JSON_NESTING", "RecursionError", "_private_directory_chain", "_validate_json_nesting")),
        ("ed25519-decoding", ed25519_path, ("y >= P", "x == 0 and sign_bit != 0", "_decode_point")),
        ("session-store", session_store_path, ("write_json_create_private", "write_json_replace_private", "ensure_private_directory")),
        ("planning-session", planning_session_path, ("write_json_create_private", "write_json_replace_private", "ensure_private_directory")),
        ("checkpoint-store", checkpoint_store_path, ("require_private_file", "write_json_replace_private", "ensure_private_directory")),
        ("workflow-state", workflow_state_path, ("write_json_replace_private",)),
    ]
    file_identities = []
    for check_id, path, markers in source_paths:
        try:
            source = path.read_text(encoding="utf-8")
            missing = [marker for marker in markers if marker not in source]
            identity = {"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path.read_bytes())}
        except OSError:
            missing = list(markers)
            identity = {"name": path.name, "bytes": None, "sha256": None}
        file_identities.append(identity)
        status = "PASS" if not missing else "FAIL"
        checks.append({"id": check_id, "status": status, "missingMarkers": missing})
        if missing:
            blockers.append({"code": "input-privacy-source-invariant-missing", "checkId": check_id, "missingMarkers": missing})

    runtime_checks = _runtime_checks()
    checks.extend(runtime_checks["checks"])
    blockers.extend(runtime_checks["blockers"])
    posix = os.name != "nt"
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "files": file_identities,
        "limits": {
            "maxJsonInputBytes": MAX_JSON_INPUT_BYTES,
            "maxJsonNesting": MAX_JSON_NESTING,
        },
        "permissionContract": {
            "platform": "POSIX" if posix else "WINDOWS",
            "exactFileMode": "0600" if posix else None,
            "exactDirectoryMode": "0700" if posix else None,
            "posixModesAuthoritative": posix,
            "windowsContract": "platform ACL boundary; POSIX mode bits are not claimed" if not posix else None,
        },
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": _digest(body)}


def _runtime_checks() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    cases = [
        ("json-unicode", {"text": "Привет"}, None),
        ("json-invalid", b"{", "invalid-json"),
        ("json-non-object", b"[]", "invalid-json-object"),
        ("json-too-large", b'{"value":"' + b"x" * MAX_JSON_INPUT_BYTES + b'"}', "json-input-too-large"),
    ]
    for check_id, payload, expected_code in cases:
        try:
            if isinstance(payload, dict):
                value = load_json_object(canonical_bytes(payload))
                if value != payload:
                    raise AssertionError("unicode JSON did not round-trip")
            else:
                load_json_object(payload)
            if expected_code is not None:
                raise AssertionError(f"expected {expected_code}")
            checks.append({"id": check_id, "status": "PASS"})
        except LifecycleError as exc:
            if exc.code == expected_code:
                checks.append({"id": check_id, "status": "PASS", "errorCode": exc.code})
            else:
                checks.append({"id": check_id, "status": "FAIL", "errorCode": exc.code})
                blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": check_id, "errorCode": exc.code})
        except Exception as exc:
            checks.append({"id": check_id, "status": "FAIL", "errorType": type(exc).__name__})
            blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": check_id, "errorType": type(exc).__name__})

    nested: dict[str, Any] = {"leaf": True}
    for _ in range(MAX_JSON_NESTING + 1):
        nested = {"child": nested}
    try:
        load_json_object(json.dumps(nested).encode("utf-8"))
    except LifecycleError as exc:
        status = "PASS" if exc.code == "json-input-depth-exceeded" else "FAIL"
        checks.append({"id": "json-depth-limit", "status": status, "errorCode": exc.code})
        if status != "PASS":
            blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "json-depth-limit", "errorCode": exc.code})
    except Exception as exc:
        checks.append({"id": "json-depth-limit", "status": "FAIL", "errorType": type(exc).__name__})
        blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "json-depth-limit", "errorType": type(exc).__name__})

    try:
        canonical_bytes({"value": float("nan")})
    except LifecycleError as exc:
        checks.append({"id": "json-nonfinite-output", "status": "PASS", "errorCode": exc.code})
    except Exception as exc:
        checks.append({"id": "json-nonfinite-output", "status": "FAIL", "errorType": type(exc).__name__})
        blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "json-nonfinite-output", "errorType": type(exc).__name__})
    else:
        checks.append({"id": "json-nonfinite-output", "status": "FAIL"})
        blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "json-nonfinite-output"})

    try:
        from agent_lifecycle.neutrality import ed25519

        rejected = []
        for encoded in (ed25519.P.to_bytes(32, "little"), bytes([1]) + bytes(30) + bytes([0x80])):
            try:
                ed25519._decode_point(encoded)
            except ValueError:
                rejected.append(True)
            else:
                rejected.append(False)
        status = "PASS" if all(rejected) else "FAIL"
        checks.append({"id": "ed25519-canonical-points", "status": status})
        if status != "PASS":
            blockers.append({"code": "input-privacy-ed25519-noncanonical-accepted", "checkId": "ed25519-canonical-points"})
    except Exception as exc:
        checks.append({"id": "ed25519-canonical-points", "status": "FAIL", "errorType": type(exc).__name__})
        blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "ed25519-canonical-points", "errorType": type(exc).__name__})

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / ".alk" / "context" / "checkpoints"
        try:
            ensure_private_directory(root)
            path = root / "state.json"
            write_json_create_private(path, {"status": "PASS"})
            modes = {
                "alk": stat.S_IMODE((Path(tmp) / ".alk").stat().st_mode),
                "context": stat.S_IMODE((Path(tmp) / ".alk" / "context").stat().st_mode),
                "directory": stat.S_IMODE(root.stat().st_mode),
                "file": stat.S_IMODE(path.stat().st_mode),
            }
            if os.name == "nt":
                status = "PASS"
            else:
                status = "PASS" if modes == {
                    "alk": PRIVATE_DIRECTORY_MODE,
                    "context": PRIVATE_DIRECTORY_MODE,
                    "directory": PRIVATE_DIRECTORY_MODE,
                    "file": PRIVATE_FILE_MODE,
                } else "FAIL"
            checks.append({"id": "private-mode-contract", "status": status, "posixAuthoritative": os.name != "nt"})
            if status != "PASS":
                blockers.append({"code": "input-privacy-private-mode-mismatch", "checkId": "private-mode-contract"})
        except Exception as exc:
            checks.append({"id": "private-mode-contract", "status": "FAIL", "errorType": type(exc).__name__})
            blockers.append({"code": "input-privacy-runtime-check-failed", "checkId": "private-mode-contract", "errorType": type(exc).__name__})
    return {"checks": checks, "blockers": blockers}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: Any) -> str:
    return _sha256(canonical_bytes(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical", required=True)
    parser.add_argument("--ed25519", required=True)
    parser.add_argument("--session-store", required=True)
    parser.add_argument("--planning-session", required=True)
    parser.add_argument("--checkpoint-store", required=True)
    parser.add_argument("--workflow-state", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_input_privacy(
        canonical_path=Path(args.canonical),
        ed25519_path=Path(args.ed25519),
        session_store_path=Path(args.session_store),
        planning_session_path=Path(args.planning_session),
        checkpoint_store_path=Path(args.checkpoint_store),
        workflow_state_path=Path(args.workflow_state),
    )
    output = Path(args.evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(payload) + b"\n")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
