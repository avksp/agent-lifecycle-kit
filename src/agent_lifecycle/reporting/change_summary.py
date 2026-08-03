"""Git-style change summary receipts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    normalize_repo_path,
)

CHANGE_SUMMARY_SCHEMA = "agent-change-summary-receipt.v1"


def build_change_summary_receipt(
    *,
    project_root: Path,
    base: str | None = None,
    head: str | None = None,
    staged: bool = False,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a read-only summary using Git's diff counters."""

    if staged and (base or head):
        raise LifecycleError(
            "change-summary-range-conflict",
            "--staged cannot be combined with --base or --head",
        )
    if head and not base:
        raise LifecycleError("change-summary-base-required", "--head requires --base")
    normalized_paths = [_normalize_filter(item) for item in paths or []]
    root = project_root.resolve()
    numstat = _run_git(
        root,
        _diff_args("--numstat", base=base, head=head, staged=staged, paths=normalized_paths),
    )
    name_status = _run_git(
        root,
        _diff_args("--name-status", base=base, head=head, staged=staged, paths=normalized_paths),
    )
    counters = _parse_numstat(numstat)
    counters.update(_parse_name_status(name_status))
    scope = {
        "base": base or ("<index>" if staged else "HEAD"),
        "head": head or ("<index>" if staged else "<worktree>"),
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
    args = ["diff", "--no-ext-diff", "--find-renames", mode]
    if staged:
        args.append("--cached")
    elif base and head:
        args.append(f"{base}..{head}")
    elif base:
        args.append(base)
    else:
        args.append("HEAD")
    return [*args, "--", *paths]


def _run_git(root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git diff failed"
        raise LifecycleError("change-summary-git-failed", detail, {"args": ["git", *args]})
    return completed.stdout


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
