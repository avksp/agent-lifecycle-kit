from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import sys
import tempfile
from pathlib import Path
from types import CodeType, ModuleType
from typing import Any
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io, canonical, paths

try:
    from release_common import digest_value, file_identity, write_json
except ModuleNotFoundError:  # pragma: no cover - supports package-style test imports
    from tools.release.release_common import digest_value, file_identity, write_json


BOUNDARY_SCHEMA = "agent-repository-input-boundary-validation.v1"

REQUIRED_FILES = {
    "paths": "contracts/paths.py",
    "git": "changesets/git.py",
    "changeSummary": "reporting/change_summary.py",
    "evidenceIndex": "evidence_index/core.py",
}

REQUIRED_MARKERS = {
    "paths": (
        "normalize_git_revision",
        "resolve_repository_file",
        "read_stable_repository_file",
        "_reject_symlink_components",
        "repository-input-changed-during-read",
    ),
    "git": (
        "_resolve_revision",
        "rev-parse",
        "--end-of-options",
        "normalize_git_revision",
    ),
    "changeSummary": (
        "_resolve_revision",
        "rev-parse",
        "--end-of-options",
        "normalize_git_revision",
    ),
    "evidenceIndex": (
        "resolve_repository_file",
        "read_stable_repository_file",
        "artifactRecognition",
        "validationStatus",
        "get_schema",
    ),
}

TEST_FILES = (
    "tests/contracts/test_path_security.py",
    "tests/changesets/test_git.py",
    "tests/reporting/test_change_summary.py",
    "tests/evidence_index/test_evidence_index.py",
    "tests/release/test_repository_input_boundary_validator.py",
)


def _live_nodes(node: ast.AST) -> list[ast.AST]:
    """Inspect ordinary function bodies, not comments, nested helpers or dead tails."""
    result = [node]
    for field, value in ast.iter_fields(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and field != "body":
            continue
        children = value if isinstance(value, list) else [value]
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Constant)
            and field == ("orelse" if node.test.value else "body")
        ):
            continue
        for child in children:
            if not isinstance(child, ast.AST):
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            result.extend(_live_nodes(child))
            if isinstance(child, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                break
    return result


def _name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value, aliases)}.{node.attr}"
    return ""


def _delegation_errors(source: str, contract: dict[str, set[str]], *, facade: bool = False) -> list[str]:
    tree = ast.parse(source)
    aliases = {}
    functions = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            aliases.update({n.asname or n.name: f"{node.module}.{n.name}" for n in node.names})
        elif isinstance(node, ast.Import):
            aliases.update({n.asname or n.name: n.name for n in node.names})
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            functions.update({f"{node.name}.{n.name}": n for n in node.body if isinstance(n, ast.FunctionDef)})
    errors = []
    for function, required in contract.items():
        node = functions.get(function)
        if node is None:
            errors.append(f"{function}:missing-function")
            continue
        nodes = _live_nodes(node)
        calls = {_name(n.func, aliases) for n in nodes if isinstance(n, ast.Call)}
        for missing in sorted(required - calls):
            errors.append(f"{function}:missing-call:{missing}")
        if facade:
            for call in calls:
                if call in {"open", "builtins.open", "io.open", "os.open", "os.fdopen"} or call.endswith(
                    (".read_bytes", ".read_text", ".write_bytes", ".write_text", ".open")
                ):
                    errors.append(f"{function}:unguarded-io:{call}")
    return errors


def _normalized_code(code: CodeType) -> CodeType:
    return code.replace(
        co_filename="<checked-source>",
        co_consts=tuple(_normalized_code(value) if isinstance(value, CodeType) else value for value in code.co_consts),
    )


def _code_matches(code: CodeType, namespace: dict[str, Any], source_path: Path) -> bool:
    for value in code.co_consts:
        if not isinstance(value, CodeType) or value.co_name.startswith("<"):
            continue
        actual = namespace.get(value.co_name)
        if inspect.isclass(actual):
            if not _code_matches(value, vars(actual), source_path):
                return False
        else:
            actual = inspect.unwrap(actual)
            if (
                not inspect.isfunction(actual)
                or Path(actual.__code__.co_filename).resolve() != source_path.resolve()
                or _normalized_code(actual.__code__) != _normalized_code(value)
            ):
                return False
    return True


