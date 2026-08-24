"""Bounded read-only projection over explicitly selected lifecycle runs."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex
from agent_lifecycle.contracts.multi_run_view_schemas import MULTI_RUN_VIEW_SCHEMA
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.reporting.attention import build_attention_projection, build_multi_run_overlap

DEFAULT_MAX_RUNS = 32
DEFAULT_MAX_BYTES_PER_RUN = 1_048_576
DEFAULT_STALE_AFTER_SECONDS = 86_400
MAX_EVENT_RECORDS = 2_048
MAX_OWNERSHIP_PATHS = 4_096
STATE_FILE_NAMES = ("run.state.json", "run-implementation.state.json", "state.json")


def build_multi_run_attention_view(
    *,
    project_root: Path,
    run_roots: list[Path],
    max_runs: int = DEFAULT_MAX_RUNS,
    max_bytes_per_run: int = DEFAULT_MAX_BYTES_PER_RUN,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one deterministic aggregate view without mutating selected runs."""

    root = _project_root(project_root)
    _require_positive_cap("max_runs", max_runs)
    _require_positive_cap("max_bytes_per_run", max_bytes_per_run)
    _require_non_negative_cap("stale_after_seconds", stale_after_seconds)

    requested = _deduplicate_roots(run_roots)
    blockers: list[dict[str, Any]] = []
    if len(requested) > max_runs:
        blockers.append(
            {
                "code": "multi-run-cap-exceeded",
                "message": "selected run roots exceed the configured limit",
                "count": len(requested),
                "maxRuns": max_runs,
            }
        )
    sources: list[dict[str, Any]] = []
    for raw_root in requested[:max_runs]:
        sources.append(_load_source(root, raw_root, max_bytes_per_run))

    attention_items = build_attention_projection(sources, now=now, stale_after_seconds=stale_after_seconds)
    overlaps = build_multi_run_overlap(sources)
    failed_sources = sum(1 for source in sources if source.get("status") != "PASS")
    body = {
        "schemaVersion": MULTI_RUN_VIEW_SCHEMA,
        "status": "PASS" if not blockers and failed_sources == 0 else "FAIL",
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "stateWritten": False,
        "projectRoot": "<checkout>",
        "sourceCount": len(sources),
        "successfulSourceCount": len(sources) - failed_sources,
        "failedSourceCount": failed_sources,
        "sources": sources,
        "attentionItems": attention_items,
        "overlaps": overlaps,
        "blockers": blockers,
        "limits": {
            "maxRuns": max_runs,
            "maxBytesPerRun": max_bytes_per_run,
            "staleAfterSeconds": stale_after_seconds,
            "maxEventRecords": MAX_EVENT_RECORDS,
            "maxOwnershipPaths": MAX_OWNERSHIP_PATHS,
        },
        "productionPromotionClaimed": False,
    }
    redacted, _changed = redact_value(body)
    if not isinstance(redacted, dict):
        raise LifecycleError("multi-run-view-invalid", "multi-run view could not be rendered")
    return {**redacted, "viewDigest": canonical_digest(redacted)}


def build_multi_run_view(**kwargs: Any) -> dict[str, Any]:
    """Compatibility name for :func:`build_multi_run_attention_view`."""

    return build_multi_run_attention_view(**kwargs)


def _load_source(project_root: Path, raw_root: Path, max_bytes: int) -> dict[str, Any]:
    try:
        root_path, explicit_state = _safe_run_root(project_root, raw_root)
        root_relative = _relative(project_root, root_path)
    except LifecycleError as exc:
        raw_display = os.path.normpath(os.fspath(raw_root))
        return {
            "schemaVersion": "agent-multi-run-source.v1",
            "sourceId": f"unavailable:{raw_display}",
            "runId": f"unavailable:{raw_display}",
            "rootPath": raw_display,
            "status": "FAIL",
            "summary": {},
            "ownershipPaths": [],
            "blockers": [{"code": exc.code, "message": exc.message}],
        }
    source_id = f"unavailable:{root_relative}"
    blockers: list[dict[str, Any]] = []
    try:
        reader = _bounded_reader(project_root, max_bytes)
        state_path = explicit_state or _find_state_path(root_path)
        if state_path is None:
            raise LifecycleError("multi-run-state-missing", "selected run has no supported state file")
        state_data = reader(state_path, "workflow state")
        state = load_json_object(state_data, label="workflow state")
        validate_workflow_state(state)
        run_id_value = state.get("runId")
        run_id: str = run_id_value if isinstance(run_id_value, str) else source_id
        source_id = run_id
        summary, ownership_paths, summary_blockers = _summarize_state(state)
        blockers.extend(summary_blockers)
        event_log = _read_event_log(project_root, root_path, state, reader)
        evidence = _read_optional_artifact(
            project_root,
            root_path,
            state.get("evidenceIndex"),
            reader,
            "evidence index",
        )
        worktree = _read_optional_artifact(
            project_root,
            root_path,
            state.get("worktreeIdentity"),
            reader,
            "worktree identity",
        )
        if event_log.get("status") == "FAIL":
            blockers.extend(event_log.get("blockers", []))
        if evidence.get("status") == "FAIL":
            blockers.extend(evidence.get("blockers", []))
        if worktree.get("status") == "FAIL":
            blockers.extend(worktree.get("blockers", []))
        source = {
            "schemaVersion": "agent-multi-run-source.v1",
            "sourceId": source_id,
            "runId": run_id,
            "rootPath": root_relative,
            "status": "PASS" if not blockers else "FAIL",
            "stateIdentity": {
                "path": _relative(project_root, state_path),
                "sha256": canonical_digest(state),
                "bytes": len(state_data),
                "stateRevision": state.get("stateRevision"),
            },
            "summary": summary,
            "eventLog": event_log,
            "evidence": evidence,
            "worktreeIdentity": worktree,
            "ownershipPaths": ownership_paths,
            "blockers": blockers,
        }
        redacted, _changed = redact_value(source)
        return redacted if isinstance(redacted, dict) else source
    except LifecycleError as exc:
        return {
            "schemaVersion": "agent-multi-run-source.v1",
            "sourceId": source_id,
            "runId": source_id,
            "rootPath": root_relative,
            "status": "FAIL",
            "summary": {},
            "ownershipPaths": [],
            "blockers": [{"code": exc.code, "message": exc.message}],
        }


