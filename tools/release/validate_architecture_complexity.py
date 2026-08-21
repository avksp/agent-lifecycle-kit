from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--target-file-lines", required=True, type=int)
    parser.add_argument("--hard-file-lines", required=True, type=int)
    parser.add_argument("--target-function-lines", required=True, type=int)
    parser.add_argument("--hard-function-lines", required=True, type=int)
    parser.add_argument("--hard-symbols", required=True, type=int)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    root = Path(args.package_root)
    blockers: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    if not root.is_dir():
        blockers.append({"code": "architecture-package-root-missing", "path": root.as_posix()})
    else:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            line_count = len(source.splitlines())
            files.append({"path": path.as_posix(), "lines": line_count, "identity": file_identity(path)})
            if line_count > args.hard_file_lines:
                blockers.append(
                    {"code": "architecture-hard-file-limit-exceeded", "path": path.as_posix(), "actualLines": line_count, "maxLines": args.hard_file_lines}
                )
            elif line_count > args.target_file_lines:
                blockers.append(
                    {"code": "architecture-file-target-exceeded", "path": path.as_posix(), "actualLines": line_count, "targetLines": args.target_file_lines}
                )
            tree = ast.parse(source, filename=path.as_posix())
            top_level = _top_level_symbol_count(tree)
            symbols.append({"path": path.as_posix(), "count": top_level})
            if top_level > args.hard_symbols:
                blockers.append(
                    {"code": "architecture-hard-symbol-limit-exceeded", "path": path.as_posix(), "actualSymbols": top_level, "maxSymbols": args.hard_symbols}
                )
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                end = getattr(node, "end_lineno", node.lineno)
                length = end - node.lineno + 1
                record = {"path": path.as_posix(), "name": node.name, "line": node.lineno, "lines": length}
                functions.append(record)
                if length > args.hard_function_lines:
                    blockers.append(
                        {"code": "architecture-hard-function-limit-exceeded", "path": path.as_posix(), "name": node.name, "actualLines": length, "maxLines": args.hard_function_lines}
                    )

    body = {
        "schemaVersion": "agent-architecture-complexity-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": root.as_posix(),
        "limits": {
            "targetFileLines": args.target_file_lines,
            "hardFileLines": args.hard_file_lines,
            "targetFunctionLines": args.target_function_lines,
            "hardFunctionLines": args.hard_function_lines,
            "hardSymbols": args.hard_symbols,
        },
        "files": files,
        "functions": sorted(functions, key=lambda item: (item["path"], item["line"], item["name"])),
        "symbols": symbols,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _top_level_symbol_count(tree: ast.AST) -> int:
    count = 0
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += 1
        elif isinstance(node, ast.Assign):
            count += len(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            count += 1
    return count


if __name__ == "__main__":
    raise SystemExit(main())
