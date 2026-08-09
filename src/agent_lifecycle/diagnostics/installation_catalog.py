"""Data-only access to installation facts declared by adapter descriptors."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol.validation import validate_installation_facts


def load_installation_facts(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return validated descriptor data without interpreting or executing argv."""

    facts = descriptor.get("installation")
    validation = validate_installation_facts(facts)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "adapter-installation-facts-invalid",
            "adapter descriptor installation facts are invalid",
            {"blockers": validation["blockers"]},
        )
    return deepcopy(facts)
