"""Provider-neutral usage normalization contracts and conservative fallback."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex

USAGE_NORMALIZER_CONTRACT = "adapter-local-usage-normalizer.v1"
USAGE_NORMALIZER_STATUSES = {"UNSUPPORTED", "FIXTURE_ONLY", "QUALIFIED"}
USAGE_ARTIFACT_FORMATS = {"stream-jsonl"}
MAX_USAGE_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_USAGE_ARTIFACT_EVENTS = 10_000
MAX_USAGE_EVENT_BYTES = 256 * 1024
MAX_USAGE_EVENT_DEPTH = 16
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """Allowlisted counters extracted by a host-local parser."""

    input_tokens: int = 0
    output_tokens: int = 0
    billable_tokens: int = 0
    cumulative_context_bytes: int | None = None
    tool_calls: int = 0
    wall_seconds: float = 0.0
    cost_usd: float | None = None
    session_id: str | None = None
    event_count: int = 0
    cumulative_context_bytes_source: str | None = None

    @property
    def has_usage_attestation(self) -> bool:
        return bool(self.billable_tokens or self.input_tokens or self.output_tokens or self.cost_usd is not None)

    @property
    def has_calibration_attestation(self) -> bool:
        return self.has_usage_attestation and self.cumulative_context_bytes is not None

    def to_receipt_usage(self) -> dict[str, Any]:
        usage: dict[str, Any] = {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "billableTokens": max(self.billable_tokens, self.input_tokens + self.output_tokens),
            "toolCalls": self.tool_calls,
            "wallSeconds": self.wall_seconds,
        }
        if self.cost_usd is not None:
            usage["costUsd"] = self.cost_usd
        if self.session_id:
            usage["sessionId"] = self.session_id
        return usage

    def to_model_usage(self) -> dict[str, int]:
        return {
            "inputTokens": _non_negative_int(self.input_tokens),
            "outputTokens": _non_negative_int(self.output_tokens),
            "billableTokens": max(
                _non_negative_int(self.billable_tokens),
                _non_negative_int(self.input_tokens) + _non_negative_int(self.output_tokens),
            ),
            "cumulativeContextBytes": _non_negative_int(self.cumulative_context_bytes),
            "toolCalls": _non_negative_int(self.tool_calls),
            "wallSeconds": max(0, int(math.ceil(self.wall_seconds))),
        }

    def to_calibration_usage(self) -> dict[str, Any]:
        usage: dict[str, Any] = self.to_model_usage()
        if self.cumulative_context_bytes_source:
            usage["cumulativeContextBytesSource"] = self.cumulative_context_bytes_source
        if self.session_id:
            usage["sessionId"] = self.session_id
        return usage

    def with_context_byte_proxy(self, value: int) -> "NormalizedUsage":
        return replace(
            self,
            cumulative_context_bytes=_non_negative_int(value),
            cumulative_context_bytes_source="harness-observed-prompt-and-jsonl-bytes",
        )


def parse_bounded_jsonl_objects(
    source: str | bytes,
    *,
    max_bytes: int = MAX_USAGE_ARTIFACT_BYTES,
    max_events: int = MAX_USAGE_ARTIFACT_EVENTS,
) -> list[dict[str, Any]]:
    """Parse a bounded JSONL artifact without retaining non-object events."""

    data = source.encode("utf-8") if isinstance(source, str) else source
    if not isinstance(data, bytes):
        raise LifecycleError("invalid-usage-artifact", "usage artifact must be text or bytes")
    if len(data) > max_bytes:
        raise LifecycleError("usage-artifact-too-large", "usage artifact exceeds the declared maximum")
    events: list[dict[str, Any]] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        if len(line) > MAX_USAGE_EVENT_BYTES:
            raise LifecycleError("usage-event-too-large", "usage event exceeds the portable maximum")
        if len(events) >= max_events:
            raise LifecycleError("usage-event-limit-exceeded", "usage artifact contains too many events")
        try:
            value = json.loads(line)
        except RecursionError as error:
            raise LifecycleError("usage-event-depth-exceeded", "usage event is nested too deeply") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LifecycleError("invalid-usage-artifact-json", "usage artifact contains invalid JSON") from error
        if not isinstance(value, dict):
            raise LifecycleError("invalid-usage-artifact-event", "usage artifact events must be objects")
        if _container_depth(value) > MAX_USAGE_EVENT_DEPTH:
            raise LifecycleError("usage-event-depth-exceeded", "usage event is nested too deeply")
        events.append(value)
    return events


def safe_session_identifier(value: Any) -> str | None:
    """Return a bounded opaque id, rejecting path and secret-shaped values."""

    if not isinstance(value, str) or not _SAFE_SESSION_ID.fullmatch(value):
        return None
    lowered = value.lower()
    if any(marker in lowered for marker in ("bearer", "token", "secret", "password", "private-key")):
        return None
    return value


def build_model_usage_sidecar(
    *,
    usage: NormalizedUsage,
    operation_id: str,
    adapter_id: str,
    host: str,
    model_class: str,
    provider_model_hash: str,
    route_decision_digest: str,
    source_bytes: bytes,
    source_format: str,
    source_kind: str,
    normalizer_status: str,
    normalizer_digest: str,
) -> dict[str, Any]:
    """Build the canonical model-usage receipt as a path-free sidecar."""

    for name, value in (
        ("operation_id", operation_id),
        ("adapter_id", adapter_id),
        ("host", host),
        ("model_class", model_class),
    ):
        if not isinstance(value, str) or not value:
            raise LifecycleError("invalid-usage-sidecar-binding", f"{name} is required")
    _require_digest(provider_model_hash, "provider_model_hash")
    _require_digest(route_decision_digest, "route_decision_digest")
    _require_digest(normalizer_digest, "normalizer_digest")
    if source_format not in USAGE_ARTIFACT_FORMATS:
        raise LifecycleError("invalid-usage-artifact-format", "source_format is unsupported")
    if source_kind not in {"host", "fixture", "core-estimate"}:
        raise LifecycleError("invalid-usage-artifact-source", "source_kind is unsupported")
    if normalizer_status not in USAGE_NORMALIZER_STATUSES:
        raise LifecycleError("invalid-usage-normalizer-status", "normalizer_status is unsupported")
    if source_kind != "host" and normalizer_status == "QUALIFIED":
        raise LifecycleError("invalid-usage-normalizer-attestation", "qualified normalizers require host evidence")
    if len(source_bytes) > MAX_USAGE_ARTIFACT_BYTES:
        raise LifecycleError(
            "usage-artifact-too-large",
            "usage artifact exceeds the portable maximum",
            {"bytes": len(source_bytes), "limit": MAX_USAGE_ARTIFACT_BYTES},
        )

    accepted = source_kind == "host" and normalizer_status == "QUALIFIED"
    body = {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": operation_id,
        "adapterId": adapter_id,
        "host": host,
        "modelClass": model_class,
        "providerModelHash": provider_model_hash,
        "routeDecisionDigest": route_decision_digest,
        "usage": usage.to_model_usage(),
        "attestation": {
            "source": source_kind,
            "status": "ATTESTED" if accepted else "ESTIMATED",
            "acceptedForS1S2": accepted,
        },
        "sourceArtifact": {
            "sha256": sha256_hex(source_bytes),
            "bytes": len(source_bytes),
            "format": source_format,
        },
        "normalizer": {
            "contract": USAGE_NORMALIZER_CONTRACT,
            "status": normalizer_status,
            "digest": normalizer_digest,
            "acceptedForS1S2": accepted,
        },
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_conservative_usage_estimate(
    *,
    operation_id: str,
    adapter_id: str,
    host: str,
    model_class: str,
    provider_model_hash: str,
    route_decision_digest: str,
    source_bytes: bytes,
    source_format: str = "stream-jsonl",
) -> dict[str, Any]:
    """Estimate at one token per byte so the fallback cannot undercount text."""

    estimated_tokens = max(1, len(source_bytes))
    usage = NormalizedUsage(
        input_tokens=estimated_tokens,
        billable_tokens=estimated_tokens,
        cumulative_context_bytes=len(source_bytes),
    )
    return build_model_usage_sidecar(
        usage=usage,
        operation_id=operation_id,
        adapter_id=adapter_id,
        host=host,
        model_class=model_class,
        provider_model_hash=provider_model_hash,
        route_decision_digest=route_decision_digest,
        source_bytes=source_bytes,
        source_format=source_format,
        source_kind="core-estimate",
        normalizer_status="UNSUPPORTED",
        normalizer_digest=canonical_digest({"contract": "core-conservative-usage-estimate.v1"}),
    )


def validate_usage_normalization_profile(
    profile: Any,
    *,
    adapter_id: str | None,
    host: str | None,
) -> dict[str, Any]:
    """Validate a descriptor declaration without loading adapter code."""

    blockers: list[dict[str, Any]] = []
    if profile is None:
        return _profile_validation("UNSUPPORTED", blockers, profile)
    if not isinstance(profile, dict):
        blockers.append({"code": "adapter-usage-normalization-type", "message": "usageNormalization must be an object"})
        return _profile_validation(None, blockers, profile)
    if profile.get("contract") != USAGE_NORMALIZER_CONTRACT:
        blockers.append({"code": "adapter-usage-normalization-contract", "message": "usageNormalization contract is unsupported"})
    status = profile.get("status")
    if status not in USAGE_NORMALIZER_STATUSES:
        blockers.append({"code": "adapter-usage-normalization-status", "message": "usageNormalization status is invalid"})
    accepted = profile.get("acceptedForS1S2")
    if not isinstance(accepted, bool):
        blockers.append({"code": "adapter-usage-normalization-acceptance", "message": "acceptedForS1S2 must be boolean"})
    elif accepted is not (status == "QUALIFIED"):
        blockers.append({"code": "adapter-usage-normalization-acceptance", "message": "only QUALIFIED normalizers may be accepted for S1/S2"})

    if status == "UNSUPPORTED":
        if not isinstance(profile.get("reason"), str) or not profile.get("reason"):
            blockers.append({"code": "adapter-usage-normalization-reason", "message": "UNSUPPORTED normalizers require a reason"})
        return _profile_validation(status, blockers, profile)

    expected_path = f"adapters/{adapter_id}/usage_normalizer.py" if adapter_id else None
    path = profile.get("path")
    if not _safe_relative_path(path) or path != expected_path:
        blockers.append(
            {
                "code": "adapter-usage-normalization-path",
                "message": "usageNormalization path must be the adapter-local normalizer",
                "expected": expected_path,
            }
        )
    if profile.get("artifactFormat") not in USAGE_ARTIFACT_FORMATS:
        blockers.append({"code": "adapter-usage-normalization-format", "message": "artifactFormat is unsupported"})
    byte_limit = profile.get("maxArtifactBytes")
    if not isinstance(byte_limit, int) or isinstance(byte_limit, bool) or not 0 < byte_limit <= MAX_USAGE_ARTIFACT_BYTES:
        blockers.append(
            {
                "code": "adapter-usage-normalization-byte-limit",
                "message": "maxArtifactBytes must be within the portable limit",
            }
        )
    if status == "QUALIFIED":
        host_range = profile.get("qualifiedHostRange")
        if not isinstance(host_range, dict) or host_range.get("host") != host:
            blockers.append({"code": "adapter-usage-normalization-host-range", "message": "QUALIFIED normalizers require a matching host range"})
        evidence = profile.get("qualificationEvidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
            blockers.append({"code": "adapter-usage-normalization-evidence", "message": "QUALIFIED normalizers require evidence"})
    return _profile_validation(status if isinstance(status, str) else None, blockers, profile)


def _profile_validation(status: str | None, blockers: list[dict[str, Any]], profile: Any) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-adapter-usage-normalization-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "declaredStatus": status,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    if isinstance(profile, dict):
        body["profileDigest"] = canonical_digest(profile)
    return body


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _container_depth(value: Any) -> int:
    maximum = 0
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, parent_depth = pending.pop()
        if isinstance(item, dict):
            depth = parent_depth + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item.values())
        elif isinstance(item, list):
            depth = parent_depth + 1
            maximum = max(maximum, depth)
            pending.extend((child, depth) for child in item)
    return maximum


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
        raise LifecycleError("invalid-usage-sidecar-binding", f"{name} must be a SHA-256 digest")


def _non_negative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0
