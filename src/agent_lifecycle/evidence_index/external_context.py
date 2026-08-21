"""Optional external context import receipts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.redaction import (
    LOCAL_PATH_REDACTION,
    contains_local_absolute_path,
    redact_text,
    redact_text_with_stats,
)

EXTERNAL_CONTEXT_RECEIPT_SCHEMA = "agent-external-context-import-receipt.v1"
EXTERNAL_CONTEXT_VALIDATION_SCHEMA = "agent-external-context-import-validation.v1"

DEFAULT_MAX_INPUT_BYTES = 32768
DEFAULT_TARGET_TOKENS = 2048
DEFAULT_MAX_HINT_CHARS = 1400

def build_external_context_import_receipt(
    source_path: Path,
    *,
    citation: str | None = None,
    source_id: str | None = None,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_hint_chars: int = DEFAULT_MAX_HINT_CHARS,
) -> dict[str, Any]:
    """Import a local exported memory/context artifact as optional context."""

    _positive_int(max_input_bytes, "maxInputBytes")
    _positive_int(target_tokens, "targetTokens")
    _positive_int(max_hint_chars, "maxHintChars")
    label = _safe_label(source_id or source_path.name or "external-context")
    blockers: list[dict[str, Any]] = []
    source: dict[str, Any] = {
        "sourceKind": "local-file",
        "sourceLabel": label,
        "sourcePathStored": False,
        "citation": _sanitize_citation(citation or label),
        "sourceDigest": None,
        "byteCount": 0,
    }
    hints: list[dict[str, Any]] = []
    redaction = _empty_redaction()
    try:
        if not source_path.is_file():
            blockers.append({"code": "external-context-source-missing", "sourceLabel": label})
        elif source_path.stat().st_size > max_input_bytes:
            blockers.append(
                {
                    "code": "external-context-input-cap-exceeded",
                    "sourceLabel": label,
                    "byteCount": source_path.stat().st_size,
                    "maxInputBytes": max_input_bytes,
                }
            )
        else:
            data = source_path.read_bytes()
            source["sourceDigest"] = sha256_hex(data)
            source["byteCount"] = len(data)
            text = _decode_context_text(data)
            sanitized, redaction = _sanitize_text(text, max_chars=max_hint_chars)
            if sanitized:
                hints.append(
                    {
                        "hintId": f"external-context-{canonical_digest({'label': label, 'digest': source['sourceDigest']})[:16]}",
                        "contextRole": "optional-external-context",
                        "sourceOfTruth": False,
                        "proof": False,
                        "citation": source["citation"],
                        "sourceDigest": source["sourceDigest"],
                        "redactionStatus": redaction["status"],
                        "text": sanitized,
                    }
                )
    except UnicodeDecodeError:
        blockers.append({"code": "external-context-source-not-utf8", "sourceLabel": label})
    except OSError as exc:
        blockers.append({"code": "external-context-source-read-failed", "sourceLabel": label, "reason": exc.__class__.__name__})
    body = {
        "schemaVersion": EXTERNAL_CONTEXT_RECEIPT_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "enabledByDefault": False,
        "activationMode": "explicit-command",
        "rawContentStored": False,
        "proofAuthority": "none",
        "resourceCaps": {
            "maxInputBytes": max_input_bytes,
            "targetTokens": target_tokens,
            "maxHintChars": max_hint_chars,
        },
        "source": source,
        "redaction": redaction,
        "hints": hints,
        "hintCount": len(hints),
        "blockers": blockers,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "providerApiCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    body["estimatedTokens"] = estimate_tokens(body)
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "external-context-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"] or not hints:
        body["status"] = "FAIL"
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_external_context_import_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-external-context-receipt", "external context receipt must be an object")
    if receipt.get("schemaVersion") != EXTERNAL_CONTEXT_RECEIPT_SCHEMA:
        blockers.append({"code": "external-context-schema-invalid"})
    if receipt.get("status") != "PASS":
        blockers.append({"code": "external-context-status-not-pass", "status": receipt.get("status")})
    if receipt.get("sourceOfTruth") is not False:
        blockers.append({"code": "external-context-source-of-truth"})
    if receipt.get("enabledByDefault") is not False:
        blockers.append({"code": "external-context-default-enabled"})
    if receipt.get("activationMode") != "explicit-command":
        blockers.append({"code": "external-context-activation-mode"})
    if receipt.get("rawContentStored") is not False:
        blockers.append({"code": "external-context-raw-content-stored"})
    for field in ("modelCallsStarted", "networkCallsStarted", "providerApiCallsStarted", "productionPromotionClaimed"):
        if receipt.get(field) is not False:
            blockers.append({"code": "external-context-forbidden-claim", "field": field})
    source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    if source.get("sourcePathStored") is not False:
        blockers.append({"code": "external-context-source-path-stored"})
    hints = receipt.get("hints")
    if not isinstance(hints, list):
        blockers.append({"code": "external-context-hints-invalid"})
        hints = []
    for index, hint in enumerate(hints):
        _validate_hint(hint, index, blockers)
    if receipt.get("hintCount") != len(hints):
        blockers.append({"code": "external-context-hint-count-mismatch"})
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    if _contains_secret_like(rendered):
        blockers.append({"code": "external-context-secret-leakage"})
    if contains_local_absolute_path(rendered):
        blockers.append({"code": "external-context-private-path-leakage"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "external-context-digest-mismatch"})
    body = {
        "schemaVersion": EXTERNAL_CONTEXT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "hintCount": len(hints),
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def external_context_hints_from_receipts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project validated external context receipts into retrieval hints."""

    hints: list[dict[str, Any]] = []
    for receipt in receipts:
        require_external_context_import_pass(validate_external_context_import_receipt(receipt))
        source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
        for hint in receipt.get("hints", []):
            if not isinstance(hint, dict):
                continue
            hints.append(
                {
                    "hintId": hint.get("hintId"),
                    "contextRole": "optional-external-context",
                    "sourceOfTruth": False,
                    "proof": False,
                    "citation": hint.get("citation") or source.get("citation"),
                    "sourceDigest": hint.get("sourceDigest") or source.get("sourceDigest"),
                    "redactionStatus": hint.get("redactionStatus"),
                    "text": hint.get("text"),
                }
            )
    return hints


