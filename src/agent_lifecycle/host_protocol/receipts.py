"""Host-operation receipt normalization helpers for adapters."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.host_protocol.contracts import HostOperationReceipt


def normalize_host_operation_receipt(payload: dict[str, Any], *, redact_sensitive: bool = True) -> dict[str, Any]:
    """Return a closed host-operation receipt with optional sensitive redaction."""

    receipt = HostOperationReceipt.from_json(payload).to_json()
    if not redact_sensitive:
        return receipt
    redacted, applied = redact_value(receipt)
    usage = dict(redacted["usage"])
    usage["receiptRedaction"] = {"applied": applied, "secretValuesStored": False}
    redacted["usage"] = usage
    return redacted
