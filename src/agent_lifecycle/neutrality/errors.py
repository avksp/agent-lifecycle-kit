"""Neutrality-specific exceptions."""

from agent_lifecycle.contracts.errors import LifecycleError


class NeutralityError(LifecycleError):
    """A fail-closed neutrality contract violation."""

    def __init__(self, message: str):
        super().__init__("neutrality-contract-violation", message)
