"""Filesystem store for managed adapter sessions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.canonical import (
    ensure_private_directory,
    write_json_create_private,
    write_json_replace_private,
)

DEFAULT_SESSION_ROOT = ".alk/adapter-sessions"


def session_path(session_id: str, *, session_root: Path | None = None) -> Path:
    if not session_id or "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
        raise LifecycleError("adapter-session-id-invalid", "session id is invalid")
    root = session_root or Path(DEFAULT_SESSION_ROOT)
    path = root / f"{session_id}.json"
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise LifecycleError("adapter-session-path-escape", "session path escapes session root")
    return path


def create_session(
    *,
    adapter_id: str,
    mode: str,
    status: str,
    launch_profile: dict[str, Any],
    session_root: Path | None = None,
    state_identity: dict[str, Any] | None = None,
    managed_workflow_proof: dict[str, Any] | None = None,
    context_checkpoint_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = uuid.uuid4().hex
    session = {
        "schemaVersion": "agent-adapter-session-state.v1",
        "sessionId": session_id,
        "adapterId": adapter_id,
        "mode": mode,
        "status": status,
        "launchProfile": {
            "status": launch_profile.get("status"),
            "reason": launch_profile.get("reason"),
        },
        "stateIdentity": state_identity,
        "managedWorkflowProof": managed_workflow_proof,
        "contextCheckpointPolicy": context_checkpoint_policy,
        "secretValuesStored": False,
        "nativeConfigWritten": False,
    }
    path = session_path(session_id, session_root=session_root)
    ensure_private_directory(path.parent)
    write_json_create_private(path, session)
    return session


def load_session(session_id: str, *, session_root: Path | None = None) -> dict[str, Any]:
    return read_json_object(session_path(session_id, session_root=session_root), label="adapter session")


def update_session(session: dict[str, Any], *, session_root: Path | None = None) -> dict[str, Any]:
    path = session_path(session["sessionId"], session_root=session_root)
    write_json_replace_private(path, session)
    return session
