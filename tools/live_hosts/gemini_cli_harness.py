from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex  # noqa: E402
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest  # noqa: E402
from tools.live_hosts.common import (  # noqa: E402
    BudgetPolicy,
    BudgetTracker,
    CommandResult,
    HarnessError,
    HostModelSelection,
    load_host_model_selection,
    write_model_selection_receipt,
)


HOST = "gemini-cli"
LIVE_HOST_RECEIPT_SCHEMA = "agent-lifecycle-live-host-conformance-receipt.v1"
LIVE_CALIBRATION_RECEIPT_SCHEMA = "agent-lifecycle-live-calibration-receipt.v1"
HARNESS_REPORT_SCHEMA = "agent-gemini-cli-live-harness-report.v1"
DEFAULT_BASELINE = Path("conformance/core/adapter-baseline.v1.json")
DEFAULT_PROFILE = Path("conformance/core/live-calibration-profile.v1.json")
DEFAULT_BUDGET_TARGETS = Path("conformance/core/budget-targets.v1.json")


@dataclass(frozen=True)
class GeminiCliUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    billable_tokens: int = 0
    cumulative_context_bytes: int | None = None
    tool_calls: int = 0
    wall_seconds: float = 0.0
    cost_usd: float | None = None
    session_id: str | None = None
    event_count: int = 0
    cumulative_context_bytes_source: str | None = None

    @property
    def has_usage_attestation(self) -> bool:
        return bool(self.billable_tokens or self.input_tokens or self.output_tokens or self.cost_usd is not None)

    @property
    def has_calibration_attestation(self) -> bool:
        return self.has_usage_attestation and self.cumulative_context_bytes is not None

    def to_receipt_usage(self) -> dict[str, Any]:
        usage: dict[str, Any] = {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "billableTokens": self.billable_tokens,
            "toolCalls": self.tool_calls,
            "wallSeconds": self.wall_seconds,
        }
        if self.cost_usd is not None:
            usage["costUsd"] = self.cost_usd
        if self.session_id:
            usage["sessionId"] = self.session_id
        return usage

    def to_calibration_usage(self) -> dict[str, Any]:
        usage = {
            "billableTokens": self.billable_tokens,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "cumulativeContextBytes": self.cumulative_context_bytes if self.cumulative_context_bytes is not None else 0,
            "toolCalls": self.tool_calls,
            "wallSeconds": self.wall_seconds,
        }
        if self.cumulative_context_bytes_source:
            usage["cumulativeContextBytesSource"] = self.cumulative_context_bytes_source
        if self.session_id:
            usage["sessionId"] = self.session_id
        return usage

    def with_context_byte_proxy(self, value: int) -> "GeminiCliUsage":
        return replace(
            self,
            cumulative_context_bytes=value,
            cumulative_context_bytes_source="harness-observed-prompt-and-jsonl-bytes",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "fixture-check", "live-host-receipt", "live-calibration"], required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE.as_posix())
    parser.add_argument("--profile", default=DEFAULT_PROFILE.as_posix())
    parser.add_argument("--budget-targets", default=DEFAULT_BUDGET_TARGETS.as_posix())
    parser.add_argument("--gemini-bin", default="gemini")
    parser.add_argument("--gemini-model")
    parser.add_argument("--gemini-fallback-model")
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
    parser.add_argument("--diagnostic-dir", default="tasks/release-0-10/evidence/live-host-diagnostics/gemini-cli")
    args = parser.parse_args(argv)

    blockers: list[dict[str, Any]] = []
    try:
        report = _dispatch(args)
    except HarnessError as error:
        blockers.append({"code": error.code, "message": error.message})
        report = _base_report("FAIL", blockers)
    _write_json(Path(args.report), report)
    return 0 if report.get("status") == "PASS" else 1


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    budget_policy = _budget_policy_from_args(args)
    model_selection = _model_selection_from_args(args)
    if args.mode == "preflight":
        return run_preflight(
            gemini_bin=args.gemini_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            budget_policy=budget_policy,
            allow_live=args.allow_live,
            model_selection=model_selection,
        )
    if args.mode == "fixture-check":
        return run_fixture_check(Path(args.baseline))
    if args.mode == "live-host-receipt":
        return run_live_host_receipt(
            gemini_bin=args.gemini_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            allow_live=args.allow_live,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostic_dir=Path(args.diagnostic_dir),
            budget_policy=budget_policy,
            gemini_model=args.gemini_model,
            gemini_fallback_model=args.gemini_fallback_model,
            invocation_timeout_seconds=args.invocation_timeout_seconds,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        )
    if args.mode == "live-calibration":
        return run_live_calibration(
            gemini_bin=args.gemini_bin,
            profile_path=Path(args.profile),
            budget_targets_path=Path(args.budget_targets),
            worktree=Path(args.worktree) if args.worktree else None,
            runs_per_scenario_cohort=args.runs_per_scenario_cohort,
            allow_live=args.allow_live,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostic_dir=Path(args.diagnostic_dir),
            budget_policy=budget_policy,
            gemini_model=args.gemini_model,
            gemini_fallback_model=args.gemini_fallback_model,
            invocation_timeout_seconds=args.invocation_timeout_seconds,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        )
    raise HarnessError("invalid-mode", f"unsupported mode: {args.mode}")


