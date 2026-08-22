"""Bounded deterministic deny-rule matching."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from agent_lifecycle.contracts.performance_limits import DEFAULT_PERFORMANCE_LIMITS

from .errors import NeutralityError


@dataclass
class _TrieNode:
    children: dict[str, int] = field(default_factory=dict)
    outputs: list[int] = field(default_factory=list)
    fail: int = 0


@dataclass(frozen=True)
class LiteralMatcher:
    """Match literal rules while preserving the legacy rule-index order."""

    rules: tuple[str, ...]
    multi_pattern: bool
    nodes: tuple[_TrieNode, ...] = ()

    def matching_indices(self, text: str) -> list[int]:
        if not self.multi_pattern:
            return [index for index, rule in enumerate(self.rules) if rule and rule in text]
        matched: set[int] = set()
        node_index = 0
        for character in text:
            while node_index and character not in self.nodes[node_index].children:
                node_index = 0
            node_index = self.nodes[node_index].children.get(character, 0)
            matched.update(self.nodes[node_index].outputs)
        return sorted(matched)


def validate_rule_limits(literals: Iterable[str], regexes: Iterable[str]) -> None:
    """Reject oversized or malformed authority-and-policy rule sets."""

    literal_values = tuple(literals)
    regex_values = tuple(regexes)
    values = literal_values + regex_values
    limits = DEFAULT_PERFORMANCE_LIMITS
    if len(values) > limits.max_deny_rules:
        raise NeutralityError("deny rule count exceeds the configured limit")
    total_bytes = 0
    for value in values:
        if not isinstance(value, str) or not value:
            raise NeutralityError("deny rules must be non-empty strings")
        size = len(value.encode("utf-8"))
        if size > limits.max_deny_rule_bytes:
            raise NeutralityError("deny rule exceeds the configured byte limit")
        total_bytes += size
    if total_bytes > limits.max_deny_rule_aggregate_bytes:
        raise NeutralityError("deny rule aggregate exceeds the configured byte limit")


def build_literal_matcher(rules: Iterable[str]) -> LiteralMatcher:
    """Build the simple reference or bounded multi-pattern matcher."""

    values = tuple(rules)
    validate_rule_limits(values, ())
    if len(values) <= DEFAULT_PERFORMANCE_LIMITS.max_simple_literal_rules:
        return LiteralMatcher(rules=values, multi_pattern=False)
    nodes = [_TrieNode()]
    for index, rule in enumerate(values):
        node_index = 0
        for character in rule:
            child = nodes[node_index].children.get(character)
            if child is None:
                child = len(nodes)
                nodes[node_index].children[character] = child
                nodes.append(_TrieNode())
            node_index = child
        nodes[node_index].outputs.append(index)
    queue = list(nodes[0].children.values())
    while queue:
        current = queue.pop(0)
        for character, child in nodes[current].children.items():
            fallback = nodes[current].fail
            while fallback and character not in nodes[fallback].children:
                fallback = nodes[fallback].fail
            if character in nodes[fallback].children and nodes[fallback].children[character] != child:
                fallback = nodes[fallback].children[character]
            nodes[child].fail = fallback
            nodes[child].outputs.extend(nodes[fallback].outputs)
            queue.append(child)
    return LiteralMatcher(rules=values, multi_pattern=True, nodes=tuple(nodes))


__all__ = ["LiteralMatcher", "build_literal_matcher", "validate_rule_limits"]