def require_external_context_import_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("external-context-import-failed", "external context import validation failed", {"validation": payload})
    return payload


def _decode_context_text(data: bytes) -> str:
    text = data.decode("utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _sanitize_text(text: str, *, max_chars: int) -> tuple[str, dict[str, Any]]:
    redaction = _empty_redaction()
    sanitized, _changed, stats = redact_text_with_stats(text)
    sanitized = sanitized.replace(LOCAL_PATH_REDACTION, "[LOCAL_PATH]").replace("<redacted>", "[REDACTED]")
    redaction["localPathsRedacted"] = stats["localPathsRedacted"]
    redaction["secretLikeMarkersRedacted"] = stats["secretLikeMarkersRedacted"]
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if len(sanitized) > max_chars:
        sanitized = sanitized[:max_chars].rstrip()
        redaction["truncated"] = True
    if redaction["secretLikeMarkersRedacted"] or redaction["localPathsRedacted"]:
        redaction["status"] = "REDACTED"
    return sanitized, redaction


def _sanitize_citation(value: str) -> str:
    sanitized, _redaction = _sanitize_text(value, max_chars=240)
    return sanitized or "external-context"


def _empty_redaction() -> dict[str, Any]:
    return {
        "status": "PASS",
        "secretLikeMarkersRedacted": 0,
        "localPathsRedacted": 0,
        "truncated": False,
        "rawContentStored": False,
        "secretValuesStored": False,
        "privatePathsStored": False,
    }


def _validate_hint(hint: Any, index: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(hint, dict):
        blockers.append({"code": "external-context-hint-invalid", "index": index})
        return
    for key in ("hintId", "contextRole", "sourceOfTruth", "proof", "citation", "sourceDigest", "redactionStatus", "text"):
        if key not in hint:
            blockers.append({"code": "external-context-hint-field-missing", "index": index, "field": key})
    if hint.get("contextRole") != "optional-external-context":
        blockers.append({"code": "external-context-hint-role-invalid", "index": index})
    if hint.get("sourceOfTruth") is not False or hint.get("proof") is not False:
        blockers.append({"code": "external-context-hint-authority-invalid", "index": index})
    if hint.get("redactionStatus") not in {"PASS", "REDACTED"}:
        blockers.append({"code": "external-context-hint-redaction-invalid", "index": index})


def _contains_secret_like(value: str) -> bool:
    sanitized, changed = redact_text(value)
    return changed and sanitized != value


def _positive_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("invalid-resource-cap", f"{field} must be a positive integer", {"field": field})


def _safe_label(value: str) -> str:
    label = re.sub(r"\s+", " ", value.strip())
    label, _changed, _stats = redact_text_with_stats(label)
    label = label.replace(LOCAL_PATH_REDACTION, "[LOCAL_PATH]").replace("<redacted>", "[REDACTED]")
    return label[:120] or "external-context"