def _budget_policy_from_args(args: argparse.Namespace) -> BudgetPolicy:
    return BudgetPolicy(
        mode=args.budget_mode,
        budget_cap_usd=args.budget_cap_usd,
        max_invocations=args.max_invocations,
        max_billable_tokens=args.max_billable_tokens,
        max_wall_seconds=args.max_wall_seconds,
    )


def _model_selection_from_args(args: argparse.Namespace) -> HostModelSelection | None:
    if not args.host_model_profile:
        return None
    if not args.model_class:
        raise HarnessError("missing-model-class", "--model-class is required with --host-model-profile")
    return load_host_model_selection(
        Path(args.host_model_profile),
        model_class=args.model_class,
        binding_id=args.model_binding,
    )


def run_preflight(
    *,
    gemini_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    budget_policy: BudgetPolicy,
    allow_live: bool,
    model_selection: HostModelSelection | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    version = _run_command([gemini_bin, "--version"], checks, "gemini-cli-version")
    help_result = _run_command([gemini_bin, "--help"], checks, "gemini-cli-help")
    skills_help = _run_command([gemini_bin, "skills", "--help"], checks, "gemini-cli-skills-help")
    extensions_help = _run_command([gemini_bin, "extensions", "--help"], checks, "gemini-cli-extensions-help")
    mcp_help = _run_command([gemini_bin, "mcp", "--help"], checks, "gemini-cli-mcp-help")
    gemma_help = _run_command([gemini_bin, "gemma", "--help"], checks, "gemini-cli-gemma-help")
    baseline = _load_json(baseline_path)
    operations = required_operations(baseline)
    if not operations:
        blockers.append({"code": "invalid-adapter-baseline", "message": "adapter baseline has no required operations"})
    if allow_live:
        try:
            budget_policy.require_authorized(allow_live=allow_live, required_invocations=len(operations))
        except HarnessError as error:
            blockers.append({"code": error.code, "message": error.message})
    if worktree is not None:
        clean = check_clean_worktree(worktree)
        checks.append({"name": "clean-worktree", "status": "PASS" if clean.get("clean") else "FAIL", "details": clean})
        if not clean.get("clean"):
            blockers.append({"code": "BLOCKED_DIRTY_WORKTREE", "message": "live runs require a clean dedicated worktree"})
    checks.append({"name": "budget-gate", "status": "PASS" if allow_live and not blockers else "BLOCKED", "details": {"budgetPolicy": budget_policy.to_json(), "allowLive": allow_live}})
    help_ok = all(result["returncode"] == 0 for result in (version, help_result, skills_help, extensions_help, mcp_help, gemma_help))
    return {
        **_base_report("PASS" if not blockers and help_ok else "FAIL", blockers),
        "checks": checks,
        "geminiCliVersion": _first_line(version["stdout"]),
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(operations),
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "budgetMode": budget_policy.mode,
        "budgetCapUsd": budget_policy.budget_cap_usd,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def run_fixture_check(baseline_path: Path) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    operations = build_fixture_operations(HOST, baseline)
    blockers: list[dict[str, Any]] = []
    for operation in operations:
        try:
            HostOperationRequest.from_json(operation["hostOperationRequest"])
            HostOperationReceipt.from_json(operation["hostOperationReceipt"])
        except LifecycleError as error:
            blockers.append({"code": "host-protocol-envelope-invalid", "message": f"{operation.get('name')}: {error.code}"})
    required = set(required_operations(baseline))
    actual = {operation.get("name") for operation in operations}
    missing = sorted(required - actual)
    if missing:
        blockers.append({"code": "fixture-operation-missing", "message": ", ".join(missing)})
    return {
        **_base_report("PASS" if not blockers else "FAIL", blockers),
        "checks": [{"name": "fixture-host-operation-envelopes", "status": "PASS" if not blockers else "FAIL", "details": {"operationCount": len(operations), "syntheticFixtureOnly": True}}],
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(required),
        "operationCount": len(operations),
        "syntheticFixtureOnly": True,
        "productionPromotionClaimed": False,
    }


def run_live_host_receipt(
    *,
    gemini_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy | None = None,
    gemini_model: str | None = None,
    gemini_fallback_model: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str]], CommandResult] = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] = None,
) -> dict[str, Any]:
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    baseline = _load_json(baseline_path)
    operations = required_operations(baseline)
    budget_policy = budget_policy or BudgetPolicy(mode="metered")
    _validate_live_inputs(blockers, checks, budget_policy, allow_live, len(operations), worktree, clean_worktree_checker, receipt_path, "live-host-receipt")
    _validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return _blocked_live_report(blockers, checks, budget_policy, model_selection=model_selection)

    assert worktree is not None
    assert receipt_path is not None
    command_runner = runner or (lambda command: run_command_capture(command, cwd=worktree, timeout_seconds=invocation_timeout_seconds))
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    live_operations: list[dict[str, Any]] = []
    budget_tracker = BudgetTracker()
    live_calls_started = False
    for index, operation_name in enumerate(operations, start=1):
        try:
            budget_policy.require_before_invocation(budget_tracker)
        except HarnessError as error:
            blockers.append({"code": error.code, "message": error.message})
            break
        invocation_id = f"gemini-cli-{operation_name}-live-{index:02d}"
        result = command_runner(_operation_command(gemini_bin, worktree, operation_name, gemini_model=gemini_model, gemini_fallback_model=gemini_fallback_model, model_selection=model_selection))
        live_calls_started = True
        transcript = _write_invocation_diagnostic(diagnostic_dir, operation_name, invocation_id, result)
        checks.append({"name": f"gemini-cli-live-{operation_name}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": _display_path(transcript)}})
        usage = _usage_or_block(result, budget_policy, blockers, operation_name)
        if usage is None:
            break
        try:
            budget_tracker.record(usage, budget_policy)
        except HarnessError as error:
            blockers.append({"code": error.code, "message": error.message})
            break
        live_operations.append(build_live_operation_record(host=HOST, name=operation_name, invocation_id=invocation_id, usage=usage, output_identity=_file_identity(transcript)))

    if not blockers and set(operation["name"] for operation in live_operations) != set(operations):
        blockers.append({"code": "live-host-operation-missing", "message": "not all baseline operations were executed"})
    if not blockers:
        model_selection_identity = None
        if model_selection is not None and model_selection_receipt_path is not None:
            write_model_selection_receipt(model_selection_receipt_path, model_selection)
            model_selection_identity = _file_identity(model_selection_receipt_path)
        _write_json(
            receipt_path,
            {
                "schemaVersion": LIVE_HOST_RECEIPT_SCHEMA,
                "status": "PASS",
                "receiptId": "gemini-cli-live-host-conformance",
                "host": HOST,
                "adapterId": HOST,
                "sourceRevision": _source_revision(),
                "syntheticReplayUsed": False,
                "usageAttested": True,
                "budgetPolicy": budget_policy.to_json(),
                "budgetUsage": budget_tracker.to_json(),
                "modelSelection": model_selection.redacted_json() if model_selection else None,
                "modelSelectionReceipt": model_selection_identity,
                "budgetMode": budget_policy.mode,
                "budgetCapUsd": budget_policy.budget_cap_usd,
                "cumulativeCostUsd": budget_tracker.cost_usd,
                "operations": live_operations,
            },
        )
    return _live_report("PASS" if not blockers else "FAIL", blockers, checks, budget_policy, budget_tracker, live_calls_started, len(operations), len(live_operations), receipt_path, model_selection=model_selection, model_selection_receipt_path=model_selection_receipt_path)


