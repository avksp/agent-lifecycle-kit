"""Provider-neutral host operation protocol."""

from agent_lifecycle.host_protocol.contracts import HostOperationReceipt, HostOperationRequest
from agent_lifecycle.host_protocol.scaffold import scaffold_adapter
from agent_lifecycle.host_protocol.validation import (
    require_adapter_validation_pass,
    validate_adapter_descriptor,
)

__all__ = [
    "HostOperationReceipt",
    "HostOperationRequest",
    "require_adapter_validation_pass",
    "scaffold_adapter",
    "validate_adapter_descriptor",
]
