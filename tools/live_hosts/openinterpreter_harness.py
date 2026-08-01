from __future__ import annotations

import argparse
import json
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
    HostEnvFile,
    HostModelSelection,
    add_host_env_args,
    dispatch_with_host_env,
    load_host_model_selection,
    subprocess_env_with_host_env,
)
from tools.live_hosts.json_cli_harness import (  # noqa: E402
    LIVE_HOST_RECEIPT_SCHEMA,
    JsonCliUsage,
    base_report,
    build_fixture_operations,
    file_identity,
    first_line,
    load_json,
    parse_jsonl_usage,
    run_command,
    run_fixture_check as run_json_fixture_check,
    run_live_calibration as run_json_live_calibration,
    run_live_host_receipt as run_json_live_host_receipt,
    write_json,
)


HOST = "openinterpreter"
HARNESS_REPORT_SCHEMA = "agent-openinterpreter-live-harness-report.v1"
DIAGNOSTIC_SCHEMA = "agent-openinterpreter-live-invocation-diagnostic.v1"
DEFAULT_BASELINE = Path("conformance/core/adapter-baseline.v1.json")
DEFAULT_PROFILE = Path("conformance/core/live-calibration-profile.v1.json")
DEFAULT_BUDGET_TARGETS = Path("conformance/core/budget-targets.v1.json")
OpenInterpreterUsage = JsonCliUsage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preflight", "fixture-check", "live-host-receipt", "live-calibration"], required=True)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE.as_posix())
    parser.add_argument("--profile", default=DEFAULT_PROFILE.as_posix())
    parser.add_argument("--budget-targets", default=DEFAULT_BUDGET_TARGETS.as_posix())
    parser.add_argument("--interpreter-bin", default="interpreter")
    parser.add_argument("--interpreter-model")
    parser.add_argument("--oss", action="store_true")
    parser.add_argument("--local-provider")
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
    parser.add_argument("--diagnostic-dir", default="work/release-1-18/evidence/live-host-diagnostics/openinterpreter")
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
    host_env = None
    if args.mode == "preflight":
        return run_preflight(
            interpreter_bin=args.interpreter_bin,
            baseline_path=Path(args.baseline),
            worktree=Path(args.worktree) if args.worktree else None,
            budget_policy=budget_policy,
            allow_live=args.allow_live,
            interpreter_model=args.interpreter_model,
            oss=args.oss,
            local_provider=args.local_provider,
            containment_receipt_path=Path(args.containment_receipt) if args.containment_receipt else None,
            model_selection=model_selection,
            host_env=host_env,
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
            interpreter_bin=args.interpreter_bin,
            interpreter_model=args.interpreter_model,
            oss=args.oss,
            local_provider=args.local_provider,
            invocation_timeout_seconds=args.invocation_timeout_seconds,
            model_selection=model_selection,
            model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
            host_env=host_env,
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
        interpreter_bin=args.interpreter_bin,
        interpreter_model=args.interpreter_model,
        oss=args.oss,
        local_provider=args.local_provider,
        invocation_timeout_seconds=args.invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=Path(args.model_selection_receipt) if args.model_selection_receipt else None,
        host_env=host_env,
    )


