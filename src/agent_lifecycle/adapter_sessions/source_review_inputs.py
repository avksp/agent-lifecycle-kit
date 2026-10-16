"""Owned source review inputs helpers."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.accounting.declared_ledger_legacy import _R11_REVIEW_ROOT
from agent_lifecycle.accounting.declared_ledger_records import _require
from agent_lifecycle.adapter_sessions.source_review_contracts import (
    _R11_PARENT_ARCHIVE,
    _R11_PARENT_INVENTORY_SHA256,
    _R11_PARENT_PROVENANCE_SHA256,
    _R11_REQUEST_CAP,
    _R11_SOURCE_ORACLE_SHA256,
    _r11_imports,
    _r11_python_index,
    _r11_ranges,
    _r11_role_material_authority,
    _r11_wip,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.authority_io import normalize_authority_path, read_authority_bytes
from agent_lifecycle.contracts.bounded_json import load_bounded_json as _r11_json


def _r11_source_inputs(
    root: Path, *, role_delivery: bool = False
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    _require(type(role_delivery) is bool, "r11-source-authority", "explicit delivery version required")
    if role_delivery:
        current = _r11_role_material_authority(root)
        return current["sourceOracle"], current["expectedWip"], current["authoritySha256"]
    plan = "tasks/release-2-16/"
    names = [
        plan + name
        for name in (
            "plan.lock.json",
            "plan.manifest.json",
            "route-bootstrap-contract.json",
            "SOURCE-EXPOSURE-ORACLE-v9.json",
            "EXPECTED-WIP-PATHS-v2.json",
        )
    ]
    raw = {name: read_authority_bytes(root / name, root=root, max_bytes=2_097_152) for name in names}
    digests = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    docs = {name: json.loads(value) for name, value in raw.items()}
    lock, manifest, route, oracle, expected = (docs[name] for name in names)
    _require(
        digests[names[3]] == _R11_SOURCE_ORACLE_SHA256
        and digests[names[4]] == oracle["expectedWipPathsSha256"]
        and route["auditJoin"]["delivery"]["sourceOracleSha256"] == digests[names[3]]
        and route["auditJoin"]["delivery"]["oracles"][0] == names[3]
        and lock["manifestHash"] == canonical_digest(manifest),
        "r11-source-authority",
        "installed source contract does not match its lock",
    )
    entries = {row["path"]: row for row in lock["entries"]}
    _require(
        len(entries) == len(lock["entries"])
        and all(
            entries.get(name, {}).get("sha256") == digests[name] and entries[name]["bytes"] == len(raw[name])
            for name in names[2:]
        ),
        "r11-source-authority",
        "source contract is not in the installed lock",
    )
    owned = expected["temporaryLeadPaths"]
    protected = [row["path"] for row in expected["protectedPaths"]]
    _require(
        len(owned) == len(set(owned))
        and len(protected) == len(set(protected))
        and not set(owned) & set(protected)
        and set(owned) | set(protected) == set(expected["allProductPaths"])
        and owned == route["ownership"]["temporaryLeadWritePaths"],
        "r11-source-ownership",
        "source ownership does not partition expected WIP",
    )
    return oracle, expected, digests


def _r11_partition_current_rows(
    root: Path,
    observed: dict,
    prior: dict,
    parent_files: dict,
    repair: set[str],
    oracle: dict,
    expected: dict,
    selection: dict,
) -> list[dict]:
    result = []
    for row in observed["rows"]:
        name = row["path"]
        before = prior.get(name)
        before_sha = before["currentSha256"] if before else None
        unchanged = before is not None and before_sha == row["sha256"] and before["currentBytes"] == row["bytes"]
        partition = "B" if name in repair else ("A" if unchanged else "C")
        if name in repair:
            _require(
                before_sha == oracle["parentCurrentChangedBeforeSha256"][name],
                "r11-source-parent",
                "observer repair parent differs",
            )
        _require(
            partition == "A" or name in expected["temporaryLeadPaths"],
            "r11-source-ownership",
            "changed source lacks an owner",
        )
        raw = read_authority_bytes(root / name, root=root, max_bytes=8_388_608)
        _require(
            hashlib.sha256(raw).hexdigest() == row["sha256"] and len(raw) == row["bytes"],
            "r11-source-stale",
            "source changed while selecting coverage",
        )
        inherited = []
        if partition == "A" and name in parent_files:
            prior_file = parent_files[name]
            _require(
                prior_file[3:] == [row["sha256"], row["bytes"]],
                "r11-source-parent",
                "parent file selection differs from inventory",
            )
            index = selection["files"].index(prior_file)
            for selected in selection["rows"]:
                if selected[0] != index:
                    continue
                _, start, end, content_sha, count, symbol, identity_sha, _ = selected
                role = "IDENTITY_ONLY" if identity_sha is not None else "CONTENT"
                part = raw[start:end]
                _require(
                    0 <= start < end <= len(raw)
                    and hashlib.sha256(part).hexdigest() == (identity_sha or content_sha)
                    and count == (0 if identity_sha is not None else len(part)),
                    "r11-source-parent",
                    "inherited extent no longer matches parent bytes",
                )
                inherited.append(
                    {
                        "start": start,
                        "end": end,
                        "symbol": symbol,
                        "role": role,
                        "sha256": hashlib.sha256(part).hexdigest(),
                    }
                )
        # Files absent from the parent's source packet inherit no semantic CONTENT.
        extents = (
            inherited
            if partition == "A"
            else [{"start": 0, "end": len(raw), "symbol": "FULL", "role": "CONTENT", "sha256": row["sha256"]}]
        )
        selectors = oracle["requiredIntegrationSelectors"].get(name, [])
        if name.endswith(".py") and selectors:
            try:
                tree = ast.parse(raw)
            except (ValueError, SyntaxError, UnicodeError) as exc:
                raise LifecycleError("r11-source-selector", "current source cannot be parsed") from exc
            definitions = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            for symbol in selectors:
                if symbol in {
                    "ALL_TOP_LEVEL_DEFINITIONS_AND_CALLED_HELPERS",
                    "MANAGED_AND_PLANNING_ENTRYPOINTS_IF_CALLED_OR_CHANGED",
                }:
                    continue
                _require(
                    definitions.count(symbol) == 1,
                    "r11-source-selector",
                    "required integration selector is missing or ambiguous",
                )
        result.append(
            {
                **row,
                "partition": partition,
                "beforeExists": before is not None,
                "beforeSha256": before_sha,
                "beforeBytes": before["currentBytes"] if before else None,
                "owner": "TEMPORARY_LEAD" if name in expected["temporaryLeadPaths"] else "PROTECTED",
                "extents": extents,
                "unexposedBytesRemainUnreviewed": partition == "A",
            }
        )
    return result


def collect_source_partition(
    project_root: Path, *, parent_inventory: bytes, parent_selection: bytes, role_delivery: bool = False
) -> dict[str, Any]:
    """Recompute A/B/C and exact source extents; this is not review or eligibility.

    Parent inputs are raw pinned r362 artifacts. No caller-authored classification
    or current inventory is accepted. Called-helper/shard and cost/reviewer joins
    remain separate obligations of the composite collector.
    """
    root = Path(project_root).absolute()
    oracle, expected, authority = _r11_source_inputs(root, role_delivery=role_delivery)
    _require(
        isinstance(parent_inventory, bytes)
        and isinstance(parent_selection, bytes)
        and hashlib.sha256(parent_inventory).hexdigest() == _R11_PARENT_INVENTORY_SHA256
        and hashlib.sha256(parent_selection).hexdigest() == oracle["parentSelectionManifestSha256"],
        "r11-source-parent",
        "parent inventory or selection bytes differ from r362",
    )
    parent_inventory = _validated_cast(bytes, parent_inventory)
    parent_selection = _validated_cast(bytes, parent_selection)
    parent = json.loads(parent_inventory)
    prior_subject = parent["inventorySubject"]
    _require(
        canonical_digest(prior_subject) == parent["canonicalInventorySubjectSha256"],
        "r11-source-parent",
        "parent inventory canonical identity differs",
    )
    prior_rows = prior_subject["trackedModified"] + prior_subject["untracked"]
    prior = {row["path"]: row for row in prior_rows}
    selection = json.loads(parent_selection)
    selection_oracle_sha = oracle["parentSourceOracleSha256"]
    if role_delivery:
        # v10's predecessor is v9; the immutable r362 selection still names
        # v9's retained selection ancestor. Keep those two typed joins distinct.
        previous_path = oracle["parentSourceOraclePath"]
        previous_raw = read_authority_bytes(root / previous_path, root=root, max_bytes=262_144)
        _require(
            hashlib.sha256(previous_raw).hexdigest()
            == oracle["parentSourceOracleSha256"]
            == authority.get(previous_path),
            "r11-source-parent",
            "immediate source oracle predecessor changed",
        )
        previous = _r11_json(previous_raw, limit=262_144)
        _require(
            previous["parentSelectionManifestSha256"] == oracle["parentSelectionManifestSha256"],
            "r11-source-parent",
            "retained selection identity differs across oracle versions",
        )
        selection_oracle_sha = previous["parentSourceOracleSha256"]
    _require(
        len(prior) == len(prior_rows) and len(prior) == 70 and selection["oracleSha256"] == selection_oracle_sha,
        "r11-source-parent",
        "parent source membership differs",
    )
    parent_files = {row[0]: row for row in selection["files"]}
    observed = _r11_wip(root, expected)
    _require(
        observed["gitHead"] == prior_subject["gitHead"], "r11-source-parent", "current Git base differs from the parent"
    )
    repair = set(oracle["parentCurrentChangedBeforeSha256"])
    result = _r11_partition_current_rows(root, observed, prior, parent_files, repair, oracle, expected, selection)
    _require(
        observed == _r11_wip(root, expected) and authority == _r11_source_inputs(root, role_delivery=role_delivery)[2],
        "r11-source-stale",
        "WIP or installed authority changed during source selection",
    )
    subject = {
        "schemaVersion": "alk-r11-source-partition.v1",
        "gitHead": observed["gitHead"],
        "authoritySha256": authority,
        "trackedDiffSha256": observed["trackedDiffSha256"],
        "parentInventorySha256": hashlib.sha256(parent_inventory).hexdigest(),
        "parentSelectionSha256": hashlib.sha256(parent_selection).hexdigest(),
        "rows": result,
        "productPathCount": len(result),
        "dependencyClosureComplete": False,
        "firstNativeBootstrapEligible": False,
    }
    return {**subject, "partitionSha256": canonical_digest(subject)}


def _r11_dependency_source(name: str, root, cache, selected, pending) -> tuple[bytes, dict[str, Any]]:
    _require(
        normalize_authority_path(name) == name and name.endswith(".py") and (name.split("/")[0] in {"src", "tests"}),
        "r11-dependency-source",
        "dependency is not a repository Python source",
    )
    if name not in cache:
        raw = read_authority_bytes(root / name, root=root, max_bytes=1048576)
        cache[name] = (raw, _r11_python_index(raw, name))
        selected.setdefault(name, {})
        for parent in Path(name).parents:
            if parent.as_posix() in {".", "src"}:
                break
            initializer = (parent / "__init__.py").as_posix()
            if initializer != name and (root / initializer).exists():
                pending.append((initializer, "@header"))
        _require(
            len(cache) <= 256 and sum(len(item[0]) for item in cache.values()) <= 8388608,
            "r11-dependency-limit",
            "source dependency closure exceeds bounded admission",
        )
    return cache[name]


def _r11_dependency_module_path(module: str, root) -> str | None:
    _require(
        all(part.isidentifier() for part in module.split(".")),
        "r11-dependency-import",
        "import module is not canonical",
    )
    base = ("src/" if module.startswith("agent_lifecycle") else "") + module.replace(".", "/")
    candidates = [name for name in (base + ".py", base + "/__init__.py") if (root / name).exists()]
    _require(len(candidates) <= 1, "r11-dependency-import", "ambiguous module and package source")
    return candidates[0] if candidates else None


def _r11_dependency_include(name: str, unit: dict[str, Any], symbol: str, selected) -> None:
    selected.setdefault(name, {}).setdefault((unit["start"], unit["end"]), set()).add(symbol)


def _r11_dependency_imported(
    caller: tuple[str, str], module: str, symbol: str | None, root, cache, selected, pending, edges
) -> None:
    target = _r11_dependency_module_path(module, root)
    _require(target is not None, "r11-dependency-import", "missing repository module: " + module)
    target = _validated_cast(str, target)
    if symbol is None:
        pending.append((target, "*"))
        edges.add((*caller, target, "*"))
    else:
        _, index = _r11_dependency_source(target, root, cache, selected, pending)
        imports = _r11_imports(list(index["tree"].body), target, repository_only=False)
        if symbol not in index["bindings"] and symbol not in imports:
            if symbol == "__file__":
                pending.append((target, "*"))
                edges.add((*caller, target, "*"))
                return
            submodule = _r11_dependency_module_path(module + "." + symbol, root)
            if submodule is not None:
                _require(
                    target.endswith("/__init__.py")
                    and "__getattr__" not in index["bindings"]
                    and ("__getattr__" not in imports),
                    "r11-dependency-import",
                    "implicit submodule binding is ambiguous",
                )
                pending.extend(((target, "@header"), (submodule, "*")))
                edges.add((*caller, target, "@header"))
                edges.add((*caller, submodule, "*"))
                return
        pending.append((target, symbol))
        edges.add((*caller, target, symbol))


def _r11_expand_dependency_worklist(root, cache, selected, pending, edges, unresolved, visited):
    while pending:
        name, symbol = pending.pop()
        if (name, symbol) in visited:
            continue
        visited.add((name, symbol))
        _require(len(visited) <= 4096, "r11-dependency-limit", "too many dependency selectors")
        _raw, index = _r11_dependency_source(name, root, cache, selected, pending)
        if symbol != "@header":
            pending.append((name, "@header"))
        global_nodes = list(index["tree"].body)
        imports = _r11_imports(global_nodes, name)
        all_imports = _r11_imports(global_nodes, name, repository_only=False)
        if symbol == "*":
            pending.extend((name, key) for key in index["bindings"])
            pending.append((name, "@header"))
            continue
        if symbol == "@header":
            units = [
                unit
                for unit in index["units"]
                if not isinstance(unit["node"], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
        elif symbol in index["bindings"]:
            units = [index["bindings"][symbol]]
        elif symbol in all_imports:
            units = [
                unit
                for unit in index["units"]
                if isinstance(unit["node"], (ast.Import, ast.ImportFrom))
                and symbol in _r11_imports([unit["node"]], name, repository_only=False)
            ]
            if symbol in imports:
                _r11_dependency_imported((name, symbol), *imports[symbol], root, cache, selected, pending, edges)
        else:
            raise LifecycleError(
                "r11-dependency-selector", "repository symbol has no static top-level binding: " + name + ":" + symbol
            )
        for unit in units:
            _r11_dependency_include(name, unit, symbol, selected)
            nodes = list(ast.walk(unit["node"]))
            local_imports = _r11_imports(global_nodes + nodes, name)
            namespace_names = set()
            parents = {id(child): parent for parent in nodes for child in ast.iter_child_nodes(parent)}
            for node in nodes:
                if not isinstance(node, ast.Attribute):
                    continue
                parent_node = parents.get(id(node))
                if isinstance(parent_node, ast.Attribute) and parent_node.value is node:
                    continue
                parts = []
                cursor = node
                while isinstance(cursor, ast.Attribute):
                    parts.insert(0, cursor.attr)
                    cursor = cursor.value
                if not isinstance(cursor, ast.Name) or cursor.id not in local_imports:
                    continue
                module, member = local_imports[cursor.id]
                if member is not None:
                    if _r11_dependency_module_path(module + "." + member, root) is None:
                        continue
                    module += "." + member
                while parts and _r11_dependency_module_path(module + "." + parts[0], root) is not None:
                    module += "." + parts.pop(0)
                _r11_dependency_imported(
                    (name, symbol), module, parts[0] if parts else None, root, cache, selected, pending, edges
                )
                namespace_names.add(id(cursor))
            for node in nodes:
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if node.id in index["bindings"]:
                        pending.append((name, node.id))
                        edges.add((name, symbol, name, node.id))
                    elif node.id in local_imports and id(node) not in namespace_names:
                        _r11_dependency_imported(
                            (name, symbol), *local_imports[node.id], root, cache, selected, pending, edges
                        )
                if isinstance(node, ast.Call):
                    callee = ast.unparse(node.func)
                    if not isinstance(node.func, ast.Name) or node.func.id not in index["bindings"]:
                        unresolved.add((name, symbol, node.lineno, callee))


def collect_source_dependencies(
    project_root: Path,
    *,
    partition: dict[str, Any],
    parent_inventory: bytes,
    parent_selection: bytes,
    parent_sources: dict[str, bytes],
    role_delivery: bool = False,
) -> dict[str, Any]:
    """Build a source-bound static dependency candidate, without executing imports.

    Full B/C bytes are mandatory. Additional dependency units are current CONTENT
    proposed for review, never retroactive promotion of inherited A coverage.
    Dynamic dispatch/patch targets are reported, not asserted resolved. Complete
    interaction acceptance still requires the independent v5 review/collector.
    """
    root = Path(project_root).absolute()
    _require(
        partition
        == collect_source_partition(
            root, parent_inventory=parent_inventory, parent_selection=parent_selection, role_delivery=role_delivery
        ),
        "r11-dependency-stale",
        "source partition changed before dependency selection",
    )
    changed = {row["path"]: row for row in partition["rows"] if row["partition"] in {"B", "C"}}
    needed_before = {name for name, row in changed.items() if row["beforeExists"]}
    _require(
        isinstance(parent_sources, dict) and set(parent_sources) == needed_before,
        "r11-dependency-parent",
        "exact existing B/C parent source membership is required",
    )
    parent_sources = _validated_cast(dict[str, Any], parent_sources)
    for name, raw in parent_sources.items():
        _require(
            isinstance(raw, bytes)
            and len(raw) == changed[name]["beforeBytes"]
            and (hashlib.sha256(raw).hexdigest() == changed[name]["beforeSha256"]),
            "r11-dependency-parent",
            "parent source bytes differ from the pinned inventory",
        )
        raw = _validated_cast(bytes, raw)
    cache: dict[str, tuple[bytes, dict[str, Any]]] = {}
    selected: dict[str, dict[tuple[int, int], set[str]]] = {}
    pending: list[tuple[str, str]] = []
    edges: set[tuple[str, str, str, str]] = set()
    unresolved: set[tuple[str, str, int, str]] = set()
    visited: set[tuple[str, str]] = set()
    full = set(changed)
    for name in sorted(changed):
        _raw, index = _r11_dependency_source(name, root, cache, selected, pending)
        old = _r11_python_index(parent_sources[name], name) if name in parent_sources else None
        imports = _r11_imports(list(index["tree"].body), name)
        old_imports = _r11_imports(list(old["tree"].body), name) if old else {}
        rebound = {alias for alias in set(imports) | set(old_imports) if imports.get(alias) != old_imports.get(alias)}
        for symbol, unit in index["bindings"].items():
            old_unit = old["bindings"].get(symbol) if old else None
            if (
                old_unit is None
                or any(
                    isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and (node.id in rebound)
                    for node in ast.walk(unit["node"])
                )
                or raw[unit["start"] : unit["end"]] != parent_sources[name][old_unit["start"] : old_unit["end"]]
            ):
                pending.append((name, symbol))
        pending.append((name, "@header"))
    oracle, _, _ = _r11_source_inputs(root, role_delivery=role_delivery)
    for name, symbols in oracle["requiredIntegrationSelectors"].items():
        if symbols == ["MANAGED_AND_PLANNING_ENTRYPOINTS_IF_CALLED_OR_CHANGED"] and name not in changed:
            continue
        _, index = _r11_dependency_source(name, root, cache, selected, pending)
        for symbol in symbols:
            if symbol in {
                "ALL_TOP_LEVEL_DEFINITIONS_AND_CALLED_HELPERS",
                "MANAGED_AND_PLANNING_ENTRYPOINTS_IF_CALLED_OR_CHANGED",
            }:
                pending.append((name, "*"))
            else:
                containers = [
                    key
                    for key, unit in index["bindings"].items()
                    if any(
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol
                        for node in ast.walk(unit["node"])
                    )
                ]
                _require(len(containers) == 1, "r11-dependency-selector", "integration owner is ambiguous")
                pending.append((name, containers[0]))
    _r11_expand_dependency_worklist(root, cache, selected, pending, edges, unresolved, visited)
    files = []
    for name in sorted(set(selected) | full):
        raw, _ = _r11_dependency_source(name, root, cache, selected, pending)
        ranges = [
            {
                "start": start,
                "end": end,
                "symbols": sorted(symbols),
                "sha256": hashlib.sha256(raw[start:end]).hexdigest(),
            }
            for (start, end), symbols in sorted(selected.get(name, {}).items())
        ]
        if name in full:
            ranges = [{"start": 0, "end": len(raw), "symbols": ["FULL_BC"], "sha256": hashlib.sha256(raw).hexdigest()}]
        files.append(
            {
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "role": "CURRENT_CONTENT_REQUIRES_REVIEW",
                "ranges": ranges,
            }
        )
    for name, (raw, _) in cache.items():
        _require(
            read_authority_bytes(root / name, root=root, max_bytes=1048576) == raw,
            "r11-dependency-stale",
            "dependency changed during selection",
        )
    _require(
        partition
        == collect_source_partition(
            root, parent_inventory=parent_inventory, parent_selection=parent_selection, role_delivery=role_delivery
        ),
        "r11-dependency-stale",
        "partition changed during dependency selection",
    )
    subject = {
        "schemaVersion": "alk-r11-static-source-dependencies.v1",
        "partitionSha256": partition["partitionSha256"],
        "files": files,
        "edges": [list(edge) for edge in sorted(edges)],
        "callsRequiringInteractionReview": [list(edge) for edge in sorted(unresolved)],
        "parentSourceSha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(parent_sources.items())},
        "dependencyClosureComplete": False,
        "firstNativeBootstrapEligible": False,
    }
    return {**subject, "selectionSha256": canonical_digest(subject)}


def _r11_source_material(
    root: Path,
    partition: dict[str, Any],
    dependencies: dict[str, Any],
    parent_sources: dict[str, bytes],
) -> tuple[dict[tuple[str, str], bytes], dict[tuple[str, str], list[tuple[int, int]]]]:
    sources = {}
    required = {}
    for row in dependencies["files"]:
        name = row["path"]
        raw = read_authority_bytes(root / name, root=root, max_bytes=1_048_576)
        _require(
            len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"],
            "r11-shard-source-stale",
            "current review source changed",
        )
        ranges = []
        for part in row["ranges"]:
            start, end = part["start"], part["end"]
            _require(
                0 <= start < end <= len(raw) and hashlib.sha256(raw[start:end]).hexdigest() == part["sha256"],
                "r11-shard-source-stale",
                "dependency extent differs from current bytes",
            )
            ranges.append((start, end))
        sources[("CURRENT", name)] = raw
        required[("CURRENT", name)] = _r11_ranges(ranges)
    for name, raw in sorted(parent_sources.items()):
        sources[("PARENT", name)] = raw
        required[("PARENT", name)] = [(0, len(raw))] if raw else []
    for row in partition["rows"]:
        if row["partition"] in {"B", "C"}:
            key = ("CURRENT", row["path"])
            _require(
                key in sources
                and len(sources[key]) == row["bytes"]
                and hashlib.sha256(sources[key]).hexdigest() == row["sha256"]
                and required[key] == ([(0, row["bytes"])] if row["bytes"] else []),
                "r11-shard-coverage",
                "complete B/C current source is required",
            )
            if row["beforeExists"]:
                raw = _validated_cast(bytes, sources.get(("PARENT", row["path"])))
                _require(
                    raw is not None
                    and len(raw) == row["beforeBytes"]
                    and hashlib.sha256(raw).hexdigest() == row["beforeSha256"],
                    "r11-shard-parent",
                    "complete exact parent source is required",
                )
    return sources, required


def _r11_read_parent_file(root: Path, path: Path) -> bytes:
    """Private historical blobs may exceed the 128 KiB launch-artifact bound.

    Use held no-follow authority I/O with a separate bounded archive limit; never
    increase the unrelated launch/request private reader's limit.
    """
    _require(path.is_relative_to(root), "r11-parent-archive", "parent archive escapes project root")
    try:
        current = path.parent
        while current != root:
            info = current.lstat()
            shared = current.relative_to(root).parts in {
                ("work",),
                ("work", "release-2-16"),
                ("work", "release-2-16", "evidence"),
            }
            _require(
                stat.S_ISDIR(info.st_mode) and (shared or stat.S_IMODE(info.st_mode) == 0o700),
                "r11-parent-archive",
                "parent archive directory is not private and regular",
            )
            current = current.parent
        info = path.lstat()
        _require(
            stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
            "r11-parent-archive",
            "parent archive file is not private and regular",
        )
        return read_authority_bytes(path, root=root, max_bytes=2_097_152)
    except OSError as exc:
        raise LifecycleError("r11-parent-archive", "parent archive is unavailable") from exc


def _r11_parent_snapshot(root: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    directory = root / _R11_PARENT_ARCHIVE
    provenance_raw = _r11_read_parent_file(root, directory / "PARENT-PROVENANCE.json")
    _require(
        hashlib.sha256(provenance_raw).hexdigest() == _R11_PARENT_PROVENANCE_SHA256,
        "r11-parent-archive",
        "parent provenance differs from the immutable r372 annex",
    )
    provenance = _r11_json(provenance_raw, limit=131_072)
    entries = {key: row for key, row in provenance["files"].items() if key != "support"}
    entries.update({"support/" + key: row for key, row in provenance["files"]["support"].items()})
    paths = {row["path"] for row in entries.values()}
    _require(
        len(paths) == len(entries)
        and all(normalize_authority_path(name) == name and name.startswith("parent-r362-private/") for name in paths),
        "r11-parent-archive",
        "parent annex path inventory is invalid",
    )
    expected_files = paths | {"PARENT-PROVENANCE.json"}
    expected_dirs = {parent.as_posix() for name in paths for parent in Path(name).parents if parent.as_posix() != "."}

    def inventory() -> None:
        seen_files: set[str] = set()
        seen_dirs: set[str] = set()
        pending = [directory]
        try:
            while pending:
                current = pending.pop()
                for path in current.iterdir():
                    name = path.relative_to(directory).as_posix()
                    mode = path.lstat().st_mode
                    if stat.S_ISDIR(mode):
                        _require(
                            name in expected_dirs and stat.S_IMODE(mode) == 0o700,
                            "r11-parent-archive",
                            "unexpected or nonprivate parent archive directory",
                        )
                        seen_dirs.add(name)
                        pending.append(path)
                    else:
                        _require(
                            stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600 and name in expected_files,
                            "r11-parent-archive",
                            "unexpected or indirect parent archive file",
                        )
                        seen_files.add(name)
            _require(
                seen_files == expected_files and seen_dirs == expected_dirs,
                "r11-parent-archive",
                "parent archive has missing members",
            )
        except OSError as exc:
            raise LifecycleError("r11-parent-archive", "parent archive cannot be enumerated") from exc

    inventory()
    raw = {}
    for key, row in entries.items():
        value = _r11_read_parent_file(root, directory / row["path"])
        _require(
            len(value) == row["bytes"] and hashlib.sha256(value).hexdigest() == row["sha256"],
            "r11-parent-archive",
            "raw parent artifact differs: " + key,
        )
        raw[key] = value
    inventory()
    _require(
        _r11_read_parent_file(root, directory / "PARENT-PROVENANCE.json") == provenance_raw,
        "r11-parent-archive",
        "parent provenance changed during read",
    )
    return raw, provenance


def collect_source_review_parent(project_root: Path) -> dict[str, Any]:
    """Reopen the complete pinned negative parent; never upgrade its verdict.

    Historical event RPC summaries remain historical summaries, not the new raw
    v5 transport protocol. Exact archive integrity and digest definitions permit
    inheritance only to the extent the current source partition proves equality.
    """
    from .codex_source_subject import _single_turn_projection

    root = Path(project_root).absolute()
    raw, provenance = _r11_parent_snapshot(root)
    definitions = provenance["digestDefinitions"]
    transport = provenance["transport"]
    subject = _r11_json(raw["subject"], limit=131_072)
    body = _r11_json(raw["review-body.raw"], limit=65_536)
    inventory = _r11_json(raw["afterWipInventory"], limit=131_072)
    selection = _r11_json(raw["SOURCE_EXPOSURE_MANIFEST"], limit=131_072)
    support = {key.removeprefix("support/"): value for key, value in raw.items() if key.startswith("support/")}
    _require(
        hashlib.sha256(raw["subject"]).hexdigest() == definitions["parentSubjectRawSha256"]
        and canonical_digest(subject)
        == definitions["parentSubjectCanonicalSha256"]
        == definitions["parentBodySubjectEcho"]
        == body.get("subjectSha256")
        and subject.get("reviewedInputDigest")
        == definitions["reviewedInputDigest"]
        == canonical_digest({key: value for key, value in subject.items() if key != "reviewedInputDigest"})
        and hashlib.sha256(raw["afterWipInventory"]).hexdigest()
        == definitions["parentInventoryRawSha256"]
        == _R11_PARENT_INVENTORY_SHA256
        and inventory.get("canonicalInventorySubjectSha256")
        == definitions["parentInventoryCanonicalSubjectSha256"]
        == canonical_digest(inventory["inventorySubject"])
        and subject.get("privateSupportReceiptDigests")
        == {name: hashlib.sha256(value).hexdigest() for name, value in support.items()}
        and support.get("after-wip-inventory.json") == raw["afterWipInventory"]
        and support.get("admission.json") == raw["admission.json"]
        and body.get("verdict") == transport["completedBodyVerdict"] == "FAIL"
        and body.get("coverageComplete") is True
        and body.get("rb11RuntimeStatus") == "NOT_RUN"
        and [row["id"] for row in body.get("findings", [])]
        == [transport["soleOpenFindingId"]]
        == ["RB-OBSERVER-TIMEOUT-01"]
        and all(row.get("status") == "OPEN" for row in body["findings"]),
        "r11-parent-join",
        "negative parent subject/support/finding digest definitions differ",
    )
    request = _r11_json(raw["review-request.json"], limit=_R11_REQUEST_CAP)
    write = _r11_json(raw["review-request-write.json"], limit=65_536)
    reads = [
        _r11_json(raw[name], limit=2_097_152) for name in ("review-thread-read-6.json", "review-thread-read-7.json")
    ]
    projections = [
        _single_turn_projection(value, thread_id=transport["threadId"], turn_id=transport["turnId"], request=request)
        for value in reads
    ]
    _require(
        projections[0] == projections[1]
        and projections[0]["bodyText"].encode("utf-8") == raw["review-body.raw"]
        and write.get("requestId") == request["id"]
        and write.get("flushed") is True
        and write.get("requestBytes") == write.get("writtenBytes") == len(raw["review-request.json"])
        and write.get("requestSha256")
        == transport["requestSha256"]
        == hashlib.sha256(raw["review-request.json"]).hexdigest(),
        "r11-parent-join",
        "archived negative request/write/body/reads differ",
    )
    settlement = _r11_json(raw["COST-SETTLEMENT.json"], limit=65_536)
    admission = _r11_json(raw["admission.json"], limit=65_536)
    cost = provenance["cost"]
    _require(
        settlement.get("status") == "MEASURED"
        and settlement.get("actualModelTokens") == cost["postTurnMeasuredTokens"]
        and settlement.get("unknownHolds")
        == cost["postTurnUnknownHolds"]
        == settlement.get("priorUnknownHolds")
        == admission.get("priorUnknownHolds")
        and settlement.get("accountedExposureLowerBound")
        == cost["postTurnLowerBound"]
        == settlement.get("priorAccountedExposureLowerBound") + settlement["actualModelTokens"]
        and settlement.get("unusedAdmissionReleased")
        == cost["unusedAdmissionReleased"]
        == admission.get("tokenCap") - settlement["actualModelTokens"],
        "r11-parent-join",
        "parent settlement arithmetic differs",
    )
    after, after_provenance = _r11_parent_snapshot(root)
    _require(
        after == raw and after_provenance == provenance,
        "r11-parent-archive",
        "parent archive changed during collection",
    )
    content = {
        "parentBody": body,
        "parentSubject": subject,
        "digestDefinitions": definitions,
        "parentInventory": inventory,
        "parentSourceSelection": selection,
        "parentSupportReceiptDigests": subject["privateSupportReceiptDigests"],
        "archivedTransportIdentity": transport,
        "parentAdmission": admission,
        "parentSettlement": settlement,
    }
    return {
        "schemaVersion": "alk-r11-parent-archive-match.v1",
        "status": "PARENT_NEGATIVE_MATCHED",
        "content": content,
        "parentSubjectSha256": canonical_digest(subject),
        "parentReviewBodySha256": hashlib.sha256(raw["review-body.raw"]).hexdigest(),
        "parentArchiveSha256": canonical_digest({key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}),
        "parentProvenanceSha256": _R11_PARENT_PROVENANCE_SHA256,
        "parentVerdict": "FAIL",
        "openParentFindingIds": ["RB-OBSERVER-TIMEOUT-01"],
        "closedParentFindingIds": [],
        "v5TransportQualified": False,
        "currentCoverageQualified": False,
        "firstNativeBootstrapEligible": False,
    }


def _r11_review_parent_sources(root: Path, partition: dict[str, Any]) -> dict[str, bytes]:
    directory = root / _R11_REVIEW_ROOT / "parent-source"
    wanted = {row["path"]: row for row in partition["rows"] if row["partition"] in {"B", "C"} and row["beforeExists"]}
    result = {}
    # Read through private no-follow ancestry before enumerating this directory.
    for name, row in sorted(wanted.items()):
        raw = _r11_read_parent_file(root, directory / name)
        _require(
            hashlib.sha256(raw).hexdigest() == row["beforeSha256"] and len(raw) == row["beforeBytes"],
            "r11-review-parent-source",
            "full before-source differs from pinned parent inventory",
        )
        result[name] = raw
    expected_dirs = {parent.as_posix() for name in wanted for parent in Path(name).parents if parent.as_posix() != "."}
    files, dirs = set(), set()
    try:
        for path in directory.rglob("*"):
            name = path.relative_to(directory).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                _require(
                    name in expected_dirs and stat.S_IMODE(mode) == 0o700,
                    "r11-review-parent-source",
                    "unexpected or indirect before-source directory",
                )
                dirs.add(name)
            else:
                _require(
                    stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600 and name in wanted,
                    "r11-review-parent-source",
                    "unexpected or indirect before-source file",
                )
                files.add(name)
    except OSError as exc:
        raise LifecycleError("r11-review-parent-source", "before-source inventory unavailable") from exc
    _require(
        files == set(wanted) and dirs == expected_dirs,
        "r11-review-parent-source",
        "before-source inventory is incomplete",
    )
    return result
