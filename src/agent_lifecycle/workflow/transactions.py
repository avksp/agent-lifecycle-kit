"""One reentrant transaction boundary for workflow API and CLI mutations."""

from __future__ import annotations

import hashlib
import os
import threading
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.process_lock import exclusive_process_lock
from agent_lifecycle.contracts.workflow_state_authority import workflow_authority_operation

_P = ParamSpec("_P")
_R = TypeVar("_R")
_ACTIVE: ContextVar[frozenset[tuple[int, int, str]]] = ContextVar("alk_workflow_transactions", default=frozenset())


def workflow_transaction(operation: Callable[_P, _R]) -> Callable[_P, _R]:
    """Lock before any state load and retain the lock through all nested work."""

    @wraps(operation)
    def serialized(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        state_path = kwargs.get("state_path", args[0] if args else None)
        with workflow_transaction_context(state_path):
            return operation(*args, **kwargs)

    return serialized


@contextmanager
def workflow_transaction_context(state_path: object, *, creation_root: Path | None = None) -> Iterator[None]:
    """Share the same lock after pure initialization input validation."""
    if not isinstance(state_path, Path):
        raise LifecycleError("workflow-state-path-invalid", "workflow mutation requires a Path")
    canonical = state_path.resolve()
    # Case/Unicode aliases share one lock even on insensitive filesystems.
    # On sensitive filesystems this only conservatively serializes more paths.
    identity = unicodedata.normalize("NFC", canonical.as_posix()).casefold()
    key = (os.getpid(), threading.get_ident(), identity)
    active = _ACTIVE.get()
    if key in active:
        yield
        return
    name_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lock_path = Path.home().resolve() / ".agent-lifecycle-kit" / "workflow-locks" / f"{name_digest}.lock"
    with exclusive_process_lock(lock_path):
        token = _ACTIVE.set(active | {key})
        try:
            with workflow_authority_operation(state_path, allow_missing=True, creation_root=creation_root):
                yield
        finally:
            _ACTIVE.reset(token)
