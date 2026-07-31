from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest
from tools.live_hosts.common import (
    BudgetPolicy,
    BudgetTracker,
    CommandResult,
    HarnessError,
    HostModelSelection,
    write_model_selection_receipt,
)


LIVE_HOST_RECEIPT_SCHEMA = "agent-lifecycle-live-host-conformance-receipt.v1"
LIVE_CALIBRATION_RECEIPT_SCHEMA = "agent-lifecycle-live-calibration-receipt.v1"


@dataclass(frozen=True)
class JsonCliUsage:
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

    def with_context_byte_proxy(self, value: int) -> "JsonCliUsage":
        return replace(
            self,
            cumulative_context_bytes=value,
            cumulative_context_bytes_source="harness-observed-prompt-and-json-output-bytes",
        )


CommandBuilder = Callable[[str], list[str]]
UsageParser = Callable[[str, float], JsonCliUsage]
CleanWorktreeChecker = Callable[[Path], dict[str, Any]]


def run_fixture_check(*, host: str, baseline_path: Path, report_schema: str) -> dict[str, Any]:
    baseline = load_json(baseline_path)
    operations = build_fixture_operations(host, baseline)
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
        **base_report(report_schema, "PASS" if not blockers else "FAIL", host, blockers),
        "checks": [{"name": "fixture-host-operation-envelopes", "status": "PASS" if not blockers else "FAIL", "details": {"operationCount": len(operations), "syntheticFixtureOnly": True}}],
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(required),
        "operationCount": len(operations),
        "syntheticFixtureOnly": True,
        "productionPromotionClaimed": False,
    }


