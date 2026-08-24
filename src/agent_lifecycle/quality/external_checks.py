"""Normalize bounded external analyzer output without retaining raw output."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.external_check_schemas import (
    CHECK_STATUSES,
    MAX_FINDINGS,
    MAX_OUTPUT_BYTES,
    build_external_check_finding,
    build_external_check_result,
    require_external_check_pass,
    validate_external_check_descriptor,
    validate_external_check_invocation,
    validate_external_check_result,
)
from agent_lifecycle.contracts.redaction import redact_text, redact_value


def normalize_external_check_result(
    payload: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    invocation: dict[str, Any],
    result_id: str,
) -> dict[str, Any]:
    """Convert one adapter-parsed payload into the neutral result contract.

    The parser belongs to the adapter boundary. This function accepts only the
    already parsed object, redacts messages and output metadata, and never
    copies raw stdout or stderr into lifecycle evidence.
    """

    require_external_check_pass(validate_external_check_descriptor(descriptor), "descriptor")
    require_external_check_pass(
        validate_external_check_invocation(invocation, descriptor=descriptor), "invocation"
    )
    if not isinstance(payload, dict):
        payload = {}
    blockers = _safe_blockers(payload.get("blockers"))
    status = payload.get("status")
    if status not in CHECK_STATUSES:
        status = _infer_status(payload)
        if payload.get("status") is not None:
            blockers.append({"code": "external-check-payload-status-invalid"})
            status = "INVALID"
    findings = _normalize_findings(payload.get("findings"), descriptor.get("toolId", "external"), blockers)
    output_digest, output_bytes, output_truncated = _output_identity(payload, blockers)
    complete = payload.get("complete") is True and not output_truncated
    if payload.get("complete") is not True:
        blockers.append({"code": "external-check-output-incomplete"})
    timed_out = payload.get("timedOut") is True
    cleanup = payload.get("processCleanupStatus", "UNAVAILABLE")
    if cleanup not in {"PASS", "FAIL", "UNAVAILABLE"}:
        cleanup = "UNAVAILABLE"
        blockers.append({"code": "external-check-cleanup-status-invalid"})
    if timed_out:
        blockers.append({"code": "external-check-timed-out"})
    exit_code = payload.get("exitCode")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        exit_code = None
        blockers.append({"code": "external-check-exit-code-invalid"})
    if exit_code not in (None, 0) and status == "PASS":
        status = "FAIL"
        blockers.append({"code": "external-check-nonzero-exit"})
    if len(findings) > MAX_FINDINGS:
        findings = findings[:MAX_FINDINGS]
        status = "INVALID"
        blockers.append({"code": "external-check-findings-limit"})
    return build_external_check_result(
        result_id=result_id,
        descriptor=descriptor,
        invocation=invocation,
        status=status,
        findings=findings,
        output_digest=output_digest,
        output_bytes=output_bytes,
        complete=complete,
        timed_out=timed_out,
        output_truncated=output_truncated,
        process_cleanup_status=cleanup,
        exit_code=exit_code,
        blockers=blockers,
    )


def validate_normalized_external_check_result(
    result: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    invocation: dict[str, Any],
) -> dict[str, Any]:
    """Validate a normalized result against both descriptor and invocation."""

    return validate_external_check_result(result, descriptor=descriptor, invocation=invocation)


def _normalize_findings(value: Any, tool_id: str, blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        blockers.append({"code": "external-check-findings-invalid"})
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            blockers.append({"code": "external-check-finding-invalid", "index": index})
            continue
        message, _changed = redact_text(str(item.get("message", "external check finding")))
        try:
            fingerprint = item.get("fingerprint")
            if (
                not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or any(c not in "0123456789abcdef" for c in fingerprint)
            ):
                fingerprint = canonical_digest({"toolId": tool_id, "fingerprint": fingerprint, "message": message})
            normalized.append(
                build_external_check_finding(
                    rule_id=str(item.get("ruleId", "external.unknown")),
                    severity=str(item.get("severity", "MEDIUM")),
                    message=message,
                    location=item.get("location"),
                    fingerprint=fingerprint,
                )
            )
        except (LifecycleError, TypeError, ValueError):
            blockers.append({"code": "external-check-finding-invalid", "index": index})
    return normalized


def _output_identity(payload: dict[str, Any], blockers: list[dict[str, Any]]) -> tuple[str | None, int, bool]:
    output = {key: payload[key] for key in ("stdout", "stderr") if key in payload}
    if not output:
        supplied_digest = payload.get("outputDigest")
        if (
            isinstance(supplied_digest, str)
            and len(supplied_digest) == 64
            and all(c in "0123456789abcdef" for c in supplied_digest)
        ):
            return (
                supplied_digest,
                _bounded_bytes(payload.get("outputBytes", 0), blockers),
                payload.get("outputTruncated") is True,
            )
        return (
            None,
            _bounded_bytes(payload.get("outputBytes", 0), blockers),
            payload.get("outputTruncated") is True,
        )
    safe_output, _changed = redact_value(output)
    encoded = canonical_bytes(safe_output)
    truncated = len(encoded) > MAX_OUTPUT_BYTES or payload.get("outputTruncated") is True
    if truncated:
        blockers.append({"code": "external-check-output-truncated"})
    return canonical_digest(safe_output), min(len(encoded), MAX_OUTPUT_BYTES), truncated


def _bounded_bytes(value: Any, blockers: list[dict[str, Any]]) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_OUTPUT_BYTES:
        blockers.append({"code": "external-check-output-bytes-invalid"})
        return 0
    return value


def _safe_blockers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:128]:
        if isinstance(item, dict) and isinstance(item.get("code"), str) and item["code"]:
            result.append({"code": item["code"][:256]})
    return result


def _infer_status(payload: dict[str, Any]) -> str:
    if payload.get("unavailable") is True:
        return "UNAVAILABLE"
    if payload.get("findings"):
        return "FAIL"
    if payload.get("exitCode") not in (None, 0):
        return "FAIL"
    return "PASS"


__all__ = ["normalize_external_check_result", "validate_normalized_external_check_result"]
