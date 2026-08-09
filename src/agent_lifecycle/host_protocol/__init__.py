"""Provider-neutral host operation protocol."""

from agent_lifecycle.host_protocol.acp_capability import (
    build_acp_capability,
    build_acp_probe_receipt,
    require_host_capabilities_pass,
    validate_host_capabilities,
    validate_no_acp_evidence_for_hosts,
)
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
from agent_lifecycle.host_protocol.usage_normalizers import (
    NormalizedUsage,
    build_conservative_usage_estimate,
    build_model_usage_sidecar,
    parse_bounded_jsonl_objects,
    safe_session_identifier,
    validate_usage_normalization_profile,
)
from agent_lifecycle.host_protocol.validation import (
    require_adapter_validation_pass,
    validate_adapter_descriptor,
)

__all__ = [
    "HostAdapterEvent",
    "HostOperationReceipt",
    "HostOperationRequest",
    "NormalizedUsage",
    "adapter_declares_event_capture",
    "build_acp_capability",
    "build_acp_probe_receipt",
    "build_capability_manifest",
    "build_conservative_usage_estimate",
    "build_model_usage_sidecar",
    "build_adapter_event_stream",
    "build_event_stream_receipt",
    "event_capture_declaration",
    "normalize_host_operation_receipt",
    "parse_bounded_jsonl_objects",
    "require_event_capture_pass",
    "require_adapter_event_stream_pass",
    "require_adapter_inspection_pass",
    "require_adapter_validation_pass",
    "require_host_capabilities_pass",
    "inspect_adapter_descriptor",
    "scaffold_adapter",
    "safe_session_identifier",
    "validate_capability_manifest",
    "validate_event_capture_conformance",
    "validate_event_capture_receipt",
    "validate_adapter_event_stream",
    "validate_adapter_descriptor",
    "validate_host_capabilities",
    "validate_no_acp_evidence_for_hosts",
    "validate_usage_normalization_profile",
]
