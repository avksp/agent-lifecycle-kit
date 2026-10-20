"""Bounded read-only reviewer input checks; no runner or host attestation.

Qualified provider/restriction observations come from the trusted host adapter.
A prompt, profile or this receipt cannot authenticate those observations.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.external_job_schemas import (
    validate_external_job_request,
)
from agent_lifecycle.contracts.paths import read_stable_repository_file
from agent_lifecycle.contracts.preparation_policy import (
    PreparationAdmission,
    review_invocation_digest,
)


def reviewer_preflight(
    *, request: dict[str, Any], repository_root: Path, source_pins: dict[str, str],
    packet: dict[str, Any], rendered_input: bytes, argv: list[str],
    qualification: dict[str, Any], preparation: PreparationAdmission,
) -> dict[str, Any]:
    """Check current source/input and existing qualified technical restrictions.

    Only opaque digests and fixed reason labels leave this portable projection.
    This check never launches a model, writes source or issues authority.
    """
    reason = "REVIEW_PREFLIGHT_UNAVAILABLE"
    source_digest = packet_digest = None
    invocation_digest = None
    request_digest = None
    try:
        if validate_external_job_request(request)["status"] != "PASS":
            raise ValueError("Exact review request required")
        request_digest = request["requestDigest"]
        if not 1 <= len(source_pins) <= 64:
            raise ValueError("Bounded source inventory required")
        total = 0
        for name, expected in sorted(source_pins.items()):
            data = read_stable_repository_file(
                repository_root, name, max_bytes=1024 * 1024,
                label="review source",
            )
            total += len(data)
            if total > 8 * 1024 * 1024:
                raise ValueError("Bounded source bytes required")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Review source changed")
        source_digest = canonical_digest(source_pins)
        packet_bytes = canonical_bytes(packet)
        packet_digest = canonical_digest(packet)
        root_digest = canonical_digest(str(repository_root.resolve()))
        if (
            len(packet_bytes) > 1024 * 1024
            or not isinstance(rendered_input, bytes)
            or not 1 <= len(rendered_input) <= 1024 * 1024
            or qualification["qualified"] is not True
            or qualification["sourceSnapshotDigest"] != source_digest
            or request["sourceSnapshotDigest"] != source_digest
            or qualification["requestDigest"] != request["requestDigest"]
            or qualification["repositoryRootDigest"] != root_digest
            or qualification["inputTransport"] != "STDIN"
            or qualification["packetDigest"] != packet_digest
            or qualification["renderedInputDigest"]
            != hashlib.sha256(rendered_input).hexdigest()
            or qualification["renderedInputBytes"] != len(rendered_input)
            or qualification["inputComplete"] is not True
            or qualification["providerReady"] is not True
            or qualification["readOnlyEnforced"] is not True
            or qualification["restrictionBasis"]
            not in {"HOST_RESTRICTIONS", "ISOLATED_WORKSPACE"}
            or not isinstance(argv, list) or not 1 <= len(argv) <= 64
            or any(not isinstance(v, str) or not v or len(v) > 4096 for v in argv)
            or any(v.split("=", 1)[0] in {
                "--yolo", "--full-auto", "--dangerously-skip-permissions",
                "--dangerously-bypass-approvals-and-sandbox",
            } for v in argv)
            or canonical_digest(argv) != qualification["allowedArgvDigest"]
        ):
            raise ValueError("Qualified reviewer input/restrictions required")
        invocation_digest = review_invocation_digest(
            request=request, argv=argv, root_digest=root_digest,
            rendered_input=rendered_input,
        )
        # Admission owns all effect/financial state; no adapter import here.
        preparation.check(repository_root=repository_root)
        reason = "READY"
    except (KeyError, TypeError, ValueError, OSError, LifecycleError):
        pass
    body = {
        "schemaVersion": "agent-reviewer-preflight.v1",
        "status": "PASS" if reason == "READY" else "UNAVAILABLE",
        "reason": reason, "sourceSnapshotDigest": source_digest,
        "packetDigest": packet_digest, "modelCalls": 0,
        "requestDigest": request_digest,
        "invocationDigest": invocation_digest,
        "authorityClaimed": False, "productionPromotionClaimed": False,
    }
    return {**body, "preflightDigest": canonical_digest(body)}
