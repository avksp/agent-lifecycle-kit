"""Bounded provenance graph analysis for research sources."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_lifecycle.contracts import canonical_digest


def analyze_provenance(sources: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze source relationships without treating copies as independent."""

    source_ids: set[str] = {
        item["sourceId"] for item in sources if isinstance(item, dict) and isinstance(item.get("sourceId"), str)
    }
    blockers: list[dict[str, Any]] = []
    adjacency: dict[str, list[str]] = defaultdict(list)
    undirected: dict[str, set[str]] = {source_id: set() for source_id in source_ids}
    duplicate_union = _UnionFind(source_ids)
    duplicate_edges: list[dict[str, Any]] = []
    independence: dict[str, str] = {source_id: "unknown" for source_id in source_ids}

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            blockers.append({"code": "provenance-edge-not-object", "index": index})
            continue
        source_id = edge.get("sourceId")
        related_id = edge.get("relatedSourceId")
        relationship = edge.get("relationship")
        if (
            not isinstance(source_id, str)
            or not isinstance(related_id, str)
            or source_id not in source_ids
            or related_id not in source_ids
        ):
            blockers.append({"code": "provenance-source-missing", "index": index})
            continue
        if source_id == related_id:
            blockers.append({"code": "provenance-self-reference", "sourceId": source_id})
            continue
        if relationship not in {"seed", "suggested-by", "derived-from", "duplicate-of"}:
            blockers.append({"code": "provenance-relationship-invalid", "index": index})
            continue
        adjacency[source_id].append(related_id)
        undirected[source_id].add(related_id)
        undirected[related_id].add(source_id)
        if relationship == "duplicate-of":
            duplicate_union.join(source_id, related_id)
            duplicate_edges.append({"sourceId": source_id, "relatedSourceId": related_id, "independence": "duplicate"})
            independence[source_id] = "duplicate"
            independence[related_id] = "duplicate"
        elif relationship == "derived-from":
            independence[source_id] = "derivative"
        elif independence[source_id] == "unknown":
            independence[source_id] = edge.get("independence", "unknown")

    cycles = _find_cycles(adjacency, source_ids)
    for cycle in cycles:
        blockers.append({"code": "provenance-cycle", "sourceIds": cycle})

    components = _components(undirected)
    disconnected = [sorted(component) for component in components if len(component) == 1 and len(source_ids) > 1]
    duplicate_groups = [sorted(group) for group in duplicate_union.groups() if len(group) > 1]
    independent_source_ids = sorted(source_id for source_id, state in independence.items() if state == "independent")
    body = {
        "status": "PASS" if not blockers else "FAIL",
        "sourceCount": len(source_ids),
        "edgeCount": len(edges),
        "cycles": cycles,
        "disconnectedSourceGroups": disconnected,
        "duplicateGroups": duplicate_groups,
        "duplicateEdges": duplicate_edges,
        "independenceBySource": independence,
        "independentSourceIds": independent_source_ids,
        "blockers": blockers,
    }
    return {**body, "provenanceDigest": canonical_digest(body)}


class _UnionFind:
    def __init__(self, values: set[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def join(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root

    def groups(self) -> list[set[str]]:
        groups: dict[str, set[str]] = defaultdict(set)
        for value in self.parent:
            groups[self.find(value)].add(value)
        return list(groups.values())


def _find_cycles(adjacency: dict[str, list[str]], source_ids: set[str]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[list[str]] = []

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            start = path.index(node) if node in path else 0
            cycle = [*path[start:], node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visiting.add(node)
        for child in adjacency.get(node, []):
            visit(child, [*path, node])
        visiting.remove(node)
        visited.add(node)

    for source_id in sorted(source_ids):
        visit(source_id, [])
    return cycles


def _components(adjacency: dict[str, set[str]]) -> list[set[str]]:
    remaining = set(adjacency)
    components: list[set[str]] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            remaining.discard(node)
            stack.extend(adjacency.get(node, set()) - component)
        components.append(component)
    return components
