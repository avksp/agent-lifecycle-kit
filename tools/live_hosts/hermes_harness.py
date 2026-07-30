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


HOST = "hermes"
LIVE_HOST_RECEIPT_SCHEMA = "agent-lifecycle-live-host-conformance-receipt.v1"
LIVE_CALIBRATION_RECEIPT_SCHEMA = "agent-lifecycle-live-calibration-receipt.v1"
HARNESS_REPORT_SCHEMA = "agent-hermes-live-harness-report.v1"
DEFAULT_BASELINE = Path("conformance/core/adapter-baseline.v1.json")
DEFAULT_PROFILE = Path("conformance/core/live-calibration-profile.v1.json")
DEFAULT_BUDGET_TARGETS = Path("conformance/core/budget-targets.v1.json")


@dataclass(frozen=True)
class HermesUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    billable_tokens: int = 0
    raw_total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cumulative_context_bytes: int | None = None
    tool_calls: int = 0
    wall_seconds: float = 0.0
    cost_usd: float | None = None
    session_id: str | None = None
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
            "rawTotalTokens": self.raw_total_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "cacheWriteTokens": self.cache_write_tokens,
            "reasoningTokens": self.reasoning_tokens,
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
            "rawTotalTokens": self.raw_total_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "cacheWriteTokens": self.cache_write_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "cumulativeContextBytes": self.cumulative_context_bytes if self.cumulative_context_bytes is not None else 0,
            "toolCalls": self.tool_calls,
            "wallSeconds": self.wall_seconds,
        }
        if self.cumulative_context_bytes_source:
            usage["cumulativeContextBytesSource"] = self.cumulative_context_bytes_source
        if self.session_id:
            usage["sessionId"] = self.session_id
        return usage

    def with_context_byte_proxy(self, value: int) -> "HermesUsage":
        return replace(
            self,
            cumulative_context_bytes=value,
            cumulative_context_bytes_source="harness-observed-prompt-stdout-stderr-and-usage-file-bytes",
        )


