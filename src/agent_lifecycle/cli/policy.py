"""CLI wiring for lifecycle policy proposal commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.policy import (
    apply_policy_proposal,
    build_adaptive_lifecycle_decision,
    build_policy_proposal,
    build_runtime_policy_receipt,
    build_policy_summary,
    require_policy_proposal_pass,
    validate_adaptive_lifecycle_decision,
    validate_runtime_policy_receipt,
)

TUNE_RESULT_SCHEMA = "agent-lifecycle-policy-tune-result.v1"


def add_policy_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    policy = subparsers.add_parser("policy", help="lifecycle policy proposal commands")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    tune = policy_sub.add_parser("tune")
    tune.add_argument("--report", required=True)
    tune.add_argument("--regression-signal", action="append", default=[])
    tune.add_argument("--risk", action="append", default=[])
    tune.add_argument("--apply", action="store_true")
    tune.add_argument("--output")
    tune.add_argument("--summary-output")
    runtime_receipt = policy_sub.add_parser("runtime-receipt")
    runtime_receipt.add_argument("--policy-id", required=True)
    runtime_receipt.add_argument("--action", choices=["ALLOW", "DENY", "ASK"], required=True)
    runtime_receipt.add_argument("--subject", required=True)
    runtime_receipt.add_argument("--adapter-evidence", required=True)
    runtime_receipt.add_argument("--enforcement-mode", choices=["enforced", "advisory"], default="advisory")
    runtime_receipt.add_argument("--evidence-id", action="append", default=[])
    runtime_receipt.add_argument("--out", required=True)
    runtime_check = policy_sub.add_parser("runtime-check")
    runtime_check.add_argument("--receipt", required=True)
    adaptive_decision = policy_sub.add_parser("adaptive-decision")
    adaptive_decision.add_argument("--request", required=True)
    adaptive_decision.add_argument("--baseline-profile", default="profiles/lifecycle-baselines.v1.json")
    adaptive_decision.add_argument("--out")
    adaptive_check = policy_sub.add_parser("adaptive-check")
    adaptive_check.add_argument("--decision", required=True)


def dispatch_policy(args: argparse.Namespace) -> dict[str, Any]:
    if args.policy_command == "runtime-receipt":
        receipt = build_runtime_policy_receipt(
            policy_id=args.policy_id,
            action=args.action,
            subject=read_json_object(Path(args.subject), label="runtime policy subject"),
            adapter_evidence=read_json_object(Path(args.adapter_evidence), label="runtime policy adapter evidence"),
            enforcement_mode=args.enforcement_mode,
            evidence_ids=args.evidence_id,
        )
        write_json_create(Path(args.out), receipt)
        return receipt
    if args.policy_command == "runtime-check":
        return validate_runtime_policy_receipt(read_json_object(Path(args.receipt), label="runtime policy receipt"))
    if args.policy_command == "adaptive-decision":
        decision = build_adaptive_lifecycle_decision(
            read_json_object(Path(args.request), label="adaptive lifecycle request"),
            read_json_object(Path(args.baseline_profile), label="lifecycle baseline profile"),
        )
        if args.out:
            write_json_create(Path(args.out), decision)
        return decision
    if args.policy_command == "adaptive-check":
        return validate_adaptive_lifecycle_decision(read_json_object(Path(args.decision), label="adaptive lifecycle decision"))
    if args.policy_command != "tune":
        raise LifecycleError("command-not-implemented", "policy command is not implemented")
    if args.output and not args.apply:
        raise LifecycleError("policy-output-without-apply", "policy output requires --apply")
    if args.apply and not args.output:
        raise LifecycleError("policy-apply-output-required", "policy apply requires --output")
    recommendation = read_json_object(Path(args.report), label="policy recommendation report")
    regression_signals = [read_json_object(Path(item), label="regression signal") for item in args.regression_signal]
    proposal = require_policy_proposal_pass(
        build_policy_proposal(recommendation, regression_signals=regression_signals, risk_flags=args.risk)
    )
    apply_result = apply_policy_proposal(proposal, Path(args.output)) if args.apply else None
    if args.summary_output:
        write_json_create(Path(args.summary_output), build_policy_summary(proposal))
    body = {
        "schemaVersion": TUNE_RESULT_SCHEMA,
        "status": "PASS",
        "mode": "apply" if args.apply else "dry-run",
        "proposal": proposal,
        "proposalDigest": proposal["proposalDigest"],
        "applyResult": apply_result,
        "applyDigest": apply_result.get("applyDigest") if isinstance(apply_result, dict) else None,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}
