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

from agent_lifecycle.contracts import canonical_digest, sha256_hex  # noqa: E402
from tools.live_hosts.common import (  # noqa: E402
    BudgetPolicy,
    CommandResult,
    HarnessError,
    HostModelSelection,
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
    parse_json_objects,
    run_command,
    run_command_capture,
    run_fixture_check as run_json_fixture_check,
    run_live_calibration as run_json_live_calibration,
    run_live_host_receipt as run_json_live_host_receipt,
    write_json,
)


HOST = "goose"
HARNESS_REPORT_SCHEMA = "agent-goose-live-harness-report.v1"
DIAGNOSTIC_SCHEMA = "agent-goose-live-invocation-diagnostic.v1"
DEFAULT_BASELINE = Path("conformance/core/adapter-baseline.v1.json")
DEFAULT_PROFILE = Path("conformance/core/live-calibration-profile.v1.json")
DEFAULT_BUDGET_TARGETS = Path("conformance/core/budget-targets.v1.json")
GooseUsage = JsonCliUsage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "fixture-check", "live-host-receipt", "live-calibration"], required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE.as_posix())
    parser.add_argument("--profile", default=DEFAULT_PROFILE.as_posix())
    parser.add_argument("--budget-targets", default=DEFAULT_BUDGET_TARGETS.as_posix())
    parser.add_argument("--goose-bin", default="goose")
    parser.add_argument("--goose-provider")
    parser.add_argument("--goose-model")
    parser.add_argument("--goose-no-profile", action="store_true")
    parser.add_argument("--host-model-profile")
    parser.add_argument("--model-class")
    parser.add_argument("--model-binding")
    parser.add_argument("--model-selection-receipt")
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
    parser.add_argument("--diagnostic-dir", default="work/release-1-16/evidence/live-host-diagnostics/goose")
    args = parser.parse_args(argv)

    blockers: list[dict[str, Any]] = []
    try:
        report = _dispatch(args)
    except HarnessError as error:
        blockers.append({"code": error.code, "message": error.message})
        report = base_report(HARNESS_REPORT_SCHEMA, "FAIL", HOST, blockers)
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
            goose_bin=args.goose_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            budget_policy=budget_policy,
            allow_live=args.allow_live,
            goose_provider=args.goose_provider,
            goose_model=args.goose_model,
            goose_no_profile=args.goose_no_profile,
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
            goose_bin=args.goose_bin,
            goose_provider=args.goose_provider,
            goose_model=args.goose_model,
            goose_no_profile=args.goose_no_profile,
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
        goose_bin=args.goose_bin,
        goose_provider=args.goose_provider,
        goose_model=args.goose_model,
        goose_no_profile=args.goose_no_profile,
        invocation_timeout_seconds=args.invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
    )


