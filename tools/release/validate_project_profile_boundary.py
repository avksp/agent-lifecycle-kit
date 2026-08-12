from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any, Iterable

from release_common import digest_value, file_identity, write_json


PROJECT_PART = "agent_lifecycle/project"
BOUNDARY_SCHEMA = "agent-project-profile-boundary-validation.v1"
MODEL_OR_NETWORK_IMPORTS = {
    "anthropic",
    "google.generativeai",
    "httpx",
    "mistralai",
    "openai",
    "requests",
    "urllib",
    "socket",
    "subprocess",
}
FORBIDDEN_PROJECT_IMPORTS = {
    "agent_lifecycle.adapter_sessions.process",
    "agent_lifecycle.adapter_sessions.launcher",
    "agent_lifecycle.workflow",
    "agent_lifecycle.runner",
    "agent_lifecycle.host_protocol",
}
WRITE_METHODS = {"write_text", "write_bytes", "write_json", "replace", "rename", "unlink", "mkdir", "rmdir"}
EXECUTION_CALLS = {"exec", "eval", "compile", "system", "popen"}


def validate_boundary(
    package_root: Path,
    *,
    profile_path: Path,
    merge_path: Path,
    start_path: Path,
    strategy_path: Path,
) -> dict[str, Any]:
    """Check the complete package tree and the project-profile boundary.

    The full tree is required for dependency direction checks. Host/provider,
    write and execution checks are scoped to the project-profile implementation
    so existing adapter process code does not weaken this boundary.
    """

    package_root = package_root.resolve()
    named_paths = [profile_path, merge_path, start_path, strategy_path]
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    python_files = sorted(package_root.rglob("*.py")) if package_root.is_dir() else []
    if not python_files:
        blockers.append({"code": "project-profile-package-root-missing", "path": package_root.as_posix()})

    trees: dict[Path, ast.AST] = {}
    for path in python_files:
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        except (OSError, SyntaxError) as exc:
            blockers.append({
                "code": "project-profile-boundary-parse-failed",
                "path": path.as_posix(),
                "message": str(exc),
            })

    checks.append(_check_named_paths(package_root, named_paths, blockers))
    checks.append(_check_import_direction(package_root, trees, blockers))
    project_files = [path for path in python_files if _is_project_file(package_root, path)]
    checks.append(_check_project_implementation(project_files, trees, blockers))
    checks.append(_check_path_containment(project_files, blockers))
    checks.append(_check_guidance_boundary(project_files, blockers))
    checks.append(_check_no_source_writes(project_files, trees, blockers))

    body: dict[str, Any] = {
        "schemaVersion": BOUNDARY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": package_root.as_posix(),
        "checkedFiles": [path.as_posix() for path in python_files],
        "namedFiles": [path.as_posix() for path in named_paths],
        "checks": checks,
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "sourceWritesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_named_paths(package_root: Path, paths: Iterable[Path], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    checked: list[str] = []
    for path in paths:
        candidate = path.resolve()
        checked.append(candidate.as_posix())
        if not candidate.is_file() or not _is_relative_to(candidate, package_root):
            blockers.append({
                "code": "project-profile-named-file-invalid",
                "path": candidate.as_posix(),
                "packageRoot": package_root.as_posix(),
            })
    return {"id": "named-boundary-files", "status": "PASS" if not any(
        item.get("code") == "project-profile-named-file-invalid" for item in blockers
    ) else "FAIL", "files": checked}


def _check_import_direction(package_root: Path, trees: dict[Path, ast.AST], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    checked = 0
    for path, tree in trees.items():
        checked += 1
        relative = path.relative_to(package_root).as_posix()
        outside_project = not relative.startswith("project/")
        for node in ast.walk(tree):
            imported = _imported_names(node)
            for name in imported:
                if outside_project and name.startswith(PROJECT_PART.replace("/", ".")):
                    # CLI and adapter facades are the public consumers of the
                    # profile. Core contracts, workflow and host-process layers
                    # must not become consumers of this project-local policy.
                    if relative.startswith(("contracts/", "workflow/", "runner/", "policy/")):
                        blockers.append({
                            "code": "project-profile-import-direction",
                            "path": path.as_posix(),
                            "line": getattr(node, "lineno", None),
                            "import": name,
                        })
                if relative.startswith("project/") and any(name == banned or name.startswith(banned + ".") for banned in FORBIDDEN_PROJECT_IMPORTS):
                    blockers.append({
                        "code": "project-profile-forbidden-import",
                        "path": path.as_posix(),
                        "line": getattr(node, "lineno", None),
                        "import": name,
                    })
    return {"id": "directional-imports", "status": "PASS" if not any(
        item.get("code") in {"project-profile-import-direction", "project-profile-forbidden-import"}
        for item in blockers
    ) else "FAIL", "pythonFilesScanned": checked}


def _check_project_implementation(project_files: list[Path], trees: dict[Path, ast.AST], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    for path in project_files:
        tree = trees.get(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = _imported_names(node)
                for name in names:
                    if _import_root(name) in MODEL_OR_NETWORK_IMPORTS:
                        blockers.append({
                            "code": "project-profile-model-network-import",
                            "path": path.as_posix(),
                            "line": getattr(node, "lineno", None),
                            "import": name,
                        })
            if isinstance(node, ast.Call):
                call_name = _call_name(node)
                if call_name in EXECUTION_CALLS or call_name.startswith("subprocess."):
                    blockers.append({
                        "code": "project-profile-execution-call",
                        "path": path.as_posix(),
                        "line": getattr(node, "lineno", None),
                        "call": call_name,
                    })
    relevant_codes = {"project-profile-model-network-import", "project-profile-execution-call"}
    return {"id": "no-model-network-host-calls", "status": "PASS" if not any(
        item.get("code") in relevant_codes for item in blockers
    ) else "FAIL", "files": [path.as_posix() for path in project_files]}


def _check_path_containment(project_files: list[Path], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    profile_text = "\n".join(path.read_text(encoding="utf-8") for path in project_files if path.name in {"profile.py", "guidance.py"})
    required = ("normalize_repo_path", "resolve", "is_symlink", "_is_relative_to", "_reject_symlink_components")
    missing = [marker for marker in required if marker not in profile_text]
    if missing:
        blockers.append({"code": "project-profile-containment-check-missing", "markers": missing})
    return {"id": "path-containment", "status": "PASS" if not missing else "FAIL", "requiredMarkers": list(required)}


def _check_guidance_boundary(project_files: list[Path], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    guidance_text = "\n".join(path.read_text(encoding="utf-8") for path in project_files if path.name in {"guidance.py", "profile.py"})
    forbidden = [marker for marker in ("exec(", "eval(", "compile(", "subprocess", "system prompt") if marker in guidance_text]
    if forbidden:
        blockers.append({"code": "project-profile-guidance-execution", "markers": forbidden})
    return {"id": "guidance-non-execution", "status": "PASS" if not forbidden else "FAIL", "guidanceExecution": False}


def _check_no_source_writes(project_files: list[Path], trees: dict[Path, ast.AST], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    for path in project_files:
        tree = trees.get(path)
        if tree is None:
            continue
        text = path.read_text(encoding="utf-8")
        if "open(" in text and any(mode in text for mode in ('"w"', "'w'", '"a"', "'a'", '"x"', "'x'")):
            blockers.append({"code": "project-profile-source-write", "path": path.as_posix(), "reason": "open-write-mode"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = _call_name(node)
                if call_name.split(".")[-1] in WRITE_METHODS:
                    blockers.append({"code": "project-profile-source-write", "path": path.as_posix(), "line": getattr(node, "lineno", None), "call": call_name})
    return {"id": "no-source-host-writes", "status": "PASS" if not any(
        item.get("code") == "project-profile-source-write" for item in blockers
    ) else "FAIL", "sourceWritesStarted": False}


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def _import_root(name: str) -> str:
    if name.startswith("google.generativeai"):
        return "google.generativeai"
    return name.split(".", 1)[0]


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        prefix = _attribute_name(function.value)
        return f"{prefix}.{function.attr}" if prefix else function.attr
    return "<dynamic>"


def _attribute_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_project_file(package_root: Path, path: Path) -> bool:
    return path.relative_to(package_root).as_posix().startswith("project/")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--merge", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_boundary(
        Path(args.package_root),
        profile_path=Path(args.profile),
        merge_path=Path(args.merge),
        start_path=Path(args.start),
        strategy_path=Path(args.strategy),
    )
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