def _inspect_source(path: Path, module: ModuleType | None) -> tuple[str, dict[str, Any], list[str]]:
    """Source arguments are data. Compile for comparison only; never execute them."""
    source = ""
    identity: dict[str, Any] = {"name": path.name, "bytes": None, "sha256": None}
    errors = []
    try:
        raw = authority_io.read_authority_bytes(path, max_bytes=canonical.MAX_JSON_INPUT_BYTES)
        source = raw.decode("utf-8")
        identity.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        tree = ast.parse(source)
        if module is None or path.resolve() != Path(str(module.__file__)).resolve():
            errors.append("source-runtime-origin-mismatch")
        else:
            # Comparing actual code objects detects stale imports after an on-disk change.
            compiled = compile(source, str(path), "exec", dont_inherit=True)
            if not _code_matches(compiled, vars(module), path):
                errors.append("source-runtime-code-mismatch")
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        expected = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                    if vars(module).get(node.targets[0].id) != expected:
                        errors.append("source-runtime-constant-mismatch")
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_lifecycle"):
                    target = sys.modules.get(node.module or "")
                    for alias in node.names:
                        if target is None or vars(module).get(alias.asname or alias.name) is not getattr(
                            target, alias.name, None
                        ):
                            errors.append("source-runtime-import-mismatch")
        if authority_io.read_authority_bytes(path, max_bytes=canonical.MAX_JSON_INPUT_BYTES) != raw:
            errors.append("source-changed-during-validation")
    except (OSError, LifecycleError, SyntaxError, UnicodeError, ValueError, RecursionError):
        errors.append("source-unavailable-or-invalid")
    return source, identity, sorted(set(errors))


_BACKEND = "agent_lifecycle.contracts.authority_io."
_FACADE_CALLS = {
    "read_json_object": {_BACKEND + "open_authority_read", "load_json_object"},
    "require_private_file": {_BACKEND + "open_authority_read"},
    "ensure_private_directory": {_BACKEND + "ensure_authority_directory"},
    "write_json_create": {_BACKEND + "create_authority_bytes"},
    "write_json_create_private": {_BACKEND + "create_authority_bytes"},
    "write_json_replace_private": {_BACKEND + "replace_authority_bytes"},
}
_BACKEND_CALLS = {
    "open_authority_read": {
        "_parent",
        "_require_regular",
        "_same_identity",
        "os.fdopen",
        "os.fstat",
        "parent.open_child",
    },
    "read_authority_bytes": {"open_authority_read", "handle.read", "os.fstat"},
    "_parent": {"_require_primitives", "_relative_parts", "_same_identity", "_check_bindings", "os.open"},
    "_require_regular": {"stat.S_ISREG", "agent_lifecycle.contracts.errors.LifecycleError"},
    "_same_identity": {"any", "getattr", "agent_lifecycle.contracts.errors.LifecycleError"},
    "_Directory.open_child": {"os.open", "_windows_file"},
    "_Directory.write_child": {"os.open", "_windows_file"},
    "_Directory.replace_child": {"os.replace"},
    "create_authority_bytes": {"_parent", "parent.write_child", "_write_fd"},
    "replace_authority_bytes": {"_parent", "_require_regular", "_write_fd", "parent.replace_child"},
    "append_authority_bytes": {"_parent", "_require_regular", "_same_identity", "_write_fd"},
}