def _summarize_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    ownership_paths: set[str] = set()
    tasks: list[dict[str, Any]] = []
    raw_tasks_value = state.get("tasks")
    raw_tasks: list[Any] = raw_tasks_value if isinstance(raw_tasks_value, list) else []
    for raw_task in raw_tasks[:MAX_OWNERSHIP_PATHS]:
        if not isinstance(raw_task, dict):
            continue
        task_id = raw_task.get("id")
        if not isinstance(task_id, str) or not task_id:
            continue
        evidence_status = _task_evidence_status(raw_task)
        task = {
            "taskId": task_id,
            "status": raw_task.get("status"),
            "attempt": raw_task.get("attempt"),
            "required": raw_task.get("required", True),
            "attemptStartedAt": raw_task.get("attemptStartedAt"),
            "attemptDeadlineAt": raw_task.get("attemptDeadlineAt"),
            "evidenceStatus": evidence_status,
        }
        tasks.append(task)
        for path in _task_paths(raw_task):
            try:
                ownership_paths.add(normalize_repo_path(path, label="declared ownership path"))
            except LifecycleError as exc:
                blockers.append({"code": "multi-run-ownership-path-invalid", "message": exc.message, "taskId": task_id})
    summary = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
        "phase": state.get("phase"),
        "blocker": state.get("blocker") if isinstance(state.get("blocker"), dict) else None,
        "authorization": _authorization_summary(state.get("authorization")),
        "tasks": tasks,
    }
    return summary, sorted(ownership_paths)[:MAX_OWNERSHIP_PATHS], blockers


def _read_event_log(
    project_root: Path,
    run_root: Path,
    state: dict[str, Any],
    reader: Callable[[Path, str], bytes],
) -> dict[str, Any]:
    declared = state.get("eventLog")
    if not isinstance(declared, str) or not declared:
        return {"status": "NOT_DECLARED", "eventCount": 0, "digest": None, "latestEventType": None, "blockers": []}
    try:
        path = _declared_path(project_root, run_root, declared, "event log")
        data = reader(path, "event log")
        count = 0
        latest: str | None = None
        for raw_line in data.splitlines():
            if not raw_line.strip():
                continue
            if count >= MAX_EVENT_RECORDS:
                raise LifecycleError("multi-run-event-cap-exceeded", "event log exceeds the configured record limit")
            event = load_json_object(raw_line, label="event log record")
            event_type = event.get("eventType") or event.get("type")
            latest = event_type if isinstance(event_type, str) else latest
            count += 1
        return {
            "status": "PASS",
            "path": _relative(project_root, path),
            "eventCount": count,
            "digest": sha256_hex(data),
            "latestEventType": latest,
            "blockers": [],
        }
    except LifecycleError as exc:
        return {
            "status": "FAIL",
            "eventCount": 0,
            "digest": None,
            "latestEventType": None,
            "blockers": [{"code": exc.code, "message": exc.message}],
        }


def _read_optional_artifact(
    project_root: Path,
    run_root: Path,
    declared: Any,
    reader: Callable[[Path, str], bytes],
    label: str,
) -> dict[str, Any]:
    if declared is None:
        return {"status": "NOT_DECLARED", "digest": None, "blockers": []}
    if isinstance(declared, dict):
        return {"status": "EMBEDDED", "digest": canonical_digest(declared), "blockers": []}
    if not isinstance(declared, str) or not declared:
        return {
            "status": "FAIL",
            "digest": None,
            "blockers": [
                {
                    "code": "multi-run-artifact-path-invalid",
                    "message": f"{label} path is invalid",
                }
            ],
        }
    try:
        path = _declared_path(project_root, run_root, declared, label)
        data = reader(path, label)
        value = load_json_object(data, label=label)
        return {
            "status": "PASS",
            "path": _relative(project_root, path),
            "digest": canonical_digest(value),
            "blockers": [],
        }
    except LifecycleError as exc:
        return {"status": "FAIL", "digest": None, "blockers": [{"code": exc.code, "message": exc.message}]}