def run_live_calibration(
    *,
    gemini_bin: str,
    profile_path: Path,
    budget_targets_path: Path,
    worktree: Path | None,
    runs_per_scenario_cohort: int | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy | None = None,
    gemini_model: str | None = None,
    gemini_fallback_model: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str]], CommandResult] = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] = None,
) -> dict[str, Any]:
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    profile = _load_json(profile_path)
    targets = _load_json(budget_targets_path)
    scenarios = _strings(profile.get("requiredScenarios"))
    cohorts = _strings(profile.get("requiredCohorts"))
    minimum_runs = _positive_int(profile.get("minimumRunsPerScenarioCohort")) or 1
    requested_runs = runs_per_scenario_cohort or minimum_runs
    required_invocations = len(scenarios) * len(cohorts) * requested_runs
    budget_policy = budget_policy or BudgetPolicy(mode="metered")
    _validate_calibration_inputs(profile, targets, blockers, scenarios, cohorts, requested_runs, minimum_runs)
    _validate_live_inputs(blockers, checks, budget_policy, allow_live, required_invocations, worktree, clean_worktree_checker, receipt_path, "live-calibration")
    _validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return _blocked_live_report(blockers, checks, budget_policy, model_selection=model_selection)

    assert worktree is not None
    assert receipt_path is not None
    command_runner = runner or (lambda command: run_command_capture(command, cwd=worktree, timeout_seconds=invocation_timeout_seconds))
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    budget_tracker = BudgetTracker()
    live_calls_started = False
    for scenario in scenarios:
        for cohort in cohorts:
            for run_index in range(1, requested_runs + 1):
                try:
                    budget_policy.require_before_invocation(budget_tracker)
                except HarnessError as error:
                    blockers.append({"code": error.code, "message": error.message})
                    break
                invocation_id = f"gemini-cli-{scenario}-{cohort}-{run_index:02d}"
                prompt = _prompt_for_calibration(scenario, cohort, run_index)
                result = command_runner(_calibration_command(gemini_bin, worktree, prompt, gemini_model=gemini_model, gemini_fallback_model=gemini_fallback_model, model_selection=model_selection))
                live_calls_started = True
                transcript = _write_invocation_diagnostic(diagnostic_dir, f"{scenario}-{cohort}-{run_index:02d}", invocation_id, result)
                checks.append({"name": f"gemini-cli-calibration-{scenario}-{cohort}-{run_index:02d}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": _display_path(transcript)}})
                usage = _calibration_usage_or_block(
                    result,
                    budget_policy,
                    blockers,
                    f"{scenario}/{cohort}/{run_index}",
                    prompt,
                )
                if usage is None:
                    break
                try:
                    budget_tracker.record(usage, budget_policy)
                except HarnessError as error:
                    blockers.append({"code": error.code, "message": error.message})
                    break
                runs.append({"runId": invocation_id, "scenarioId": scenario, "cohort": cohort, "usageAttested": True, "qualityStatus": "PASS", "usage": usage.to_calibration_usage()})
            if blockers:
                break
        if blockers:
            break

    if not blockers:
        model_selection_identity = None
        if model_selection is not None and model_selection_receipt_path is not None:
            write_model_selection_receipt(model_selection_receipt_path, model_selection)
            model_selection_identity = _file_identity(model_selection_receipt_path)
        _write_json(
            receipt_path,
            {
                "schemaVersion": LIVE_CALIBRATION_RECEIPT_SCHEMA,
                "status": "PASS",
                "receiptId": "gemini-cli-live-calibration",
                "host": HOST,
                "profileId": profile.get("profileId"),
                "profileDigest": canonical_digest(profile),
                "budgetTargetsDigest": canonical_digest(targets),
                "sourceRevision": _source_revision(),
                "liveModelInvocations": len(runs),
                "syntheticReplayUsed": False,
                "qualityRegressionCount": 0,
                "usageAttestationPolicy": budget_policy.usage_attestation_policy("gemini-cli-json"),
                "contextByteAccounting": "host-jsonl-or-harness-observed-prompt-and-jsonl-bytes",
                "budgetPolicy": budget_policy.to_json(),
                "modelSelection": model_selection.redacted_json() if model_selection else None,
                "modelSelectionReceipt": model_selection_identity,
                "budgetUsage": budget_tracker.to_json(),
                "budgetMode": budget_policy.mode,
                "budgetCapUsd": budget_policy.budget_cap_usd,
                "cumulativeCostUsd": budget_tracker.cost_usd,
                "runs": runs,
            },
        )
    report = _live_report("PASS" if not blockers else "FAIL", blockers, checks, budget_policy, budget_tracker, live_calls_started, required_invocations, len(runs), receipt_path, model_selection=model_selection, model_selection_receipt_path=model_selection_receipt_path)
    return {**report, "profileDigest": canonical_digest(profile), "budgetTargetsDigest": canonical_digest(targets), "requiredScenarioCount": len(scenarios), "requiredCohortCount": len(cohorts), "runsPerScenarioCohort": requested_runs}


