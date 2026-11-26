"""Evaluate a declared local review budget without substituting estimates for observations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, TypeGuard

BUDGET_SCHEMA = "agent-plan-review-budget-snapshot.v1"
_MAX_TOKEN_COUNT = (1 << 63) - 1
_MAX_FRESHNESS = timedelta(hours=1)


def _tokens(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_TOKEN_COUNT:
        raise ValueError("Invalid token count")
    return value


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a UTC offset")
    return parsed


def _require_observation(snapshot: dict[str, Any], now: datetime) -> int:
    previous = _time(snapshot["previousObservedAt"])
    observed = _time(snapshot["observedAt"])
    until = _time(snapshot["validUntil"])
    prior_gross = _tokens(snapshot["previousGrossTokens"])
    gross = _tokens(snapshot["grossTokens"])
    if not previous < observed <= now < until or until - observed > _MAX_FRESHNESS:
        raise ValueError("Snapshot times are stale, out of order, or outside the freshness bound")
    if gross < prior_gross:
        raise ValueError("Gross tokens decreased")
    return gross


def _group(rows: list[dict[str, Any]], seen: set[str], amount: str) -> tuple[int, bool]:
    if not isinstance(rows, list) or len(rows) > 128:
        raise ValueError("Invalid reservation list")
    total = 0
    unknown = False
    for item in rows:
        identity = item["operationId"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Operation identities must be unique within the accounting window")
        seen.add(identity)
        count = item[amount]
        if count is None and amount == "unreportedTokens":
            unknown = True
        else:
            total += _tokens(count)
    return total, unknown


def _decision(status: str, reason: str, *, lower: int | None = None, upper: int | None = None) -> dict[str, Any]:
    return {"status": status, "reasonCode": reason, "lowerBoundTokens": lower, "upperBoundTokens": upper}


def evaluate_preparation_budget(
    snapshot: dict[str, Any], *, now: datetime, packet_sha256: str, command_digest: str
) -> dict[str, Any]:
    """Use ordered gross observations, named reserves and an explicitly bound cold-cache upper bound."""
    try:
        if snapshot["schemaVersion"] != BUDGET_SCHEMA:
            raise ValueError("Unknown snapshot format")
        gross = _require_observation(snapshot, now)
        ceiling = _tokens(snapshot["ceilingTokens"])
        seen: set[str] = set()
        reserved, _ = _group(snapshot["reserves"], seen, "tokens")
        unreported, unknown = _group(snapshot["startedAbsentFromGross"], seen, "unreportedTokens")
        lower = gross + reserved + unreported
    except (AttributeError, KeyError, TypeError, ValueError):
        return _decision("DEFERRED", "BUDGET_OBSERVATION_INVALID")

    if lower > ceiling:
        return _decision("INSUFFICIENT", "BUDGET_LOWER_BOUND_EXCEEDS_CEILING", lower=lower)
    bound = snapshot.get("coldCacheBound")
    if unknown or not _bound_matches(bound, packet_sha256, command_digest):
        return _decision("DEFERRED", "BUDGET_UPPER_BOUND_UNQUALIFIED", lower=lower)
    try:
        upper = lower + _tokens(bound["tokens"])
    except (KeyError, TypeError, ValueError):
        return _decision("DEFERRED", "BUDGET_UPPER_BOUND_UNQUALIFIED", lower=lower)
    if upper > ceiling:
        return _decision("DEFERRED", "BUDGET_UPPER_BOUND_EXCEEDS_CEILING", lower=lower, upper=upper)
    return _decision("READY", "BUDGET_FITS_WITH_COLD_CACHE", lower=lower, upper=upper)


def _bound_matches(bound: object, packet_sha256: str, command_digest: str) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(bound, dict)
        and bound.get("qualification") == "DECLARED_LOCAL"
        and bound.get("packetSha256") == packet_sha256
        and bound.get("commandDigest") == command_digest
        and isinstance(bound.get("basis"), str)
        and bool(bound["basis"].strip())
    )