def _authority_checks(package_root: Path, backend_path: Path | None = None) -> dict[str, Any]:
    inputs = (
        ("canonical", package_root / "contracts/canonical.py", canonical, _FACADE_CALLS),
        (
            "paths",
            package_root / "contracts/paths.py",
            paths,
            {
                "normalize_repo_path": {_BACKEND + "normalize_authority_path"},
                "read_stable_repository_file": {_BACKEND + "read_authority_bytes", "resolve_repository_file"},
            },
        ),
        ("backend", backend_path or package_root / "contracts/authority_io.py", authority_io, _BACKEND_CALLS),
    )
    checks, identities = [], []
    for label, path, module, contract in inputs:
        source, identity, errors = _inspect_source(path, module)
        try:
            errors.extend(_delegation_errors(source, contract, facade=label != "backend"))
            if label == "backend":
                tree = ast.parse(source)
                declarations = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
                declarations.update(
                    {
                        f"{n.name}.{m.name}": m
                        for n in tree.body
                        if isinstance(n, ast.ClassDef)
                        for m in n.body
                        if isinstance(m, ast.FunctionDef)
                    }
                )
                for function, symbols in {
                    "_Directory.open_child": {"os.O_NOFOLLOW", "dir_fd"},
                    "_Directory.write_child": {"os.O_NOFOLLOW", "os.O_EXCL", "dir_fd"},
                    "_parent": {"os.O_NOFOLLOW", "os.O_DIRECTORY", "dir_fd"},
                    "_same_identity": {"st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns"},
                }.items():
                    nodes = _live_nodes(declarations[function]) if function in declarations else []
                    present = {_name(n, {}) for n in nodes if isinstance(n, ast.Attribute)}
                    present.update(n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str))
                    present.update(n.arg for n in nodes if isinstance(n, ast.keyword))
                    errors.extend(f"{function}:missing-primitive:{s}" for s in sorted(symbols - present))
                reader = declarations.get("open_authority_read")
                bindings = (
                    {
                        tuple(ast.unparse(a) for a in n.args)
                        for n in _live_nodes(reader)
                        if isinstance(n, ast.Call) and _name(n.func, {}) == "_same_identity"
                    }
                    if reader
                    else set()
                )
                for pair in (
                    ("before_path", "before"),
                    ("before", "os.fstat(handle.fileno())"),
                    ("before", "parent.stat_child(leaf)"),
                ):
                    if pair not in bindings:
                        errors.append("open_authority_read:missing-descriptor-binding:" + "/".join(pair))
        except (SyntaxError, RecursionError):
            errors.append("unresolved-delegation")
        if label == "backend" and path.absolute() != (package_root / "contracts/authority_io.py").absolute():
            errors.append("backend-outside-source-context")
        identities.append({"role": label, **identity})
        checks.append(
            {"id": f"authority-{label}", "status": "FAIL" if errors else "PASS", "errors": sorted(set(errors))}
        )
    _, identity, errors = _inspect_source(Path(__file__), sys.modules[__name__])
    identities.append({"role": "validator", **identity})
    checks.append({"id": "authority-validator", "status": "FAIL" if errors else "PASS", "errors": errors})
    return {"checks": checks, "files": identities}


def _authority_runtime_checks() -> list[dict[str, Any]]:
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        path = root / ".alk" / "input.json"
        try:
            canonical.write_json_create_private(path, {"value": 1})
            assert canonical.read_json_object(path) == {"value": 1}
            assert paths.read_stable_repository_file(root, ".alk/input.json", max_bytes=64) == b'{"value":1}\n'
            canonical.write_json_replace_private(path, {"value": 2})
            assert canonical.read_json_object(path) == {"value": 2}
            authority_io.append_authority_bytes(path, b"\n", root=root)
            assert path.read_bytes() == b'{"value":2}\n\n'
            checks.append({"id": "authority-runtime-roundtrip", "status": "PASS"})
        except (OSError, LifecycleError, AssertionError):
            checks.append({"id": "authority-runtime-roundtrip", "status": "FAIL"})
        for label, expected, call in (
            (
                "cap",
                "repository-input-too-large",
                lambda: paths.read_stable_repository_file(root, ".alk/input.json", max_bytes=1),
            ),
            (
                "traversal",
                "invalid-repo-path",
                lambda: paths.read_stable_repository_file(root, "../outside", max_bytes=64),
            ),
            ("git-option", "invalid-git-revision", lambda: paths.normalize_git_revision("--output=unexpected")),
            (
                "directory",
                "authority-input-not-regular",
                lambda: authority_io.read_authority_bytes(path.parent, root=root, max_bytes=64),
            ),
        ):
            try:
                call()
            except LifecycleError as exc:
                passed = exc.code == expected
            except OSError:
                passed = False
            else:
                passed = False
            checks.append({"id": f"authority-runtime-{label}", "status": "PASS" if passed else "FAIL"})
        link = root / "link"
        try:
            link.symlink_to(path)
        except OSError:
            checks.append(
                {"id": "authority-runtime-symlink", "status": "UNAVAILABLE", "nativeSymlinkPrivilegeRequired": True}
            )
        else:
            try:
                canonical.read_json_object(link)
            except LifecycleError:
                passed = True
            else:
                passed = False
            checks.append({"id": "authority-runtime-symlink", "status": "PASS" if passed else "FAIL"})
        for parent_swap in (False, True):
            check_id = "authority-runtime-parent-race" if parent_swap else "authority-runtime-leaf-race"
            folder = root / ("parent" if parent_swap else "leaf")
            folder.mkdir()
            victim = folder / "value"
            victim.write_bytes(b"inside")
            replacement = root / "replacement"
            replacement.write_bytes(b"outside")
            (root / "value").write_bytes(b"outside")
            original = authority_io._Directory.open_child

            def substitute(
                handle,
                name,
                swap_parent=parent_swap,
                folder=folder,
                victim=victim,
                replacement=replacement,
                original=original,
            ):
                if swap_parent:
                    folder.rename(root / "moved")
                    folder.symlink_to(root, target_is_directory=True)
                else:
                    replacement.replace(victim)
                return original(handle, name)

            # Only this trusted fixture injects a race; supplied source is never executed.
            try:
                with patch.object(authority_io._Directory, "open_child", substitute):
                    paths.read_stable_repository_file(root, victim.relative_to(root).as_posix(), max_bytes=64)
            except LifecycleError as exc:
                passed = exc.code in {"repository-input-changed-during-read", "repository-input-read-failed"}
            except OSError:
                passed = False
            else:
                passed = False
            checks.append({"id": check_id, "status": "PASS" if passed else "FAIL"})
    return checks