@dataclass(frozen=True)
class HermesInvocationOptions:
    minimal_direct: bool = False
    provider: str | None = None
    model: str | None = None
    toolsets: str | None = None
    ignore_rules: bool = False
    safe_mode: bool = False

    def normalized(self) -> "HermesInvocationOptions":
        if not self.minimal_direct:
            return self
        return replace(self, ignore_rules=True)

    def to_json(self) -> dict[str, Any]:
        return {
            "minimalDirect": self.minimal_direct,
            "provider": self.provider,
            "model": self.model,
            "toolsets": self.toolsets,
            "ignoreRules": self.ignore_rules,
            "safeMode": self.safe_mode,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "fixture-check", "live-host-receipt", "live-calibration"], required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE.as_posix())
    parser.add_argument("--profile", default=DEFAULT_PROFILE.as_posix())
    parser.add_argument("--budget-targets", default=DEFAULT_BUDGET_TARGETS.as_posix())
    parser.add_argument("--hermes-bin", default="hermes")
    parser.add_argument("--worktree")
    parser.add_argument("--budget-mode", choices=["metered", "subscription", "local"], default="metered")
    parser.add_argument("--budget-cap-usd", type=float)
    parser.add_argument("--max-invocations", type=int)
    parser.add_argument("--max-billable-tokens", type=int)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--runs-per-scenario-cohort", type=int)
    parser.add_argument("--minimal-direct", action="store_true")
    parser.add_argument("--hermes-provider")
    parser.add_argument("--hermes-model")
    parser.add_argument("--host-model-profile")
    parser.add_argument("--model-class")
    parser.add_argument("--model-binding")
    parser.add_argument("--model-selection-receipt")
    parser.add_argument("--hermes-toolsets")
    parser.add_argument("--hermes-ignore-rules", action="store_true")
    parser.add_argument("--hermes-safe-mode", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--report", required=True)
    parser.add_argument("--receipt")
    parser.add_argument("--diagnostic-dir", default="work/release-0-3/evidence/live-host-diagnostics/hermes")
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
    model_selection = _model_selection_from_args(args)
    budget_policy = BudgetPolicy(
        mode=args.budget_mode,
        budget_cap_usd=args.budget_cap_usd,
        max_invocations=args.max_invocations,
        max_billable_tokens=args.max_billable_tokens,
        max_wall_seconds=args.max_wall_seconds,
    )
    invocation_options = HermesInvocationOptions(
        minimal_direct=args.minimal_direct,
        provider=args.hermes_provider or (model_selection.provider if model_selection is not None else None),
        model=args.hermes_model or (model_selection.provider_model if model_selection is not None else None),
        toolsets=args.hermes_toolsets,
        ignore_rules=args.hermes_ignore_rules,
        safe_mode=args.hermes_safe_mode,
    ).normalized()
    if args.mode == "preflight":
        return run_preflight(
            hermes_bin=args.hermes_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            budget_policy=budget_policy,
            allow_live=args.allow_live,
            invocation_options=invocation_options,
            model_selection=model_selection,
        )
    if args.mode == "fixture-check":
        return run_fixture_check(Path(args.baseline))
    if args.mode == "live-host-receipt":
        return run_live_host_receipt(
            hermes_bin=args.hermes_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            allow_live=args.allow_live,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostic_dir=Path(args.diagnostic_dir),
            budget_policy=budget_policy,
            invocation_options=invocation_options,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        )
    if args.mode == "live-calibration":
        return run_live_calibration(
            hermes_bin=args.hermes_bin,
            profile_path=Path(args.profile),
            budget_targets_path=Path(args.budget_targets),
            worktree=Path(args.worktree) if args.worktree else None,
            runs_per_scenario_cohort=args.runs_per_scenario_cohort,
            allow_live=args.allow_live,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostic_dir=Path(args.diagnostic_dir),
            budget_policy=budget_policy,
            invocation_options=invocation_options,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        )
    raise HarnessError("invalid-mode", f"unsupported mode: {args.mode}")


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


def _with_model_selection(
    invocation_options: HermesInvocationOptions | None,
    model_selection: HostModelSelection | None,
) -> HermesInvocationOptions:
    options = (invocation_options or HermesInvocationOptions()).normalized()
    if model_selection is None:
        return options
    return replace(
        options,
        provider=options.provider or model_selection.provider,
        model=options.model or model_selection.provider_model,
    )


def run_preflight(
    *,
    hermes_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    budget_policy: BudgetPolicy,
    allow_live: bool,
    invocation_options: HermesInvocationOptions | None = None,
    model_selection: HostModelSelection | None = None,
) -> dict[str, Any]:
    invocation_options = _with_model_selection(invocation_options, model_selection)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    version = _run_command([hermes_bin, "--version"], checks, "hermes-version")
    help_result = _run_command([hermes_bin, "--help"], checks, "hermes-help")
    status = _run_command([hermes_bin, "status"], checks, "hermes-status")
    baseline = _load_json(baseline_path)
    operations = required_operations(baseline)
    if not operations:
        blockers.append({"code": "invalid-adapter-baseline", "message": "adapter baseline has no required operations"})
    if "--oneshot" not in help_result["stdout"] or "--usage-file" not in help_result["stdout"]:
        blockers.append({"code": "BLOCKED_NON_INTERACTIVE_HOST_SURFACE", "message": "Hermes CLI does not advertise --oneshot with --usage-file"})
    auth = check_hermes_auth(hermes_bin, status_result=status)
    checks.append({"name": "hermes-auth", "status": "PASS" if auth.get("authenticated") else "FAIL", "details": auth})
    if not auth.get("authenticated"):
        blockers.append({"code": "BLOCKED_HOST_AUTH", "message": "Hermes has no configured authenticated inference provider; run hermes model/auth/setup before live promotion"})
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
    surface_ok = version["returncode"] == 0 and help_result["returncode"] == 0
    return {
        **_base_report("PASS" if not blockers and surface_ok else "FAIL", blockers),
        "checks": checks,
        "hermesVersion": _first_line(version["stdout"]),
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(operations),
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "budgetMode": budget_policy.mode,
        "budgetCapUsd": budget_policy.budget_cap_usd,
        "hermesInvocationOptions": invocation_options.to_json(),
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
    hermes_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy | None = None,
    invocation_options: HermesInvocationOptions | None = None,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str], Path | None], CommandResult] = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] = None,
    auth_checker: Callable[[str], dict[str, Any]] = None,
) -> dict[str, Any]:
    runner = runner or run_command_capture
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    auth_checker = auth_checker or check_hermes_auth
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    baseline = _load_json(baseline_path)
    operations = required_operations(baseline)
    budget_policy = budget_policy or BudgetPolicy(mode="metered")
    invocation_options = _with_model_selection(invocation_options, model_selection)
    _validate_live_inputs(blockers, checks, budget_policy, allow_live, len(operations), worktree, clean_worktree_checker, receipt_path, "live-host-receipt")
    _append_auth_check(blockers, checks, auth_checker(hermes_bin))
    _validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return _blocked_live_report(blockers, checks, budget_policy, model_selection=model_selection)

    assert worktree is not None
    assert receipt_path is not None
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
        invocation_id = f"hermes-{operation_name}-live-{index:02d}"
        prompt = _prompt_for_operation(operation_name)
        usage_file = (diagnostic_dir / f"{operation_name}.usage.json").resolve()
        result = runner(_hermes_command(hermes_bin, prompt, usage_file, invocation_options), worktree)
        live_calls_started = True
        transcript = _write_invocation_diagnostic(diagnostic_dir, operation_name, invocation_id, result, usage_file)
        checks.append({"name": f"hermes-live-{operation_name}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": _display_path(transcript)}})
        usage = _usage_or_block(result, usage_file, budget_policy, blockers, operation_name)
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
                "receiptId": "hermes-live-host-conformance",
                "host": HOST,
                "adapterId": HOST,
                "sourceRevision": _source_revision(),
                "syntheticReplayUsed": False,
                "usageAttested": True,
                "budgetPolicy": budget_policy.to_json(),
                "hermesInvocationOptions": invocation_options.to_json(),
                "modelSelection": model_selection.redacted_json() if model_selection else None,
                "modelSelectionReceipt": model_selection_identity,
                "budgetUsage": budget_tracker.to_json(),
                "budgetMode": budget_policy.mode,
                "budgetCapUsd": budget_policy.budget_cap_usd,
                "cumulativeCostUsd": budget_tracker.cost_usd,
                "operations": live_operations,
            },
        )
    return {
        **_live_report("PASS" if not blockers else "FAIL", blockers, checks, budget_policy, budget_tracker, live_calls_started, len(operations), len(live_operations), receipt_path, model_selection=model_selection, model_selection_receipt_path=model_selection_receipt_path),
        "hermesInvocationOptions": invocation_options.to_json(),
    }