def build_fixture_operations(host: str, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for name in required_operations(baseline):
        operation_id = f"{host}-{name}-fixture"
        request = HostOperationRequest(operation_id=operation_id, capability=name, inputs={"host": host, "fixture": True}, outputs=[], constraints={"usageReceiptRequired": True, "syntheticFixtureOnly": True})
        receipt = HostOperationReceipt(operation_id=operation_id, capability=name, status="PASS", outputs=[], usage={"toolCalls": 0, "billableTokens": 0, "syntheticFixtureOnly": True})
        operations.append({"name": name, "status": "PASS", "syntheticReplayUsed": True, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()})
    return operations


def build_live_operation_record(
    *,
    host: str,
    name: str,
    invocation_id: str,
    usage: GeminiCliUsage,
    output_identity: dict[str, Any],
) -> dict[str, Any]:
    request = HostOperationRequest(operation_id=invocation_id, capability=name, inputs={"host": host}, outputs=[output_identity], constraints={"usageReceiptRequired": True, "syntheticReplayForbidden": True})
    receipt = HostOperationReceipt(operation_id=invocation_id, capability=name, status="PASS", outputs=[output_identity], usage=usage.to_receipt_usage())
    return {"name": name, "status": "PASS", "syntheticReplayUsed": False, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()}


def parse_gemini_cli_stream_json(text: str, *, wall_seconds: float = 0.0) -> GeminiCliUsage:
    events = _json_objects(text)
    result_usage: dict[str, Any] | None = None
    fallback_usage: dict[str, Any] | None = None
    costs: list[float] = []
    session_id: str | None = None
    tool_calls = 0
    result_wall_seconds = 0.0
    for event in events:
        session_id = session_id or _find_string(event, {"session_id", "sessionId", "sessionID", "conversation_id", "conversationId"})
        event_usage = event.get("usage")
        if not isinstance(event_usage, dict):
            event_usage = event.get("usageMetadata")
        if isinstance(event_usage, dict):
            fallback_usage = event_usage
            if event.get("type") in {"result", "final", "response.completed"}:
                result_usage = event_usage
                duration_ms = _number_from_any(event.get("duration_ms"))
                if duration_ms > 0:
                    result_wall_seconds = duration_ms / 1000
        if fallback_usage is None:
            nested_usage = _find_dicts(event, {"usage", "usageMetadata", "token_usage", "tokenUsage", "tokens"})
            if nested_usage:
                fallback_usage = nested_usage[-1]
        costs.extend(_find_numbers(event, {"cost_usd", "costUsd", "costUSD", "cost"}))
        tool_calls += _count_tool_calls(event)
    usage = result_usage or fallback_usage or {}
    input_tokens = _int_from_any(_first_present(usage, ("inputTokens", "input_tokens", "input", "prompt_tokens", "promptTokens", "promptTokenCount")))
    output_tokens = _int_from_any(_first_present(usage, ("outputTokens", "output_tokens", "output", "completion_tokens", "completionTokens", "candidatesTokenCount")))
    total_tokens = _int_from_any(_first_present(usage, ("billableTokens", "billable_tokens", "total", "total_tokens", "totalTokens", "totalTokenCount")))
    context_bytes = _int_from_any(_first_present(usage, ("cumulativeContextBytes", "cumulative_context_bytes", "contextBytes", "context_bytes")))
    billable_tokens = total_tokens or input_tokens + output_tokens
    return GeminiCliUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable_tokens,
        cumulative_context_bytes=context_bytes if context_bytes else None,
        cumulative_context_bytes_source="host-jsonl" if context_bytes else None,
        tool_calls=tool_calls,
        wall_seconds=round(result_wall_seconds or wall_seconds, 3),
        cost_usd=sum(costs) if costs else None,
        session_id=session_id,
        event_count=len(events),
    )


