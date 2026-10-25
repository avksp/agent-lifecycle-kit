"""Deterministic Markdown file and folder import helpers."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable
from fnmatch import fnmatch
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.authority_io import hold_authority_directory, open_authority_read
from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_text,
    require_no_import_secrets,
)

MARKDOWN_COLLECTION_SCHEMA = "agent-markdown-source-collection.v1"
DEFAULT_MAX_MARKDOWN_FILES = 32
_MAX_DISCOVERY_ENTRIES = 4096
_MAX_DISCOVERY_DIRECTORIES = 256
_MAX_DISCOVERY_DEPTH = 32
_DISCOVERY_SECONDS = 5.0
_T = TypeVar("_T")


def import_markdown_collection(
    source_path: Path,
    *,
    package_id: str = "markdown-import",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_files: int = DEFAULT_MAX_MARKDOWN_FILES,
    dialect_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import one Markdown file or a directory of Markdown files as draft input."""

    collection = collect_markdown_collection(source_path, max_input_bytes=max_input_bytes, max_files=max_files)
    text = collection.pop("_combinedText", "")
    result = import_planning_text(
        text,
        source_label=collection["sourceLabel"],
        package_id=package_id,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        dialect_profile=dialect_profile,
    )
    result["markdownCollection"] = collection
    if collection["blockers"]:
        result["blockers"].extend(collection["blockers"])
        result["status"] = "FAIL"
        result["candidateLifecycleStatus"] = "BLOCKED"
        result["candidatePlan"] = None
    result["importDigest"] = canonical_digest({key: value for key, value in result.items() if key != "importDigest"})
    return result


def collect_markdown_collection(
    source_path: Path,
    *,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    max_files: int = DEFAULT_MAX_MARKDOWN_FILES,
) -> dict[str, Any]:
    for field, cap in (("maxFiles", max_files), ("maxInputBytes", max_input_bytes)):
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise LifecycleError("invalid-resource-cap", f"{field} must be a positive integer", {"field": field})
    require_no_import_secrets(source_path.name)
    files, root, source_kind = _collection_files(source_path, max_files=max_files)
    blockers: list[dict[str, Any]] = []
    if not files:
        blockers.append({"code": "markdown-collection-empty", "sourceLabel": source_path.name})
    if len(files) > max_files:
        blockers.append({"code": "markdown-collection-file-cap-exceeded", "fileCount": len(files), "cap": max_files})
        files = []

    entries: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    total_input_bytes = 0
    for path in sorted(files):
        rel = path.relative_to(root).as_posix() if source_kind == "directory" else path.name
        require_no_import_secrets(rel)
        with open_authority_read(path) as handle:
            data = handle.read(max_input_bytes - total_input_bytes + 1)
        total_input_bytes += len(data)
        if total_input_bytes > max_input_bytes:
            blockers.append(
                {
                    "code": "markdown-collection-input-cap-exceeded",
                    "inputBytes": total_input_bytes,
                    "cap": max_input_bytes,
                }
            )
            break
        entries.append({"label": rel, "digest": sha256_hex(data), "inputBytes": len(data)})
        text = _decode_markdown(data, rel, blockers)
        require_no_import_secrets(text)
        combined_parts.append(f"# Source: {rel}\n\n{text.strip()}\n")
    combined_text = "" if blockers else "\n".join(combined_parts).strip()

    body = {
        "schemaVersion": MARKDOWN_COLLECTION_SCHEMA,
        "sourceKind": source_kind,
        "sourceLabel": source_path.name,
        "ordering": "lexical-relative-posix",
        "fileCount": len(entries),
        "totalInputBytes": total_input_bytes,
        "resourceCaps": {"maxInputBytes": max_input_bytes, "maxFiles": max_files},
        "files": entries,
        "blockers": blockers,
    }
    body["collectionDigest"] = canonical_digest(body)
    body["_combinedText"] = combined_text
    return body


