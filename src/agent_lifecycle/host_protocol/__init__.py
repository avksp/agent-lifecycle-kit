"""Provider-neutral host operation protocol."""

from agent_lifecycle.host_protocol.capabilities import (
    build_capability_manifest,
    validate_capability_manifest,
)
from agent_lifecycle.host_protocol.contracts import HostAdapterEvent, HostOperationReceipt, HostOperationRequest
from agent_lifecycle.host_protocol.event_capture import (
    adapter_declares_event_capture,
    build_adapter_event_stream,
    build_event_stream_receipt,
    event_capture_declaration,
    require_event_capture_pass,
    validate_event_capture_conformance,
    validate_event_capture_receipt,
)
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
    "adapter_declares_event_capture",
    "build_capability_manifest",
    "build_adapter_event_stream",
    "build_event_stream_receipt",
    "event_capture_declaration",
    "normalize_host_operation_receipt",
    "require_event_capture_pass",
    "require_adapter_event_stream_pass",
    "require_adapter_inspection_pass",
    "require_adapter_validation_pass",
    "inspect_adapter_descriptor",
    "scaffold_adapter",
    "validate_capability_manifest",
    "validate_event_capture_conformance",
    "validate_event_capture_receipt",
    "validate_adapter_event_stream",
    "validate_adapter_descriptor",
]
