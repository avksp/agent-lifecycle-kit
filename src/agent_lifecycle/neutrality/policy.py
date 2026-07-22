"""Neutrality policy loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Pattern

from .canonical import load_json
from .errors import NeutralityError


@dataclass(frozen=True)
class NeutralityPolicy:
    raw: dict[str, Any]
    path_excludes: tuple[Pattern[str], ...]
    deny_literals: tuple[str, ...]
    deny_regexes: tuple[Pattern[str], ...]
    max_file_bytes: int
    max_object_bytes: int
    max_archive_entries: int
    max_expanded_entry_bytes: int


def load_policy(path: Path) -> NeutralityPolicy:
    document = load_json(path.read_bytes())
    if document.get("schemaVersion") != "agent-lifecycle-neutrality-policy.v1":
        raise NeutralityError("unsupported neutrality policy schemaVersion")
    scan = document.get("scan", {})
    archives = document.get("archives", {})
    return NeutralityPolicy(
        raw=document,
        path_excludes=tuple(re.compile(value) for value in _string_list(document, "pathExcludes")),
        deny_literals=tuple(_string_list(document, "denyLiterals")),
        deny_regexes=tuple(re.compile(value) for value in _string_list(document, "denyRegexes")),
        max_file_bytes=int(scan.get("maxFileBytes", 16_777_216)),
        max_object_bytes=int(scan.get("maxObjectBytes", 16_777_216)),
        max_archive_entries=int(archives.get("maxEntriesPerArchive", 10_000)),
        max_expanded_entry_bytes=int(archives.get("maxExpandedBytesPerEntry", 268_435_456)),
    )


def _string_list(document: dict[str, Any], key: str) -> list[str]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise NeutralityError(f"{key} must be a list of strings")
    return value
