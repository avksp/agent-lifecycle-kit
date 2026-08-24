"""Deprecated import location for historical runner schemas.

Active code must use workflow contracts. Legacy readers may import the
explicit compatibility registry instead.
"""

from agent_lifecycle.contracts.legacy_runner_schemas import LEGACY_RUNNER_CORE_SCHEMAS

__all__ = ["LEGACY_RUNNER_CORE_SCHEMAS"]
