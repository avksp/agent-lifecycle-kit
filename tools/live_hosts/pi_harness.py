from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from tools.live_hosts.common import (  # noqa: E402
    BudgetPolicy,
    CommandResult,
    HarnessError,
    HostModelSelection,
    add_host_env_args,
    dispatch_with_host_env,
    load_host_model_selection,
)
from tools.live_hosts.json_cli_harness import (  # noqa: E402
    LIVE_CALIBRATION_RECEIPT_SCHEMA,
    LIVE_HOST_RECEIPT_SCHEMA,
    JsonCliUsage,
    base_report,
    build_fixture_operations,
    file_identity,
    first_line,
    load_json,
    parse_jsonl_objects,
    run_command,
    run_fixture_check as run_json_fixture_check,
    run_live_calibration as run_json_live_calibration,
    run_live_host_receipt as run_json_live_host_receipt,
    write_json,
)


HOST = "pi"
HARNESS_REPORT_SCHEMA = "agent-pi-live-harness-report.v1"
DIAGNOSTIC_SCHEMA = "agent-pi-live-invocation-diagnostic.v1"
DEFAULT_BASELINE = Path("conformance/core/adapter-baseline.v1.json")
DEFAULT_PROFILE = Path("conformance/core/live-calibration-profile.v1.json")
DEFAULT_BUDGET_TARGETS = Path("conformance/core/budget-targets.v1.json")
PiUsage = JsonCliUsage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "fixture-check", "live-host-receipt", "live-calibration"], required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE.as_posix())
    parser.add_argument("--profile", default=DEFAULT_PROFILE.as_posix())
    parser.add_argument("--budget-targets", default=DEFAULT_BUDGET_TARGETS.as_posix())
    parser.add_argument("--pi-bin", default="pi")
    parser.add_argument("--pi-provider")
    parser.add_argument("--pi-model")
    parser.add_argument("--pi-thinking")
    parser.add_argument("--host-model-profile")
    parser.add_argument("--model-class")
    parser.add_argument("--model-binding")
    parser.add_argument("--model-selection-receipt")
    add_host_env_args(parser)
    parser.add_argument("--worktree")
    parser.add_argument("--budget-mode", choices=["metered", "subscription", "local"], default="metered")
    parser.add_argument("--budget-cap-usd", type=float)
    parser.add_argument("--max-invocations", type=int)
    parser.add_argument("--max-billable-tokens", type=int)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--invocation-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--runs-per-scenario-cohort", type=int)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--report", required=True)
    parser.add_argument("--receipt")
    parser.add_argument("--containment-receipt")
    parser.add_argument("--diagnostic-dir", default="work/release-1-19/evidence/live-host-diagnostics/pi")
    args = parser.parse_args(argv)

    try:
        report = dispatch_with_host_env(args, _dispatch)
    except HarnessError as error:
        report = base_report(HARNESS_REPORT_SCHEMA, "FAIL", HOST, [{"code": error.code, "message": error.message}])
    write_json(Path(args.report), report)
    return 0 if report.get("status") == "PASS" else 1


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    budget_policy = BudgetPolicy(
        mode=args.budget_mode,
        budget_cap_usd=args.budget_cap_usd,
        max_invocations=args.max_invocations,
        max_billable_tokens=args.max_billable_tokens,
        max_wall_seconds=args.max_wall_seconds,
    )
    model_selection = _model_selection_from_args(args)
    if args.mode == "preflight":
        return run_preflight(
            pi_bin=args.pi_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            budget_policy=budget_policy,
            allow_live=args.allow_live,
            pi_provider=args.pi_provider,
            pi_model=args.pi_model,
            pi_thinking=args.pi_thinking,
            containment_receipt_path=Path(args.containment_receipt) if args.containment_receipt else None,
            model_selection=model_selection,
        )
    if args.mode == "fixture-check":
        return run_fixture_check(Path(args.baseline))
    if args.mode == "live-host-receipt":
        return run_live_host_receipt(
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            allow_live=args.allow_live,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostic_dir=Path(args.diagnostic_dir),
            budget_policy=budget_policy,
            pi_bin=args.pi_bin,
            pi_provider=args.pi_provider,
            pi_model=args.pi_model,
            pi_thinking=args.pi_thinking,
            invocation_timeout_seconds=args.invocation_timeout_seconds,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        )
    return run_live_calibration(
        profile_path=Path(args.profile),
        budget_targets_path=Path(args.budget_targets),
        worktree=Path(args.worktree) if args.worktree else None,
        runs_per_scenario_cohort=args.runs_per_scenario_cohort,
        allow_live=args.allow_live,
        receipt_path=Path(args.receipt) if args.receipt else None,
        diagnostic_dir=Path(args.diagnostic_dir),
        budget_policy=budget_policy,
        pi_bin=args.pi_bin,
        pi_provider=args.pi_provider,
        pi_model=args.pi_model,
        pi_thinking=args.pi_thinking,
        invocation_timeout_seconds=args.invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
    )