def run_preflight(
    *,
    goose_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    budget_policy: BudgetPolicy,
    allow_live: bool,
    goose_provider: str | None = None,
    goose_model: str | None = None,
    goose_no_profile: bool = False,
    containment_receipt_path: Path | None = None,
    model_selection: HostModelSelection | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    version = run_command([goose_bin, "--version"], checks, "goose-version")
    help_result = run_command([goose_bin, "--help"], checks, "goose-help")
    run_help = run_command([goose_bin, "run", "--help"], checks, "goose-run-help")
    acp_help = run_command([goose_bin, "acp", "--help"], checks, "goose-acp-help")
    info_result = run_command([goose_bin, "info"], checks, "goose-info")
    baseline = load_json(baseline_path)
    operations = _required_operations(baseline)
    containment_policy = _containment_policy(
        goose_provider=goose_provider,
        goose_model=goose_model,
        goose_no_profile=goose_no_profile,
        model_selection=model_selection,
    )
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
    help_ok = all(result["returncode"] == 0 for result in (version, help_result, run_help, acp_help, info_result))
    status = "PASS" if not blockers and help_ok else "FAIL"
    if containment_receipt_path is not None:
        write_json(containment_receipt_path, _containment_receipt(status=status, blockers=blockers, policy=containment_policy, goose_cli_version=first_line(version["stdout"])))
    return {
        **base_report(HARNESS_REPORT_SCHEMA, status, HOST, blockers),
        "checks": checks,
        "gooseCliVersion": first_line(version["stdout"]),
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
    goose_bin: str = "goose",
    goose_provider: str | None = None,
    goose_model: str | None = None,
    goose_no_profile: bool = False,
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
        command_for_operation=lambda operation: _operation_command(goose_bin, operation, goose_provider=goose_provider, goose_model=goose_model, goose_no_profile=goose_no_profile, model_selection=model_selection),
        usage_parser=parse_goose_stream_json,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(goose_provider=goose_provider, goose_model=goose_model, goose_no_profile=goose_no_profile, model_selection=model_selection),
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
    goose_bin: str = "goose",
    goose_provider: str | None = None,
    goose_model: str | None = None,
    goose_no_profile: bool = False,
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
        command_for_prompt=lambda prompt: _run_command(goose_bin, prompt, goose_provider=goose_provider, goose_model=goose_model, goose_no_profile=goose_no_profile, model_selection=model_selection),
        usage_parser=parse_goose_stream_json,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(goose_provider=goose_provider, goose_model=goose_model, goose_no_profile=goose_no_profile, model_selection=model_selection),
        runner=runner,
        clean_worktree_checker=clean_worktree_checker,
    )


def parse_goose_stream_json(text: str, wall_seconds: float = 0.0) -> GooseUsage:
    events = parse_json_objects(text)
    usage: dict[str, Any] = {}
    costs: list[float] = []
    session_id: str | None = None
    tool_calls = 0
    for event in events:
        session_id = session_id or _find_string(event, {"session_id", "sessionId", "sessionID", "conversation_id", "conversationId"})
        candidate = event.get("metadata")
        if not isinstance(candidate, dict):
            candidate = event.get("usage") if isinstance(event.get("usage"), dict) else event.get("usageMetadata")
        if isinstance(candidate, dict):
            usage = candidate
        costs.extend(_find_numbers(event, {"cost_usd", "costUsd", "costUSD", "cost"}))
        tool_calls += _count_tool_calls(event)
    input_tokens = _int_from_any(_first_present(usage, ("inputTokens", "input_tokens", "prompt_tokens", "promptTokens", "promptTokenCount")))
    output_tokens = _int_from_any(_first_present(usage, ("outputTokens", "output_tokens", "completion_tokens", "completionTokens", "candidatesTokenCount")))
    total_tokens = _int_from_any(_first_present(usage, ("billableTokens", "billable_tokens", "total", "total_tokens", "totalTokens", "totalTokenCount")))
    context_bytes = _int_from_any(_first_present(usage, ("cumulativeContextBytes", "cumulative_context_bytes", "contextBytes", "context_bytes")))
    return GooseUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=total_tokens or input_tokens + output_tokens,
        cumulative_context_bytes=context_bytes if context_bytes else None,
        cumulative_context_bytes_source="host-json" if context_bytes else None,
        tool_calls=tool_calls,
        wall_seconds=round(wall_seconds, 3),
        cost_usd=sum(costs) if costs else None,
        session_id=session_id,
        event_count=len(events),
    )


def _operation_command(goose_bin: str, operation_name: str, *, goose_provider: str | None, goose_model: str | None, goose_no_profile: bool, model_selection: HostModelSelection | None) -> list[str]:
    return _run_command(
        goose_bin,
        (
            f"ALK goose live conformance probe. Operation: {operation_name}. "
            "Do not use tools. Do not modify files. Reply only with compact JSON: {\"operation\":\"<operation>\",\"status\":\"PASS\"}."
        ),
        goose_provider=goose_provider,
        goose_model=goose_model,
        goose_no_profile=goose_no_profile,
        model_selection=model_selection,
    )