def _bounded_reader(project_root: Path, max_bytes: int) -> Callable[[Path, str], bytes]:
    total = 0

    def read(path: Path, label: str) -> bytes:
        nonlocal total
        relative = _relative(project_root, path)
        data = read_stable_repository_file(project_root, relative, max_bytes=max_bytes, label=label)
        total += len(data)
        if total > max_bytes:
            raise LifecycleError("multi-run-byte-cap-exceeded", "selected run exceeds the configured byte limit")
        return data

    return read


def _safe_run_root(project_root: Path, raw_root: Path) -> tuple[Path, Path | None]:
    if not isinstance(raw_root, Path):
        raise LifecycleError("multi-run-root-invalid", "run root must be a path")
    candidate = (raw_root if raw_root.is_absolute() else project_root / raw_root).absolute()
    try:
        candidate.relative_to(project_root)
    except ValueError:
        # Accept a platform path alias such as macOS /var -> /private/var only
        # after canonicalizing it; direct symlink components under the project
        # root are still rejected below.
        candidate = candidate.resolve(strict=False)
    _require_contained(project_root, candidate, "multi-run-root")
    _reject_symlinks(project_root, candidate, "multi-run-root")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise LifecycleError("multi-run-root-unavailable", "selected run root is unavailable") from exc
    _require_contained(project_root, resolved, "multi-run-root")
    if resolved.is_file():
        if resolved.name not in STATE_FILE_NAMES:
            raise LifecycleError("multi-run-root-invalid", "a file run root must be a supported state file")
        return resolved.parent, resolved
    if not resolved.is_dir():
        raise LifecycleError("multi-run-root-invalid", "selected run root is not a directory")
    if resolved == project_root:
        raise LifecycleError("multi-run-root-too-broad", "the project root cannot be used as a run root")
    return resolved, None


def _find_state_path(root: Path) -> Path | None:
    for name in STATE_FILE_NAMES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _declared_path(project_root: Path, run_root: Path, value: str, label: str) -> Path:
    normalized = normalize_repo_path(value, label=label)
    project_candidate = project_root.joinpath(*normalized.split("/"))
    run_candidate = run_root.joinpath(*normalized.split("/"))
    for candidate in (project_candidate, run_candidate):
        try:
            _require_contained(run_root, candidate, label)
            _reject_symlinks(project_root, candidate, label)
            if candidate.is_file():
                return candidate
        except LifecycleError:
            continue
    raise LifecycleError("multi-run-artifact-unavailable", f"{label} is unavailable inside the selected run root")


def _project_root(path: Path) -> Path:
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise LifecycleError("multi-run-project-root-invalid", "project root is unavailable") from exc
    if not root.is_dir():
        raise LifecycleError("multi-run-project-root-invalid", "project root is not a directory")
    return root


def _require_contained(root: Path, candidate: Path, label: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LifecycleError("multi-run-path-outside-root", f"{label} escapes its configured root") from exc


def _reject_symlinks(root: Path, candidate: Path, label: str) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise LifecycleError("multi-run-path-outside-root", f"{label} escapes its configured root") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise LifecycleError("multi-run-symlink-input", f"{label} contains a symlinked component")


def _relative(root: Path, path: Path) -> str:
    try:
        return normalize_repo_path(path.relative_to(root).as_posix(), label="display path")
    except (ValueError, LifecycleError) as exc:
        raise LifecycleError("multi-run-path-outside-root", "display path escapes project root") from exc


def _deduplicate_roots(values: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        key = os.path.normpath(os.fspath(value))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _task_paths(task: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("writes", "changedFiles"):
        raw = task.get(key)
        if isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str))
    change_set = task.get("resultChangeSetEvidence")
    if isinstance(change_set, dict):
        raw = change_set.get("changedFiles")
        if isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str))
    return values[:MAX_OWNERSHIP_PATHS]


def _task_evidence_status(task: dict[str, Any]) -> str | None:
    audit = task.get("implementationAuditReport")
    if isinstance(audit, dict):
        validation = audit.get("validation")
        if isinstance(validation, dict) and validation.get("status") == "FAIL":
            return "FAIL"
        verdict = audit.get("verdict")
        if verdict in {"CHANGES_REQUIRED", "BLOCKED", "FAIL"}:
            return "FAIL"
        if verdict == "ACCEPTED":
            return "PASS"
    return None


def _authorization_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "required": value.get("required"),
        "granted": value.get("granted"),
    }


def _require_positive_cap(label: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("multi-run-invalid-cap", f"{label} must be a positive integer")


def _require_non_negative_cap(label: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("multi-run-invalid-cap", f"{label} must be a non-negative integer")


__all__ = [
    "DEFAULT_MAX_BYTES_PER_RUN",
    "DEFAULT_MAX_RUNS",
    "DEFAULT_STALE_AFTER_SECONDS",
    "build_multi_run_attention_view",
    "build_multi_run_view",
]
