"""Trusted controller integration with the existing Journal, never a store.

The qualifier is an in-process trusted source port, not reviewer JSON. It must
refresh grant/readiness/progress provenance. Upper bounds remain charged across
failed or unknown work; this conservative policy never invents a refund.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from agent_lifecycle.accounting.contracts import EvidenceRef, Operation
from agent_lifecycle.accounting.journal import (
    Journal,
    JournalUnavailable,
    RevisionConflict,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.execution_target import (
    inspect_execution_target,
    require_execution_target_digest,
)
from agent_lifecycle.contracts.preparation_policy import (
    evaluate_preparation_policy,
    require_preparation_pass,
)

T = TypeVar("T")
_META_SCHEMA = "agent-preparation-operation.v1"


def local_preparation_input_digest(
    *,
    profile_digest: str,
    operation: str,
    repository_root: Path,
    source_revision: str | None,
    task_id: str | None,
    task_text: str | None,
    immutable_context: dict[str, Any] | None,
) -> str:
    """Bind the actual controlled local invocation without exporting its text."""
    return canonical_digest(
        {
            "profileDigest": profile_digest,
            "operation": operation,
            "rootDigest": canonical_digest(str(repository_root.resolve())),
            "sourceRevision": source_revision,
            "taskId": task_id,
            "taskTextDigest": hashlib.sha256(
                task_text.encode("utf-8"),
            ).hexdigest()
            if task_text is not None
            else None,
            "immutableContextDigest": canonical_digest(immutable_context) if immutable_context is not None else None,
        }
    )


@dataclass(frozen=True)
class ExecutionTargetSelection:
    """Exact real selectors used by the existing target producer."""

    root: Path
    source_identity: dict[str, Any]
    plan_identity: dict[str, Any]
    source_paths: list[str]
    outputs: list[dict[str, Any]]
    state_path: str
    event_log: str
    stage: str
    expected_digest: str

    def recheck(self) -> dict[str, Any]:
        current = inspect_execution_target(
            self.root,
            source_identity=self.source_identity,
            plan_identity=self.plan_identity,
            source_paths=self.source_paths,
            outputs=self.outputs,
            state_path=self.state_path,
            event_log=self.event_log,
            stage=self.stage,
        )
        require_execution_target_digest(self.expected_digest, current)
        return current


def preparation_operation_reason(
    *,
    goal_digest: str,
    phase_digest: str,
    source_digest: str,
    charged_milliseconds: int,
    semantic_round: int,
    quantity: str,
) -> str:
    """Construct metadata before the existing operation is authorized/bound."""
    body = {
        "schemaVersion": _META_SCHEMA,
        "goalDigest": goal_digest,
        "phaseDigest": phase_digest,
        "sourceDigest": source_digest,
        "chargedMilliseconds": charged_milliseconds,
        "semanticRound": semantic_round,
        "quantity": quantity,
    }
    _metadata(json.dumps(body, sort_keys=True, separators=(",", ":")))
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _metadata(reason: str) -> dict[str, Any]:
    if len(reason.encode("utf-8")) > 4096:
        raise ValueError("Bounded preparation metadata required")
    value = json.loads(reason)
    if value.get("schemaVersion") != _META_SCHEMA:
        raise ValueError("Qualified preparation operation required")
    for key in ("goalDigest", "phaseDigest", "sourceDigest"):
        text = value[key]
        if not isinstance(text, str) or len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("Preparation operation binding required")
    for key in ("chargedMilliseconds", "semanticRound"):
        if type(value[key]) is not int or not 0 < value[key] < 2**63:
            raise ValueError("Finite preparation upper bound required")
    if value["quantity"] not in {"RESERVATION_TOKENS", "SELECTED_ALK_INPUT"}:
        raise ValueError("Supported preparation quantity required")
    return value


@dataclass(frozen=True)
class JournalPreparationAdmission:
    journal: Journal
    operation: Operation
    qualify: Callable[[dict[str, Any]], dict[str, Any]]
    clock: Callable[[], int] = lambda: int(time.time())
    target: ExecutionTargetSelection | None = None
    max_prefix_rows: int = 4096
    max_prefix_bytes: int = 16 * 1024 * 1024

    def _prefix(self) -> dict[str, Any]:
        op = self.operation
        try:
            projection = self.journal.snapshot(op.budget_scope_id)
            if projection.qualification != "QUALIFIED" or projection.gate_status != "READY":
                raise ValueError("Journal is not ready and qualified")
            revision = projection.journal_revision
            return self.journal.bounded_prefix(
                op.budget_scope_id,
                expected_revision=revision,
                boundary=(revision, 0),
                max_rows=self.max_prefix_rows,
                max_bytes=self.max_prefix_bytes,
            )
        except (JournalUnavailable, RevisionConflict, KeyError, ValueError) as exc:
            raise LifecycleError(
                "PREPARATION_HISTORY_UNAVAILABLE",
                "Complete current ready journal prefix unavailable",
            ) from exc

    def _current(self) -> tuple[dict[str, Any], dict[str, Any], int]:
        op = self.operation
        prefix = self._prefix()
        revision = prefix["revision"]
        try:
            context = self.qualify(prefix)
            current = _metadata(op.attribution_reason)
            if type(context["executionChain"]) is not bool:
                raise ValueError("Declared chain type required")
            if op.retry_ordinal > 0 and context["repeat"]["required"] is not True:
                raise ValueError("Retry requires justified affected repeat")
            if (
                context["goalDigest"] != current["goalDigest"]
                or context["phaseDigest"] != current["phaseDigest"]
                or context["sourceDigest"] != current["sourceDigest"]
                or context["quantity"] != current["quantity"]
                or context["inputDigest"] != op.input_digest
                or context["unitDefinitionId"] != op.unit_definition_id
                or context["routeQualificationDigest"] != op.route_qualification.digest
                or context["issuerDigest"] != op.issuer.digest
                or context["validityDigest"] != op.validity.digest
                or context["request"]
                != {
                    "tokens": op.upper_bound_tokens,
                    "requests": 1,
                    "chargedMilliseconds": current["chargedMilliseconds"],
                    "semanticRound": current["semanticRound"],
                }
            ):
                raise ValueError("Current operation/context mismatch")
            usage = self._usage(prefix, current, context)
            if context["executionChain"] is True:
                if self.target is None:
                    raise ValueError("Actual execution target required")
                target = self.target.recheck()
                if (
                    target["targetId"] != context["targetId"]
                    or canonical_digest(self.target.source_identity) != context["sourceDigest"]
                ):
                    raise ValueError("Actual execution target binding mismatch")
            elif self.target is not None:
                raise ValueError("Planning-only route cannot substitute target")
        except (KeyError, TypeError, ValueError) as exc:
            raise LifecycleError(
                "PREPARATION_HISTORY_UNAVAILABLE",
                "Complete bound preparation observations are required",
            ) from exc
        decision = evaluate_preparation_policy(context, usage, now=self.clock())
        require_preparation_pass(decision)
        return decision, prefix, revision

    def _usage(
        self,
        prefix: dict[str, Any],
        current: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        usage = {
            "qualified": True,
            "prefixDigest": prefix["prefixDigest"],
            "quantity": current["quantity"],
            "tokens": 0,
            "requests": 0,
            "chargedMilliseconds": 0,
            "semanticRound": 0,
            "goalRequests": 0,
        }
        opening = json.loads(prefix["events"][0]["payload"])
        if prefix["events"][0]["kind"] != "OPEN":
            raise ValueError("Complete native opening required")
        amounts = list(opening["opening"]["task_spent"].values())
        amounts.append(opening["opening"]["run_overhead"])
        if any(type(v) is not int or v != 0 for v in amounts):
            raise ValueError("Opening request/work history unavailable")
        if opening["opening"]["pending_operations"]:
            raise ValueError("Opening pending request/work history unavailable")
        if opening["policy"]["authorization"]["digest"] != context["authorization"]["digest"]:
            raise ValueError("Scope authorization mismatch")
        for event in prefix["events"]:
            if event["kind"] != "RESERVE":
                continue
            binding = json.loads(event["payload"])["operation"]
            prior = _metadata(binding["attribution_reason"])
            same_goal = all(
                prior[k] == current[k]
                for k in (
                    "goalDigest",
                    "phaseDigest",
                )
            )
            if prior["quantity"] != current["quantity"]:
                raise ValueError("Scope quantity cannot reset")
            if not same_goal:
                change = context.get("scopeChange", {})
                allowed = change.get("allowedPredecessorGoalPhases", [])
                if (
                    change.get("qualified") is not True
                    or change.get("authorizationDigest") != context["authorization"]["digest"]
                    or change.get("newGoalDigest") != current["goalDigest"]
                    or change.get("newPhaseDigest") != current["phaseDigest"]
                    or not isinstance(allowed, list)
                    or not 1 <= len(allowed) <= 64
                    or {"goalDigest": prior["goalDigest"], "phaseDigest": prior["phaseDigest"]} not in allowed
                ):
                    raise ValueError("Scope goal/phase cannot silently reset")
            if binding["operation_id"] == self.operation.operation_id:
                if canonical_digest(binding) != self.operation.binding_digest:
                    raise ValueError("Current operation binding changed")
                # Already committed upper bound is the requested operation,
                # not a second charge. Fresh reserve/claim still gate dispatch.
                continue
            usage["tokens"] += binding["upper_bound_tokens"]
            usage["requests"] += 1
            usage["goalRequests"] += int(same_goal)
            usage["chargedMilliseconds"] += prior["chargedMilliseconds"]
            usage["semanticRound"] = max(
                usage["semanticRound"],
                prior["semanticRound"],
            )
        return usage

    def _require_root(self, root: Path | None) -> None:
        if self.target is not None and (root is None or root.resolve() != self.target.root.resolve()):
            raise LifecycleError(
                "PREPARATION_TARGET_MISMATCH",
                "Actual target root differs",
            )

    def check_retry(
        self,
        *,
        prior_request_digest: str,
        prior_result_digest: str,
        retry_ordinal: int,
    ) -> None:
        """Only an explicitly qualified finite settled-transient allowance."""
        _, prefix, _ = self._current()
        try:
            context = self.qualify(prefix)
            retry = context["retry"]
            if (
                retry["qualified"] is not True
                or retry["authorizationDigest"] != context["authorization"]["digest"]
                or retry["priorRequestDigest"] != prior_request_digest
                or retry["priorResultDigest"] != prior_result_digest
                or retry["disposition"] != "TRANSIENT_SETTLED"
                or type(retry["maxGenerationRetries"]) is not int
                or not 1 <= retry_ordinal <= retry["maxGenerationRetries"] <= 8
                or self.operation.retry_ordinal != retry_ordinal
            ):
                raise ValueError("No qualified transient retry grant")
        except (KeyError, ValueError, TypeError) as exc:
            raise LifecycleError(
                "REVIEW_ROUTE_SUSPENDED",
                "Finite corrected retry unavailable",
            ) from exc

    def check(self, *, repository_root: Path | None = None) -> dict[str, Any]:
        """Preflight without reserving, claiming or dispatching anything."""
        if repository_root is not None:
            self._require_root(repository_root)
        decision, _, _ = self._current()
        return decision

    def invoke(
        self,
        effect: Callable[[], T],
        *,
        input_digest: str,
        repository_root: Path | None = None,
    ) -> T:
        """Fresh expected-revision reservation and unique claim gate dispatch."""
        op = self.operation
        self._require_root(repository_root)
        if input_digest != op.input_digest:
            raise LifecycleError(
                "PREPARATION_INPUT_MISMATCH",
                "Controlled input changed",
            )
        decision, _, revision = self._current()
        if self.journal.reserve(op, expected_revision=revision) != "RESERVED":
            raise LifecycleError(
                "PREPARATION_ADMISSION_REPLAY",
                "No fresh dispatch reservation",
            )
        claim = self.journal.claim(
            op.budget_scope_id,
            op.operation_id,
            op.binding_digest,
            "preparation:" + op.dispatch_key,
        )
        if claim != "CLAIM_GRANTED":
            raise LifecycleError(
                "PREPARATION_ADMISSION_REPLAY",
                "No fresh dispatch claim",
            )
        # Recheck changing readiness/target after admission and just before the
        # effect; any refusal/crash leaves the original conservative hold.
        self.check()
        proof = EvidenceRef("preparation:dispatch", decision["decisionDigest"])
        if (
            self.journal.note_dispatch(
                op.budget_scope_id,
                op.operation_id,
                proof,
            )
            != "RECORDED"
        ):
            raise LifecycleError(
                "PREPARATION_DISPATCH_UNAVAILABLE",
                "Dispatch record unavailable",
            )
        try:
            return effect()
        except BaseException:
            self.journal.note_unavailable(
                op.budget_scope_id,
                op.operation_id,
                proof,
            )
            raise
