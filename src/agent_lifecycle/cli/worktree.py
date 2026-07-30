"""CLI wiring for worktree isolation receipts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import read_json_object, write_json_create
from agent_lifecycle.worktree import (
    build_attempt_isolation_receipt,
    validate_attempt_isolation_receipt,
    validate_worktree_policy,
)


def add_worktree_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    worktree = subparsers.add_parser("worktree", help="worktree isolation receipt commands")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)
    policy_check = worktree_sub.add_parser("policy-check")
    policy_check.add_argument("--policy", required=True)
    receipt = worktree_sub.add_parser("receipt")
    receipt.add_argument("--state", required=True)
    receipt.add_argument("--policy", required=True)
    receipt.add_argument("--task", required=True)
    receipt.add_argument("--attempt", required=True, type=int)
    receipt.add_argument("--worktree-path", required=True)
    receipt.add_argument("--baseline-ref", required=True)
    receipt.add_argument("--baseline-sha", required=True)
    receipt.add_argument("--changed-file", action="append", default=[])
    receipt.add_argument("--outcome", choices=["PASS", "FAILED", "BLOCKED"], default="PASS")
    receipt.add_argument("--cleanup-decision", choices=["PRESERVE", "REMOVE"])
    receipt.add_argument("--operator-authorization")
    receipt.add_argument("--reason", required=True)
    receipt.add_argument("--out", required=True)
    check = worktree_sub.add_parser("check")
    check.add_argument("--receipt", required=True)
    check.add_argument("--state")
    check.add_argument("--policy")


def dispatch_worktree(args: argparse.Namespace) -> dict[str, Any]:
    if args.worktree_command == "policy-check":
        return validate_worktree_policy(read_json_object(Path(args.policy), label="worktree policy"))
    if args.worktree_command == "receipt":
        state = read_json_object(Path(args.state), label="workflow state")
        policy = read_json_object(Path(args.policy), label="worktree policy")
        authorization = (
            read_json_object(Path(args.operator_authorization), label="operator authorization")
            if args.operator_authorization
            else None
        )
        receipt = build_attempt_isolation_receipt(
            state,
            task_id=args.task,
            attempt=args.attempt,
            policy=policy,
            worktree_path=args.worktree_path,
            baseline_ref=args.baseline_ref,
            baseline_sha=args.baseline_sha,
            changed_files=args.changed_file,
            outcome=args.outcome,
            cleanup_decision=args.cleanup_decision,
            operator_authorization=authorization,
            reason=args.reason,
        )
        write_json_create(Path(args.out), receipt)
        return receipt
    if args.worktree_command == "check":
        receipt = read_json_object(Path(args.receipt), label="worktree receipt")
        state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        policy = read_json_object(Path(args.policy), label="worktree policy") if args.policy else None
        return validate_attempt_isolation_receipt(receipt, workflow_state=state, policy=policy)
    raise AssertionError("unreachable worktree command")