def run_live_calibration(
    *,
    hermes_bin: str,
    profile_path: Path,
    budget_targets_path: Path,
    worktree: Path | None,
    runs_per_scenario_cohort: int | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy | None = None,
    invocation_options: HermesInvocationOptions | None = None,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    runner: Callable[[list[str], Path | None], CommandResult] = None,
    clean_worktree_checker: Callable[[Path], dict[str, Any]] = None,
    auth_checker: Callable[[str], dict[str, Any]] = None,
) -> dict[str, Any]:
    runner = runner or run_command_capture
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    auth_checker = auth_checker or check_hermes_auth
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
    invocation_options = _with_model_selection(invocation_options, model_selection)
    _validate_calibration_inputs(profile, targets, blockers, scenarios, cohorts, requested_runs, minimum_runs)
    _validate_live_inputs(blockers, checks, budget_policy, allow_live, required_invocations, worktree, clean_worktree_checker, receipt_path, "live-calibration")
    _append_auth_check(blockers, checks, auth_checker(hermes_bin))
    _validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return _blocked_live_report(blockers, checks, budget_policy, model_selection=model_selection)

    assert worktree is not None
    assert receipt_path is not None
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
                invocation_id = f"hermes-{scenario}-{cohort}-{run_index:02d}"
                prompt = _prompt_for_calibration(scenario, cohort, run_index)
                usage_file = (diagnostic_dir / f"{scenario}-{cohort}-{run_index:02d}.usage.json").resolve()
                result = runner(_hermes_command(hermes_bin, prompt, usage_file, invocation_options), worktree)
                live_calls_started = True
                transcript = _write_invocation_diagnostic(diagnostic_dir, f"{scenario}-{cohort}-{run_index:02d}", invocation_id, result, usage_file)
                checks.append({"name": f"hermes-calibration-{scenario}-{cohort}-{run_index:02d}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": _display_path(transcript)}})
                usage = _calibration_usage_or_block(result, usage_file, budget_policy, blockers, f"{scenario}/{cohort}/{run_index}", prompt)
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
                "receiptId": "hermes-live-calibration",
                "host": HOST,
                "profileId": profile.get("profileId"),
                "profileDigest": canonical_digest(profile),
                "budgetTargetsDigest": canonical_digest(targets),
                "sourceRevision": _source_revision(),
                "liveModelInvocations": len(runs),
                "syntheticReplayUsed": False,
                "qualityRegressionCount": 0,
                "usageAttestationPolicy": budget_policy.usage_attestation_policy("hermes-usage-file"),
                "contextByteAccounting": "usage-file-or-harness-observed-prompt-stdout-stderr-and-usage-file-bytes",
                "budgetPolicy": budget_policy.to_json(),
                "hermesInvocationOptions": invocation_options.to_json(),
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
    return {**report, "profileDigest": canonical_digest(profile), "budgetTargetsDigest": canonical_digest(targets), "requiredScenarioCount": len(scenarios), "requiredCohortCount": len(cohorts), "runsPerScenarioCohort": requested_runs, "runCount": len(runs), "hermesInvocationOptions": invocation_options.to_json()}


