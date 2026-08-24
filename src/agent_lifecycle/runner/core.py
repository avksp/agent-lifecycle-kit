"""Fail-closed compatibility boundary for removed controlled-runner calls.

Release 2.0 keeps no executable runner state machine. The CLI dispatcher is
updated in WS200-03; this temporary import boundary makes any earlier call
fail without reading, writing or mutating runner state.
"""

from __future__ import annotations

from typing import Any, NoReturn

from agent_lifecycle.contracts import LifecycleError


def _removed(operation: str) -> NoReturn:
    raise LifecycleError(
        "runner-authority-removed",
        "controlled runner authority was removed; use the workflow command",
        {"operation": operation, "replacement": "workflow run"},
    )


def load_runner_policy(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("load-policy")


def initialize_runner_state(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("initialize")


def load_runner_state(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("load-state")


def validate_runner_state(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("validate")


def transition_runner(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("transition")


def request_runner_stop(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("stop")


def resume_runner(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("resume")


def build_runner_snapshot(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("snapshot")


def write_runner_state(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("write-state")


def write_runner_state_create(*_args: Any, **_kwargs: Any) -> NoReturn:
    _removed("write-state-create")


__all__ = [
    "build_runner_snapshot",
    "initialize_runner_state",
    "load_runner_policy",
    "load_runner_state",
    "request_runner_stop",
    "resume_runner",
    "transition_runner",
    "validate_runner_state",
    "write_runner_state",
    "write_runner_state_create",
]