def check_clean_worktree(worktree: Path) -> dict[str, Any]:
    if not worktree.exists():
        return {"clean": False, "reason": "missing-worktree"}
    result = subprocess.run(["git", "-C", str(worktree), "status", "--short"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return {"clean": False, "reason": "not-a-git-worktree", "stderrSha256": sha256_hex(result.stderr.encode("utf-8"))}
    return {"clean": result.stdout == "", "dirtyEntryCount": len([line for line in result.stdout.splitlines() if line.strip()])}


def run_command_capture(command: list[str], *, cwd: Path | None = None, timeout_seconds: float | None = None) -> CommandResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            returncode=124,
            stdout=error.stdout if isinstance(error.stdout, str) else "",
            stderr=error.stderr if isinstance(error.stderr, str) else f"timed out after {timeout_seconds} seconds",
            wall_seconds=round(time.monotonic() - started, 3),
        )
    return CommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, wall_seconds=round(time.monotonic() - started, 3))


def required_operations(baseline: dict[str, Any]) -> list[str]:
    value = baseline.get("requiredOperations")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _validate_live_inputs(
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    budget_policy: BudgetPolicy,
    allow_live: bool,
    required_invocations: int,
    worktree: Path | None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]],
    receipt_path: Path | None,
    mode: str,
) -> None:
    try:
        budget_policy.require_authorized(allow_live=allow_live, required_invocations=required_invocations)
    except HarnessError as error:
        blockers.append({"code": error.code, "message": error.message})
    if worktree is None:
        blockers.append({"code": "BLOCKED_DIRTY_WORKTREE", "message": "a clean dedicated worktree is required for live calls"})
    else:
        clean = clean_worktree_checker(worktree)
        checks.append({"name": "clean-worktree", "status": "PASS" if clean.get("clean") else "FAIL", "details": clean})
        if not clean.get("clean"):
            blockers.append({"code": "BLOCKED_DIRTY_WORKTREE", "message": "live runs require a clean dedicated worktree"})
    if receipt_path is None:
        blockers.append({"code": f"missing-{mode}-receipt-path", "message": f"--receipt is required in {mode} mode"})


