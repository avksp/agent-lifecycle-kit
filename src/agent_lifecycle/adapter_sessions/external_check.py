"""Run optional external checks through the bounded process boundary."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.worktree_identity import capture_git_worktree_identity
from agent_lifecycle.audit.external_checks import audit_external_check_result
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.external_check_schemas import (
    MAX_ARG_BYTES,
    MAX_OUTPUT_BYTES,
    build_external_check_descriptor,
    build_external_check_invocation,
)
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.quality.external_checks import normalize_external_check_result

PROFILE_SCHEMA = "agent-external-check-profile.v1"
MAX_PROFILE_BYTES = 32768
MAX_SOURCE_FILE_LIST_BYTES = 4 * 1024 * 1024
MAX_PROFILE_ARG_COUNT = 64
MAX_PROFILE_TIMEOUT_SECONDS = 3600
DEFAULT_PROFILE_DIRECTORY = "external-checks"
SUPPORTED_CHECKS = ("import-boundaries", "module-dependencies", "declared-dependencies")


def default_external_check_profile(check_id: str) -> Path:
    """Return the installed package-data profile for one supported check."""

    if check_id not in SUPPORTED_CHECKS:
        raise LifecycleError("external-check-profile-unsupported", "external check is not supported")
    from agent_lifecycle.resources import builtin_profile_path

    return builtin_profile_path(f"{DEFAULT_PROFILE_DIRECTORY}/{check_id}.v1.json")


def load_external_check_profile(profile_path: Path) -> dict[str, Any]:
    """Load and validate one static, provider-neutral external-check profile."""

    try:
        if profile_path.stat().st_size > MAX_PROFILE_BYTES:
            raise LifecycleError("external-check-profile-too-large", "external check profile exceeds its byte limit")
        profile = read_json_object(profile_path, label="external check profile")
    except OSError as exc:
        raise LifecycleError("external-check-profile-unavailable", "external check profile is unavailable") from exc
    _validate_profile(profile)
    return profile


def run_external_check(
    *,
    project_root: Path,
    plan_digest: str,
    plan_lock_digest: str,
    operation_id: str,
    check_id: str,
    profile_path: Path | None = None,
    config_path: str | None = None,
    source_revision: str | None = None,
    blocking_required: bool = False,
    process_runner: Any = run_process,
) -> dict[str, Any]:
    """Run an explicitly requested check and return only bounded evidence."""

    root = project_root.resolve()
    profile = load_external_check_profile(profile_path or default_external_check_profile(check_id))
    if profile["checkId"] != check_id:
        raise LifecycleError("external-check-profile-mismatch", "profile checkId does not match the request")
    source_snapshot = _source_snapshot(root, source_revision)
    selected_config = config_path or profile.get("configPath")
    config_digest, config_blocker = _config_identity(root, selected_config)
    descriptor = build_external_check_descriptor(
        descriptor_id=f"{profile['profileId']}-{source_snapshot['revision'][:12]}",
        check_id=profile["checkId"],
        tool_id=profile["toolId"],
        tool_version=profile["toolVersion"],
        executable=profile["executable"],
        argv=list(profile["argv"]),
        config_digest=config_digest,
        source_snapshot=source_snapshot,
        plan_digest=plan_digest,
        plan_lock_digest=plan_lock_digest,
        working_directory=profile.get("workingDirectory"),
        timeout_seconds=profile["timeoutSeconds"],
        max_output_bytes=profile["maxOutputBytes"],
        environment_allow=list(profile["environment"]["allow"]),
    )
    started_at = _now()
    env, _env_receipt = resolve_launch_env(
        {"env": profile["environment"]},
        process_env=dict(os.environ),
    )
    executable = _resolve_executable(profile["executable"], env)
    if config_blocker is not None:
        process_payload = _unavailable_payload(config_blocker)
        invocation_status = "ABORTED"
    elif executable is None:
        process_payload = _unavailable_payload({"code": "external-check-executable-unavailable"})
        invocation_status = "ABORTED"
    else:
        process_payload = _run_process(
            process_runner,
            profile,
            root,
            env,
            operation_id,
        )
        _mark_source_drift(process_payload, root, source_snapshot)
        invocation_status = "COMPLETED"
    invocation = build_external_check_invocation(
        invocation_id=f"{operation_id}-invocation",
        operation_id=operation_id,
        descriptor=descriptor,
        started_at=started_at,
        status=invocation_status,
        ended_at=_now(),
    )
    normalized = normalize_external_check_result(
        process_payload,
        descriptor=descriptor,
        invocation=invocation,
        result_id=f"{operation_id}-result",
    )
    audit = audit_external_check_result(
        normalized,
        descriptor=descriptor,
        invocation=invocation,
        blocking_required=blocking_required,
    )
    return {
        "schemaVersion": "agent-external-check-run.v1",
        "status": normalized["status"],
        "checkId": check_id,
        "descriptor": descriptor,
        "invocation": invocation,
        "result": normalized,
        "audit": audit,
        "productionPromotionClaimed": False,
    }


def _run_process(
    process_runner: Any,
    profile: dict[str, Any],
    root: Path,
    env: dict[str, str],
    operation_id: str,
) -> dict[str, Any]:
    result = process_runner(
        list(profile["argv"]),
        env=env,
        timeout_seconds=float(profile["timeoutSeconds"]),
        cwd=root,
        max_output_bytes=profile["maxOutputBytes"],
        operation_id=operation_id,
        attempt_id=operation_id,
        adapter_id=profile["toolId"],
    )
    payload = _parse_output(profile, result)
    payload.update(
        {
            "complete": _process_complete(result),
            "timedOut": result.get("timedOut") is True,
            "outputTruncated": result.get("outputLimitExceeded") is True,
            "processCleanupStatus": _cleanup_status(result),
            "exitCode": result.get("exitCode"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
        }
    )
    return payload


def _parse_output(profile: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    stdout = result.get("stdout")
    if profile["outputFormat"] == "json" and isinstance(stdout, str):
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, RecursionError):
            return {"status": "INVALID", "blockers": [{"code": "external-check-output-json-invalid"}]}
        if isinstance(parsed, dict):
            return dict(parsed)
        return {"status": "INVALID", "blockers": [{"code": "external-check-output-json-not-object"}]}
    return {"status": "PASS" if result.get("status") == "PASS" else "FAIL", "findings": []}


def _unavailable_payload(blocker: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "unavailable": True,
        "complete": False,
        "timedOut": False,
        "outputTruncated": False,
        "processCleanupStatus": "UNAVAILABLE",
        "exitCode": None,
        "blockers": [blocker],
        "findings": [],
    }


def _mark_source_drift(payload: dict[str, Any], root: Path, before: dict[str, Any]) -> None:
    try:
        after = _source_snapshot(root, before["revision"])
    except LifecycleError:
        payload.setdefault("blockers", []).append({"code": "external-check-source-unavailable-after-run"})
        payload["status"] = "INVALID"
        return
    if after != before:
        payload.setdefault("blockers", []).append({"code": "external-check-source-drift"})
        payload["status"] = "FAIL"


def _process_complete(result: dict[str, Any]) -> bool:
    return bool(
        result.get("processStarted") is True
        and result.get("timedOut") is False
        and result.get("outputLimitExceeded") is False
        and _cleanup_status(result) == "PASS"
    )


def _cleanup_status(result: dict[str, Any]) -> str:
    cleanup = result.get("cleanup")
    status = cleanup.get("status") if isinstance(cleanup, dict) else None
    return status if status in {"PASS", "FAIL", "UNAVAILABLE"} else "UNAVAILABLE"


def _resolve_executable(executable: str, env: dict[str, str]) -> Path | None:
    candidate = Path(executable)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    resolved = shutil.which(executable, path=env.get("PATH"))
    return Path(resolved) if resolved else None


def _source_snapshot(root: Path, revision: str | None) -> dict[str, Any]:
    identity = capture_git_worktree_identity(root)
    resolved_revision = revision or identity["head"]
    if resolved_revision != identity["head"]:
        raise LifecycleError("external-check-source-revision-mismatch", "requested source revision is not HEAD")
    paths = _source_paths(root)
    return {
        "revision": identity["head"],
        "fileSetDigest": canonical_digest({"paths": paths}),
        "workingTreeDigest": identity["identityDigest"],
    }


def _source_paths(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("external-check-source-unavailable", "source file set could not be captured") from exc
    if completed.returncode != 0 or len(completed.stdout) > MAX_SOURCE_FILE_LIST_BYTES:
        raise LifecycleError("external-check-source-unavailable", "source file set could not be captured")
    try:
        paths = [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]
        return sorted(normalize_repo_path(item, label="source file") for item in paths)
    except (LifecycleError, UnicodeDecodeError) as exc:
        raise LifecycleError("external-check-source-invalid", "source file set is invalid") from exc


def _config_identity(root: Path, config_path: str | None) -> tuple[str, dict[str, Any] | None]:
    if config_path is None:
        return canonical_digest({"config": None}), None
    try:
        normalized = normalize_repo_path(config_path, label="external check config")
        data = read_stable_repository_file(root, normalized, max_bytes=MAX_OUTPUT_BYTES, label="external check config")
    except LifecycleError as exc:
        return canonical_digest({"config": config_path, "status": "UNAVAILABLE"}), {"code": exc.code}
    return hashlib.sha256(data).hexdigest(), None


def _validate_profile(profile: dict[str, Any]) -> None:
    required = (
        "profileId",
        "checkId",
        "toolId",
        "toolVersion",
        "executable",
        "argv",
        "timeoutSeconds",
        "maxOutputBytes",
        "environment",
        "outputFormat",
    )
    if profile.get("schemaVersion") != PROFILE_SCHEMA or any(
        not isinstance(profile.get(item), str) or not profile[item] for item in required[:5]
    ):
        raise LifecycleError("external-check-profile-invalid", "external check profile identity is invalid")
    argv = profile.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_PROFILE_ARG_COUNT or argv[0] != profile["executable"]:
        raise LifecycleError("external-check-profile-invalid", "external check profile argv is invalid")
    if any(
        not isinstance(item, str) or not item or "\x00" in item or len(item.encode()) > MAX_ARG_BYTES
        for item in argv
    ):
        raise LifecycleError("external-check-profile-invalid", "external check profile argv is invalid")
    if (
        not isinstance(profile.get("timeoutSeconds"), int)
        or not 1 <= profile["timeoutSeconds"] <= MAX_PROFILE_TIMEOUT_SECONDS
    ):
        raise LifecycleError("external-check-profile-invalid", "external check profile timeout is invalid")
    if not isinstance(profile.get("maxOutputBytes"), int) or not 1 <= profile["maxOutputBytes"] <= MAX_OUTPUT_BYTES:
        raise LifecycleError("external-check-profile-invalid", "external check profile output limit is invalid")
    environment = profile.get("environment")
    if (
        not isinstance(environment, dict)
        or not isinstance(environment.get("allow"), list)
        or environment.get("allowPatterns") != []
    ):
        raise LifecycleError("external-check-profile-invalid", "external check profile environment is invalid")
    if not all(isinstance(item, str) and item for item in environment["allow"]):
        raise LifecycleError("external-check-profile-invalid", "external check profile environment is invalid")
    if profile.get("outputFormat") not in {"text", "json"}:
        raise LifecycleError("external-check-profile-invalid", "external check profile output format is invalid")
    config_path = profile.get("configPath")
    if config_path is not None:
        normalize_repo_path(config_path, label="external check config")
    if profile.get("workingDirectory") is not None:
        normalize_repo_path(profile["workingDirectory"], label="external check working directory")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["SUPPORTED_CHECKS", "default_external_check_profile", "load_external_check_profile", "run_external_check"]
