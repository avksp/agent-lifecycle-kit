"""Workflow-facing facade for sandbox boundary receipts.

The implementation lives in the lower host-protocol boundary so adapter
capability validation does not import the workflow package. Workflow policy
code keeps this module as its stable public entry point.
"""

from agent_lifecycle.host_protocol.sandbox_receipts import (
    BOUNDARY_NAMES,
    CAPABILITY_STATUSES,
    ENFORCEMENT_SOURCES,
    SANDBOX_CAPABILITY_SCHEMA,
    SANDBOX_CAPABILITY_VALIDATION_SCHEMA,
    SANDBOX_RECEIPT_SCHEMA,
    SANDBOX_RECEIPT_VALIDATION_SCHEMA,
    SANDBOX_STATUSES,
    build_credential_proxy_details,
    build_partial_process_boundary,
    build_sandbox_receipt,
    build_unknown_sandbox_capability,
    require_sandbox_receipt_pass,
    validate_sandbox_capability,
    validate_sandbox_receipt,
)

__all__ = [
    "BOUNDARY_NAMES",
    "CAPABILITY_STATUSES",
    "ENFORCEMENT_SOURCES",
    "SANDBOX_CAPABILITY_SCHEMA",
    "SANDBOX_CAPABILITY_VALIDATION_SCHEMA",
    "SANDBOX_RECEIPT_SCHEMA",
    "SANDBOX_RECEIPT_VALIDATION_SCHEMA",
    "SANDBOX_STATUSES",
    "build_credential_proxy_details",
    "build_partial_process_boundary",
    "build_sandbox_receipt",
    "build_unknown_sandbox_capability",
    "require_sandbox_receipt_pass",
    "validate_sandbox_capability",
    "validate_sandbox_receipt",
]