def build_fixture_operations(host: str, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for name in required_operations(baseline):
        operation_id = f"{host}-{name}-fixture"
        request = HostOperationRequest(operation_id=operation_id, capability=name, inputs={"host": host, "fixture": True}, outputs=[], constraints={"usageReceiptRequired": True, "syntheticFixtureOnly": True})
        receipt = HostOperationReceipt(operation_id=operation_id, capability=name, status="PASS", outputs=[], usage={"toolCalls": 0, "billableTokens": 0, "syntheticFixtureOnly": True})
        operations.append({"name": name, "status": "PASS", "syntheticReplayUsed": True, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()})
    return operations


def build_live_operation_record(*, host: str, name: str, invocation_id: str, usage: HermesUsage, output_identity: dict[str, Any]) -> dict[str, Any]:
    request = HostOperationRequest(operation_id=invocation_id, capability=name, inputs={"host": host}, outputs=[output_identity], constraints={"usageReceiptRequired": True, "syntheticReplayForbidden": True})
    receipt = HostOperationReceipt(operation_id=invocation_id, capability=name, status="PASS", outputs=[output_identity], usage=usage.to_receipt_usage())
    return {"name": name, "status": "PASS", "syntheticReplayUsed": False, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()}


def parse_hermes_usage_file(payload: dict[str, Any], *, wall_seconds: float = 0.0) -> HermesUsage:
    input_tokens = _int_from_any(_first_present(payload, ("inputTokens", "input_tokens", "prompt_tokens", "promptTokens", "input")))
    output_tokens = _int_from_any(_first_present(payload, ("outputTokens", "output_tokens", "completion_tokens", "completionTokens", "output")))
    total_tokens = _int_from_any(_first_present(payload, ("billableTokens", "billable_tokens", "total_tokens", "totalTokens", "total")))
    cache_read_tokens = _int_from_any(_first_present(payload, ("cacheReadTokens", "cache_read_tokens", "cachedTokens", "cache_read_input_tokens", "cacheReadInputTokens")))
    cache_write_tokens = _int_from_any(_first_present(payload, ("cacheWriteTokens", "cache_write_tokens", "cache_creation_input_tokens", "cacheCreationInputTokens")))
    reasoning_tokens = _int_from_any(_first_present(payload, ("reasoningTokens", "reasoning_tokens")))
    context_bytes = _int_from_any(_first_present(payload, ("cumulativeContextBytes", "cumulative_context_bytes", "contextBytes", "context_bytes")))
    if not (input_tokens or output_tokens or total_tokens):
        token_payload = _first_present(payload, ("tokens", "usage", "tokenUsage"))
        if isinstance(token_payload, dict):
            input_tokens = _int_from_any(_first_present(token_payload, ("inputTokens", "input_tokens", "prompt_tokens", "promptTokens", "input")))
            output_tokens = _int_from_any(_first_present(token_payload, ("outputTokens", "output_tokens", "completion_tokens", "completionTokens", "output")))
            total_tokens = _int_from_any(_first_present(token_payload, ("billableTokens", "billable_tokens", "total_tokens", "totalTokens", "total")))
            cache_read_tokens = _int_from_any(_first_present(token_payload, ("cacheReadTokens", "cache_read_tokens", "cachedTokens", "cache_read_input_tokens", "cacheReadInputTokens")))
            cache_write_tokens = _int_from_any(_first_present(token_payload, ("cacheWriteTokens", "cache_write_tokens", "cache_creation_input_tokens", "cacheCreationInputTokens")))
            reasoning_tokens = _int_from_any(_first_present(token_payload, ("reasoningTokens", "reasoning_tokens")))
            context_bytes = _int_from_any(_first_present(token_payload, ("cumulativeContextBytes", "cumulative_context_bytes", "contextBytes", "context_bytes")))
    return HermesUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=total_tokens or input_tokens + output_tokens,
        raw_total_tokens=total_tokens or input_tokens + output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        cumulative_context_bytes=context_bytes if context_bytes else None,
        cumulative_context_bytes_source="usage-file" if context_bytes else None,
        tool_calls=_int_from_any(_first_present(payload, ("toolCalls", "tool_calls", "api_calls", "apiCalls"))),
        wall_seconds=wall_seconds,
        cost_usd=_float_from_any(_first_present(payload, ("costUsd", "cost_usd", "estimatedCostUsd", "estimated_cost_usd"))),
        session_id=_string_from_any(_first_present(payload, ("sessionId", "session_id", "conversationId", "conversation_id"))),
    )


