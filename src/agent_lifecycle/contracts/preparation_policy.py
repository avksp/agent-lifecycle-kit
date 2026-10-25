"""Pure preparation decisions for already qualified controller observations.

Inputs are not authority or host attestation. Effect owners must freshly obtain
them through their trusted controller/Journal boundary before each effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.errors import LifecycleError

POLICY_SCHEMA = "agent-preparation-policy-context.v1"
QUANTITIES = frozenset({"RESERVATION_TOKENS", "SELECTED_ALK_INPUT"})
REVIEW_PREFLIGHT_FIELDS = frozenset(
    {
        "schemaVersion",
        "status",
        "reason",
        "sourceSnapshotDigest",
        "packetDigest",
        "requestDigest",
        "invocationDigest",
        "modelCalls",
        "authorityClaimed",
        "productionPromotionClaimed",
        "preflightDigest",
    }
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX = (1 << 63) - 1
T = TypeVar("T")


class PreparationAdmission(Protocol):
    """Trusted higher-layer integration port, never a serialized permission."""

    def check(self, *, repository_root: Path | None = None) -> dict[str, Any]: ...

    def invoke(
        self,
        effect: Callable[[], T],
        *,
        input_digest: str,
        repository_root: Path | None = None,
    ) -> T: ...

    def check_retry(
        self,
        *,
        prior_request_digest: str,
        prior_result_digest: str,
        retry_ordinal: int,
    ) -> None: ...


def _uint(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or not int(positive) <= value <= _MAX:
        raise ValueError("Finite preparation integer required")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("Preparation identity digest required")
    return value


def review_invocation_digest(
    *,
    request: dict[str, Any],
    argv: list[str],
    root_digest: str,
    rendered_input: bytes,
) -> str:
    """Pure identity shared by reviewer preflight and its real bounded sink."""
    if (
        not isinstance(rendered_input, bytes)
        or not 1 <= len(rendered_input) <= 1024 * 1024
        or not isinstance(argv, list)
        or not 1 <= len(argv) <= 64
        or any(not isinstance(v, str) or not v or len(v) > 4096 for v in argv)
    ):
        raise ValueError("Bounded exact review invocation required")
    return canonical_digest(
        {
            "requestDigest": _digest(request["requestDigest"]),
            "sourceSnapshotDigest": _digest(request["sourceSnapshotDigest"]),
            "argvDigest": canonical_digest(argv),
            "rootDigest": _digest(root_digest),
            "renderedInputDigest": hashlib.sha256(rendered_input).hexdigest(),
            "renderedInputBytes": len(rendered_input),
            "inputTransport": "STDIN",
        }
    )


def _decision(reason: str, identity: str | None) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-preparation-decision.v1",
        "status": "PASS" if reason == "READY" else "REFUSED",
        "reason": reason,
        "contextDigest": identity,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "decisionDigest": canonical_digest(body)}


def _authority_reason(context: dict[str, Any], usage: dict[str, Any], grant: dict[str, Any], now: int) -> str | None:
    _digest(grant["digest"])
    if grant["qualified"] is not True or now >= _uint(grant["expiresAt"]):
        return "PREPARATION_AUTHORITY_UNAVAILABLE"
    if now >= _uint(context["nativeDeadlineAt"]):
        return "PREPARATION_NATIVE_DEADLINE_EXPIRED"
    if context["quantity"] not in QUANTITIES:
        return "PREPARATION_QUANTITY_UNSUPPORTED"
    if usage["quantity"] != context["quantity"]:
        return "PREPARATION_QUANTITY_UNSUPPORTED"
    return None


def _review_chain_reason(context: dict[str, Any], grant: dict[str, Any], now: int) -> str | None:
    chain = context["chain"]
    required = chain["required"]
    slots = chain["slots"]
    if (
        not isinstance(required, list)
        or not 1 <= len(required) <= 64
        or len(set(required)) != len(required)
        or not isinstance(slots, list)
        or len(slots) > 64
        or any(not isinstance(x, str) or len(x) > 64 for x in required)
        or not {"integration", "final"}.issubset(required)
    ):
        return "REVIEW_CHAIN_NOT_READY"
    ready = set()
    for slot in slots:
        if (
            slot["qualified"] is True
            and slot["authorizationDigest"] == grant["digest"]
            and now < _uint(slot["expiresAt"])
            and _uint(slot["remaining"], positive=True)
        ):
            ready.add(slot["stage"])
    if not set(required).issubset(ready):
        return "REVIEW_CHAIN_NOT_READY"
    return None


def _readiness_reason(context: dict[str, Any]) -> str | None:
    readiness = context["readiness"]
    if (
        readiness["qualified"] is not True
        or readiness["sourceDigest"] != context["sourceDigest"]
        or not isinstance(readiness["checks"], dict)
        or not 1 <= len(readiness["checks"]) <= 64
        or any(value != "PASS" for value in readiness["checks"].values())
    ):
        return "PREPARATION_READINESS_UNAVAILABLE"
    return None


def _progress_reason(context: dict[str, Any], usage: dict[str, Any], grant: dict[str, Any], now: int) -> str | None:
    progress = context["progress"]
    if (
        usage["qualified"] is not True
        or progress["qualified"] is not True
        or progress["journalPrefixDigest"] != usage["prefixDigest"]
        or progress["goalDigest"] != context["goalDigest"]
        or progress["phaseDigest"] != context["phaseDigest"]
        or progress["sourceDigest"] != context["sourceDigest"]
    ):
        return "PREPARATION_HISTORY_UNAVAILABLE"
    rounds = _uint(progress["completedRounds"])
    streak = _uint(progress["nonproductiveRounds"])
    if streak > rounds:
        raise ValueError("Nonproductive rounds exceed completed history")
    initial = progress.get("verifiedInitial") is True and rounds == 0
    state = progress["status"]
    if state not in {"ADVANCING", "STALLED", "EXPECTED_WAIT"} and not (
        state == "UNAVAILABLE" and initial and usage.get("goalRequests", usage["requests"]) == 0
    ):
        return "PREPARATION_HISTORY_UNAVAILABLE"
    if state == "EXPECTED_WAIT":
        if now >= _uint(progress["waitUntil"]):
            return "PREPARATION_HISTORY_UNAVAILABLE"
        return "PROCESS_EXPECTED_WAIT"
    limit = context.get("nonproductiveRoundLimit", 2)
    _uint(limit, positive=True)
    if limit != 2 and context.get("stallOverrideAuthorization") != grant:
        return "PREPARATION_AUTHORITY_UNAVAILABLE"
    if streak >= limit:
        return "PROCESS_PROGRESS_STALLED"
    return None


def _repeat_reason(context: dict[str, Any]) -> str | None:
    repeat = context["repeat"]
    if type(repeat["required"]) is not bool:
        raise ValueError("Repeat disposition required")
    if repeat["required"] is True and (
        repeat["qualified"] is not True
        or repeat["disposition"] not in {"MISSING", "INVALIDATED"}
        or not 1 <= len(repeat["inputDigests"]) <= 64
        or any(not _digest(v) for v in repeat["inputDigests"])
        or not _digest(repeat["benefitDigest"])
    ):
        return "REPEAT_NOT_JUSTIFIED"
    return None


def _budget_reason(context: dict[str, Any], usage: dict[str, Any]) -> str | None:
    rounds = context["progress"]["completedRounds"]
    bounds, request = context["limits"], context["request"]
    for name in ("tokens", "chargedMilliseconds", "requests"):
        used = _uint(usage[name])
        amount = _uint(request[name], positive=True)
        maximum = _uint(bounds[name], positive=True)
        reserve = _uint(bounds["closeoutTokens"]) if name == "tokens" else 0
        if used + amount + reserve > maximum:
            return "PREPARATION_BUDGET_EXHAUSTED"
    if request["requests"] != 1:
        raise ValueError("One expensive request per admission")
    round_bound = _uint(bounds["semanticRounds"], positive=True)
    requested_round = _uint(request["semanticRound"], positive=True)
    if max(rounds, usage["semanticRound"], requested_round) > round_bound:
        return "PREPARATION_BUDGET_EXHAUSTED"
    return None


def evaluate_preparation_policy(
    context: dict[str, Any],
    usage: dict[str, Any],
    *,
    now: int,
) -> dict[str, Any]:
    """Fail closed without I/O, side effects, permission or inferred zeros."""
    identity = None
    try:
        raw = json.dumps(context, allow_nan=False).encode("utf-8")
        if len(raw) > 65536 or context["schemaVersion"] != POLICY_SCHEMA:
            raise ValueError("Bounded preparation context required")
        identity = canonical_digest(context)
        _uint(now)
        for name in ("goalDigest", "phaseDigest", "sourceDigest"):
            _digest(context[name])
        grant = context["authorization"]
        reason = _authority_reason(context, usage, grant, now)
        if reason is not None:
            return _decision(reason, identity)
        reason = _review_chain_reason(context, grant, now)
        if reason is not None:
            return _decision(reason, identity)
        reason = _readiness_reason(context)
        if reason is not None:
            return _decision(reason, identity)
        reason = _progress_reason(context, usage, grant, now)
        if reason is not None:
            return _decision(reason, identity)
        reason = _repeat_reason(context)
        if reason is not None:
            return _decision(reason, identity)
        reason = _budget_reason(context, usage)
        if reason is not None:
            return _decision(reason, identity)
        return _decision("READY", identity)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return _decision("PREPARATION_INPUT_UNAVAILABLE", identity)


def require_preparation_pass(decision: dict[str, Any]) -> None:
    """Use only immediately after trusted qualification, never as authority."""
    if decision.get("status") != "PASS":
        raise LifecycleError(
            str(decision.get("reason", "PREPARATION_INPUT_UNAVAILABLE")),
            "Qualified preparation requirements are not satisfied",
        )
