"""CLI wiring for follow-up register commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.followup import (
    add_followup_item,
    build_followup_summary,
    close_followup_item,
    load_followup_register,
    validate_followup_register,
    write_followup_register,
)


def add_followup_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    followup = subparsers.add_parser("followup", help="follow-up register commands")
    followup_sub = followup.add_subparsers(dest="followup_command", required=True)
    check = followup_sub.add_parser("check")
    check.add_argument("--register", required=True)
    check.add_argument("--state")
    check.add_argument("--root", default=".")
    check.add_argument("--fail-on-finalization-blockers", action="store_true")
    add = followup_sub.add_parser("add")
    add.add_argument("--register", required=True)
    add.add_argument("--item", required=True)
    add.add_argument("--out")
    close = followup_sub.add_parser("close")
    close.add_argument("--register", required=True)
    close.add_argument("--item-id", required=True)
    close.add_argument("--evidence-id", action="append", default=[])
    close.add_argument("--artifact", action="append", default=[])
    close.add_argument("--verifier", required=True)
    close.add_argument("--reason", required=True)
    close.add_argument("--root", default=".")
    close.add_argument("--out")
    sweep = followup_sub.add_parser("sweep")
    sweep.add_argument("--register", required=True)
    sweep.add_argument("--state")
    sweep.add_argument("--profile")
    sweep.add_argument("--target-window")


def dispatch_followup(args: argparse.Namespace) -> dict[str, Any]:
    register_path = Path(args.register)
    register = load_followup_register(register_path)
    if args.followup_command == "check":
        state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        validation = validate_followup_register(register, state=state, root=Path(args.root))
        if args.fail_on_finalization_blockers and validation["finalizationBlockers"]:
            raise LifecycleError(
                "follow-up-finalization-blocked",
                "open follow-up items contradict current finalization",
                {"items": validation["finalizationBlockers"]},
            )
        return validation
    if args.followup_command == "add":
        updated = add_followup_item(register, read_json_object(Path(args.item), label="follow-up item"))
        out = Path(args.out) if args.out else register_path
        write_followup_register(out, updated)
        return validate_followup_register(updated)
    if args.followup_command == "close":
        updated = close_followup_item(
            register,
            item_id=args.item_id,
            evidence_ids=args.evidence_id,
            artifact_paths=args.artifact,
            verifier=args.verifier,
            reason=args.reason,
            root=Path(args.root),
        )
        out = Path(args.out) if args.out else register_path
        write_followup_register(out, updated)
        validation = validate_followup_register(updated, root=Path(args.root))
        return {
            "schemaVersion": "agent-follow-up-close-result.v1",
            "status": "PASS",
            "itemId": args.item_id,
            "registerDigest": validation["registerDigest"],
        }
    if args.followup_command == "sweep":
        state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        profile = read_json_object(Path(args.profile), label="context profile") if args.profile else None
        return build_followup_summary(register, state=state, profile=profile, window=args.target_window)
    raise LifecycleError("command-not-implemented", "followup command is not implemented")