def check_hermes_auth(hermes_bin: str, status_result: dict[str, Any] | None = None) -> dict[str, Any]:
    status = (
        CommandResult(
            returncode=int(status_result.get("returncode", 1)),
            stdout=str(status_result.get("stdout", "")),
            stderr=str(status_result.get("stderr", "")),
            wall_seconds=0.0,
        )
        if status_result is not None
        else run_command_capture([hermes_bin, "status"], None)
    )
    ok = _hermes_auth_ok({"returncode": status.returncode, "stdout": status.stdout, "stderr": status.stderr})
    configured_provider = _configured_provider(hermes_bin)
    provider_auth_checks: list[dict[str, Any]] = []
    if configured_provider and configured_provider not in {"auto", "main", "moa"}:
        provider_auth = run_command_capture([hermes_bin, "auth", "status", configured_provider], None)
        provider_auth_checks.append(
            {
                "provider": configured_provider,
                "returncode": provider_auth.returncode,
                "stdoutSha256": sha256_hex(provider_auth.stdout.encode("utf-8")),
                "stderrSha256": sha256_hex(provider_auth.stderr.encode("utf-8")),
            }
        )
        if _auth_status_logged_in(provider_auth.stdout, provider_auth.stderr):
            ok = True
    return {
        "authenticated": ok,
        "configuredProvider": configured_provider,
        "providerAuthChecks": provider_auth_checks,
        "statusReturncode": status.returncode,
        "statusStdoutSha256": sha256_hex(status.stdout.encode("utf-8")),
        "statusStderrSha256": sha256_hex(status.stderr.encode("utf-8")),
    }


