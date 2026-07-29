"""Provider-neutral host operation protocol."""

from agent_lifecycle.host_protocol.capabilities import (
    build_capability_manifest,
    validate_capability_manifest,
)
from agent_lifecycle.host_protocol.contracts import HostAdapterEvent, HostOperationReceipt, HostOperationRequest
from agent_lifecycle.host_protocol.events import (
    require_adapter_event_stream_pass,
    validate_adapter_event_stream,
)
from agent_lifecycle.host_protocol.inspection import (
    inspect_adapter_descriptor,
    require_adapter_inspection_pass,
)
from agent_lifecycle.host_protocol.receipts import normalize_host_operation_receipt
from agent_lifecycle.host_protocol.scaffold import scaffold_adapter
from agent_lifecycle.host_protocol.validation import (
    require_adapter_validation_pass,
    validate_adapter_descriptor,
)

__all__ = [
    "HostAdapterEvent",
    "HostOperationReceipt",
    "HostOperationRequest",
    "build_capability_manifest",
    "normalize_host_operation_receipt",
    "require_adapter_event_stream_pass",
    "require_adapter_inspection_pass",
    "require_adapter_validation_pass",
    "inspect_adapter_descriptor",
    "scaffold_adapter",
    "validate_capability_manifest",
    "validate_adapter_event_stream",
    "validate_adapter_descriptor",
]
