"""Usage/session export aggregation from local lifecycle artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, sha256_hex

USAGE_EXPORT_SCHEMA = "agent-usage-export.v1"
USAGE_EXPORT_VALIDATION_SCHEMA = "agent-usage-export-validation.v1"
USAGE_EXPORT_GENERATION_SCHEMA = "agent-usage-export-generation.v1"

_SECRET_MARKERS = (
    "BEGIN " + "RSA PRIVATE KEY",
    "BEGIN " + "OPENSSH PRIVATE KEY",
    "BEGIN " + "PRIVATE KEY",
    "github" + "_pat_",
    "gh" + "p_",
    "xo" + "xb-",
)
_LOCAL_PATH_PREFIXES = ("/Vol" "umes/", "/Us" "ers/")


def build_usage_export(*, artifact_paths: list[Path], project_root: Path | None = None) -> dict[str, Any]:
    """Build a deterministic usage export from explicit local JSON artifacts."""

    if not artifact_paths:
        raise LifecycleError("usage-export-artifacts-required", "at least one artifact path is required")
    root = (project_root or Path.cwd()).resolve()
    source_artifacts: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, raw_path in enumerate(artifact_paths):
        payload, source = _load_artifact(raw_path, root)
        source_artifacts.append(source)
        entry = _entry_from_payload(index, source, payload)
        entries.append(entry)
        blockers.extend(_redaction_blockers(entry, index))
    totals = usage_export_totals(entries)
    body = {
        "schemaVersion": USAGE_EXPORT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "generatedBy": "agent-lifecycle metrics usage-export",
        "sourceArtifacts": source_artifacts,
        "lineage": _lineage(entries),
        "entries": entries,
        "totals": totals,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "exportDigest": canonical_digest(body)}


def validate_usage_export(export: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-built usage export."""

    blockers: list[dict[str, Any]] = []
    if export.get("schemaVersion") != USAGE_EXPORT_SCHEMA:
        blockers.append({"code": "usage-export-schema", "message": "unsupported usage export schemaVersion"})
    if export.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "usage-export-production-claim", "message": "usage export must not claim production promotion"})
    entries = export.get("entries")
    if not isinstance(entries, list) or not entries:
        blockers.append({"code": "usage-export-entries", "message": "entries must be a non-empty array"})
        entries = []
    for index, entry in enumerate(entries):
        _validate_entry(index, entry, blockers)
    valid_entries = [entry for entry in entries if isinstance(entry, dict)]
    totals = usage_export_totals(valid_entries)
    if isinstance(export.get("totals"), dict) and export["totals"] != totals:
        blockers.append({"code": "usage-export-totals-mismatch", "message": "totals do not match entries"})
    blockers.extend(_redaction_blockers(export, "export"))
    body = {
        "schemaVersion": USAGE_EXPORT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "entryCount": len(entries),
        "totals": totals,
        "blockers": blockers,
        "exportDigest": canonical_digest(export),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_usage_export_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") == "FAIL":
        raise LifecycleError("usage-export-validation-failed", "usage export validation failed", {"validation": validation})
    return validation


def usage_export_totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = {"input": 0, "output": 0, "total": 0}
    steps = 0
    duration_ms = 0
    resource_totals: dict[str, int] = {}
    metered_entries = 0
    host_reported_cost_total = 0.0
    host_reported_cost_count = 0
    for entry in entries:
        usage = entry.get("tokens") if isinstance(entry.get("tokens"), dict) else {}
        tokens["input"] += _non_negative_int(usage.get("input"))
        tokens["output"] += _non_negative_int(usage.get("output"))
        tokens["total"] += _non_negative_int(usage.get("total"))
        steps += _non_negative_int(entry.get("steps"))
        duration_ms += _non_negative_int(entry.get("durationMs"))
        resources = entry.get("resources") if isinstance(entry.get("resources"), dict) else {}
        for key, value in resources.items():
            if isinstance(key, str):
                resource_totals[key] = resource_totals.get(key, 0) + _non_negative_int(value)
        monetary = entry.get("monetary") if isinstance(entry.get("monetary"), dict) else None
        if monetary is not None:
            metered_entries += 1
            amount = monetary.get("cost_usd")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                host_reported_cost_total += float(amount)
                host_reported_cost_count += 1
    return {
        "tokens": tokens,
        "steps": steps,
        "durationMs": duration_ms,
        "resources": dict(sorted(resource_totals.items())),
        "entries": len(entries),
        "meteredEntries": metered_entries,
        "hostReportedCost": {
            "currency": "USD",
            "entryCount": host_reported_cost_count,
            "total": round(host_reported_cost_total, 6),
            "canonical": False,
        },
    }


def _load_artifact(raw_path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = raw_path if raw_path.is_absolute() else root / raw_path
    display_path = _display_path(path, root)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LifecycleError("usage-export-artifact-unavailable", "usage export artifact cannot be read", {"path": display_path}) from exc
    payload = load_json_object(data, label=display_path)
    source = {
        "path": display_path,
        "sha256": sha256_hex(data),
        "bytes": len(data),
        "schemaVersion": payload.get("schemaVersion"),
        "payloadDigest": canonical_digest(payload),
    }
    return payload, source


def _entry_from_payload(index: int, source: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "entryId": f"usage-{index + 1}",
        "source": source,
        "schemaVersion": payload.get("schemaVersion"),
        "adapterId": _first_string(payload, ("adapterId", "host", "adapter")),
        "sessionId": _first_string(payload, ("sessionId", "runId")),
        "attemptId": _first_string(payload, ("attemptId", "attempt")),
        "runId": _string_or_none(payload.get("runId")),
        "packageId": _string_or_none(payload.get("packageId")),
        "taskId": _first_string(payload, ("taskId", "task")),
        "operationId": _string_or_none(payload.get("operationId")),
        "receiptDigests": _receipt_digests(payload),
        "tokens": _tokens(payload),
        "steps": _steps(payload),
        "resources": _resources(payload),
        "durationMs": _duration_ms(payload),
        "budgetDecision": _budget_decision(payload),
    }
    monetary = _monetary(payload)
    if monetary is not None:
        entry["monetary"] = monetary
    return entry


def _tokens(payload: dict[str, Any]) -> dict[str, int]:
    for candidate in (payload.get("usage"), payload.get("usageTotals"), payload.get("tokenUsage"), payload.get("tokens"), payload.get("counters")):
        if not isinstance(candidate, dict):
            continue
        input_tokens = _first_int(candidate, ("inputTokens", "promptTokens", "input"))
        output_tokens = _first_int(candidate, ("outputTokens", "completionTokens", "output"))
        total_tokens = _first_int(candidate, ("totalTokens", "reportedTokens", "billableTokens", "tokens", "total"))
        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = _non_negative_int(input_tokens) + _non_negative_int(output_tokens)
        if input_tokens is not None or output_tokens is not None or total_tokens is not None:
            return {
                "input": _non_negative_int(input_tokens),
                "output": _non_negative_int(output_tokens),
                "total": _non_negative_int(total_tokens),
            }
    return {"input": 0, "output": 0, "total": 0}


def _steps(payload: dict[str, Any]) -> int:
    for candidate in (payload.get("usage"), payload.get("usageTotals"), payload.get("counters"), payload):
        if isinstance(candidate, dict):
            value = _first_int(candidate, ("steps", "toolCalls", "validationRuns", "iterations"))
            if value is not None:
                return max(0, value)
    return 1


def _resources(payload: dict[str, Any]) -> dict[str, int]:
    resources: dict[str, int] = {}
    for candidate in (payload.get("resources"), payload.get("resourceUsage"), payload.get("usage"), payload.get("counters")):
        if not isinstance(candidate, dict):
            continue
        for source_key, export_key in (
            ("cumulativeContextBytes", "contextBytes"),
            ("contextBytes", "contextBytes"),
            ("filesChanged", "filesChanged"),
            ("toolCalls", "toolCalls"),
            ("validationRuns", "validationRuns"),
            ("cpuMs", "cpuMs"),
            ("memoryMb", "memoryMb"),
        ):
            value = candidate.get(source_key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                resources[export_key] = resources.get(export_key, 0) + value
    return dict(sorted(resources.items()))


def _duration_ms(payload: dict[str, Any]) -> int:
    for candidate in (payload.get("usage"), payload.get("duration"), payload.get("timing"), payload):
        if not isinstance(candidate, dict):
            continue
        value = _first_int(candidate, ("durationMs", "elapsedMs", "wallMs"))
        if value is not None:
            return max(0, value)
        seconds = _number(candidate.get("durationSeconds")) or _number(candidate.get("wallSeconds"))
        if seconds is not None:
            return max(0, int(round(seconds * 1000)))
    return 0


def _budget_decision(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("budgetDecision", "budget", "routeDecision"):
        value = payload.get(key)
        if isinstance(value, dict):
            return {
                item_key: _safe_scalar(item)
                for item_key, item in sorted(value.items())
                if item_key in {"action", "decision", "mode", "reason", "status", "limit", "remainingTokens"}
                and isinstance(item, (str, int, float, bool))
            }
    return None


def _monetary(payload: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in (payload.get("hostReportedCost"), payload.get("monetary"), payload.get("usage")):
        if not isinstance(candidate, dict) or "cost_usd" not in candidate:
            continue
        return {
            "hostReported": True,
            "currency": "USD",
            "cost_usd": _cost_or_none(candidate.get("cost_usd")),
            "canonical": False,
        }
    return None


def _receipt_digests(payload: dict[str, Any]) -> list[str]:
    digests: set[str] = set()
    _collect_digest_values(payload, digests)
    return sorted(digests)


def _collect_digest_values(value: Any, digests: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("Digest") and isinstance(item, str) and len(item) == 64:
                digests.add(item)
            _collect_digest_values(item, digests)
    elif isinstance(value, list):
        for item in value:
            _collect_digest_values(item, digests)


def _lineage(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    keys = ("adapterId", "sessionId", "runId", "packageId", "taskId", "operationId")
    return {
        f"{key}s": sorted({entry[key] for entry in entries if isinstance(entry.get(key), str) and entry[key]})
        for key in keys
    }


def _validate_entry(index: int, entry: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(entry, dict):
        blockers.append({"code": "usage-export-entry-type", "index": index})
        return
    tokens = entry.get("tokens")
    if not isinstance(tokens, dict):
        blockers.append({"code": "usage-export-entry-tokens", "index": index})
    else:
        for key in ("input", "output", "total"):
            if not isinstance(tokens.get(key), int) or isinstance(tokens.get(key), bool) or tokens.get(key) < 0:
                blockers.append({"code": "usage-export-entry-token-value", "index": index, "field": key})
    if not isinstance(entry.get("steps"), int) or isinstance(entry.get("steps"), bool) or entry.get("steps") < 0:
        blockers.append({"code": "usage-export-entry-steps", "index": index})
    if not isinstance(entry.get("durationMs"), int) or isinstance(entry.get("durationMs"), bool) or entry.get("durationMs") < 0:
        blockers.append({"code": "usage-export-entry-duration", "index": index})
    monetary = entry.get("monetary")
    if monetary is not None:
        _validate_monetary(index, monetary, blockers)


def _validate_monetary(index: int, monetary: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(monetary, dict):
        blockers.append({"code": "usage-export-monetary-type", "index": index})
        return
    if monetary.get("hostReported") is not True or monetary.get("canonical") is not False:
        blockers.append({"code": "usage-export-monetary-authority", "index": index})
    if monetary.get("currency") != "USD":
        blockers.append({"code": "usage-export-monetary-currency", "index": index})
    amount = monetary.get("cost_usd")
    if amount is not None and (not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0):
        blockers.append({"code": "usage-export-monetary-amount", "index": index})


def _redaction_blockers(value: Any, index: int | str) -> list[dict[str, Any]]:
    text = str(value)
    blockers = []
    if any(prefix in text for prefix in _LOCAL_PATH_PREFIXES):
        blockers.append({"code": "usage-export-local-path-leak", "index": index})
    for marker in _SECRET_MARKERS:
        if marker in text:
            blockers.append({"code": "usage-export-secret-marker-leak", "index": index})
    return blockers


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        text = _string_or_none(value)
        if text is not None:
            return text
    return None


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return _safe_string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _first_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _non_negative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _cost_or_none(value: Any) -> float | None:
    amount = _number(value)
    if amount is None or amount < 0:
        return None
    return round(amount, 6)


def _safe_scalar(value: str | int | float | bool) -> str | int | float | bool:
    return _safe_string(value) if isinstance(value, str) else value


def _safe_string(value: str) -> str:
    text = re.sub(r"/(?:Volumes|Users)/\S+", "<redacted-local-path>", value)
    for marker in _SECRET_MARKERS:
        if marker in text:
            text = text.replace(marker, "<redacted-secret>")
    return text
