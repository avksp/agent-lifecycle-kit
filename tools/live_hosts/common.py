from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


BudgetMode = str


class HarnessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    wall_seconds: float


class UsageSnapshot(Protocol):
    billable_tokens: int
    wall_seconds: float
    cost_usd: float | None


@dataclass(frozen=True)
class BudgetPolicy:
    mode: BudgetMode
    budget_cap_usd: float | None = None
    max_invocations: int | None = None
    max_billable_tokens: int | None = None
    max_wall_seconds: float | None = None

    def require_authorized(self, *, allow_live: bool, required_invocations: int) -> None:
        if not allow_live:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "--allow-live and an explicit budget mode cap are required before live calls")
        if self.mode not in {"metered", "subscription", "local"}:
            raise HarnessError("invalid-budget-mode", f"unsupported budget mode: {self.mode}")
        if self.mode == "metered" and not _positive_number(self.budget_cap_usd):
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "metered live calls require a positive --budget-cap-usd")
        if self.mode in {"subscription", "local"}:
            if not _positive_int(self.max_invocations):
                raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", f"{self.mode} live calls require --max-invocations")
            if self.max_invocations < required_invocations:
                raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "--max-invocations is below the required live invocation count")
            if not (_positive_int(self.max_billable_tokens) or _positive_number(self.max_wall_seconds)):
                raise HarnessError(
                    "BLOCKED_BUDGET_EXHAUSTED",
                    f"{self.mode} live calls require --max-billable-tokens or --max-wall-seconds",
                )

    def require_before_invocation(self, tracker: "BudgetTracker") -> None:
        if self.max_invocations is not None and tracker.invocations >= self.max_invocations:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "invocation cap reached before starting next invocation")
        if self.budget_cap_usd is not None and tracker.cost_usd >= self.budget_cap_usd:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "USD cap reached before starting next invocation")
        if self.max_billable_tokens is not None and tracker.billable_tokens >= self.max_billable_tokens:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "token cap reached before starting next invocation")
        if self.max_wall_seconds is not None and tracker.wall_seconds >= self.max_wall_seconds:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "wall-clock cap reached before starting next invocation")

    def usage_requires_cost(self) -> bool:
        return self.mode == "metered"

    def usage_attestation_policy(self, host: str) -> str:
        if self.mode == "metered":
            return f"{host}-usage-and-cost-required-per-invocation"
        return f"{host}-usage-required-per-invocation-{self.mode}-resource-budget"

    def to_json(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "budgetCapUsd": self.budget_cap_usd,
            "maxInvocations": self.max_invocations,
            "maxBillableTokens": self.max_billable_tokens,
            "maxWallSeconds": self.max_wall_seconds,
        }


@dataclass
class BudgetTracker:
    invocations: int = 0
    cost_usd: float = 0.0
    billable_tokens: int = 0
    wall_seconds: float = 0.0

    def record(self, usage: UsageSnapshot, policy: BudgetPolicy) -> None:
        self.invocations += 1
        self.billable_tokens += usage.billable_tokens
        self.wall_seconds += usage.wall_seconds
        if usage.cost_usd is not None:
            self.cost_usd += usage.cost_usd
        if policy.budget_cap_usd is not None and self.cost_usd > policy.budget_cap_usd:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "USD cap exceeded after invocation accounting reconciliation")
        if policy.max_invocations is not None and self.invocations > policy.max_invocations:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "invocation cap exceeded after invocation accounting reconciliation")
        if policy.max_billable_tokens is not None and self.billable_tokens > policy.max_billable_tokens:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "token cap exceeded after invocation accounting reconciliation")
        if policy.max_wall_seconds is not None and self.wall_seconds > policy.max_wall_seconds:
            raise HarnessError("BLOCKED_BUDGET_EXHAUSTED", "wall-clock cap exceeded after invocation accounting reconciliation")

    def to_json(self) -> dict[str, object]:
        return {
            "invocations": self.invocations,
            "costUsd": self.cost_usd,
            "billableTokens": self.billable_tokens,
            "wallSeconds": self.wall_seconds,
        }


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
