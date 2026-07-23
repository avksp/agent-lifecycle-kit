"""Repository neutrality scanner."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Pattern

from .canonical import canonical_bytes, sha256_hex
from .errors import NeutralityError
from .paths import stable_read_bytes, validate_output_paths, validate_repository_relative_path
from .policy import NeutralityPolicy


@dataclass(frozen=True)
class NeutralityFinding:
    source: str
    ruleId: str
    category: str

    def to_json(self) -> dict[str, str]:
        return {"source": self.source, "ruleId": self.ruleId, "category": self.category}


@dataclass
class NeutralityReport:
    scope: str
    findings: list[NeutralityFinding] = field(default_factory=list)
    skipped_inputs: int = 0
    opaque_inputs: int = 0
    read_races: int = 0
    incomplete_scans: int = 0
    unsupported_archives: int = 0
    archive_limit_breaches: int = 0
    occupied_output_conflicts: int = 0
    path_alias_conflicts: int = 0
    scanned_files: int = 0
    scanned_git_objects: int = 0
    working_tree_digest: str = "0" * 64
    git_object_set_digest: str = "0" * 64

    def to_json(self, operation: dict[str, Any]) -> dict[str, Any]:
        counters = {
            "findings": len(self.findings),
            "skippedInputs": self.skipped_inputs,
            "opaqueInputs": self.opaque_inputs,
            "readRaces": self.read_races,
            "incompleteScans": self.incomplete_scans,
            "unsupportedArchives": self.unsupported_archives,
            "archiveLimitBreaches": self.archive_limit_breaches,
            "occupiedOutputConflicts": self.occupied_output_conflicts,
            "pathAliasConflicts": self.path_alias_conflicts,
        }
        subject = {
            "scope": self.scope,
            "counters": counters,
            "workingTreeDigest": self.working_tree_digest,
            "gitObjectSetDigest": self.git_object_set_digest,
            "findingIds": [finding.ruleId for finding in self.findings],
        }
        return {
            "schemaVersion": "agent-neutrality-report.v1",
            "operation": operation,
            "scope": self.scope,
            "counters": counters,
            "scanned": {
                "files": self.scanned_files,
                "gitObjects": self.scanned_git_objects,
            },
            "digests": {
                "workingTreeDigest": self.working_tree_digest,
                "gitObjectSetDigest": self.git_object_set_digest,
                "subjectDigest": sha256_hex(canonical_bytes(subject)),
            },
            "findings": [finding.to_json() for finding in self.findings],
        }


@dataclass
class ArchiveScanBudget:
    archives: int = 0
    entries: int = 0
    expanded_bytes: int = 0


def scan_repository(
    *,
    workspace_root: Path,
    policy: NeutralityPolicy,
    deny_literals: Iterable[str],
    deny_regexes: Iterable[str],
    scope: str,
    output_paths: list[Path],
) -> NeutralityReport:
    report = NeutralityReport(scope=scope)
    try:
        normalized_outputs = validate_output_paths(output_paths)
    except NeutralityError:
        report.path_alias_conflicts += 1
        normalized_outputs = []
    for output_path in output_paths:
        if (workspace_root / output_path).exists():
            report.occupied_output_conflicts += 1

    literal_rules = tuple(deny_literals) + policy.deny_literals
    regex_rules = tuple(re.compile(value) for value in deny_regexes) + policy.deny_regexes
    archive_budget = ArchiveScanBudget()

    worktree_entries: list[dict[str, Any]] = []
    for rel_path in _walk_repository_files(workspace_root, policy):
        path = workspace_root / rel_path
        try:
            validate_repository_relative_path(rel_path)
            data = stable_read_bytes(path, max_bytes=policy.max_file_bytes)
        except NeutralityError:
            report.read_races += 1
            continue
        report.scanned_files += 1
        report.findings.extend(_match_data(rel_path, data, literal_rules, regex_rules))
        _scan_archive(rel_path, data, policy, report, literal_rules, regex_rules, archive_budget, depth=1)
        worktree_entries.append({"path": rel_path, "sha256": sha256_hex(data), "bytes": len(data)})

    git_entries: list[dict[str, Any]] = []
    if scope == "full-repository" and (workspace_root / ".git").exists():
        for object_id, data in _git_objects(workspace_root, policy):
            report.scanned_git_objects += 1
            report.findings.extend(_match_data(f"git:{object_id}", data, literal_rules, regex_rules))
            git_entries.append({"object": object_id, "sha256": sha256_hex(data), "bytes": len(data)})

    report.working_tree_digest = sha256_hex(canonical_bytes({"files": worktree_entries, "outputs": normalized_outputs}))
    report.git_object_set_digest = sha256_hex(canonical_bytes({"objects": git_entries}))
    return report


def _walk_repository_files(workspace_root: Path, policy: NeutralityPolicy) -> Iterable[str]:
    for root, dirnames, filenames in os.walk(workspace_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(workspace_root).as_posix()
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _excluded(_join_rel(rel_root, dirname), policy.path_excludes)
        ]
        for filename in filenames:
            rel_path = _join_rel(rel_root, filename)
            if _excluded(rel_path, policy.path_excludes):
                continue
            mode = os.lstat(root_path / filename).st_mode
            if stat.S_ISREG(mode):
                yield rel_path


def _join_rel(root: str, name: str) -> str:
    return name if root == "." else f"{root}/{name}"


def _excluded(path: str, excludes: tuple[Pattern[str], ...]) -> bool:
    return any(pattern.search(path) for pattern in excludes)


def _match_data(
    source: str,
    data: bytes,
    literal_rules: tuple[str, ...],
    regex_rules: tuple[Pattern[str], ...],
) -> list[NeutralityFinding]:
    findings: list[NeutralityFinding] = []
    text = data.decode("utf-8", errors="ignore")
    for index, literal in enumerate(literal_rules):
        if literal and literal in text:
            findings.append(NeutralityFinding(source=source, ruleId=f"literal:{index}", category="deny-literal"))
    for index, pattern in enumerate(regex_rules):
        if pattern.search(text):
            findings.append(NeutralityFinding(source=source, ruleId=f"regex:{index}", category="deny-regex"))
    return findings


def _scan_archive(
    source: str,
    data: bytes,
    policy: NeutralityPolicy,
    report: NeutralityReport,
    literal_rules: tuple[str, ...],
    regex_rules: tuple[Pattern[str], ...],
    archive_budget: ArchiveScanBudget,
    *,
    depth: int,
) -> None:
    if not data.startswith(b"PK\x03\x04"):
        return
    import io

    if depth > policy.max_archive_nesting_depth:
        report.archive_limit_breaches += 1
        return
    archive_budget.archives += 1
    if archive_budget.archives > policy.max_archives_per_subject:
        report.archive_limit_breaches += 1
        return
    if len(data) > policy.max_compressed_bytes_per_archive:
        report.archive_limit_breaches += 1
        return

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names: set[str] = set()
            infos = archive.infolist()
            if len(infos) > policy.max_archive_entries:
                report.archive_limit_breaches += 1
                return
            expanded_bytes = sum(info.file_size for info in infos)
            compressed_bytes = sum(info.compress_size for info in infos)
            if expanded_bytes > policy.max_expanded_bytes_per_archive:
                report.archive_limit_breaches += 1
                return
            if _ratio_exceeds(expanded_bytes, compressed_bytes, policy.max_compression_ratio):
                report.archive_limit_breaches += 1
                return
            if archive_budget.entries + len(infos) > policy.max_entries_per_subject:
                report.archive_limit_breaches += 1
                return
            if archive_budget.expanded_bytes + expanded_bytes > policy.max_expanded_bytes_per_subject:
                report.archive_limit_breaches += 1
                return
            archive_budget.entries += len(infos)
            archive_budget.expanded_bytes += expanded_bytes
            for info in infos:
                key = info.filename.casefold()
                if key in names or info.filename.startswith("/") or ".." in Path(info.filename).parts:
                    report.archive_limit_breaches += 1
                    return
                names.add(key)
                if info.file_size > policy.max_expanded_entry_bytes:
                    report.archive_limit_breaches += 1
                    return
                if _ratio_exceeds(info.file_size, info.compress_size, policy.max_compression_ratio):
                    report.archive_limit_breaches += 1
                    return
                if info.is_dir():
                    continue
                content = archive.read(info, pwd=None)
                report.findings.extend(_match_data(f"{source}!{info.filename}", content, literal_rules, regex_rules))
                _scan_archive(
                    f"{source}!{info.filename}",
                    content,
                    policy,
                    report,
                    literal_rules,
                    regex_rules,
                    archive_budget,
                    depth=depth + 1,
                )
    except (zipfile.BadZipFile, RuntimeError):
        report.unsupported_archives += 1


def _ratio_exceeds(expanded_bytes: int, compressed_bytes: int, max_ratio: int) -> bool:
    if expanded_bytes <= 0:
        return False
    if compressed_bytes <= 0:
        return True
    return expanded_bytes > compressed_bytes * max_ratio


def _git_objects(workspace_root: Path, policy: NeutralityPolicy) -> Iterable[tuple[str, bytes]]:
    try:
        objects = subprocess.run(
            ["git", "rev-list", "--objects", "--all", "--reflog"],
            cwd=workspace_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return
    seen: set[str] = set()
    for line in objects:
        object_id = line.split(" ", 1)[0]
        if object_id in seen:
            continue
        seen.add(object_id)
        try:
            size = int(
                subprocess.run(
                    ["git", "cat-file", "-s", object_id],
                    cwd=workspace_root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).stdout.strip()
            )
            if size > policy.max_object_bytes:
                continue
            data = subprocess.run(
                ["git", "cat-file", "-p", object_id],
                cwd=workspace_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
        except (OSError, subprocess.CalledProcessError, ValueError):
            continue
        yield object_id, data
