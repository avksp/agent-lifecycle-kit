from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json

from agent_lifecycle.quality.dependency_impact import (
    build_module_dependency_report,
    graph_edges,
    graph_from_report,
    module_root,
    package_dependency_graph,
    package_name,
    strongly_connected_components,
)

POLICY_SCHEMA = "agent-architecture-dependencies.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--repository-root")
    parser.add_argument("--policy")
    parser.add_argument("--require-acyclic-modules", action="store_true")
    parser.add_argument("--require-acyclic-packages", action="store_true")
    parser.add_argument("--forbid-cycle", action="append", default=[])
    parser.add_argument("--max-lines", action="append", default=[])
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    package_root = Path(args.package_root).resolve()
    repository_root = _repository_root(package_root, args.repository_root)
    blockers: list[dict[str, Any]] = []
    policy: dict[str, Any] = {}
    if args.policy:
        try:
            policy = _load_policy(Path(args.policy))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            blockers.append({"code": "architecture-policy-invalid", "path": args.policy, "message": str(exc)})

    dependency_report = build_module_dependency_report(package_root, repository_root=repository_root)
    graph = graph_from_report(dependency_report)
    identities = dependency_report["sourceFiles"]
    module_paths = {item["module"]: Path(item["path"]) for item in identities}
    package_graph = package_dependency_graph(graph, package_root)
    module_sccs = strongly_connected_components(graph)
    package_sccs = strongly_connected_components(package_graph)

    if args.require_acyclic_modules:
        blockers.extend({"code": "module-import-cycle", "modules": cycle} for cycle in module_sccs)
    if args.require_acyclic_packages:
        blockers.extend({"code": "package-import-cycle", "packages": cycle} for cycle in package_sccs)

    layer_policy = _layer_policy_result(graph, package_root, policy, module_paths)
    blockers.extend(layer_policy["blockers"])

    forbidden_cycles = [_parse_cycle(value) for value in args.forbid_cycle]
    for cycle in forbidden_cycles:
        if _nodes_share_cycle(graph, cycle):
            blockers.append({"code": "module-import-cycle", "modules": cycle})

    line_checks = []
    for value in args.max_lines:
        path, maximum = _parse_line_check(value)
        count = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else None
        line_checks.append({"path": path.as_posix(), "maxLines": maximum, "actualLines": count})
        if count is None:
            blockers.append({"code": "module-line-check-path-missing", "path": path.as_posix()})
        elif count > maximum:
            blockers.append(
                {
                    "code": "module-line-limit-exceeded",
                    "path": path.as_posix(),
                    "actualLines": count,
                    "maxLines": maximum,
                }
            )

    body = {
        "schemaVersion": "agent-module-dependency-validation.v2",
        "status": "PASS" if not blockers else "FAIL",
        "moduleCount": len(graph),
        "packageCount": len(package_graph),
        "sourceFiles": identities,
        "moduleEdges": dependency_report["moduleEdges"],
        "dependencyReportDigest": dependency_report["reportDigest"],
        "dependencyReport": dependency_report,
        "moduleSccs": module_sccs,
        "packageSccs": package_sccs,
        "packageEdges": graph_edges(package_graph),
        "layerPolicy": layer_policy,
        "policy": policy,
        "forbiddenCycles": forbidden_cycles,
        "lineChecks": line_checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != POLICY_SCHEMA:
        raise ValueError(f"expected {POLICY_SCHEMA}")
    return value


def _repository_root(package_root: Path, explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
    else:
        completed = subprocess.run(
            ["git", "-C", str(package_root), "rev-parse", "--show-toplevel"],
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        root = Path(completed.stdout.strip()).resolve() if completed.returncode == 0 else package_root.parent
    if not package_root.is_relative_to(root):
        raise SystemExit("--package-root must be inside --repository-root")
    return root


def _layer_policy_result(
    graph: dict[str, set[str]],
    package_root: Path,
    policy: dict[str, Any],
    module_paths: dict[str, Path],
) -> dict[str, Any]:
    root = module_root(package_root)
    package_levels = policy.get("packageLevels", {}) if isinstance(policy.get("packageLevels"), dict) else {}
    module_levels = policy.get("moduleLevels", {}) if isinstance(policy.get("moduleLevels"), dict) else {}
    violations: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for source in sorted(graph):
        source_level = _level(source, root, package_levels, module_levels)
        if source_level is None:
            unclassified.append(source)
            continue
        for target in sorted(graph[source]):
            target_level = _level(target, root, package_levels, module_levels)
            if target_level is None:
                unclassified.append(target)
            elif source_level < target_level:
                violations.append({"from": source, "to": target, "fromLevel": source_level, "toLevel": target_level})
    blockers = []
    if policy:
        if unclassified:
            blockers.append({"code": "architecture-layer-unclassified", "modules": sorted(set(unclassified))})
        if violations:
            blockers.append({"code": "architecture-layer-violation", "edges": violations})
    return {
        "schemaVersion": POLICY_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "packageLevels": package_levels,
        "moduleLevels": module_levels,
        "violations": violations,
        "unclassified": sorted(set(unclassified)),
        "blockers": blockers,
        "modulePathCount": len(module_paths),
    }


def _level(module: str, root: str, package_levels: dict[str, Any], module_levels: dict[str, Any]) -> int | None:
    value = module_levels.get(module)
    if value is None:
        value = package_levels.get(package_name(module, root))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_cycle(value: str) -> list[str]:
    modules = [item.strip() for item in value.split(",") if item.strip()]
    if len(modules) < 2:
        raise SystemExit("--forbid-cycle must contain at least two comma-separated modules")
    return modules


def _parse_line_check(value: str) -> tuple[Path, int]:
    path_text, separator, limit_text = value.rpartition("=")
    if not separator or not path_text or not limit_text.isdigit() or int(limit_text) < 1:
        raise SystemExit("--max-lines must use PATH=POSITIVE_INTEGER")
    return Path(path_text), int(limit_text)


def _nodes_share_cycle(graph: dict[str, set[str]], nodes: list[str]) -> bool:
    return all(_reachable(graph, source, target) for source in nodes for target in nodes if source != target)


def _reachable(graph: dict[str, set[str]], source: str, target: str) -> bool:
    pending = [source]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(graph.get(current, set()).difference(visited))
    return False


if __name__ == "__main__":
    raise SystemExit(main())