def _validate_calibration_inputs(
    profile: dict[str, Any],
    targets: dict[str, Any],
    blockers: list[dict[str, Any]],
    scenarios: list[str],
    cohorts: list[str],
    requested_runs: int,
    minimum_runs: int,
) -> None:
    if profile.get("requiredReceiptSchemaVersion") != LIVE_CALIBRATION_RECEIPT_SCHEMA:
        blockers.append({"code": "invalid-live-calibration-profile", "message": "profile requires an unsupported receipt schema"})
    if HOST not in _strings(profile.get("requiredHosts")):
        blockers.append({"code": "live-calibration-host-unsupported", "message": "gemini-cli is not in requiredHosts"})
    if set(scenarios) != set(_strings(targets.get("corpus"))):
        blockers.append({"code": "live-calibration-corpus-mismatch", "message": "profile scenarios must match budget target corpus"})
    if set(cohorts) != set(_strings(targets.get("cohorts"))):
        blockers.append({"code": "live-calibration-cohort-mismatch", "message": "profile cohorts must match budget target cohorts"})
    if requested_runs < minimum_runs:
        blockers.append({"code": "live-calibration-run-count-too-low", "message": "runs per scenario/cohort is below profile minimum"})


def _usage_or_block(result: CommandResult, budget_policy: BudgetPolicy, blockers: list[dict[str, Any]], label: str) -> GeminiCliUsage | None:
    if result.returncode != 0:
        blockers.append({"code": "gemini-cli-live-invocation-failed", "message": f"{label} returned {result.returncode}"})
        return None
    usage = parse_gemini_cli_stream_json(result.stdout, wall_seconds=result.wall_seconds)
    if not usage.has_usage_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose trustworthy usage"})
        return None
    if budget_policy.usage_requires_cost() and usage.cost_usd is None:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose cost accounting for USD budget reconciliation"})
        return None
    return usage