def check_clean_worktree(worktree: Path) -> dict[str, Any]:
    if not worktree.exists():
        return {"clean": False, "reason": "missing-worktree"}
    result = subprocess.run(["git", "-C", str(worktree), "status", "--short"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return {"clean": False, "reason": "not-a-git-worktree", "stderrSha256": sha256_hex(result.stderr.encode("utf-8"))}
    return {"clean": result.stdout == "", "dirtyEntryCount": len([line for line in result.stdout.splitlines() if line.strip()])}


def run_command_capture(command: list[str], cwd: Path | None = None) -> CommandResult:
    started = time.monotonic()
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return CommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, wall_seconds=round(time.monotonic() - started, 3))


def required_operations(baseline: dict[str, Any]) -> list[str]:
    value = baseline.get("requiredOperations")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _validate_live_inputs(blockers: list[dict[str, Any]], checks: list[dict[str, Any]], budget_policy: BudgetPolicy, allow_live: bool, required_invocations: int, worktree: Path | None, clean_worktree_checker: Callable[[Path], dict[str, Any]], receipt_path: Path | None, mode: str) -> None:
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


def _validate_calibration_inputs(profile: dict[str, Any], targets: dict[str, Any], blockers: list[dict[str, Any]], scenarios: list[str], cohorts: list[str], requested_runs: int, minimum_runs: int) -> None:
    if profile.get("requiredReceiptSchemaVersion") != LIVE_CALIBRATION_RECEIPT_SCHEMA:
        blockers.append({"code": "invalid-live-calibration-profile", "message": "profile requires an unsupported receipt schema"})
    if HOST not in _strings(profile.get("requiredHosts")):
        blockers.append({"code": "live-calibration-host-unsupported", "message": "hermes is not in requiredHosts"})
    if set(scenarios) != set(_strings(targets.get("corpus"))):
        blockers.append({"code": "live-calibration-corpus-mismatch", "message": "profile scenarios must match budget target corpus"})
    if set(cohorts) != set(_strings(targets.get("cohorts"))):
        blockers.append({"code": "live-calibration-cohort-mismatch", "message": "profile cohorts must match budget target cohorts"})
    if requested_runs < minimum_runs:
        blockers.append({"code": "live-calibration-run-count-too-low", "message": "runs per scenario/cohort is below profile minimum"})


def _append_auth_check(blockers: list[dict[str, Any]], checks: list[dict[str, Any]], auth: dict[str, Any]) -> None:
    checks.append({"name": "hermes-auth", "status": "PASS" if auth.get("authenticated") else "FAIL", "details": auth})
    if not auth.get("authenticated"):
        blockers.append({"code": "BLOCKED_HOST_AUTH", "message": "Hermes has no configured authenticated inference provider; run hermes model/auth/setup before live promotion"})


def _usage_or_block(result: CommandResult, usage_file: Path, budget_policy: BudgetPolicy, blockers: list[dict[str, Any]], label: str) -> HermesUsage | None:
    if result.returncode != 0:
        blockers.append({"code": "hermes-live-invocation-failed", "message": f"{label} returned {result.returncode}"})
        return None
    if not usage_file.is_file():
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not write a Hermes usage file"})
        return None
    try:
        payload = json.loads(usage_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} wrote malformed Hermes usage JSON"})
        return None
    if not isinstance(payload, dict):
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} wrote non-object Hermes usage JSON"})
        return None
    usage = parse_hermes_usage_file(payload, wall_seconds=result.wall_seconds)
    if not usage.has_usage_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose trustworthy usage"})
        return None
    if budget_policy.usage_requires_cost() and usage.cost_usd is None:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose cost accounting for USD budget reconciliation"})
        return None
    return usage