def _run_command(goose_bin: str, prompt: str, *, goose_provider: str | None, goose_model: str | None, goose_no_profile: bool, model_selection: HostModelSelection | None) -> list[str]:
    provider = goose_provider or (model_selection.provider if model_selection is not None else None)
    model = goose_model or (model_selection.provider_model if model_selection is not None else None)
    command = [
        goose_bin,
        "run",
        "--no-session",
        "--max-turns",
        "1",
        "--max-tool-repetitions",
        "1",
        "--output-format",
        "json",
    ]
    if goose_no_profile:
        command.append("--no-profile")
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    command.extend(["--text", prompt])
    return command


def _containment_blockers(*, goose_provider: str | None, goose_model: str | None, goose_no_profile: bool, model_selection: HostModelSelection | None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    _validate_containment(
        _containment_policy(
            goose_provider=goose_provider,
            goose_model=goose_model,
            goose_no_profile=goose_no_profile,
            model_selection=model_selection,
        ),
        blockers,
    )
    return blockers


def _containment_policy(*, goose_provider: str | None, goose_model: str | None, goose_no_profile: bool, model_selection: HostModelSelection | None) -> dict[str, Any]:
    provider = goose_provider or (model_selection.provider if model_selection is not None else None)
    model = goose_model or (model_selection.provider_model if model_selection is not None else None)
    return {
        "schemaVersion": "agent-goose-live-containment-policy.v1",
        "host": HOST,
        "noSession": True,
        "noProfile": goose_no_profile,
        "defaultExtensionsLoaded": not goose_no_profile,
        "cliSpecifiedExtensions": [],
        "maxTurns": 1,
        "maxToolRepetitions": 1,
        "outputFormat": "json",
        "providerOverridePresent": provider is not None,
        "modelOverridePresent": model is not None,
        "postInvocationCleanWorktreeRequired": True,
        "promptPolicy": "no-tools-no-file-modifications-json-only",
    }


def _validate_containment(policy: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if policy.get("noProfile") is not True:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_PROFILE", "message": "goose live promotion requires --goose-no-profile"})
    if policy.get("providerOverridePresent") is not True or policy.get("modelOverridePresent") is not True:
        blockers.append({"code": "BLOCKED_MODEL_BINDING_UNDECLARED", "message": "goose live promotion requires explicit host-local provider and model"})
    if policy.get("maxTurns") != 1 or policy.get("maxToolRepetitions") != 1:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_INVOCATION", "message": "goose live promotion requires bounded turns and tool repetitions"})


def _containment_receipt(*, status: str, blockers: list[dict[str, Any]], policy: dict[str, Any], goose_cli_version: str | None) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-goose-live-containment-receipt.v1",
        "status": status,
        "host": HOST,
        "gooseCliVersion": goose_cli_version,
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
    result = run_command_capture(["git", "-C", str(worktree), "status", "--short"], timeout_seconds=30)
    if result.returncode != 0:
        return {"clean": False, "reason": "not-a-git-worktree", "stderrSha256": sha256_hex(result.stderr.encode("utf-8"))}
    return {"clean": result.stdout == "", "dirtyEntryCount": len([line for line in result.stdout.splitlines() if line.strip()])}


def _required_operations(baseline: dict[str, Any]) -> list[str]:
    value = baseline.get("requiredOperations")
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _first_present(value: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _int_from_any(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


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


def _find_numbers(value: Any, keys: set[str]) -> list[float]:
    found: list[float] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, (int, float)) and not isinstance(item, bool):
                found.append(float(item))
            found.extend(_find_numbers(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_numbers(item, keys))
    return found


def _count_tool_calls(value: Any) -> int:
    if isinstance(value, dict):
        total = 0
        if value.get("type") in {"toolRequest", "toolResponse", "tool_request", "tool_response"}:
            total += 1
        for key, item in value.items():
            if key in {"tool_call", "toolCall", "tool_calls", "toolCalls"}:
                total += len(item) if isinstance(item, list) else int(isinstance(item, dict))
            total += _count_tool_calls(item)
        return total
    if isinstance(value, list):
        return sum(_count_tool_calls(item) for item in value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