def run_preflight(
    *,
    pi_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    budget_policy: BudgetPolicy,
    allow_live: bool,
    pi_provider: str | None = None,
    pi_model: str | None = None,
    pi_thinking: str | None = None,
    containment_receipt_path: Path | None = None,
    model_selection: HostModelSelection | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    version = run_command([pi_bin, "--version"], checks, "pi-version")
    help_result = run_command([pi_bin, "--help"], checks, "pi-help")
    list_models = run_command(_list_models_command(pi_bin, model_selection=model_selection, pi_provider=pi_provider), checks, "pi-list-models")
    baseline = load_json(baseline_path)
    operations = _required_operations(baseline)
    containment_policy = _containment_policy(pi_provider=pi_provider, pi_model=pi_model, pi_thinking=pi_thinking, model_selection=model_selection)
    if not operations:
        blockers.append({"code": "invalid-adapter-baseline", "message": "adapter baseline has no required operations"})
    _validate_containment(containment_policy, blockers)
    if allow_live:
        try:
            budget_policy.require_authorized(allow_live=allow_live, required_invocations=len(operations))
        except HarnessError as error:
            blockers.append({"code": error.code, "message": error.message})
    if worktree is not None:
        clean = _check_clean_worktree(worktree)
        checks.append({"name": "clean-worktree", "status": "PASS" if clean.get("clean") else "FAIL", "details": clean})
        if not clean.get("clean"):
            blockers.append({"code": "BLOCKED_DIRTY_WORKTREE", "message": "live runs require a clean dedicated worktree"})
    checks.append({"name": "budget-gate", "status": "PASS" if allow_live and not blockers else "BLOCKED", "details": {"budgetPolicy": budget_policy.to_json(), "allowLive": allow_live}})
    commands_ok = all(result["returncode"] == 0 for result in (version, help_result, list_models))
    status = "PASS" if not blockers and commands_ok else "FAIL"
    if containment_receipt_path is not None:
        write_json(
            containment_receipt_path,
            _containment_receipt(
                status=status,
                blockers=blockers,
                policy=containment_policy,
                pi_version=first_line(version["stdout"]),
                model_catalog_available=list_models["returncode"] == 0,
            ),
        )
    return {
        **base_report(HARNESS_REPORT_SCHEMA, status, HOST, blockers),
        "checks": checks,
        "piVersion": first_line(version["stdout"]),
        "modelCatalogAvailable": list_models["returncode"] == 0,
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(operations),
        "containmentPolicy": containment_policy,
        "containmentReceipt": file_identity(containment_receipt_path) if containment_receipt_path and containment_receipt_path.exists() else None,
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "budgetMode": budget_policy.mode,
        "budgetCapUsd": budget_policy.budget_cap_usd,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def run_fixture_check(baseline_path: Path) -> dict[str, Any]:
    return run_json_fixture_check(host=HOST, baseline_path=baseline_path, report_schema=HARNESS_REPORT_SCHEMA)


def run_live_host_receipt(
    *,
    baseline_path: Path,
    worktree: Path | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy,
    pi_bin: str = "pi",
    pi_provider: str | None = None,
    pi_model: str | None = None,
    pi_thinking: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str]], CommandResult] | None = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return run_json_live_host_receipt(
        host=HOST,
        report_schema=HARNESS_REPORT_SCHEMA,
        diagnostic_schema=DIAGNOSTIC_SCHEMA,
        baseline_path=baseline_path,
        worktree=worktree,
        allow_live=allow_live,
        receipt_path=receipt_path,
        diagnostic_dir=diagnostic_dir,
        budget_policy=budget_policy,
        command_for_operation=lambda operation: _operation_command(
            pi_bin,
            operation,
            pi_provider=pi_provider,
            pi_model=pi_model,
            pi_thinking=pi_thinking,
            model_selection=model_selection,
        ),
        usage_parser=parse_pi_jsonl,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(pi_provider=pi_provider, pi_model=pi_model, pi_thinking=pi_thinking, model_selection=model_selection),
        runner=runner,
        clean_worktree_checker=clean_worktree_checker,
    )


