"""Filesystem store for managed adapter sessions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, read_json_object, write_json_create

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
    write_json_create(session_path(session_id, session_root=session_root), session)
    return session


def load_session(session_id: str, *, session_root: Path | None = None) -> dict[str, Any]:
    return read_json_object(session_path(session_id, session_root=session_root), label="adapter session")


def update_session(session: dict[str, Any], *, session_root: Path | None = None) -> dict[str, Any]:
    path = session_path(session["sessionId"], session_root=session_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(session) + b"\n")
    return session
