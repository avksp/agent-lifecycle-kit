"""Public detached-decision parser; no signing or private-key arguments."""

from __future__ import annotations

import argparse


def add_operator_signature_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser("operator-signature", help="prepare or verify public detached decisions")
    actions = group.add_subparsers(dest="operator_signature_command", required=True)
    for action in ("request", "verify"):
        parser = actions.add_parser(action)
        parser.add_argument("--kind", required=True, choices=("freeze", "authorize", "accept"))
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--manifest")
        source.add_argument("--state")
        parser.add_argument("--subject")
        parser.add_argument("--operation-id")
        parser.add_argument("--out")
        if action == "request":
            parser.add_argument("--signer-fingerprint", required=True)
            parser.add_argument("--valid-from", required=True)
            parser.add_argument("--expires-at", required=True)
        else:
            parser.add_argument("--signature", required=True)
