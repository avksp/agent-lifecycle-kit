from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json


BANNED_IMPORT_ROOTS = {
    "anthropic",
    "google.generativeai",
    "httpx",
    "mistralai",
    "openai",
    "requests",
    "urllib",
}


def validate_no_model_calls(paths: list[Path]) -> dict[str, Any]:
    checks = [_check_path(path) for path in paths]
    blockers = [blocker for check in checks for blocker in check["blockers"]]
    status = "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": "agent-no-model-call-scan.v1",
        "status": status,
        "paths": [path.as_posix() for path in paths],
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_path(path: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=path.as_posix())
    except SyntaxError as exc:
        blockers.append({
            "code": "python-parse-failed",
            "path": path.as_posix(),
            "line": exc.lineno,
            "message": exc.msg,
        })
        return {"path": path.as_posix(), "status": "FAIL", "blockers": blockers}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root in BANNED_IMPORT_ROOTS:
                    blockers.append(_import_blocker(path, root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = _import_root(module)
            if root in BANNED_IMPORT_ROOTS:
                blockers.append(_import_blocker(path, root, node.lineno))

    return {"path": path.as_posix(), "status": "PASS" if not blockers else "FAIL", "blockers": blockers}


def _import_root(name: str) -> str:
    if name.startswith("google.generativeai"):
        return "google.generativeai"
    return name.split(".", 1)[0]


def _import_blocker(path: Path, import_name: str, line: int) -> dict[str, Any]:
    return {
        "code": "model-or-network-import-detected",
        "path": path.as_posix(),
        "line": line,
        "import": import_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    payload = validate_no_model_calls([Path(item) for item in args.path])
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
