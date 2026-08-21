from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, file_identity, write_json
except ModuleNotFoundError:  # imported as a test module rather than run as a script
    from tools.release.release_common import digest_value, file_identity, write_json

from agent_lifecycle.host_protocol.inspection_profile import (
    INSPECTION_PROFILE_FILENAME,
    INSPECTION_PROFILE_SCHEMA,
    INSPECTION_HANDLER_IDS,
    load_inspection_profile,
    validate_inspection_profile,
)

EXPECTED_ADAPTERS = (
    "claude",
    "codex",
    "cursor",
    "gemini-cli",
    "goose",
    "grok-build",
    "hermes",
    "kimi-code",
    "opencode",
    "openinterpreter",
    "pi",
    "qwen-code",
)
UNSUPPORTED_ADAPTERS = frozenset({"goose", "grok-build", "openinterpreter", "pi"})
_HOST_BRANCH = re.compile(r"\bhost\s*(?:==|!=|in|not\s+in)")


def validate_profiles(adapter_root: Path, inspection_path: Path) -> dict[str, Any]:
    """Validate every shipped profile and the generic inspection boundary."""

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    actual_adapters = sorted(path.name for path in adapter_root.iterdir() if path.is_dir()) if adapter_root.is_dir() else []
    missing_adapters = sorted(set(EXPECTED_ADAPTERS) - set(actual_adapters))
    unexpected_adapters = sorted(set(actual_adapters) - set(EXPECTED_ADAPTERS))
    if missing_adapters:
        blockers.append({"code": "inspection-adapter-missing", "adapters": missing_adapters})
    if unexpected_adapters:
        blockers.append({"code": "inspection-adapter-unexpected", "adapters": unexpected_adapters})

    for adapter_id in EXPECTED_ADAPTERS:
        adapter_path = adapter_root / adapter_id
        descriptor_path = adapter_path / "adapter.descriptor.json"
        profile_path = adapter_path / INSPECTION_PROFILE_FILENAME
        check_blockers: list[dict[str, Any]] = []
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            if not isinstance(descriptor, dict):
                raise ValueError("descriptor must be an object")
            profile, info = load_inspection_profile(
                adapter_id,
                descriptor_path=descriptor_path,
                project_root=adapter_root.parent,
                host=descriptor.get("host") if isinstance(descriptor.get("host"), str) else None,
            )
            expected_status = "UNSUPPORTED" if adapter_id in UNSUPPORTED_ADAPTERS else "SUPPORTED"
            if profile.get("status") != expected_status:
                check_blockers.append({"code": "inspection-profile-status-mismatch", "expected": expected_status})
            if adapter_id in UNSUPPORTED_ADAPTERS and profile.get("handler") is not None:
                check_blockers.append({"code": "inspection-unsupported-handler-present"})
            check_blockers.extend(_profile_ast_blockers(profile_path))
            checks.append(
                {
                    "adapterId": adapter_id,
                    "status": "PASS" if not check_blockers else "FAIL",
                    "profile": file_identity(profile_path),
                    "profileDigest": info["profileDigest"],
                    "profileStatus": profile.get("status"),
                    "handler": profile.get("handler"),
                    "blockers": check_blockers,
                }
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            check_blockers.append({"code": "inspection-profile-fixture-invalid", "error": type(exc).__name__})
            checks.append({"adapterId": adapter_id, "status": "FAIL", "blockers": check_blockers})
        except Exception as exc:  # fail closed while preserving a machine-readable report
            check_blockers.append({"code": getattr(exc, "code", "inspection-profile-load-failed")})
            checks.append({"adapterId": adapter_id, "status": "FAIL", "blockers": check_blockers})

    inspection_blockers = _inspection_boundary_blockers(inspection_path)
    for check in checks:
        if check["status"] != "FAIL":
            continue
        for blocker in check.get("blockers", []):
            blockers.append({"adapterId": check["adapterId"], **blocker})
    blockers.extend(inspection_blockers)
    body = {
        "schemaVersion": "agent-adapter-inspection-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterRoot": adapter_root.as_posix(),
        "inspection": file_identity(inspection_path) if inspection_path.is_file() else None,
        "profileSchema": INSPECTION_PROFILE_SCHEMA,
        "supportedHandlers": sorted(INSPECTION_HANDLER_IDS),
        "expectedAdapters": list(EXPECTED_ADAPTERS),
        "unsupportedAdapters": sorted(UNSUPPORTED_ADAPTERS),
        "checks": checks,
        "inspectionBoundary": {"blockers": inspection_blockers, "profileExtensible": not inspection_blockers},
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostCommandsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _profile_ast_blockers(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return [{"code": "inspection-profile-missing"}]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    except (OSError, UnicodeDecodeError, SyntaxError):
        return [{"code": "inspection-profile-not-parseable"}]
    forbidden = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom, ast.Call))]
    return [{"code": "inspection-profile-executable-code"}] if forbidden else []


def _inspection_boundary_blockers(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return [{"code": "inspection-module-missing"}]
    source = path.read_text(encoding="utf-8")
    blockers: list[dict[str, Any]] = []
    if _HOST_BRANCH.search(source):
        blockers.append({"code": "inspection-central-host-branch"})
    tree = ast.parse(source, filename=path.as_posix())
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and isinstance(node.module, str)
            and node.module.rsplit(".", 1)[-1]
            in {f"inspection_{handler.replace('-', '_')}" for handler in INSPECTION_HANDLER_IDS}
        ):
            blockers.append({"code": "inspection-central-handler-import"})
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--inspection", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_profiles(Path(args.adapter_root), Path(args.inspection))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