def run_live_calibration(
    *,
    profile_path: Path,
    budget_targets_path: Path,
    worktree: Path | None,
    runs_per_scenario_cohort: int | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy,
    pi_bin: str = "pi",
    pi_provider: str | None = None,
    pi_model: str | None = None,
    pi_thinking: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str]], CommandResult] | None = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return run_json_live_calibration(
        host=HOST,
        report_schema=HARNESS_REPORT_SCHEMA,
        diagnostic_schema=DIAGNOSTIC_SCHEMA,
        profile_path=profile_path,
        budget_targets_path=budget_targets_path,
        worktree=worktree,
        runs_per_scenario_cohort=runs_per_scenario_cohort,
        allow_live=allow_live,
        receipt_path=receipt_path,
        diagnostic_dir=diagnostic_dir,
        budget_policy=budget_policy,
        command_for_prompt=lambda prompt: _run_command(
            pi_bin,
            prompt,
            pi_provider=pi_provider,
            pi_model=pi_model,
            pi_thinking=pi_thinking,
            model_selection=model_selection,
        ),
        usage_parser=parse_pi_jsonl,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(pi_provider=pi_provider, pi_model=pi_model, pi_thinking=pi_thinking, model_selection=model_selection),
        runner=runner,
        clean_worktree_checker=clean_worktree_checker,
    )


def parse_pi_jsonl(text: str, wall_seconds: float = 0.0) -> PiUsage:
    events = parse_jsonl_objects(text)
    session_id: str | None = None
    selected_usage: dict[str, Any] = {}
    cost_usd: float | None = None
    for event in events:
        session_id = session_id or _find_string(event, {"id", "session_id", "sessionId"})
        for usage in _find_usage_dicts(event):
            if _billable_tokens(usage) <= 0:
                continue
            selected_usage = usage
            cost_usd = _host_reported_cost(usage)
    input_tokens = _int_from_any(selected_usage.get("input"))
    output_tokens = _int_from_any(selected_usage.get("output"))
    billable_tokens = _billable_tokens(selected_usage)
    return PiUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable_tokens or input_tokens + output_tokens,
        cumulative_context_bytes=None,
        tool_calls=_count_tool_calls(events),
        wall_seconds=round(wall_seconds, 3),
        cost_usd=cost_usd,
        session_id=session_id,
        event_count=len(events),
    )


def _operation_command(pi_bin: str, operation_name: str, *, pi_provider: str | None, pi_model: str | None, pi_thinking: str | None, model_selection: HostModelSelection | None) -> list[str]:
    return _run_command(
        pi_bin,
        (
            f"ALK Pi live conformance probe. Operation: {operation_name}. "
            "Do not use tools. Do not modify files. Reply only with compact JSON: {\"operation\":\"<operation>\",\"status\":\"PASS\"}."
        ),
        pi_provider=pi_provider,
        pi_model=pi_model,
        pi_thinking=pi_thinking,
        model_selection=model_selection,
    )


def _run_command(pi_bin: str, prompt: str, *, pi_provider: str | None, pi_model: str | None, pi_thinking: str | None, model_selection: HostModelSelection | None) -> list[str]:
    provider = pi_provider or (model_selection.provider if model_selection is not None else None)
    model = pi_model or (model_selection.provider_model if model_selection is not None else None)
    command = [
        pi_bin,
        "--mode",
        "json",
        "--no-session",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-approve",
        "--offline",
    ]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    if pi_thinking:
        command.extend(["--thinking", pi_thinking])
    command.extend(["--print", prompt])
    return command


def _list_models_command(pi_bin: str, *, model_selection: HostModelSelection | None, pi_provider: str | None) -> list[str]:
    provider = pi_provider or (model_selection.provider if model_selection is not None else None)
    command = [pi_bin, "--list-models"]
    if provider:
        command.append(provider)
    command.append("--offline")
    return command