def _calibration_usage_or_block(
    result: CommandResult,
    budget_policy: BudgetPolicy,
    blockers: list[dict[str, Any]],
    label: str,
    prompt: str,
) -> GeminiCliUsage | None:
    usage = _usage_or_block(result, budget_policy, blockers, label)
    if usage is not None and usage.has_usage_attestation and usage.cumulative_context_bytes is None:
        usage = usage.with_context_byte_proxy(_context_byte_proxy(prompt, result))
    if usage is not None and not usage.has_calibration_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose all required usage metrics"})
        return None
    return usage


def _operation_command(
    gemini_bin: str,
    worktree: Path,
    operation_name: str,
    *,
    gemini_model: str | None = None,
    gemini_fallback_model: str | None = None,
    model_selection: HostModelSelection | None = None,
) -> list[str]:
    _ = worktree
    command = [gemini_bin, "--approval-mode", "plan", "--output-format", "stream-json"]
    command.extend(_model_args(gemini_model, gemini_fallback_model, model_selection))
    command.extend(["--prompt", _prompt_for_operation(operation_name)])
    return command


def _calibration_command(
    gemini_bin: str,
    worktree: Path,
    prompt: str,
    *,
    gemini_model: str | None = None,
    gemini_fallback_model: str | None = None,
    model_selection: HostModelSelection | None = None,
) -> list[str]:
    _ = worktree
    return [gemini_bin, "--approval-mode", "plan", "--output-format", "stream-json", *_model_args(gemini_model, gemini_fallback_model, model_selection), "--prompt", prompt]


def _model_args(
    gemini_model: str | None,
    gemini_fallback_model: str | None,
    model_selection: HostModelSelection | None,
) -> list[str]:
    model = gemini_model or (model_selection.provider_model if model_selection is not None else None)
    _ = gemini_fallback_model
    args: list[str] = []
    if model:
        args.extend(["--model", model])
    return args


def _validate_model_selection_inputs(
    blockers: list[dict[str, Any]],
    model_selection: HostModelSelection | None,
    model_selection_receipt_path: Path | None,
) -> None:
    if model_selection is not None and model_selection_receipt_path is None:
        blockers.append({"code": "missing-model-selection-receipt-path", "message": "--model-selection-receipt is required with --host-model-profile"})