def run_preflight(
    *,
    interpreter_bin: str,
    baseline_path: Path,
    worktree: Path | None,
    budget_policy: BudgetPolicy,
    allow_live: bool,
    interpreter_model: str | None = None,
    oss: bool = False,
    local_provider: str | None = None,
    containment_receipt_path: Path | None = None,
    model_selection: HostModelSelection | None = None,
    host_env: HostEnvFile | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    environment = _subprocess_env(host_env)
    version = run_command([interpreter_bin, "--version"], checks, "openinterpreter-version", env=environment)
    help_result = run_command([interpreter_bin, "--help"], checks, "openinterpreter-help", env=environment)
    exec_help = run_command([interpreter_bin, "exec", "--help"], checks, "openinterpreter-exec-help", env=environment)
    doctor = run_command(_doctor_command(interpreter_bin, interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection), checks, "openinterpreter-doctor-json", env=environment)
    doctor_summary = _doctor_summary(doctor["stdout"])
    baseline = load_json(baseline_path)
    operations = _required_operations(baseline)
    containment_policy = _containment_policy(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection)
    if not operations:
        blockers.append({"code": "invalid-adapter-baseline", "message": "adapter baseline has no required operations"})
    _validate_containment(containment_policy, blockers)
    _collect_doctor_blockers(doctor, doctor_summary, blockers)
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
    commands_ok = all(result["returncode"] == 0 for result in (version, help_result, exec_help, doctor))
    status = "PASS" if not blockers and commands_ok else "FAIL"
    if containment_receipt_path is not None:
        write_json(
            containment_receipt_path,
            _containment_receipt(
                status=status,
                blockers=blockers,
                policy=containment_policy,
                interpreter_version=first_line(version["stdout"]),
                doctor_summary=doctor_summary,
            ),
        )
    return {
        **base_report(HARNESS_REPORT_SCHEMA, status, HOST, blockers),
        "checks": checks,
        "interpreterVersion": first_line(version["stdout"]),
        "doctorSummary": doctor_summary,
        "baselineDigest": canonical_digest(baseline),
        "requiredOperationCount": len(operations),
        "containmentPolicy": containment_policy,
        "containmentReceipt": file_identity(containment_receipt_path) if containment_receipt_path and containment_receipt_path.exists() else None,
        "budgetPolicy": budget_policy.to_json(),
        "modelSelection": model_selection.redacted_json() if model_selection else None,
        "hostEnv": host_env.redacted_json() if host_env else None,
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
    interpreter_bin: str = "interpreter",
    interpreter_model: str | None = None,
    oss: bool = False,
    local_provider: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    host_env: HostEnvFile | None = None,
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
            interpreter_bin,
            operation,
            interpreter_model=interpreter_model,
            oss=oss,
            local_provider=local_provider,
            model_selection=model_selection,
        ),
        usage_parser=parse_openinterpreter_jsonl,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection),
        runner=runner or _runner_with_env(host_env, worktree=worktree, timeout_seconds=invocation_timeout_seconds),
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
    interpreter_bin: str = "interpreter",
    interpreter_model: str | None = None,
    oss: bool = False,
    local_provider: str | None = None,
    invocation_timeout_seconds: float = 600.0,
    model_selection: HostModelSelection | None = None,
    model_selection_receipt_path: Path | None = None,
    host_env: HostEnvFile | None = None,
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
            interpreter_bin,
            prompt,
            interpreter_model=interpreter_model,
            oss=oss,
            local_provider=local_provider,
            model_selection=model_selection,
        ),
        usage_parser=parse_openinterpreter_jsonl,
        invocation_timeout_seconds=invocation_timeout_seconds,
        model_selection=model_selection,
        model_selection_receipt_path=model_selection_receipt_path,
        extra_blockers=_containment_blockers(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection),
        runner=runner or _runner_with_env(host_env, worktree=worktree, timeout_seconds=invocation_timeout_seconds),
        clean_worktree_checker=clean_worktree_checker,
    )


def parse_openinterpreter_jsonl(text: str, wall_seconds: float = 0.0) -> OpenInterpreterUsage:
    return parse_jsonl_usage(text, wall_seconds=wall_seconds, context_source="host-jsonl")


