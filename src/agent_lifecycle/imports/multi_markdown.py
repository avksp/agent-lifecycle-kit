"""Deterministic Markdown file and folder import helpers."""

from __future__ import annotations

from itertools import islice
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.authority_io import open_authority_read
from agent_lifecycle.imports.planning import (
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_TARGET_TOKENS,
    import_planning_text,
    require_no_import_secrets,
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
    if source_path.is_symlink():
        raise LifecycleError("authority-input-not-regular", "import source must not be a symlink")
    if source_path.is_file():
        return [source_path], source_path.parent, "file"
    if source_path.is_dir():
        candidates = (path for path in source_path.rglob("*.md") if path.is_file() or path.is_symlink())
        return list(islice(candidates, max_files + 1)), source_path, "directory"
    return [], source_path.parent, "missing"


def _decode_markdown(data: bytes, label: str, blockers: list[dict[str, Any]]) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        blockers.append({"code": "markdown-collection-decode-failed", "sourceLabel": label})
        return ""
