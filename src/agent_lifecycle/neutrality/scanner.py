"""Repository neutrality scanner."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Any

from .canonical import canonical_bytes, sha256_hex
from .errors import NeutralityError
from .git_objects import iter_git_objects
from .matching import LiteralMatcher, build_literal_matcher, validate_rule_limits
from .paths import (
    StableReadRaceError,
    resolve_repository_relative_root,
    stable_read_bytes_with_retry,
    validate_output_paths,
    validate_repository_relative_path,
)
from .policy import NeutralityPolicy

TRACKED_RELEASE_SCOPE = "tracked-release"
LEGACY_NEUTRALITY_SCOPES = ("current-tree-complete", "full-repository")
NEUTRALITY_SCOPE_CHOICES = (TRACKED_RELEASE_SCOPE, *LEGACY_NEUTRALITY_SCOPES)
_REGULAR_GIT_MODES = {"100644", "100755"}
_SYMLINK_GIT_MODE = "120000"
_GITLINK_MODE = "160000"
_GIT_COMMAND_TIMEOUT_SECONDS = 120


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
    recovered_read_races: int = 0
    incomplete_scans: int = 0
    unsupported_archives: int = 0
    archive_limit_breaches: int = 0
    occupied_output_conflicts: int = 0
    path_alias_conflicts: int = 0
    scanned_files: int = 0
    scanned_git_objects: int = 0
    scanned_tracked_files: int = 0
    scanned_gitlinks: int = 0
    scanned_local_artifacts: int = 0
    working_tree_digest: str = "0" * 64
    git_object_set_digest: str = "0" * 64
    tracked_entry_digest: str = "0" * 64
    local_artifact_digest: str = "0" * 64
    local_artifact_roots_digest: str = "0" * 64
    source_revision: str | None = None
    source_class: str = "working-tree"
    include_local_artifacts: bool = False
    local_artifact_roots: tuple[str, ...] = ()

    def to_json(self, operation: dict[str, Any]) -> dict[str, Any]:
        counters = {
            "findings": len(self.findings),
            "skippedInputs": self.skipped_inputs,
            "opaqueInputs": self.opaque_inputs,
            "readRaces": self.read_races,
            "recoveredReadRaces": self.recovered_read_races,
            "incompleteScans": self.incomplete_scans,
            "unsupportedArchives": self.unsupported_archives,
            "archiveLimitBreaches": self.archive_limit_breaches,
            "occupiedOutputConflicts": self.occupied_output_conflicts,
            "pathAliasConflicts": self.path_alias_conflicts,
        }
        scope_binding = {
            "scope": self.scope,
            "sourceClass": self.source_class,
            "sourceRevision": self.source_revision,
            "trackedEntryDigest": self.tracked_entry_digest,
            "deprecatedScope": self.scope in LEGACY_NEUTRALITY_SCOPES,
            "includeLocalArtifacts": self.include_local_artifacts,
            "localArtifactRoots": list(self.local_artifact_roots),
            "localArtifactRootsDigest": self.local_artifact_roots_digest,
        }
        scanned = {
            "files": self.scanned_files,
            "gitObjects": self.scanned_git_objects,
            "trackedFiles": self.scanned_tracked_files,
            "gitlinks": self.scanned_gitlinks,
            "localArtifacts": self.scanned_local_artifacts,
        }
        digests = {
            "workingTreeDigest": self.working_tree_digest,
            "gitObjectSetDigest": self.git_object_set_digest,
            "trackedEntryDigest": self.tracked_entry_digest,
            "localArtifactDigest": self.local_artifact_digest,
            "localArtifactRootsDigest": self.local_artifact_roots_digest,
        }
        subject = {
            "scopeBinding": scope_binding,
            "counters": counters,
            "scanned": scanned,
            "digests": digests,
            "findings": [finding.to_json() for finding in self.findings],
        }
        digests["subjectDigest"] = sha256_hex(canonical_bytes(subject))
        return {
            "schemaVersion": "agent-neutrality-report.v1",
            "operation": operation,
            "scope": self.scope,
            "scopeBinding": scope_binding,
            "counters": counters,
            "scanned": scanned,
            "digests": digests,
            "findings": [finding.to_json() for finding in self.findings],
        }


@dataclass
class ArchiveScanBudget:
    archives: int = 0
    entries: int = 0
    expanded_bytes: int = 0


@dataclass
class LocalArtifactScanBudget:
    files: int = 0
    bytes: int = 0
    breached: bool = False


def scan_repository(
    *,
    workspace_root: Path,
    policy: NeutralityPolicy,
    deny_literals: Iterable[str],
    deny_regexes: Iterable[str],
    scope: str,
    output_paths: list[Path],
    include_local_artifacts: bool = False,
) -> NeutralityReport:
    if scope not in NEUTRALITY_SCOPE_CHOICES:
        raise NeutralityError(f"unsupported neutrality scope: {scope}")
    if include_local_artifacts and scope != TRACKED_RELEASE_SCOPE:
        raise NeutralityError("local artifacts require tracked-release scope")
    if include_local_artifacts and not policy.local_artifact_roots:
        raise NeutralityError("local artifacts require declared localArtifactRoots")
    report = NeutralityReport(scope=scope, include_local_artifacts=include_local_artifacts)
    try:
        normalized_outputs = validate_output_paths(output_paths)
    except NeutralityError:
        report.path_alias_conflicts += 1
        normalized_outputs = []
    for output_path in output_paths:
        if (workspace_root / output_path).exists():
            report.occupied_output_conflicts += 1

    literal_values = tuple(deny_literals) + policy.deny_literals
    regex_values = tuple(deny_regexes)
    validate_rule_limits(literal_values, regex_values + tuple(policy.raw.get("denyRegexes", [])))
    literal_rules = build_literal_matcher(literal_values)
    regex_rules = tuple(re.compile(value) for value in regex_values) + policy.deny_regexes
    archive_budget = ArchiveScanBudget()

    worktree_entries: list[dict[str, Any]] = []
    tracked_paths: set[str] = set()
    if scope == TRACKED_RELEASE_SCOPE:
        report.source_class = "git-index"
        tracked_paths = _scan_tracked_release(
            workspace_root,
            policy,
            report,
            literal_rules,
            regex_rules,
            archive_budget,
            worktree_entries,
        )
    else:
        report.source_class = "working-tree-plus-git-objects" if scope == "full-repository" else "working-tree"
        report.source_revision = _git_head_revision(workspace_root)
        for rel_path in _walk_repository_files(workspace_root, policy):
            _scan_regular_path(
                workspace_root,
                rel_path,
                policy,
                report,
                literal_rules,
                regex_rules,
                archive_budget,
                worktree_entries,
                source_class="legacy-worktree",
            )

    local_entries: list[dict[str, Any]] = []
    if include_local_artifacts:
        report.local_artifact_roots = policy.local_artifact_roots
        report.local_artifact_roots_digest = sha256_hex(canonical_bytes({"roots": list(policy.local_artifact_roots)}))
        output_set = set(normalized_outputs)
        local_budget = LocalArtifactScanBudget()
        for root_value in policy.local_artifact_roots:
            try:
                root = resolve_repository_relative_root(workspace_root, root_value, label="local artifact root")
                for rel_path in _walk_local_artifacts(workspace_root, root):
                    if rel_path in tracked_paths or rel_path in output_set or _excluded(rel_path, policy.path_excludes):
                        continue
                    _scan_local_artifact(
                        workspace_root,
                        rel_path,
                        policy,
                        report,
                        literal_rules,
                        regex_rules,
                        archive_budget,
                        local_entries,
                        local_budget,
                    )
                    if local_budget.breached:
                        break
            except (OSError, NeutralityError):
                report.skipped_inputs += 1
                report.incomplete_scans += 1
            if local_budget.breached:
                break

    git_entries: list[dict[str, Any]] = []
    if scope == "full-repository" and (workspace_root / ".git").exists():
        try:
            for object_id, data in iter_git_objects(workspace_root, policy):
                report.scanned_git_objects += 1
                report.findings.extend(_match_data(f"git:{object_id}", data, literal_rules, regex_rules))
                git_entries.append({"object": object_id, "sha256": sha256_hex(data), "bytes": len(data)})
        except NeutralityError:
            report.skipped_inputs += 1
            report.incomplete_scans += 1

    report.working_tree_digest = sha256_hex(canonical_bytes({"files": worktree_entries, "outputs": normalized_outputs}))
    report.git_object_set_digest = sha256_hex(canonical_bytes({"objects": git_entries}))
    report.local_artifact_digest = sha256_hex(canonical_bytes({"files": local_entries}))
    return report


def _scan_tracked_release(
    workspace_root: Path,
    policy: NeutralityPolicy,
    report: NeutralityReport,
    literal_rules: LiteralMatcher,
    regex_rules: tuple[Pattern[str], ...],
    archive_budget: ArchiveScanBudget,
    content_entries: list[dict[str, Any]],
) -> set[str]:
    report.source_revision = _git_head_revision(workspace_root)
    if report.source_revision is None:
        report.skipped_inputs += 1
        report.incomplete_scans += 1
    try:
        entries = _git_tracked_entries(workspace_root)
    except NeutralityError:
        report.skipped_inputs += 1
        report.incomplete_scans += 1
        entries = []
    report.tracked_entry_digest = sha256_hex(canonical_bytes({"entries": entries}))
    for entry in entries:
        rel_path = entry["path"]
        mode = entry["mode"]
        if entry["stage"] != 0:
            report.skipped_inputs += 1
            report.incomplete_scans += 1
            continue
        if mode in _REGULAR_GIT_MODES:
            before = len(content_entries)
            _scan_regular_path(
                workspace_root,
                rel_path,
                policy,
                report,
                literal_rules,
                regex_rules,
                archive_budget,
                content_entries,
                source_class="tracked-file",
            )
            if len(content_entries) > before:
                report.scanned_tracked_files += 1
        elif mode == _SYMLINK_GIT_MODE:
            try:
                data, recovered = _stable_tracked_symlink_payload(
                    workspace_root / rel_path,
                    max_bytes=policy.max_file_bytes,
                )
                if recovered:
                    report.recovered_read_races += 1
                _record_scanned_data(
                    rel_path,
                    data,
                    report,
                    policy,
                    literal_rules,
                    regex_rules,
                    archive_budget,
                    content_entries,
                    source_class="tracked-symlink",
                )
                report.scanned_tracked_files += 1
            except StableReadRaceError:
                report.read_races += 1
                report.incomplete_scans += 1
            except (OSError, NeutralityError):
                report.skipped_inputs += 1
                report.incomplete_scans += 1
        elif mode == _GITLINK_MODE:
            report.scanned_gitlinks += 1
            content_entries.append(
                {"path": rel_path, "sourceClass": "gitlink", "gitMode": mode, "objectId": entry["objectId"]}
            )
        else:
            report.skipped_inputs += 1
            report.incomplete_scans += 1
    return {entry["path"] for entry in entries}


def _scan_regular_path(
    workspace_root: Path,
    rel_path: str,
    policy: NeutralityPolicy,
    report: NeutralityReport,
    literal_rules: LiteralMatcher,
    regex_rules: tuple[Pattern[str], ...],
    archive_budget: ArchiveScanBudget,
    entries: list[dict[str, Any]],
    *,
    source_class: str,
) -> None:
    try:
        validate_repository_relative_path(rel_path)
        result = stable_read_bytes_with_retry(workspace_root / rel_path, max_bytes=policy.max_file_bytes)
        if result.recovered_race:
            report.recovered_read_races += 1
        _record_scanned_data(
            rel_path,
            result.data,
            report,
            policy,
            literal_rules,
            regex_rules,
            archive_budget,
            entries,
            source_class=source_class,
        )
    except StableReadRaceError:
        report.read_races += 1
        report.incomplete_scans += 1
    except (OSError, NeutralityError):
        report.skipped_inputs += 1
        report.incomplete_scans += 1


def _scan_local_artifact(
    workspace_root: Path,
    rel_path: str,
    policy: NeutralityPolicy,
    report: NeutralityReport,
    literal_rules: LiteralMatcher,
    regex_rules: tuple[Pattern[str], ...],
    archive_budget: ArchiveScanBudget,
    entries: list[dict[str, Any]],
    budget: LocalArtifactScanBudget,
) -> None:
    try:
        validate_repository_relative_path(rel_path)
        path = workspace_root / rel_path
        estimated_size = path.stat(follow_symlinks=False).st_size
        if (
            budget.files + 1 > policy.max_local_artifact_files
            or budget.bytes + estimated_size > policy.max_local_artifact_bytes
        ):
            budget.breached = True
            report.archive_limit_breaches += 1
            report.incomplete_scans += 1
            return
        remaining_bytes = policy.max_local_artifact_bytes - budget.bytes
        result = stable_read_bytes_with_retry(
            path,
            max_bytes=min(policy.max_file_bytes, remaining_bytes),
        )
        if result.recovered_race:
            report.recovered_read_races += 1
        if (
            budget.files + 1 > policy.max_local_artifact_files
            or budget.bytes + len(result.data) > policy.max_local_artifact_bytes
        ):
            budget.breached = True
            report.archive_limit_breaches += 1
            report.incomplete_scans += 1
            return
        budget.files += 1
        budget.bytes += len(result.data)
        _record_scanned_data(
            rel_path,
            result.data,
            report,
            policy,
            literal_rules,
            regex_rules,
            archive_budget,
            entries,
            source_class="local-artifact",
        )
        report.scanned_local_artifacts += 1
    except StableReadRaceError:
        report.read_races += 1
        report.incomplete_scans += 1
    except (OSError, NeutralityError):
        report.skipped_inputs += 1
        report.incomplete_scans += 1


def _record_scanned_data(
    rel_path: str,
    data: bytes,
    report: NeutralityReport,
    policy: NeutralityPolicy,
    literal_rules: LiteralMatcher,
    regex_rules: tuple[Pattern[str], ...],
    archive_budget: ArchiveScanBudget,
    entries: list[dict[str, Any]],
    *,
    source_class: str,
) -> None:
    report.scanned_files += 1
    report.findings.extend(_match_data(rel_path, data, literal_rules, regex_rules))
    _scan_archive(rel_path, data, policy, report, literal_rules, regex_rules, archive_budget, depth=1)
    entries.append({"path": rel_path, "sourceClass": source_class, "sha256": sha256_hex(data), "bytes": len(data)})


def _git_tracked_entries(workspace_root: Path) -> list[dict[str, Any]]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z", "--stage", "--cached"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise NeutralityError("tracked-release git index enumeration failed") from exc
    return _parse_git_tracked_entries(output)


def _parse_git_tracked_entries(output: bytes) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_id, raw_stage = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
            validate_repository_relative_path(path)
            mode_text = mode.decode("ascii")
            object_text = object_id.decode("ascii")
            stage = int(raw_stage)
            if not re.fullmatch(r"[0-7]{6}", mode_text) or not re.fullmatch(r"[0-9a-f]{40,64}", object_text):
                raise ValueError
        except (UnicodeDecodeError, ValueError, NeutralityError) as exc:
            raise NeutralityError("malformed tracked-release git index entry") from exc
        entries.append({"path": path, "mode": mode_text, "objectId": object_text, "stage": stage})
    return sorted(entries, key=lambda item: item["path"].encode("utf-8"))


def _git_head_revision(workspace_root: Path) -> str | None:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return value if re.fullmatch(r"[0-9a-f]{40,64}", value) else None


def _stable_tracked_symlink_payload(path: Path, *, max_bytes: int) -> tuple[bytes, bool]:
    mode = os.lstat(path).st_mode
    if stat.S_ISREG(mode):
        result = stable_read_bytes_with_retry(path, max_bytes=max_bytes)
        return result.data, result.recovered_race
    if not stat.S_ISLNK(mode):
        raise NeutralityError(f"not a tracked symlink: {path}")
    try:
        return _read_symlink_once(path, max_bytes=max_bytes), False
    except StableReadRaceError:
        return _read_symlink_once(path, max_bytes=max_bytes), True


def _read_symlink_once(path: Path, *, max_bytes: int) -> bytes:
    before = os.lstat(path)
    if not stat.S_ISLNK(before.st_mode):
        raise NeutralityError(f"not a tracked symlink: {path}")
    payload = os.fsencode(path.readlink())
    if len(payload) > max_bytes:
        raise NeutralityError(f"file exceeds max bytes: {path}")
    after = os.lstat(path)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity:
        raise StableReadRaceError(f"stable read identity changed: {path}")
    return payload


def _walk_local_artifacts(workspace_root: Path, root: Path) -> Iterable[str]:
    if not root.exists():
        raise NeutralityError("declared local artifact root does not exist")
    if root.is_symlink() or not root.is_dir():
        raise NeutralityError("local artifact root must be a real directory")
    normalized_workspace = workspace_root.resolve()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames.sort(key=os.fsencode)
        filenames.sort(key=os.fsencode)
        for dirname in list(dirnames):
            candidate = current_path / dirname
            if dirname.casefold() == ".git":
                raise NeutralityError("nested Git metadata is not allowed in local artifact roots")
            if candidate.is_symlink():
                raise NeutralityError("local artifact symlinks are not allowed")
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink():
                raise NeutralityError("local artifact symlinks are not allowed")
            if candidate.is_file():
                yield candidate.relative_to(normalized_workspace).as_posix()


def _walk_repository_files(workspace_root: Path, policy: NeutralityPolicy) -> Iterable[str]:
    for root, dirnames, filenames in os.walk(workspace_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(workspace_root).as_posix()
        dirnames[:] = [
            dirname for dirname in dirnames if not _excluded(_join_rel(rel_root, dirname), policy.path_excludes)
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
    literal_rules: LiteralMatcher,
    regex_rules: tuple[Pattern[str], ...],
) -> list[NeutralityFinding]:
    findings: list[NeutralityFinding] = []
    text = data.decode("utf-8", errors="ignore")
    for index in literal_rules.matching_indices(text):
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
    literal_rules: LiteralMatcher,
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