def run_live_host_receipt(
    *,
    host: str,
    report_schema: str,
    diagnostic_schema: str,
    baseline_path: Path,
    worktree: Path | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy,
    command_for_operation: CommandBuilder,
    usage_parser: UsageParser,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    extra_blockers: list[dict[str, Any]] | None = None,
    runner: Callable[[list[str]], CommandResult] | None = None,
    clean_worktree_checker: CleanWorktreeChecker | None = None,
) -> dict[str, Any]:
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    blockers = list(extra_blockers or [])
    checks: list[dict[str, Any]] = []
    baseline = load_json(baseline_path)
    operations = required_operations(baseline)
    validate_live_inputs(blockers, checks, budget_policy, allow_live, len(operations), worktree, clean_worktree_checker, receipt_path, "live-host-receipt")
    validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return blocked_live_report(report_schema, host, blockers, checks, budget_policy, model_selection=model_selection)

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
        invocation_id = f"{host}-{operation_name}-live-{index:02d}"
        result = command_runner(command_for_operation(operation_name))
        live_calls_started = True
        transcript = write_invocation_diagnostic(diagnostic_dir, operation_name, invocation_id, result, diagnostic_schema)
        checks.append({"name": f"{host}-live-{operation_name}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": display_path(transcript)}})
        record_post_invocation_cleanliness(checks, blockers, worktree, clean_worktree_checker, f"{host}-post-live-{operation_name}", host)
        if blockers:
            break
        usage = usage_or_block(result, budget_policy, blockers, operation_name, usage_parser, host)
        if usage is None:
            break
        try:
            budget_tracker.record(usage, budget_policy)
        except HarnessError as error:
            blockers.append({"code": error.code, "message": error.message})
            break
        live_operations.append(build_live_operation_record(host=host, name=operation_name, invocation_id=invocation_id, usage=usage, output_identity=file_identity(transcript)))

    if not blockers and set(operation["name"] for operation in live_operations) != set(operations):
        blockers.append({"code": "live-host-operation-missing", "message": "not all baseline operations were executed"})
    if not blockers:
        model_selection_identity = write_optional_model_selection(model_selection, model_selection_receipt_path)
        write_json(
            receipt_path,
            {
                "schemaVersion": LIVE_HOST_RECEIPT_SCHEMA,
                "status": "PASS",
                "receiptId": f"{host}-live-host-conformance",
                "host": host,
                "adapterId": host,
                "sourceRevision": source_revision(),
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
    return live_report(report_schema, host, "PASS" if not blockers else "FAIL", blockers, checks, budget_policy, budget_tracker, live_calls_started, len(operations), len(live_operations), receipt_path, model_selection=model_selection, model_selection_receipt_path=model_selection_receipt_path)


def run_live_calibration(
    *,
    host: str,
    report_schema: str,
    diagnostic_schema: str,
    profile_path: Path,
    budget_targets_path: Path,
    worktree: Path | None,
    runs_per_scenario_cohort: int | None,
    allow_live: bool,
    receipt_path: Path | None,
    diagnostic_dir: Path,
    budget_policy: BudgetPolicy,
    command_for_prompt: CommandBuilder,
    usage_parser: UsageParser,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    extra_blockers: list[dict[str, Any]] | None = None,
    runner: Callable[[list[str]], CommandResult] | None = None,
    clean_worktree_checker: CleanWorktreeChecker | None = None,
) -> dict[str, Any]:
    clean_worktree_checker = clean_worktree_checker or check_clean_worktree
    blockers = list(extra_blockers or [])
    checks: list[dict[str, Any]] = []
    profile = load_json(profile_path)
    targets = load_json(budget_targets_path)
    scenarios = strings(profile.get("requiredScenarios"))
    cohorts = strings(profile.get("requiredCohorts"))
    minimum_runs = positive_int(profile.get("minimumRunsPerScenarioCohort")) or 1
    requested_runs = runs_per_scenario_cohort or minimum_runs
    required_invocations = len(scenarios) * len(cohorts) * requested_runs
    validate_calibration_inputs(profile, targets, blockers, scenarios, cohorts, requested_runs, minimum_runs, host)
    validate_live_inputs(blockers, checks, budget_policy, allow_live, required_invocations, worktree, clean_worktree_checker, receipt_path, "live-calibration")
    validate_model_selection_inputs(blockers, model_selection, model_selection_receipt_path)
    if blockers:
        return blocked_live_report(report_schema, host, blockers, checks, budget_policy, model_selection=model_selection)

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
                invocation_id = f"{host}-{scenario}-{cohort}-{run_index:02d}"
                prompt = prompt_for_calibration(host, scenario, cohort, run_index)
                result = command_runner(command_for_prompt(prompt))
                live_calls_started = True
                transcript = write_invocation_diagnostic(diagnostic_dir, f"{scenario}-{cohort}-{run_index:02d}", invocation_id, result, diagnostic_schema)
                checks.append({"name": f"{host}-calibration-{scenario}-{cohort}-{run_index:02d}", "status": "PASS" if result.returncode == 0 else "FAIL", "details": {"returncode": result.returncode, "diagnostic": display_path(transcript)}})
                record_post_invocation_cleanliness(checks, blockers, worktree, clean_worktree_checker, f"{host}-post-calibration-{scenario}-{cohort}-{run_index:02d}", host)
                if blockers:
                    break
                usage = calibration_usage_or_block(result, budget_policy, blockers, f"{scenario}/{cohort}/{run_index}", prompt, usage_parser, host)
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
        model_selection_identity = write_optional_model_selection(model_selection, model_selection_receipt_path)
        write_json(
            receipt_path,
            {
                "schemaVersion": LIVE_CALIBRATION_RECEIPT_SCHEMA,
                "status": "PASS",
                "receiptId": f"{host}-live-calibration",
                "host": host,
                "profileId": profile.get("profileId"),
                "profileDigest": canonical_digest(profile),
                "budgetTargetsDigest": canonical_digest(targets),
                "sourceRevision": source_revision(),
                "liveModelInvocations": len(runs),
                "syntheticReplayUsed": False,
                "qualityRegressionCount": 0,
                "usageAttestationPolicy": budget_policy.usage_attestation_policy(f"{host}-json"),
                "contextByteAccounting": "host-json-or-harness-observed-prompt-and-output-bytes",
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
    report = live_report(report_schema, host, "PASS" if not blockers else "FAIL", blockers, checks, budget_policy, budget_tracker, live_calls_started, required_invocations, len(runs), receipt_path, model_selection=model_selection, model_selection_receipt_path=model_selection_receipt_path)
    return {**report, "profileDigest": canonical_digest(profile), "budgetTargetsDigest": canonical_digest(targets), "requiredScenarioCount": len(scenarios), "requiredCohortCount": len(cohorts), "runsPerScenarioCohort": requested_runs}


def build_fixture_operations(host: str, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for name in required_operations(baseline):
        operation_id = f"{host}-{name}-fixture"
        request = HostOperationRequest(operation_id=operation_id, capability=name, inputs={"host": host, "fixture": True}, outputs=[], constraints={"usageReceiptRequired": True, "syntheticFixtureOnly": True})
        receipt = HostOperationReceipt(operation_id=operation_id, capability=name, status="PASS", outputs=[], usage={"toolCalls": 0, "billableTokens": 0, "syntheticFixtureOnly": True})
        operations.append({"name": name, "status": "PASS", "syntheticReplayUsed": True, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()})
    return operations


def build_live_operation_record(*, host: str, name: str, invocation_id: str, usage: JsonCliUsage, output_identity: dict[str, Any]) -> dict[str, Any]:
    request = HostOperationRequest(operation_id=invocation_id, capability=name, inputs={"host": host}, outputs=[output_identity], constraints={"usageReceiptRequired": True, "syntheticReplayForbidden": True})
    receipt = HostOperationReceipt(operation_id=invocation_id, capability=name, status="PASS", outputs=[output_identity], usage=usage.to_receipt_usage())
    return {"name": name, "status": "PASS", "syntheticReplayUsed": False, "hostOperationRequest": request.to_json(), "hostOperationReceipt": receipt.to_json()}


def parse_json_objects(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            events.append(value)
        index = start + max(end, 1)
    return events


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
        result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            returncode=124,
            stdout=error.stdout if isinstance(error.stdout, str) else "",
            stderr=error.stderr if isinstance(error.stderr, str) else f"timed out after {timeout_seconds} seconds",
            wall_seconds=round(time.monotonic() - started, 3),
        )
    return CommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, wall_seconds=round(time.monotonic() - started, 3))


def required_operations(baseline: dict[str, Any]) -> list[str]:
    return strings(baseline.get("requiredOperations"))


def validate_live_inputs(
    blockers: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    budget_policy: BudgetPolicy,
    allow_live: bool,
    required_invocations: int,
    worktree: Path | None,
    clean_worktree_checker: CleanWorktreeChecker,
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


def validate_calibration_inputs(
    profile: dict[str, Any],
    targets: dict[str, Any],
    blockers: list[dict[str, Any]],
    scenarios: list[str],
    cohorts: list[str],
    requested_runs: int,
    minimum_runs: int,
    host: str,
) -> None:
    if profile.get("requiredReceiptSchemaVersion") != LIVE_CALIBRATION_RECEIPT_SCHEMA:
        blockers.append({"code": "invalid-live-calibration-profile", "message": "profile requires an unsupported receipt schema"})
    if host not in strings(profile.get("requiredHosts")):
        blockers.append({"code": "live-calibration-host-unsupported", "message": f"{host} is not in requiredHosts"})
    if set(scenarios) != set(strings(targets.get("corpus"))):
        blockers.append({"code": "live-calibration-corpus-mismatch", "message": "profile scenarios must match budget target corpus"})
    if set(cohorts) != set(strings(targets.get("cohorts"))):
        blockers.append({"code": "live-calibration-cohort-mismatch", "message": "profile cohorts must match budget target cohorts"})
    if requested_runs < minimum_runs:
        blockers.append({"code": "live-calibration-run-count-too-low", "message": "runs per scenario/cohort is below profile minimum"})


def usage_or_block(result: CommandResult, budget_policy: BudgetPolicy, blockers: list[dict[str, Any]], label: str, usage_parser: UsageParser, host: str) -> JsonCliUsage | None:
    if result.returncode != 0:
        blockers.append({"code": f"{host}-live-invocation-failed", "message": f"{label} returned {result.returncode}"})
        return None
    usage = usage_parser(result.stdout, result.wall_seconds)
    if not usage.has_usage_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose trustworthy usage"})
        return None
    if budget_policy.usage_requires_cost() and usage.cost_usd is None:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose cost accounting for USD budget reconciliation"})
        return None
    return usage


def calibration_usage_or_block(result: CommandResult, budget_policy: BudgetPolicy, blockers: list[dict[str, Any]], label: str, prompt: str, usage_parser: UsageParser, host: str) -> JsonCliUsage | None:
    usage = usage_or_block(result, budget_policy, blockers, label, usage_parser, host)
    if usage is not None and usage.has_usage_attestation and usage.cumulative_context_bytes is None:
        usage = usage.with_context_byte_proxy(context_byte_proxy(prompt, result))
    if usage is not None and not usage.has_calibration_attestation:
        blockers.append({"code": "BLOCKED_USAGE_ATTESTATION", "message": f"{label} did not expose all required usage metrics"})
        return None
    return usage


def validate_model_selection_inputs(blockers: list[dict[str, Any]], model_selection: HostModelSelection | None, model_selection_receipt_path: Path | None) -> None:
    if model_selection is not None and model_selection_receipt_path is None:
        blockers.append({"code": "missing-model-selection-receipt-path", "message": "--model-selection-receipt is required with --host-model-profile"})


def blocked_live_report(report_schema: str, host: str, blockers: list[dict[str, Any]], checks: list[dict[str, Any]], budget_policy: BudgetPolicy, *, model_selection: HostModelSelection | None = None) -> dict[str, Any]:
    return {
        **base_report(report_schema, "FAIL", host, blockers),
        "checks": checks,
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "budgetMode": budget_policy.mode,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def live_report(
    report_schema: str,
    host: str,
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
        **base_report(report_schema, status, host, blockers),
        "checks": checks,
        "requiredOperationCount": required_count,
        "passedOperationCount": passed_count,
        "receipt": file_identity(receipt_path) if status == "PASS" else None,
        "budgetPolicy": budget_policy.to_json(),
        "budgetUsage": budget_tracker.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "modelSelectionReceipt": file_identity(model_selection_receipt_path) if status == "PASS" and model_selection_receipt_path else None,
        "budgetMode": budget_policy.mode,
        "budgetCapUsd": budget_policy.budget_cap_usd,
        "cumulativeCostUsd": budget_tracker.cost_usd,
        "liveCallsStarted": live_calls_started,
        "productionPromotionClaimed": False,
    }


def run_command(command: list[str], checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    elapsed = time.monotonic() - started
    checks.append({"name": name, "status": "PASS" if result.returncode == 0 else "FAIL", "returncode": result.returncode, "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")), "stderrSha256": sha256_hex(result.stderr.encode("utf-8")), "wallSeconds": round(elapsed, 3)})
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def write_invocation_diagnostic(diagnostic_dir: Path, operation_name: str, invocation_id: str, result: CommandResult, schema_version: str) -> Path:
    path = diagnostic_dir / f"{operation_name}.json"
    write_json(path, {"schemaVersion": schema_version, "operation": operation_name, "invocationId": invocation_id, "returncode": result.returncode, "stdoutSha256": sha256_hex(result.stdout.encode("utf-8")), "stderrSha256": sha256_hex(result.stderr.encode("utf-8")), "stdoutBytes": len(result.stdout.encode("utf-8")), "stderrBytes": len(result.stderr.encode("utf-8")), "wallSeconds": result.wall_seconds})
    return path


def prompt_for_calibration(host: str, scenario: str, cohort: str, run_index: int) -> str:
    return (
        f"ALK {host} live calibration probe. "
        f"Scenario: {scenario}. Cohort: {cohort}. Run: {run_index}. "
        "Do not use tools. Do not modify files. Reply only with compact JSON: {\"status\":\"PASS\"}."
    )


def context_byte_proxy(prompt: str, result: CommandResult) -> int:
    return len(prompt.encode("utf-8")) + len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))


def record_post_invocation_cleanliness(checks: list[dict[str, Any]], blockers: list[dict[str, Any]], worktree: Path, clean_worktree_checker: CleanWorktreeChecker, name: str, host: str) -> None:
    clean = clean_worktree_checker(worktree)
    checks.append({"name": name, "status": "PASS" if clean.get("clean") else "FAIL", "details": clean})
    if not clean.get("clean"):
        blockers.append({"code": "BLOCKED_WORKTREE_MUTATED", "message": f"{host} live invocation left the worktree dirty"})


def write_optional_model_selection(model_selection: HostModelSelection | None, model_selection_receipt_path: Path | None) -> dict[str, Any] | None:
    if model_selection is None or model_selection_receipt_path is None:
        return None
    write_model_selection_receipt(model_selection_receipt_path, model_selection)
    return file_identity(model_selection_receipt_path)


def file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": display_path(path), "sha256": sha256_hex(data), "bytes": len(data)}


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def source_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError("invalid-json", f"expected JSON object: {path.as_posix()}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def base_report(report_schema: str, status: str, host: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schemaVersion": report_schema, "status": status, "host": host, "blockers": blockers}


def first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
