"""Fail closed when host-local or generated roots enter Git authority."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json

from agent_lifecycle.contracts.redaction import redact_text

POLICY_SCHEMA = "agent-repository-hygiene-policy.v1"
VALIDATION_SCHEMA = "agent-repository-hygiene-validation.v1"
DEFAULT_POLICY = Path("policy/repository-hygiene.json")


@dataclass(frozen=True)
class Budgets:
    timeout_seconds: int
    max_git_output_bytes: int
    max_reported_findings: int
    max_reported_path_bytes: int


@dataclass(frozen=True)
class Policy:
    index_roots: frozenset[str]
    history_roots: frozenset[str]
    budgets: Budgets


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: str


class FindingCollector:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.items: list[dict[str, Any]] = []
        self.suppressed = 0

    def add(self, finding: dict[str, Any]) -> None:
        if len(self.items) < self.limit:
            self.items.append(finding)
        else:
            self.suppressed += 1


def validate_repository_hygiene(
    *,
    repository_root: Path,
    policy_path: Path,
    refs: list[str],
    all_refs: bool,
    require_history: bool,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    try:
        policy = _load_policy(policy_path)
    except (OSError, ValueError, SystemExit) as error:
        body = {
            "schemaVersion": VALIDATION_SCHEMA,
            "status": "FAIL",
            "policy": {"path": _safe_text(policy_path.as_posix())},
            "index": {"status": "NOT_RUN", "trackedPathCount": 0},
            "history": {"status": "NOT_RUN", "requestedRefs": [], "scannedRefs": []},
            "findings": [],
            "suppressedFindingCount": 0,
            "blockers": [{"code": "invalid-repository-hygiene-policy", "message": _safe_text(str(error))}],
            "productionPromotionClaimed": False,
        }
        return {**body, "validationDigest": digest_value(body)}

    findings = FindingCollector(policy.budgets.max_reported_findings)
    tracked_paths = _tracked_paths(repository_root, policy, blockers)
    for path in tracked_paths:
        _check_path(
            path,
            forbidden_roots=policy.index_roots,
            code="forbidden-index-root",
            scope="index",
            budgets=policy.budgets,
            findings=findings,
        )

    history_requested = require_history or all_refs or bool(refs)
    requested_refs = list(refs)
    if history_requested and not requested_refs:
        requested_refs.append("HEAD")
    if all_refs and "HEAD" not in requested_refs:
        requested_refs.insert(0, "HEAD")

    scanned_refs: list[dict[str, str]] = []
    unique_objects: set[str] = set()
    if history_requested:
        _require_complete_checkout(repository_root, policy, blockers)
        if all_refs:
            requested_refs.extend(_local_refs(repository_root, policy, blockers))
        requested_refs = list(dict.fromkeys(requested_refs))
        _scan_history(
            repository_root,
            policy=policy,
            requested_refs=requested_refs,
            scanned_refs=scanned_refs,
            unique_objects=unique_objects,
            findings=findings,
            blockers=blockers,
        )

    blockers.extend(
        {"code": item["code"], "scope": item["scope"], "root": item["root"]}
        for item in findings.items
        if item.get("code") in {"forbidden-index-root", "forbidden-history-root"}
    )
    if findings.suppressed:
        blockers.append({"code": "repository-hygiene-findings-suppressed", "count": findings.suppressed})

    history_failed = any(item.get("scope") == "history" for item in findings.items) or any(
        str(item.get("code", "")).startswith("repository-history-") for item in blockers
    )
    policy_identity = file_identity(policy_path)
    policy_identity["path"] = _safe_text(str(policy_identity["path"]))
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "policy": policy_identity,
        "index": {
            "status": "PASS" if not any(item.get("scope") == "index" for item in findings.items) else "FAIL",
            "trackedPathCount": len(tracked_paths),
            "forbiddenRoots": sorted(policy.index_roots),
        },
        "history": {
            "status": "NOT_REQUESTED" if not history_requested else "FAIL" if history_failed else "PASS",
            "allRefs": all_refs,
            "requestedRefs": [_safe_text(_bounded(ref, policy.budgets)) for ref in requested_refs],
            "scannedRefs": scanned_refs,
            "uniqueObjectCount": len(unique_objects),
            "forbiddenRoots": sorted(policy.history_roots),
        },
        "findings": findings.items,
        "suppressedFindingCount": findings.suppressed,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _load_policy(path: Path) -> Policy:
    value = load_json(path)
    if value.get("schemaVersion") != POLICY_SCHEMA:
        raise ValueError("unsupported repository hygiene policy schemaVersion")
    index_roots = _roots(value.get("indexForbiddenRoots"), "indexForbiddenRoots")
    history_roots = _roots(value.get("historyForbiddenRoots"), "historyForbiddenRoots")
    if not history_roots.issubset(index_roots):
        raise ValueError("historyForbiddenRoots must be a subset of indexForbiddenRoots")
    raw_budgets = value.get("budgets")
    if not isinstance(raw_budgets, dict):
        raise ValueError("budgets must be an object")
    budgets = Budgets(
        timeout_seconds=_positive_int(raw_budgets, "gitCommandTimeoutSeconds", maximum=600),
        max_git_output_bytes=_positive_int(raw_budgets, "maxGitOutputBytes", maximum=1 << 30),
        max_reported_findings=_positive_int(raw_budgets, "maxReportedFindings", maximum=10_000),
        max_reported_path_bytes=_positive_int(raw_budgets, "maxReportedPathBytes", maximum=65_536),
    )
    return Policy(index_roots=index_roots, history_roots=history_roots, budgets=budgets)


def _roots(value: Any, label: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    roots: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item in {".", ".."}:
            raise ValueError(f"{label} entries must be non-empty root names")
        if "/" in item or "\\" in item or "\x00" in item or item.startswith("-"):
            raise ValueError(f"{label} entries must be literal repository root names")
        roots.append(item)
    if len(roots) != len(set(roots)):
        raise ValueError(f"{label} contains duplicate roots")
    return frozenset(roots)


def _positive_int(value: dict[str, Any], key: str, *, maximum: int) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1 or item > maximum:
        raise ValueError(f"budgets.{key} must be an integer between 1 and {maximum}")
    return item


def _tracked_paths(root: Path, policy: Policy, blockers: list[dict[str, Any]]) -> list[str]:
    result = _git(root, ["ls-files", "-z"], policy.budgets)
    if result.returncode != 0:
        blockers.append({"code": "repository-index-enumeration-failed", "message": result.stderr})
        return []
    return _decode_nul_paths(result.stdout, code="repository-index-path-invalid", blockers=blockers)


def _require_complete_checkout(root: Path, policy: Policy, blockers: list[dict[str, Any]]) -> None:
    result = _git(root, ["rev-parse", "--is-shallow-repository"], policy.budgets)
    if result.returncode != 0:
        blockers.append({"code": "repository-history-completeness-unavailable", "message": result.stderr})
        return
    if result.stdout.strip() != b"false":
        blockers.append({"code": "repository-history-shallow-checkout"})


def _local_refs(root: Path, policy: Policy, blockers: list[dict[str, Any]]) -> list[str]:
    result = _git(root, ["for-each-ref", "--format=%(refname)"], policy.budgets)
    if result.returncode != 0:
        blockers.append({"code": "repository-history-ref-enumeration-failed", "message": result.stderr})
        return []
    try:
        refs = result.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        blockers.append({"code": "repository-history-ref-invalid"})
        return []
    invalid = [ref for ref in refs if not _valid_ref(ref)]
    if invalid:
        blockers.append({"code": "repository-history-ref-invalid", "count": len(invalid)})
    return sorted(ref for ref in refs if _valid_ref(ref))


def _scan_history(
    root: Path,
    *,
    policy: Policy,
    requested_refs: list[str],
    scanned_refs: list[dict[str, str]],
    unique_objects: set[str],
    findings: FindingCollector,
    blockers: list[dict[str, Any]],
) -> None:
    scanned_tips: set[str] = set()
    seen_associations: set[tuple[str, str]] = set()
    for ref in requested_refs:
        if not _valid_ref(ref):
            blockers.append(
                {"code": "repository-history-ref-invalid", "ref": _safe_text(_bounded(ref, policy.budgets))}
            )
            continue
        resolved = _git(root, ["--no-replace-objects", "rev-parse", "--verify", f"{ref}^{{commit}}"], policy.budgets)
        commit = resolved.stdout.decode("ascii", errors="ignore").strip()
        if resolved.returncode != 0 or not _valid_object_id(commit):
            blockers.append(
                {
                    "code": "repository-history-ref-resolution-failed",
                    "ref": _safe_text(_bounded(ref, policy.budgets)),
                    "message": resolved.stderr,
                }
            )
            continue
        scanned_refs.append({"ref": _safe_text(_bounded(ref, policy.budgets)), "commit": commit})
        if commit in scanned_tips:
            continue
        scanned_tips.add(commit)
        result = _git(root, ["--no-replace-objects", "rev-list", "-z", "--objects", commit], policy.budgets)
        if result.returncode != 0:
            blockers.append({"code": "repository-history-scan-failed", "ref": ref, "message": result.stderr})
            continue
        object_ids, records = _parse_history_records(result.stdout, ref=ref, blockers=blockers)
        unique_objects.update(object_ids)
        for object_text, raw_path in records:
            try:
                path = raw_path.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                blockers.append({"code": "repository-history-path-invalid", "ref": ref})
                continue
            association = (object_text, path)
            if association in seen_associations:
                continue
            seen_associations.add(association)
            _check_path(
                path,
                forbidden_roots=policy.history_roots,
                code="forbidden-history-root",
                scope="history",
                budgets=policy.budgets,
                findings=findings,
                extra={"ref": ref, "objectId": object_text},
            )


def _parse_history_records(
    data: bytes,
    *,
    ref: str,
    blockers: list[dict[str, Any]],
) -> tuple[set[str], list[tuple[str, bytes]]]:
    """Parse both legacy and current NUL-delimited git object records."""

    object_ids: set[str] = set()
    records: list[tuple[str, bytes]] = []
    current_object: str | None = None
    for entry in data.split(b"\x00"):
        if not entry:
            continue
        if entry.startswith(b"path="):
            if current_object is None or not entry[5:]:
                blockers.append({"code": "repository-history-output-invalid", "ref": ref})
                continue
            records.append((current_object, entry[5:]))
            continue

        raw_object, separator, legacy_path = entry.partition(b" ")
        try:
            object_id = raw_object.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            object_id = ""
        if not _valid_object_id(object_id):
            blockers.append({"code": "repository-history-output-invalid", "ref": ref})
            current_object = None
            continue
        current_object = object_id
        object_ids.add(object_id)
        if separator:
            if not legacy_path:
                blockers.append({"code": "repository-history-output-invalid", "ref": ref})
                continue
            records.append((object_id, legacy_path))
    return object_ids, records


def _check_path(
    path: str,
    *,
    forbidden_roots: frozenset[str],
    code: str,
    scope: str,
    budgets: Budgets,
    findings: FindingCollector,
    extra: dict[str, str] | None = None,
) -> None:
    root = path.split("/", 1)[0]
    if root not in forbidden_roots:
        return
    finding: dict[str, Any] = {
        "code": code,
        "scope": scope,
        "root": root,
        "path": _bounded(path, budgets),
    }
    if extra:
        finding.update(extra)
    findings.add(finding)


def _decode_nul_paths(data: bytes, *, code: str, blockers: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    for raw in data.split(b"\x00"):
        if not raw:
            continue
        try:
            output.append(raw.decode("utf-8", errors="strict"))
        except UnicodeDecodeError:
            blockers.append({"code": code})
    return output


def _valid_ref(ref: str) -> bool:
    return bool(ref) and not ref.startswith("-") and "\x00" not in ref and "\n" not in ref and len(ref) <= 1024


def _valid_object_id(value: str) -> bool:
    return len(value) in {40, 64} and all(char in "0123456789abcdef" for char in value)


def _bounded(value: str, budgets: Budgets) -> str:
    data = value.encode("utf-8", errors="replace")
    if len(data) <= budgets.max_reported_path_bytes:
        return value
    return data[: budgets.max_reported_path_bytes].decode("utf-8", errors="ignore") + "..."


def _git(root: Path, args: list[str], budgets: Budgets) -> GitResult:
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.run(
                ["git", *args],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
                timeout=budgets.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return GitResult(returncode=255, stdout=b"", stderr=f"git command unavailable: {type(error).__name__}")
        stdout_size = stdout_file.tell()
        stderr_size = stderr_file.tell()
        if stdout_size > budgets.max_git_output_bytes or stderr_size > budgets.max_git_output_bytes:
            return GitResult(returncode=255, stdout=b"", stderr="git command exceeded the configured byte budget")
        stdout_file.seek(0)
        stderr_file.seek(0)
        return GitResult(
            returncode=process.returncode,
            stdout=stdout_file.read(),
            stderr=_safe_text(stderr_file.read(65_536).decode("utf-8", errors="replace").strip()),
        )


def _safe_text(value: str) -> str:
    return redact_text(value)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--policy", default=DEFAULT_POLICY.as_posix())
    parser.add_argument("--ref", action="append", default=[])
    parser.add_argument("--all-refs", action="store_true")
    parser.add_argument("--require-history", action="store_true")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    payload = validate_repository_hygiene(
        repository_root=Path(args.root).resolve(),
        policy_path=Path(args.policy),
        refs=args.ref,
        all_refs=args.all_refs,
        require_history=args.require_history,
    )
    write_json(Path(args.evidence), payload)
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
