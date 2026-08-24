"""Validate that the runtime package imports only stdlib or itself."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, write_json
except ModuleNotFoundError:
    from tools.release.release_common import digest_value, write_json


def validate_stdlib_runtime_boundary(package_root: Path) -> dict[str, Any]:
    allowed = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    allowed.add("__future__")
    blockers: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    if not package_root.is_dir():
        blockers.append({"code": "stdlib-package-root-missing", "path": package_root.as_posix()})
    else:
        for path in sorted(package_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
            except (OSError, SyntaxError) as exc:
                blockers.append({"code": "stdlib-source-unreadable", "path": path.as_posix(), "message": str(exc)})
                continue
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    targets = [node.module]
                for target in targets:
                    root = target.split(".", 1)[0]
                    local = root == "agent_lifecycle"
                    status = "PASS" if local or root in allowed else "FAIL"
                    imports.append({"path": path.as_posix(), "module": target, "status": status})
                    if not local and root not in allowed:
                        blockers.append({"code": "stdlib-runtime-import", "path": path.as_posix(), "module": target})
    body = {
        "schemaVersion": "agent-stdlib-runtime-boundary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": package_root.as_posix(),
        "sourceFileCount": len(list(package_root.rglob("*.py"))) if package_root.is_dir() else 0,
        "imports": imports,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_stdlib_runtime_boundary(Path(args.package_root))
    write_json(Path(args.evidence), result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
