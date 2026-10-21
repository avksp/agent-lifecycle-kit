"""Bounded progress projection from already qualified operation observations."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

MAX_OBSERVATIONS = 64
STATES = ("ADVANCING", "STALLED", "EXPECTED_WAIT", "UNAVAILABLE")
_BINDINGS = ("goalDigest", "phaseDigest", "subjectDigest", "sourceRevision")
_OBLIGATIONS = ("criteriaDigests", "evidenceDigests", "outcomeDigests")
_OBSERVATION_FIELDS = {
    *_BINDINGS,
    "stateRevision",
    "operationDigest",
    "qualificationDigest",
    "acceptedCriteria",
    "qualifiedEvidence",
    "verifiedOutcomes",
    "kind",
    "semanticRoundCompleted",
    "observedAt",
    "waitingUntil",
    "waitAuthorizationDigest",
}


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _identities(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 256
        and all(_digest(item) for item in value)
        and len(set(value)) == len(value)
    )


def build_goal_progress(
    context: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    qualified_receipts: dict[str, dict[str, Any]],
    now: int,
) -> dict[str, Any]:
    """No I/O or attestation: the caller owns provenance of checked receipts.

    A digest alone is never qualification. Each source observation must join a
    separately checked receipt for this exact operation and current subject.
    The result grants neither execution authority nor permission to retry.
    """
    _context(context, observations, now)
    if not isinstance(qualified_receipts, dict) or len(qualified_receipts) > MAX_OBSERVATIONS + 1:
        raise LifecycleError("goal-progress-qualification-invalid", "Bounded qualified inputs are required")
    state, reason, stalled = "UNAVAILABLE", "qualified-history-required", 0
    history = qualified_receipts.get(context["historyDigest"], {})
    complete = (
        isinstance(history, dict)
        and history.get("status") == "PASS"
        and history.get("provenanceValidated") is True
        and history.get("completePrefix") is True
        and history.get("historyDigest") == context["historyDigest"]
        and history.get("stateRevision") == context["stateRevision"]
        and history.get("obligationsDigest") == canonical_digest({key: context[key] for key in _OBLIGATIONS})
        and all(history.get(key) == context[key] for key in _BINDINGS)
    )
    if not complete:
        reason = "complete-qualified-prefix-required"
    elif not observations:
        if context["verifiedInitial"] is True and context["stateRevision"] == 0:
            state, reason = "ADVANCING", "verified-initial-context"
    else:
        state, reason, stalled = _derive(
            context,
            observations,
            qualified_receipts,
            now,
        )
    body = {
        "schemaVersion": "agent-goal-progress-observation.v1",
        "state": state,
        "reasonCode": reason,
        "nonproductiveRounds": stalled,
        "initialContext": not observations and state != "UNAVAILABLE",
        "observationCount": len(observations),
        "historyDigest": canonical_digest(observations),
        **{key: context[key] for key in _BINDINGS},
        "stateRevision": context["stateRevision"],
        "obligationsDigest": canonical_digest({key: context[key] for key in _OBLIGATIONS}),
        "qualification": "CALLER_VERIFIED_INPUTS_ONLY",
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "progressDigest": canonical_digest(body)}


def _context(context: Any, observations: Any, now: Any) -> None:
    fields = {*_BINDINGS, *_OBLIGATIONS, "stateRevision", "verifiedInitial", "historyDigest"}
    if not isinstance(context, dict) or set(context) != fields:
        raise LifecycleError("goal-progress-context-invalid", "Exact progress context is required")
    if (
        not all(_digest(context[key]) for key in _BINDINGS if key != "sourceRevision")
        or not isinstance(context["sourceRevision"], str)
        or len(context["sourceRevision"]) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in context["sourceRevision"])
        or type(context["stateRevision"]) is not int
        or context["stateRevision"] < 0
        or type(context["verifiedInitial"]) is not bool
        or not all(_identities(context[key]) for key in _OBLIGATIONS)
        or not isinstance(observations, list)
        or len(observations) > MAX_OBSERVATIONS
        or type(now) is not int
        or now < 0
    ):
        raise LifecycleError("goal-progress-context-invalid", "Progress context is unbounded or invalid")
    if canonical_digest(observations) != context["historyDigest"]:
        raise LifecycleError("goal-progress-history-invalid", "Progress history binding differs")


def _qualified(
    observation: dict[str, Any],
    context: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
) -> bool:
    if set(observation) != _OBSERVATION_FIELDS:
        return False
    if not _digest(observation["qualificationDigest"]):
        return False
    if any(observation[key] != context[key] for key in _BINDINGS):
        return False
    if not all(
        _identities(observation[key])
        for key in (
            "acceptedCriteria",
            "qualifiedEvidence",
            "verifiedOutcomes",
        )
    ):
        return False
    # These are stable approved obligation identities, never artifact hashes.
    if any(
        not set(observation[observed]) <= set(context[allowed])
        for observed, allowed in (
            ("acceptedCriteria", "criteriaDigests"),
            ("qualifiedEvidence", "evidenceDigests"),
            ("verifiedOutcomes", "outcomeDigests"),
        )
    ):
        return False
    receipt = receipts.get(observation["qualificationDigest"])
    if not isinstance(receipt, dict):
        return False
    return (
        receipt.get("status") == "PASS"
        and receipt.get("operationDigest") == observation["operationDigest"]
        and all(receipt.get(key) == context[key] for key in _BINDINGS)
        and receipt.get("observationDigest") == canonical_digest(observation)
        and receipt.get("provenanceValidated") is True
    )


def _derive(
    context: dict[str, Any],
    observations: list[dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
    now: int,
) -> tuple[str, str, int]:
    previous_revision = -1
    previous_time = 0
    seen: set[str] = set()
    accepted: set[str] = set()
    evidence: set[str] = set()
    outcomes: set[str] = set()
    stalled = 0
    state, reason = "UNAVAILABLE", "comparable-history-required"
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict) or not _qualified(observation, context, receipts):
            return "UNAVAILABLE", "observation-not-qualified", 0
        revision, operation = observation["stateRevision"], observation["operationDigest"]
        if (
            type(revision) is not int
            or revision <= previous_revision
            or not _digest(operation)
            or operation in seen
            or type(observation["semanticRoundCompleted"]) is not bool
            or observation["kind"] not in {"WORK", "AUDIT", "DIAGNOSIS", "WAIT"}
            or type(observation["observedAt"]) is not int
            or not previous_time <= observation["observedAt"] <= now
        ):
            return "UNAVAILABLE", "history-order-or-identity-invalid", 0
        previous_revision = revision
        previous_time = observation["observedAt"]
        seen.add(operation)
        current = [
            set(observation[key])
            for key in (
                "acceptedCriteria",
                "qualifiedEvidence",
                "verifiedOutcomes",
            )
        ]
        if not all(old <= new for old, new in zip((accepted, evidence, outcomes), current, strict=True)):
            return "UNAVAILABLE", "history-regressed-or-incomparable", 0
        improved = any(new - old for old, new in zip((accepted, evidence, outcomes), current, strict=True))
        accepted, evidence, outcomes = current
        if observation["kind"] == "WAIT":
            if (
                type(observation["waitingUntil"]) is not int
                or not observation["observedAt"] < observation["waitingUntil"] <= observation["observedAt"] + 86400
                or not _digest(observation["waitAuthorizationDigest"])
                or observation["semanticRoundCompleted"]
                or improved
            ):
                return "UNAVAILABLE", "wait-not-bounded-or-authorized", 0
            if index == len(observations) - 1 and observation["waitingUntil"] <= now:
                return "UNAVAILABLE", "current-wait-expired", 0
            state, reason = "EXPECTED_WAIT", "authorized-bounded-wait"
        elif index == 0:
            state, reason = "UNAVAILABLE", "comparable-history-required"
        elif improved:
            state, reason, stalled = "ADVANCING", "qualified-outcome-added", 0
        else:
            if observation["semanticRoundCompleted"]:
                stalled += 1
            state, reason = "STALLED", "no-new-qualified-outcome"
    if previous_revision != context["stateRevision"]:
        return "UNAVAILABLE", "history-not-current", 0
    return state, reason, stalled