def _collection_files(source_path: Path, *, max_files: int) -> tuple[list[Path], Path, str]:
    discovery = _MarkdownDiscovery(max_files)
    try:
        try:
            info = discovery.operation(source_path.lstat)
        except FileNotFoundError:
            return [], source_path.parent, "missing"
        _require_unlinked(info)
        if stat.S_ISREG(info.st_mode):
            return [source_path], source_path.parent, "file"
        if stat.S_ISDIR(info.st_mode):
            return discovery.collect(source_path, info), source_path, "directory"
        return [], source_path.parent, "missing"
    except OSError:
        raise LifecycleError(
            "markdown-collection-discovery-unavailable", "Markdown discovery metadata or directory is unavailable"
        ) from None


def _require_unlinked(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise LifecycleError(
            "authority-input-not-regular", "Markdown discovery must not traverse links or reparse points"
        )


class _MarkdownDiscovery:
    """Count all directory entries, with cooperative checks around filesystem I/O."""

    def __init__(self, max_files: int) -> None:
        self.max_files = max_files
        self.deadline = time.monotonic() + _DISCOVERY_SECONDS
        self.entries = 0
        self.directories = 1  # The source directory is depth zero and counts toward the cap.
        self.files: list[Path] = []
        self.pending: list[tuple[Path, int, os.stat_result]] = []

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            self.exceeded("seconds", _DISCOVERY_SECONDS)

    def exceeded(self, limit: str, cap: int | float) -> None:
        raise LifecycleError(
            "markdown-collection-discovery-limit-exceeded",
            "Markdown discovery exceeded its cooperative resource limit",
            {"limit": limit, "cap": cap},
        )

    def operation(self, action: Callable[[], _T]) -> _T:
        self.check()
        try:
            return action()
        finally:
            self.check()

    def collect(self, root: Path, info: os.stat_result) -> list[Path]:
        self.pending.append((root, 0, info))
        while self.pending and len(self.files) <= self.max_files:
            self.scan(*self.pending.pop())
        return self.files

    def scan(self, path: Path, depth: int, expected: os.stat_result) -> None:
        self.check()
        # Reopen one guarded directory at a time: the queue retains identities,
        # never thousands of ancestor descriptors. The guard validates bindings
        # on exit; fd-based scandir stays attached to the held POSIX directory.
        with hold_authority_directory(path) as directory:
            self.check()
            if directory.fd is None:
                actual = self.operation(directory.path.lstat)
            else:
                descriptor = directory.fd
                actual = self.operation(lambda: os.fstat(descriptor))
            expected_identity = (expected.st_dev, expected.st_ino, expected.st_mode)
            actual_identity = (actual.st_dev, actual.st_ino, actual.st_mode)
            if expected_identity != actual_identity:
                raise LifecycleError("authority-input-changed", "authority input changed during I/O")
            self.check()
            with os.scandir(directory.fd if directory.fd is not None else directory.path) as entries:
                self.check()
                while len(self.files) <= self.max_files:
                    try:
                        entry = self.operation(lambda: next(entries))
                    except StopIteration:
                        break
                    if self.entries >= _MAX_DISCOVERY_ENTRIES:
                        # A sentinel detects overflow; do not inspect its metadata.
                        self.exceeded("entries", _MAX_DISCOVERY_ENTRIES)
                    self.entries += 1
                    # DirEntry.stat caches metadata and has zero identity fields
                    # on Windows 3.11. Use the held directory's fresh no-follow stat.
                    info = self.operation(partial(directory.stat_child, entry.name))
                    self.visit(path / entry.name, depth, info)
                self.check()
            self.check()
        self.check()

    def visit(self, path: Path, depth: int, info: os.stat_result) -> None:
        _require_unlinked(info)
        if stat.S_ISDIR(info.st_mode):
            if depth >= _MAX_DISCOVERY_DEPTH:
                self.exceeded("depth", _MAX_DISCOVERY_DEPTH)
            if self.directories >= _MAX_DISCOVERY_DIRECTORIES:
                self.exceeded("directories", _MAX_DISCOVERY_DIRECTORIES)
            self.directories += 1
            self.pending.append((path, depth + 1, info))
        elif fnmatch(path.name, "*.md"):
            if not stat.S_ISREG(info.st_mode):
                raise LifecycleError("authority-input-not-regular", "Markdown input must be a regular file")
            self.files.append(path)


def _decode_markdown(data: bytes, label: str, blockers: list[dict[str, Any]]) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append({"code": "markdown-collection-decode-failed", "sourceLabel": label})
        return ""