def _blocked_live_report(
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    budget_policy: BudgetPolicy,
    *,
    model_selection: HostModelSelection | None = None,
) -> dict[str, Any]:
    return {
        **_base_report("FAIL", blockers),
        "checks": checks,
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "budgetMode": budget_policy.mode,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def _live_report(
    status: str,
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    budget_policy: BudgetPolicy,
    budget_tracker: BudgetTracker,
    live_calls_started: bool,
    required_count: int,
    passed_count: int,
    receipt_path: Path,
    *,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
) -> dict[str, Any]:
    return {
        **_base_report(status, blockers),
        "checks": checks,
        "requiredOperationCount": required_count,
        "passedOperationCount": passed_count,
        "receipt": _file_identity(receipt_path) if status == "PASS" else None,
        "budgetPolicy": budget_policy.to_json(),
        "budgetUsage": budget_tracker.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "modelSelectionReceipt": _file_identity(model_selection_receipt_path) if status == "PASS" and model_selection_receipt_path else None,
        "budgetMode": budget_policy.mode,
        "budgetCapUsd": budget_policy.budget_cap_usd,
        "cumulativeCostUsd": budget_tracker.cost_usd,
        "liveCallsStarted": live_calls_started,
        "productionPromotionClaimed": False,
    }


def _run_command(command: list[str], checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    elapsed = time.monotonic() - started
    checks.append({"name": name, "status": "PASS" if result.returncode == 0 else "FAIL", "returncode": result.returncode, "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")), "stderrSha256": sha256_hex(result.stderr.encode("utf-8")), "wallSeconds": round(elapsed, 3)})
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _write_invocation_diagnostic(diagnostic_dir: Path, operation_name: str, invocation_id: str, result: CommandResult) -> Path:
    path = diagnostic_dir / f"{operation_name}.json"
    _write_json(path, {"schemaVersion": "agent-gemini-cli-live-invocation-diagnostic.v1", "operation": operation_name, "invocationId": invocation_id, "returncode": result.returncode, "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")), "stderrSha256": sha256_hex(result.stderr.encode("utf-8")), "stdoutBytes": len(result.stdout.encode("utf-8")), "stderrBytes": len(result.stderr.encode("utf-8")), "wallSeconds": result.wall_seconds})
    return path


def _prompt_for_operation(operation_name: str) -> str:
    return (
        "ALK gemini-cli live conformance probe. "
        f"Operation: {operation_name}. "
        "Do not modify files. Reply only with compact JSON: {\"operation\":\"<operation>\",\"status\":\"PASS\"}."
    )


def _prompt_for_calibration(scenario: str, cohort: str, run_index: int) -> str:
    return (
        "ALK gemini-cli live calibration probe. "
        f"Scenario: {scenario}. Cohort: {cohort}. Run: {run_index}. "
        "Do not modify files. Reply only with compact JSON: {\"status\":\"PASS\"}."
    )


def _context_byte_proxy(prompt: str, result: CommandResult) -> int:
    return (
        len(prompt.encode("utf-8"))
        + len(result.stdout.encode("utf-8"))
        + len(result.stderr.encode("utf-8"))
    )


def _json_objects(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": _display_path(path), "sha256": sha256_hex(data), "bytes": len(data)}


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _source_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError("invalid-json", f"expected JSON object: {path.as_posix()}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base_report(status: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schemaVersion": HARNESS_REPORT_SCHEMA, "status": status, "host": HOST, "blockers": blockers}


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


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


def _number_from_any(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


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


def _find_dicts(value: Any, keys: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, dict):
                found.append(item)
            found.extend(_find_dicts(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_dicts(item, keys))
    return found


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
        for key, item in value.items():
            if key in {"tool_call", "toolCall", "tool_calls", "toolCalls"}:
                if isinstance(item, list):
                    total += len(item)
                elif isinstance(item, dict):
                    total += 1
                elif isinstance(item, int):
                    total += item
            total += _count_tool_calls(item)
        return total
    if isinstance(value, list):
        return sum(_count_tool_calls(item) for item in value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
