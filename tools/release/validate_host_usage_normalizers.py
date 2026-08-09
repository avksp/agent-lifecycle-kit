from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json

BANNED_IMPORTS = {
    "aiohttp",
    "anthropic",
    "httpx",
    "importlib",
    "mistralai",
    "openai",
    "os",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}
BANNED_CALLS = {"__import__", "compile", "eval", "exec", "open", "system", "popen", "run", "Popen"}


def validate_host_usage_normalizers(adapter_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    repository_root = adapter_root.resolve().parent
    for descriptor_path in sorted(adapter_root.glob("*/adapter.descriptor.json")):
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        profile = descriptor.get("usageNormalization")
        if not isinstance(profile, dict) or profile.get("status") == "UNSUPPORTED":
            continue
        normalizer_path = repository_root / profile.get("path", "")
        checks.append(_check_normalizer(descriptor, profile, normalizer_path, repository_root))
    blockers = [blocker for check in checks for blocker in check["blockers"]]
    body = {
        "schemaVersion": "agent-host-usage-normalizer-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "blockers": blockers,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_normalizer(
    descriptor: dict[str, Any],
    profile: dict[str, Any],
    path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    adapter_id = descriptor.get("adapterId")
    expected = repository_root / "adapters" / str(adapter_id) / "usage_normalizer.py"
    if path != expected or not path.is_file() or path.is_symlink():
        blockers.append({"code": "usage-normalizer-path", "adapterId": adapter_id})
        return {"adapterId": adapter_id, "status": "FAIL", "blockers": blockers}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    except SyntaxError as error:
        blockers.append({"code": "usage-normalizer-syntax", "adapterId": adapter_id, "line": error.lineno})
        return {"adapterId": adapter_id, "status": "FAIL", "blockers": blockers}
    parse_entries = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "parse_usage":
            parse_entries += 1
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(adapter_id, alias.name, node.lineno, blockers)
        elif isinstance(node, ast.ImportFrom):
            _check_import(adapter_id, node.module or "", node.lineno, blockers)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in BANNED_CALLS:
                blockers.append({"code": "usage-normalizer-forbidden-call", "adapterId": adapter_id, "call": name, "line": node.lineno})
    if parse_entries != 1:
        blockers.append({"code": "usage-normalizer-entrypoint", "adapterId": adapter_id, "count": parse_entries})
    status = profile.get("status")
    accepted = profile.get("acceptedForS1S2")
    if status not in {"FIXTURE_ONLY", "QUALIFIED"} or accepted is not (status == "QUALIFIED"):
        blockers.append({"code": "usage-normalizer-qualification-inconsistent", "adapterId": adapter_id})
    if status == "QUALIFIED":
        evidence = profile.get("qualificationEvidence")
        host_range = profile.get("qualifiedHostRange")
        if not isinstance(evidence, list) or not evidence or not isinstance(host_range, dict):
            blockers.append({"code": "usage-normalizer-qualified-evidence-missing", "adapterId": adapter_id})
    return {
        "adapterId": adapter_id,
        "status": "PASS" if not blockers else "FAIL",
        "normalizer": file_identity(path),
        "blockers": blockers,
    }


def _check_import(adapter_id: Any, name: str, line: int, blockers: list[dict[str, Any]]) -> None:
    root = name.split(".", 1)[0]
    if root in BANNED_IMPORTS or name.startswith("google.generativeai"):
        blockers.append({"code": "usage-normalizer-forbidden-import", "adapterId": adapter_id, "import": name, "line": line})


def _call_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_host_usage_normalizers(Path(args.adapter_root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