def _containment_blockers(*, pi_provider: str | None, pi_model: str | None, pi_thinking: str | None, model_selection: HostModelSelection | None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    _validate_containment(_containment_policy(pi_provider=pi_provider, pi_model=pi_model, pi_thinking=pi_thinking, model_selection=model_selection), blockers)
    return blockers


def _containment_policy(*, pi_provider: str | None, pi_model: str | None, pi_thinking: str | None, model_selection: HostModelSelection | None) -> dict[str, Any]:
    provider = pi_provider or (model_selection.provider if model_selection is not None else None)
    model = pi_model or (model_selection.provider_model if model_selection is not None else None)
    return {
        "schemaVersion": "agent-pi-live-containment-policy.v1",
        "host": HOST,
        "jsonEvents": True,
        "noSession": True,
        "toolsDisabled": True,
        "extensionsDisabled": True,
        "skillsDisabled": True,
        "promptTemplatesDisabled": True,
        "themesDisabled": True,
        "contextFilesDisabled": True,
        "projectLocalFilesIgnored": True,
        "startupNetworkDisabled": True,
        "providerOverridePresent": provider is not None,
        "modelOverridePresent": model is not None,
        "thinkingOverridePresent": pi_thinking is not None,
        "postInvocationCleanWorktreeRequired": True,
        "promptPolicy": "no-tools-no-file-modifications-json-only",
    }


def _validate_containment(policy: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if policy.get("jsonEvents") is not True or policy.get("noSession") is not True:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_INVOCATION", "message": "pi live promotion requires JSON event output and --no-session"})
    if policy.get("toolsDisabled") is not True:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_TOOLS", "message": "pi live promotion requires --no-tools"})
    for key in ("extensionsDisabled", "skillsDisabled", "promptTemplatesDisabled", "themesDisabled", "contextFilesDisabled", "projectLocalFilesIgnored"):
        if policy.get(key) is not True:
            blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_CONTEXT", "message": f"pi live promotion requires {key}"})
    if policy.get("providerOverridePresent") is not True or policy.get("modelOverridePresent") is not True:
        blockers.append({"code": "BLOCKED_MODEL_BINDING_UNDECLARED", "message": "pi live promotion requires explicit host-local provider and model"})


def _containment_receipt(*, status: str, blockers: list[dict[str, Any]], policy: dict[str, Any], pi_version: str | None, model_catalog_available: bool) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-pi-live-containment-receipt.v1",
        "status": status,
        "host": HOST,
        "piVersion": pi_version,
        "modelCatalogAvailable": model_catalog_available,
        "policy": policy,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def _model_selection_from_args(args: argparse.Namespace) -> HostModelSelection | None:
    if not args.host_model_profile:
        return None
    if not args.model_class:
        raise HarnessError("missing-model-class", "--model-class is required with --host-model-profile")
    return load_host_model_selection(Path(args.host_model_profile), model_class=args.model_class, binding_id=args.model_binding)


def _check_clean_worktree(worktree: Path) -> dict[str, Any]:
    from tools.live_hosts.json_cli_harness import check_clean_worktree

    return check_clean_worktree(worktree)


def _required_operations(baseline: dict[str, Any]) -> list[str]:
    value = baseline.get("requiredOperations")
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _find_usage_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "usage" and isinstance(item, dict):
                found.append(item)
            found.extend(_find_usage_dicts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_usage_dicts(item))
    return found


def _find_string(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item:
                return item
            found = _find_string(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_string(item, keys)
            if found:
                return found
    return None


def _count_tool_calls(value: Any) -> int:
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            if key in {"toolResults", "tool_call", "toolCall", "tool_calls", "toolCalls"}:
                if isinstance(item, list):
                    total += len(item)
                elif isinstance(item, dict):
                    total += 1
                elif isinstance(item, int) and not isinstance(item, bool):
                    total += item
            total += _count_tool_calls(item)
        return total
    if isinstance(value, list):
        return sum(_count_tool_calls(item) for item in value)
    return 0


def _billable_tokens(usage: dict[str, Any]) -> int:
    total = _int_from_any(usage.get("totalTokens"))
    if total:
        return total
    return (
        _int_from_any(usage.get("input"))
        + _int_from_any(usage.get("output"))
        + _int_from_any(usage.get("cacheRead"))
        + _int_from_any(usage.get("cacheWrite"))
    )


def _host_reported_cost(usage: dict[str, Any]) -> float | None:
    cost = usage.get("cost")
    if not isinstance(cost, dict):
        return None
    total = cost.get("total")
    if isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
        return float(total)
    return None


def _int_from_any(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