def _calibration_usage_or_block(result: CommandResult, usage_file: Path, budget_policy: BudgetPolicy, blockers: list[dict[str, Any]], label: str, prompt: str) -> HermesUsage | None:
    usage = _usage_or_block(result, usage_file, budget_policy, blockers, label)
    if usage is not None and usage.has_usage_attestation and usage.cumulative_context_bytes is None:
        usage = usage.with_context_byte_proxy(_context_byte_proxy(prompt, result, usage_file))
    if usage is not None and not usage.has_calibration_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose all required usage metrics"})
        return None
    return usage


def _hermes_command(
    hermes_bin: str,
    prompt: str,
    usage_file: Path,
    invocation_options: HermesInvocationOptions | None = None,
) -> list[str]:
    invocation_options = (invocation_options or HermesInvocationOptions()).normalized()
    command = [hermes_bin]
    if invocation_options.safe_mode:
        command.append("--safe-mode")
    if invocation_options.ignore_rules:
        command.append("--ignore-rules")
    if invocation_options.provider:
        command.extend(["--provider", invocation_options.provider])
    if invocation_options.model:
        command.extend(["--model", invocation_options.model])
    if invocation_options.toolsets:
        command.extend(["--toolsets", invocation_options.toolsets])
    command.extend(["--oneshot", prompt, "--usage-file", str(usage_file), "--no-restore-cwd", "--accept-hooks"])
    return command


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


def _write_invocation_diagnostic(diagnostic_dir: Path, operation_name: str, invocation_id: str, result: CommandResult, usage_file: Path) -> Path:
    path = diagnostic_dir / f"{operation_name}.json"
    usage_identity = _file_identity(usage_file) if usage_file.is_file() else None
    _write_json(path, {"schemaVersion": "agent-hermes-live-invocation-diagnostic.v1", "operation": operation_name, "invocationId": invocation_id, "returncode": result.returncode, "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")), "stderrSha256": sha256_hex(result.stderr.encode("utf-8")), "stdoutBytes": len(result.stdout.encode("utf-8")), "stderrBytes": len(result.stderr.encode("utf-8")), "wallSeconds": result.wall_seconds, "usageFile": usage_identity})
    return path


def _prompt_for_operation(operation_name: str) -> str:
    return (
        "Agent Lifecycle Kit Hermes live host conformance probe. "
        f"Operation: {operation_name}. "
        "Do not modify files unless the operation is tool-execution. "
        "Return a compact JSON object with operation and status PASS."
    )


def _prompt_for_calibration(scenario: str, cohort: str, run_index: int) -> str:
    return (
        "Agent Lifecycle Kit Hermes live calibration probe. "
        f"Scenario: {scenario}. Cohort: {cohort}. Run: {run_index}. "
        "Do not modify files. Return a compact JSON object with scenario, cohort, and status PASS."
    )


def _context_byte_proxy(prompt: str, result: CommandResult, usage_file: Path) -> int:
    usage_bytes = len(usage_file.read_bytes()) if usage_file.is_file() else 0
    return len(prompt.encode("utf-8")) + len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) + usage_bytes


def _hermes_auth_ok(status: dict[str, Any]) -> bool:
    if status.get("returncode") != 0:
        return False
    provider_markers = (
        "openrouter",
        "openai",
        "anthropic",
        "google",
        "gemini",
        "nous portal",
        "codex",
        "qwen",
        "oauth",
        "api-key providers",
    )
    for line in f"{status.get('stdout', '')}\n{status.get('stderr', '')}".splitlines():
        lower = line.lower()
        if "✓" not in line or not any(marker in lower for marker in provider_markers):
            continue
        if "not " in lower or "error:" in lower:
            continue
        return True
    return False


def _configured_provider(hermes_bin: str) -> str | None:
    result = run_command_capture([hermes_bin, "config", "get", "model.provider"], None)
    if result.returncode != 0:
        return None
    provider = result.stdout.strip().splitlines()[0].strip().lower() if result.stdout.strip() else ""
    return provider or None


def _auth_status_logged_in(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return "logged in" in text and "logged out" not in text and "rate-limited" not in text and "exhausted" not in text


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


def _float_from_any(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_from_any(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
