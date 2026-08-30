"""Validate canonical stdlib test discovery and CI security boundaries."""

from __future__ import annotations

import argparse
import ast
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


VALIDATION_SCHEMA = "agent-ci-security-validation.v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*([^\s#]+)(?:\s+#\s*(.*))?\s*$")
VERSION_COMMENT_RE = re.compile(r"\bv\d+(?:\.\d+){0,2}\b")
REQUIRED_WORKFLOWS = ("ci.yml", "matrix.yml", "neutrality.yml", "release.yml", "publish.yml", "codeql.yml")
REQUIRED_TEST_PACKAGES = (
    "tests",
    "tests/security",
)


def validate_ci_security(
    *,
    workflow_root: Path,
    tests_root: Path,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Validate workflow pinning, test discovery and mutation tripwires."""

    root = (repository_root or Path.cwd()).resolve()
    workflows = workflow_root if workflow_root.is_absolute() else root / workflow_root
    tests = tests_root if tests_root.is_absolute() else root / tests_root
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    workflow_result = _validate_workflows(workflows, root)
    checks.extend(workflow_result["checks"])
    blockers.extend(workflow_result["blockers"])

    test_result = _validate_test_loader(root, tests)
    checks.extend(test_result["checks"])
    blockers.extend(test_result["blockers"])

    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "workflowRoot": workflows.relative_to(root).as_posix() if workflows.is_relative_to(root) else workflows.name,
        "testsRoot": tests.relative_to(root).as_posix() if tests.is_relative_to(root) else tests.name,
        "workflows": workflow_result["workflows"],
        "testInventory": test_result["inventory"],
        "loader": test_result["loader"],
        "securitySuite": test_result["securitySuite"],
        "mutationChecks": test_result["mutationChecks"],
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _validate_workflows(workflow_root: Path, repository_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    workflows: list[dict[str, Any]] = []
    if not workflow_root.is_dir():
        blocker = {"code": "workflow-root-missing", "path": workflow_root.name}
        return {"checks": [{"id": "workflow-root", "status": "FAIL"}], "blockers": [blocker], "workflows": []}

    paths = sorted(path for path in workflow_root.iterdir() if path.suffix in {".yml", ".yaml"} and path.is_file())
    names = {path.name for path in paths}
    missing = [name for name in REQUIRED_WORKFLOWS if name not in names]
    checks.append({"id": "required-workflows", "status": "PASS" if not missing else "FAIL", "missing": missing})
    blockers.extend({"code": "required-workflow-missing", "path": name} for name in missing)

    for path in paths:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(repository_root).as_posix() if path.is_relative_to(repository_root) else path.name
        identity = file_identity(path)
        workflow_blockers: list[dict[str, Any]] = []
        if "pull_request_target" in text:
            workflow_blockers.append({"code": "unsafe-pull-request-trigger", "path": relative})
        if "permissions:" not in text or not re.search(r"permissions:\s*\n(?:[^\n]*\n){0,8}?\s+contents:\s+read\b", text):
            workflow_blockers.append({"code": "workflow-permissions-not-explicit", "path": relative})

        action_checks = []
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = USES_RE.match(line)
            if not match:
                continue
            action_ref, comment = match.groups()
            action, separator, revision = action_ref.partition("@")
            action_check = {"action": action, "revision": revision, "versionComment": comment or ""}
            if not separator or not SHA_RE.fullmatch(revision):
                action_check["status"] = "FAIL"
                workflow_blockers.append({"code": "action-reference-not-immutable", "path": relative, "action": action_ref})
            elif not comment or not VERSION_COMMENT_RE.search(comment):
                action_check["status"] = "FAIL"
                workflow_blockers.append({"code": "action-version-comment-missing", "path": relative, "action": action})
            else:
                action_check["status"] = "PASS"
            if action == "actions/checkout":
                nearby = "\n".join(lines[index : index + 10])
                if "persist-credentials: false" not in nearby:
                    action_check["status"] = "FAIL"
                    workflow_blockers.append({"code": "checkout-credentials-not-disabled", "path": relative})
            action_checks.append(action_check)
        if "persist-credentials: true" in text:
            workflow_blockers.append({"code": "checkout-credentials-enabled", "path": relative})
        if path.name in {"ci.yml", "matrix.yml", "neutrality.yml", "release.yml"}:
            if "python -m unittest discover" not in text or "-t ." not in text:
                workflow_blockers.append({"code": "canonical-test-top-level-missing", "path": relative})
        if path.name == "ci.yml" and "tests/security" not in text:
            workflow_blockers.append({"code": "security-suite-not-directly-run", "path": relative})
        if path.name == "codeql.yml":
            codeql_actions = ("github/codeql-action/init", "github/codeql-action/analyze")
            for action in codeql_actions:
                if not any(item["action"] == action and item["status"] == "PASS" for item in action_checks):
                    workflow_blockers.append({"code": "codeql-action-missing-or-unpinned", "path": relative, "action": action})
            revisions = {
                item["revision"]
                for item in action_checks
                if item["action"] in codeql_actions and item["status"] == "PASS"
            }
            if len(revisions) > 1:
                workflow_blockers.append(
                    {"code": "codeql-action-revision-mismatch", "path": relative, "revisions": sorted(revisions)}
                )
        status = "PASS" if not workflow_blockers else "FAIL"
        checks.append({"id": f"workflow:{relative}", "status": status, "actionCount": len(action_checks)})
        blockers.extend(workflow_blockers)
        workflows.append({**identity, "path": relative, "actions": action_checks, "status": status})

    dependabot = repository_root / ".github/dependabot.yml"
    if not dependabot.is_file():
        checks.append({"id": "dependabot", "status": "FAIL"})
        blockers.append({"code": "dependabot-config-missing"})
    else:
        text = dependabot.read_text(encoding="utf-8")
        required = ("version: 2", "package-ecosystem: github-actions", "package-ecosystem: pip", "schedule:")
        missing = [value for value in required if value not in text]
        checks.append({"id": "dependabot", "status": "PASS" if not missing else "FAIL", "missing": missing})
        blockers.extend({"code": "dependabot-config-incomplete", "value": value} for value in missing)
    return {"checks": checks, "blockers": blockers, "workflows": workflows}


def _validate_test_loader(repository_root: Path, tests_root: Path) -> dict[str, Any]:
    files = sorted(path for path in tests_root.rglob("test*.py") if path.is_file()) if tests_root.is_dir() else []
    inventory = _test_inventory(files)
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    loader = unittest.TestLoader()
    loader_errors: list[str] = []
    try:
        suite = loader.discover(str(tests_root), pattern="test*.py", top_level_dir=str(repository_root))
        discovered = suite.countTestCases()
        loader_errors = list(loader.errors)
    except Exception as exc:
        discovered = 0
        loader_errors = [type(exc).__name__]
    expected = inventory["expectedCaseCount"]
    loader_status = "PASS" if not loader_errors and discovered >= expected and inventory["topLevelFunctionCount"] == 0 else "FAIL"
    checks.append({"id": "canonical-test-loader", "status": loader_status})
    if loader_errors:
        blockers.append({"code": "test-loader-failure", "errors": loader_errors})
    if discovered < expected:
        blockers.append({"code": "test-case-count-below-inventory", "expected": expected, "discovered": discovered})
    if inventory["topLevelFunctionCount"]:
        blockers.append({"code": "top-level-test-functions-not-collected", "count": inventory["topLevelFunctionCount"]})

    security_suite = unittest.TestLoader()
    security_errors: list[str] = []
    security_count = 0
    security_root = tests_root / "security"
    try:
        security = security_suite.discover(str(security_root), pattern="test*.py", top_level_dir=str(repository_root))
        security_count = security.countTestCases()
        security_errors = list(security_suite.errors)
    except Exception as exc:
        security_errors = [type(exc).__name__]
    security_status = "PASS" if security_count > 0 and not security_errors else "FAIL"
    checks.append({"id": "security-test-loader", "status": security_status, "tests": security_count})
    if security_errors or security_count == 0:
        blockers.append({"code": "security-test-suite-not-loaded", "errors": security_errors, "tests": security_count})

    mutation_checks = _mutation_checks()
    for mutation in mutation_checks:
        checks.append({"id": f"mutation:{mutation['id']}", "status": mutation["status"]})
        if mutation["status"] != "PASS":
            blockers.append({"code": "test-loader-mutation-not-detected", "mutation": mutation["id"]})
    return {
        "checks": checks,
        "blockers": blockers,
        "inventory": inventory,
        "loader": {"expectedCaseCount": expected, "discoveredCaseCount": discovered, "loaderErrors": loader_errors},
        "securitySuite": {"tests": security_count, "loaderErrors": security_errors},
        "mutationChecks": mutation_checks,
    }


def _test_inventory(files: list[Path]) -> dict[str, Any]:
    class_methods = 0
    top_level_functions = 0
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                top_level_functions += 1
            if isinstance(node, ast.ClassDef):
                class_methods += sum(
                    1
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")
                )
    return {
        "fileCount": len(files),
        "expectedCaseCount": class_methods + top_level_functions,
        "classMethodCount": class_methods,
        "topLevelFunctionCount": top_level_functions,
        "files": [path.as_posix() for path in files],
    }


def _mutation_checks() -> list[dict[str, Any]]:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tests = root / "tests"
        package = tests / "pkg"
        package.mkdir(parents=True)
        (package / "test_missing_marker.py").write_text("class Sample:\n    def test_case(self):\n        pass\n", encoding="utf-8")
        results.append(_mutation_result("missing-package-marker", tests, expected=1, require_error=False))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tests = root / "tests"
        failing = tests / "failing"
        failing.mkdir(parents=True)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (failing / "__init__.py").write_text("", encoding="utf-8")
        (failing / "test_import_failure.py").write_text("raise ImportError('fixture failure')\n", encoding="utf-8")
        results.append(_mutation_result("failing-import", tests, expected=0, require_error=True))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tests = root / "tests"
        function_only = tests / "function_only"
        function_only.mkdir(parents=True, exist_ok=True)
        (function_only / "__init__.py").write_text("", encoding="utf-8")
        (function_only / "test_function_only.py").write_text("def test_ignored():\n    pass\n", encoding="utf-8")
        results.append(_mutation_result("uncollected-top-level-function", tests, expected=1, require_error=False))
    return results


def _mutation_result(identifier: str, tests_root: Path, *, expected: int, require_error: bool) -> dict[str, Any]:
    loader = unittest.TestLoader()
    try:
        suite = loader.discover(str(tests_root), pattern="test*.py", top_level_dir=str(tests_root.parent))
        discovered = suite.countTestCases()
    except Exception:
        discovered = 0
    inventory = _test_inventory(sorted(tests_root.rglob("test*.py")))
    detected = (
        bool(loader.errors)
        if require_error
        else discovered != expected or inventory["topLevelFunctionCount"] > 0
    )
    return {
        "id": identifier,
        "status": "PASS" if detected else "FAIL",
        "discovered": discovered,
        "errors": len(loader.errors),
        "topLevelFunctionCount": inventory["topLevelFunctionCount"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-root", required=True)
    parser.add_argument("--tests-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    payload = validate_ci_security(workflow_root=Path(args.workflow_root), tests_root=Path(args.tests_root))
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