def validate_sources(package_root: Path, *, authority_backend_path: Path | None = None) -> dict[str, Any]:
    """Validate the source-level repository input boundary contract."""

    root = package_root.resolve()
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    modules = {
        "paths": paths,
        "git": importlib.import_module("agent_lifecycle.changesets.git"),
        "changeSummary": importlib.import_module("agent_lifecycle.reporting.change_summary"),
        "evidenceIndex": importlib.import_module("agent_lifecycle.evidence_index.core"),
    }
    for label, relative in REQUIRED_FILES.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            blockers.append({"code": "repository-boundary-source-missing", "label": label, "path": relative})
            continue
        text, identity, errors = _inspect_source(path, modules[label])
        identities.append(identity)
        try:
            executable = ast.unparse(ast.parse(text))
        except (SyntaxError, RecursionError):
            executable = ""
        missing = [marker for marker in REQUIRED_MARKERS[label] if marker not in executable]
        if missing or errors:
            blockers.append(
                {
                    "code": "repository-boundary-marker-missing",
                    "label": label,
                    "path": relative,
                    "markers": missing,
                    "sourceErrors": errors,
                }
            )
        checks.append(
            {
                "id": f"source-{label}",
                "status": "PASS" if not missing and not errors else "FAIL",
                "path": relative,
                "markers": list(REQUIRED_MARKERS[label]),
            }
        )

    for relative in TEST_FILES:
        path = root.parents[1] / relative
        if not path.is_file() or path.is_symlink():
            blockers.append({"code": "repository-boundary-test-missing", "path": relative})
            continue
        identities.append(file_identity(path))
    checks.append(
        {
            "id": "security-regression-tests",
            "status": "PASS"
            if not any(item.get("code") == "repository-boundary-test-missing" for item in blockers)
            else "FAIL",
            "files": list(TEST_FILES),
        }
    )

    authority = _authority_checks(package_root, authority_backend_path)
    checks.extend(authority["checks"])
    identities.extend(authority["files"])
    if all(check["status"] == "PASS" for check in authority["checks"]):
        checks.extend(_authority_runtime_checks())
        after = _authority_checks(package_root, authority_backend_path)
        checks.append(
            {
                "id": "authority-source-freshness",
                "status": "PASS"
                if after["checks"] == authority["checks"] and after["files"] == authority["files"]
                else "FAIL",
            }
        )
        for label, relative in REQUIRED_FILES.items():
            _, identity, errors = _inspect_source(root / relative, modules[label])
            if errors or identity not in identities:
                checks.append({"id": "authority-source-freshness-" + label, "status": "FAIL"})
    for check in checks:
        if check["status"] != "PASS" and check["id"].startswith("authority-"):
            blockers.append(
                {
                    "code": "repository-boundary-authority-check-failed",
                    "checkId": check["id"],
                    "errors": check.get("errors", []),
                }
            )
    validated = not blockers

    body = {
        "schemaVersion": BOUNDARY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageRoot": root.as_posix(),
        "checks": checks,
        "files": identities,
        "requiredProperties": {
            "gitRevisionOptionBoundary": validated,
            "stableRegularFileContainment": validated,
            "symlinksRejected": validated,
            "artifactRecognitionSeparateFromValidation": validated,
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "hostProcessesStarted": False,
        "sourceWritesStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--authority-backend")
    args = parser.parse_args()
    payload = validate_sources(
        Path(args.package_root), authority_backend_path=Path(args.authority_backend) if args.authority_backend else None
    )
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
