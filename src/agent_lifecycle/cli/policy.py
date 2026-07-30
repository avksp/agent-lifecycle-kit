"""CLI wiring for lifecycle policy proposal commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.policy import (
    apply_policy_proposal,
    build_policy_proposal,
    build_policy_summary,
    require_policy_proposal_pass,
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


def dispatch_policy(args: argparse.Namespace) -> dict[str, Any]:
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
