from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.model_routing import validate_host_model_profile


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


@dataclass(frozen=True)
class HostModelSelection:
    host: str
    profile_id: str
    profile_digest: str
    model_class: str
    binding_id: str
    binding_digest: str
    provider_model: str
    provider_model_hash: str
    provider: str | None = None
    variant: str | None = None

    def redacted_json(self) -> dict[str, object]:
        return {
            "host": self.host,
            "profileId": self.profile_id,
            "profileDigest": self.profile_digest,
            "modelClass": self.model_class,
            "bindingId": self.binding_id,
            "bindingDigest": self.binding_digest,
            "providerModelHash": self.provider_model_hash,
            "providerPresent": self.provider is not None,
            "variantPresent": self.variant is not None,
        }


def load_host_model_selection(
    profile_path: Path,
    *,
    model_class: str,
    binding_id: str | None = None,
) -> HostModelSelection:
    profile = _read_json_object(profile_path)
    validation = validate_host_model_profile(profile)
    bindings = profile.get("bindings", {})
    binding = bindings.get(model_class)
    if not isinstance(binding, dict):
        raise HarnessError("missing-model-binding", f"{model_class} binding is missing from {profile_path}")
    checked_binding = validation["bindings"][model_class]
    provider_model = binding.get("providerModel")
    if not isinstance(provider_model, str) or not provider_model:
        raise HarnessError("missing-provider-model", f"{model_class} binding has no providerModel")
    provider = binding.get("provider")
    variant = binding.get("variant")
    return HostModelSelection(
        host=str(profile["host"]),
        profile_id=str(profile["profileId"]),
        profile_digest=str(validation["profileDigest"]),
        model_class=model_class,
        binding_id=binding_id or model_class,
        binding_digest=str(checked_binding["bindingDigest"]),
        provider_model=provider_model,
        provider_model_hash=str(checked_binding["providerModelHash"]),
        provider=provider if isinstance(provider, str) and provider else None,
        variant=variant if isinstance(variant, str) and variant else None,
    )


def write_model_selection_receipt(
    path: Path,
    selection: HostModelSelection,
    *,
    route_decision_digest: str | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> dict[str, object]:
    digest = route_decision_digest or canonical_digest(
        {
            "source": "host-harness-standalone-selection",
            "host": selection.host,
            "profileDigest": selection.profile_digest,
            "modelClass": selection.model_class,
            "bindingId": selection.binding_id,
        }
    )
    receipt = {
        "schemaVersion": "agent-host-model-selection-receipt.v1",
        "host": selection.host,
        "routeDecisionDigest": digest,
        "modelClass": selection.model_class,
        "profileDigest": selection.profile_digest,
        "bindingId": selection.binding_id,
        "bindingDigest": selection.binding_digest,
        "providerModelHash": selection.provider_model_hash,
        "fallbackUsed": fallback_used,
        "fallbackReason": fallback_reason,
        "routeDecisionBinding": "host-harness-standalone-selection" if route_decision_digest is None else "route-decision",
        "productionPromotionClaimed": False,
    }
    write_json_create(path, receipt)
    return receipt


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError("invalid-host-model-profile", f"expected JSON object: {path}")
    return value