def _operation_command(
    interpreter_bin: str,
    operation_name: str,
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> list[str]:
    return _run_command(
        interpreter_bin,
        (
            f"ALK OpenInterpreter live conformance probe. Operation: {operation_name}. "
            "Do not use tools. Do not modify files. Reply only with compact JSON: {\"operation\":\"<operation>\",\"status\":\"PASS\"}."
        ),
        interpreter_model=interpreter_model,
        oss=oss,
        local_provider=local_provider,
        model_selection=model_selection,
    )


def _run_command(
    interpreter_bin: str,
    prompt: str,
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> list[str]:
    return [
        interpreter_bin,
        "--ask-for-approval",
        "never",
        "--no-alt-screen",
        *_model_args(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection),
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--cd",
        ".",
        prompt,
    ]


def _doctor_command(
    interpreter_bin: str,
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> list[str]:
    return [
        interpreter_bin,
        *_model_args(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection),
        "doctor",
        "--json",
    ]


def _model_args(
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> list[str]:
    model = interpreter_model or (model_selection.provider_model if model_selection is not None else None)
    args: list[str] = []
    if oss:
        args.append("--oss")
    if local_provider:
        args.extend(["--local-provider", local_provider])
    if model:
        args.extend(["--model", model])
    return args


def _containment_blockers(
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    _validate_containment(_containment_policy(interpreter_model=interpreter_model, oss=oss, local_provider=local_provider, model_selection=model_selection), blockers)
    return blockers


def _containment_policy(
    *,
    interpreter_model: str | None,
    oss: bool,
    local_provider: str | None,
    model_selection: HostModelSelection | None,
) -> dict[str, Any]:
    model = interpreter_model or (model_selection.provider_model if model_selection is not None else None)
    return {
        "schemaVersion": "agent-openinterpreter-live-containment-policy.v1",
        "host": HOST,
        "commandSurface": "codex-like-exec",
        "jsonEvents": True,
        "ephemeral": True,
        "sandboxMode": "read-only",
        "approvalPolicy": "never",
        "webSearchEnabled": False,
        "altScreenDisabled": True,
        "ossMode": oss,
        "localProviderOverridePresent": bool(local_provider),
        "modelOverridePresent": model is not None,
        "postInvocationCleanWorktreeRequired": True,
        "promptPolicy": "no-tools-no-file-modifications-json-only",
    }


def _validate_containment(policy: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if policy.get("jsonEvents") is not True or policy.get("ephemeral") is not True:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_INVOCATION", "message": "openinterpreter live promotion requires JSON event output and ephemeral exec"})
    if policy.get("sandboxMode") != "read-only" or policy.get("approvalPolicy") != "never":
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_TOOLS", "message": "openinterpreter live promotion requires read-only sandbox and approval=never"})
    if policy.get("webSearchEnabled") is not False:
        blockers.append({"code": "BLOCKED_UNBOUNDED_HOST_NETWORK", "message": "openinterpreter live promotion must not enable web search"})
    if policy.get("modelOverridePresent") is not True:
        blockers.append({"code": "BLOCKED_MODEL_BINDING_UNDECLARED", "message": "openinterpreter live promotion requires explicit host-local model"})


def _doctor_summary(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"parseStatus": "FAIL", "overallStatus": None, "failedChecks": []}
    if not isinstance(payload, dict):
        return {"parseStatus": "FAIL", "overallStatus": None, "failedChecks": []}
    checks = payload.get("checks")
    failed: list[dict[str, Any]] = []
    if isinstance(checks, dict):
        for check in checks.values():
            if not isinstance(check, dict) or check.get("status") not in {"fail", "warn"}:
                continue
            failed.append(
                {
                    "id": check.get("id"),
                    "category": check.get("category"),
                    "status": check.get("status"),
                    "summary": check.get("summary"),
                    "remediation": check.get("remediation"),
                }
            )
    return {
        "parseStatus": "PASS",
        "overallStatus": payload.get("overallStatus"),
        "codexVersion": payload.get("codexVersion"),
        "failedChecks": failed,
    }


def _collect_doctor_blockers(doctor: dict[str, Any], summary: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if summary.get("parseStatus") != "PASS":
        blockers.append({"code": "OPENINTERPRETER_DOCTOR_UNREADABLE", "message": "interpreter doctor --json did not return a JSON object"})
        return
    if doctor.get("returncode") != 0 or summary.get("overallStatus") != "ok":
        blockers.append({"code": "OPENINTERPRETER_PREFLIGHT_FAILED", "message": "interpreter doctor did not pass"})
    for check in summary.get("failedChecks", []):
        if not isinstance(check, dict):
            continue
        if check.get("category") == "auth":
            blockers.append({"code": "BLOCKED_MODEL_CONNECTION_UNAVAILABLE", "message": str(check.get("summary") or "model provider auth failed")})


def _containment_receipt(
    *,
    status: str,
    blockers: list[dict[str, Any]],
    policy: dict[str, Any],
    interpreter_version: str | None,
    doctor_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-openinterpreter-live-containment-receipt.v1",
        "status": status,
        "host": HOST,
        "interpreterVersion": interpreter_version,
        "policy": policy,
        "doctorSummary": doctor_summary,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }


def _model_selection_from_args(args: argparse.Namespace) -> HostModelSelection | None:
    if not args.host_model_profile:
        return None
    if not args.model_class:
        raise HarnessError("missing-model-class", "--model-class is required with --host-model-profile")
    return load_host_model_selection(Path(args.host_model_profile), model_class=args.model_class, binding_id=args.model_binding)


def _subprocess_env(host_env: HostEnvFile | None) -> dict[str, str] | None:
    return subprocess_env_with_host_env(host_env)


def _runner_with_env(host_env: HostEnvFile | None, *, worktree: Path | None, timeout_seconds: float) -> Callable[[list[str]], CommandResult] | None:
    if host_env is None:
        return None
    from tools.live_hosts.json_cli_harness import run_command_capture

    env = _subprocess_env(host_env)
    return lambda command: run_command_capture(command, cwd=worktree, timeout_seconds=timeout_seconds, env=env)


def _check_clean_worktree(worktree: Path) -> dict[str, Any]:
    from tools.live_hosts.json_cli_harness import check_clean_worktree

    return check_clean_worktree(worktree)


def _required_operations(baseline: dict[str, Any]) -> list[str]:
    value = baseline.get("requiredOperations")
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
