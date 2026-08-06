"""Deterministic Markdown file and folder import helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_text,
)

MARKDOWN_COLLECTION_SCHEMA = "agent-markdown-source-collection.v1"
DEFAULT_MAX_MARKDOWN_FILES = 32


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
    if max_files <= 0:
        raise LifecycleError("invalid-resource-cap", "maxFiles must be a positive integer", {"field": "maxFiles"})
    if source_path.is_file():
        files = [source_path]
        root = source_path.parent
        source_kind = "file"
    elif source_path.is_dir():
        root = source_path
        files = sorted(path for path in source_path.rglob("*.md") if path.is_file())
        source_kind = "directory"
    else:
        files = []
        root = source_path.parent
        source_kind = "missing"
    blockers: list[dict[str, Any]] = []
    if not files:
        blockers.append({"code": "markdown-collection-empty", "sourceLabel": source_path.name})
    if len(files) > max_files:
        blockers.append({"code": "markdown-collection-file-cap-exceeded", "fileCount": len(files), "cap": max_files})
        files = files[:max_files]

    entries: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    total_input_bytes = 0
    for path in files:
        rel = path.relative_to(root).as_posix() if source_kind == "directory" else path.name
        data = path.read_bytes()
        total_input_bytes += len(data)
        entries.append({"label": rel, "digest": sha256_hex(data), "inputBytes": len(data)})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            blockers.append({"code": "markdown-collection-decode-failed", "sourceLabel": rel})
            text = ""
        combined_parts.append(f"# Source: {rel}\n\n{text.strip()}\n")

    if total_input_bytes > max_input_bytes:
        blockers.append({"code": "markdown-collection-input-cap-exceeded", "inputBytes": total_input_bytes, "cap": max_input_bytes})
        combined_text = ""
    else:
        combined_text = "\n".join(combined_parts).strip()

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
