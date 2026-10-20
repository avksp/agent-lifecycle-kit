"""Git-style change summary receipts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.changesets.git import resolve_revision
from agent_lifecycle.changesets.git_io import run_bounded_command
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.display_identity import MAX_DISPLAY_IDENTITIES, digest_display_prefixes
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.process_redaction import redact_process_text
from agent_lifecycle.contracts.redaction import redact_value

CHANGE_SUMMARY_SCHEMA = "agent-change-summary-receipt.v1"


def build_digest_display_view(payload: dict[str, Any], *, minimum_length: int = 12) -> dict[str, Any]:
    """Render a separate read-only view while retaining the complete payload."""
    digests: list[str] = []
    pending: list[tuple[Any, int]] = [(payload, 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 100_000 or len(digests) > MAX_DISPLAY_IDENTITIES:
            raise LifecycleError("display-identity-limit", "Display payload exceeds its traversal limit")
        if isinstance(value, dict):
            if len(pending) + len(value) + visited > 100_000:
                raise LifecycleError("display-identity-limit", "Display payload exceeds its traversal limit")
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            if len(pending) + len(value) + visited > 100_000:
                raise LifecycleError("display-identity-limit", "Display payload exceeds its traversal limit")
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            digests.append(value)
    prefixes = digest_display_prefixes(digests, minimum_length=minimum_length)
    return {
        "schemaVersion": "agent-digest-display-view.v1",
        "data": deepcopy(payload),
        "displayIdentities": [{"fullDigest": full, "displayPrefix": short} for full, short in prefixes.items()],
        "readOnly": True,
        "stateWritten": False,
        "authorityClaimed": False,
        "prefixesUsableAsAuthority": False,
    }


def build_change_summary_receipt(
    *,
    project_root: Path,
    base: str | None = None,
    head: str | None = None,
    staged: bool = False,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a read-only summary using Git's diff counters."""

    if staged and (base is not None or head is not None):
        raise LifecycleError(
            "change-summary-range-conflict",
            "--staged cannot be combined with --base or --head",
        )
    if head is not None and base is None:
        raise LifecycleError("change-summary-base-required", "--head requires --base")
    normalized_paths = [_normalize_filter(item) for item in paths or []]
    root = project_root.resolve()
    resolved_base = _resolve_revision(root, base, label="base") if base is not None else None
    resolved_head = _resolve_revision(root, head, label="head") if head is not None else None
    numstat = _run_git(
        root,
        _diff_args("--numstat", base=resolved_base, head=resolved_head, staged=staged, paths=normalized_paths),
    )
    name_status = _run_git(
        root,
        _diff_args("--name-status", base=resolved_base, head=resolved_head, staged=staged, paths=normalized_paths),
    )
    counters = _parse_numstat(numstat)
    counters.update(_parse_name_status(name_status))
    scope = {
        "base": resolved_base or ("<index>" if staged else "HEAD"),
        "head": resolved_head or ("<index>" if staged else "<worktree>"),
        "staged": staged,
        "paths": normalized_paths,
    }
    body = {
        "schemaVersion": CHANGE_SUMMARY_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "projectRoot": "<checkout>",
        "scope": scope,
        "filesChanged": counters["filesChanged"],
        "insertions": counters["insertions"],
        "deletions": counters["deletions"],
        "modified": counters["modified"],
        "added": counters["added"],
        "deleted": counters["deleted"],
        "line": format_change_summary_line(counters),
        "productionPromotionClaimed": False,
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def format_change_summary_line(summary: dict[str, int]) -> str:
    return (
        f"{summary['filesChanged']} files changed · {summary['insertions']} insertions · "
        f"{summary['deletions']} deletions · {summary['modified']} modified · "
        f"{summary['added']} added · {summary['deleted']} deleted"
    )


def _diff_args(
    mode: str,
    *,
    base: str | None,
    head: str | None,
    staged: bool,
    paths: list[str],
) -> list[str]:
    args = ["diff", "--no-ext-diff", "--no-textconv", "--find-renames", mode]
    if staged:
        args.append("--cached")
    elif base is not None and head is not None:
        args.extend(["--end-of-options", f"{base}..{head}"])
    elif base is not None:
        args.extend(["--end-of-options", base])
    else:
        args.append("HEAD")
    return [*args, "--", *paths]


def _run_git(root: Path, args: list[str]) -> str:
    try:
        completed = run_bounded_command(
            ["git", *args],
            cwd=root,
            timeout_seconds=30,
            max_stdout_bytes=16 * 1024 * 1024,
        )
    except (OSError, LifecycleError) as exc:
        raise LifecycleError("change-summary-git-failed", "Git summary transport failed closed") from exc
    stdout = completed.stdout.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        safe_stderr, stderr_redacted = redact_process_text(completed.stderr.decode("utf-8", errors="replace"))
        safe_stdout, stdout_redacted = redact_process_text(stdout)
        detail = (safe_stderr.strip() or safe_stdout.strip() or "git diff failed")[-2000:]
        raise LifecycleError(
            "change-summary-git-failed",
            detail,
            {
                "args": redact_value(["git", *args])[0],
                "stdoutRedacted": stdout_redacted,
                "stderrRedacted": stderr_redacted,
            },
        )
    return stdout


def _resolve_revision(root: Path, revision: str, *, label: str) -> str:
    return resolve_revision(root, revision, label=label)


def _parse_numstat(output: str) -> dict[str, int]:
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files_changed += 1
        insertions += _git_int(parts[0])
        deletions += _git_int(parts[1])
    return {"filesChanged": files_changed, "insertions": insertions, "deletions": deletions}


def _parse_name_status(output: str) -> dict[str, int]:
    modified = 0
    added = 0
    deleted = 0
    for line in output.splitlines():
        status = line.split("\t", 1)[0]
        if not status:
            continue
        prefix = status[0]
        if prefix == "A":
            added += 1
        elif prefix == "D":
            deleted += 1
        elif prefix in {"M", "R", "C", "T"}:
            modified += 1
    return {"modified": modified, "added": added, "deleted": deleted}


def _git_int(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _normalize_filter(path: str) -> str:
    return normalize_repo_path(path)
