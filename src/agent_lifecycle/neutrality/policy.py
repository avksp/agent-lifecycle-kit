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
    max_archive_nesting_depth: int
    max_archives_per_subject: int
    max_archive_entries: int
    max_entries_per_subject: int
    max_compressed_bytes_per_archive: int
    max_expanded_bytes_per_archive: int
    max_expanded_entry_bytes: int
    max_expanded_bytes_per_subject: int
    max_compression_ratio: int


def load_policy(path: Path) -> NeutralityPolicy:
    document = load_json(path.read_bytes())
    if document.get("schemaVersion") != "agent-lifecycle-neutrality-policy.v1":
        raise NeutralityError("unsupported neutrality policy schemaVersion")
    scan = _object(document, "scan")
    archives = _object(document, "archives")
    return NeutralityPolicy(
        raw=document,
        path_excludes=tuple(re.compile(value) for value in _string_list(document, "pathExcludes")),
        deny_literals=tuple(_string_list(document, "denyLiterals")),
        deny_regexes=tuple(re.compile(value) for value in _string_list(document, "denyRegexes")),
        max_file_bytes=_positive_int(scan, "maxFileBytes", 16_777_216),
        max_object_bytes=_positive_int(scan, "maxObjectBytes", 16_777_216),
        max_archive_nesting_depth=_positive_int(archives, "maxArchiveNestingDepth", 4),
        max_archives_per_subject=_positive_int(archives, "maxArchivesPerSubject", 1_000),
        max_archive_entries=_positive_int(archives, "maxEntriesPerArchive", 10_000),
        max_entries_per_subject=_positive_int(archives, "maxEntriesPerSubject", 100_000),
        max_compressed_bytes_per_archive=_positive_int(archives, "maxCompressedBytesPerArchive", 536_870_912),
        max_expanded_bytes_per_archive=_positive_int(archives, "maxExpandedBytesPerArchive", 2_147_483_648),
        max_expanded_entry_bytes=_positive_int(archives, "maxExpandedBytesPerEntry", 268_435_456),
        max_expanded_bytes_per_subject=_positive_int(archives, "maxExpandedBytesPerSubject", 4_294_967_296),
        max_compression_ratio=_positive_int(archives, "maxCompressionRatio", 100),
    )


def _string_list(document: dict[str, Any], key: str) -> list[str]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise NeutralityError(f"{key} must be a list of strings")
    return value


def _object(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key, {})
    if not isinstance(value, dict):
        raise NeutralityError(f"{key} must be an object")
    return value


def _positive_int(document: dict[str, Any], key: str, default: int) -> int:
    value = document.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise NeutralityError(f"{key} must be a positive integer")
    return value
