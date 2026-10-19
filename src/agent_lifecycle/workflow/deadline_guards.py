"""Complete original-consumer deadline assessment; comparison data grants no authority."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.deadline_schemas import DURATION_RULE_V1, utc_microseconds
from agent_lifecycle.contracts.deadlines import (
    evaluate_original_duration,
    evaluate_original_freshness,
    evaluate_original_permission,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schemas import get_schema

_MAX_CONSUMERS = 4096
_DURATION_KINDS = frozenset(get_schema(DURATION_RULE_V1)["properties"]["kind"]["enum"])


def evaluate_deadline_guards(
    consumers: list[dict[str, Any]],
    *,
    expected_consumer_ids: list[str],
    observed_at: str,
) -> dict[str, Any]:
    """Compare all independently selected consumer inputs without replacing original rules.

    Selection and the clock's authenticity remain external. A DATA_CANDIDATE
    is not a native pre-dispatch permit or permission to retry completed work.
    """
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "consumers": [],
        "nativeClockQualified": False,
        "nativePermissionGranted": False,
        "dispatchAuthorized": False,
        "financialAdmission": False,
        "originalRulesReplaced": False,
    }
    try:
        utc_microseconds(observed_at)
        if (
            type(expected_consumer_ids) is not list
            or not expected_consumer_ids
            or len(expected_consumer_ids) > _MAX_CONSUMERS
            or any(type(v) is not str or not 1 <= len(v) <= 256 for v in expected_consumer_ids)
            or len(set(expected_consumer_ids)) != len(expected_consumer_ids)
        ):
            raise LifecycleError("deadline-guard-invalid", "Complete unique consumer selection required")
        if type(consumers) is not list or len(consumers) > _MAX_CONSUMERS:
            raise LifecycleError("deadline-guard-invalid", "Bounded consumer records required")
        if len(canonical_bytes(consumers)) > 1_048_576:
            raise LifecycleError("deadline-guard-invalid", "Consumer records exceed the byte limit")
        ids = []
        for consumer in consumers:
            if (
                type(consumer) is not dict
                or set(consumer) != {"consumerId", "rule", "generatedAt"}
                or type(consumer["consumerId"]) is not str
                or not 1 <= len(consumer["consumerId"]) <= 256
            ):
                raise LifecycleError("deadline-guard-invalid", "Closed consumer identity required")
            ids.append(consumer["consumerId"])
        if len(set(ids)) != len(ids):
            raise LifecycleError("deadline-guard-invalid", "Duplicate consumer identity")
        if set(ids) != set(expected_consumer_ids):
            return {**result, "reason": "Consumer inventory differs from the independent selection"}
        rows = []
        for consumer in consumers:
            rule = consumer["rule"]
            comparison = {"disposition": "UNAVAILABLE"}
            if rule is not None:
                if type(rule) is not dict:
                    raise LifecycleError("deadline-guard-invalid", "Rule must be a record or unavailable")
                kind = rule.get("kind")
                if kind == "EXECUTION_PERMISSION":
                    comparison = evaluate_original_permission(rule, observed_at)
                elif kind in _DURATION_KINDS:
                    comparison = evaluate_original_duration(rule, observed_at)
                elif kind == "EVIDENCE_FRESHNESS":
                    if consumer["generatedAt"] is not None:
                        comparison = evaluate_original_freshness(rule, consumer["generatedAt"], observed_at)
                else:
                    raise LifecycleError("deadline-guard-invalid", "Unregistered original rule kind")
            rows.append(
                {"consumerId": consumer["consumerId"], "originalInput": deepcopy(consumer), "comparison": comparison}
            )
        result["consumers"] = rows
        dispositions = {row["comparison"]["disposition"] for row in rows}
        result["status"] = (
            "REFUSED"
            if dispositions - {"DATA_CANDIDATE", "UNAVAILABLE"}
            else "UNAVAILABLE"
            if "UNAVAILABLE" in dispositions
            else "DATA_CANDIDATE"
        )
    except LifecycleError as error:
        result.update(status="DENY", errorCode=error.code, reason=str(error))
    except (TypeError, ValueError, RecursionError) as error:
        result.update(status="DENY", errorCode="deadline-guard-invalid", reason=type(error).__name__)
    return result


__all__ = ["evaluate_deadline_guards"]
