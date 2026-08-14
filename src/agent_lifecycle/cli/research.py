"""Argument parsing for the bounded research evidence commands."""

from __future__ import annotations

import argparse


def add_research_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    research = subparsers.add_parser("research", help="validate operator-supplied research evidence")
    research_sub = research.add_subparsers(dest="research_command", required=True)

    validate = research_sub.add_parser("validate", help="validate a local evidence package")
    validate.add_argument("--package", required=True)
    validate.add_argument(
        "--snapshot",
        action="append",
        default=[],
        metavar="SOURCE_ID=PATH",
        help="supply one UTF-8 source snapshot for quote verification",
    )
    validate.add_argument("--max-bytes", type=int, default=33_554_432)
    validate.add_argument("--out")

    summary = research_sub.add_parser("summary", help="summarize a local evidence package")
    summary.add_argument("--package", required=True)
    summary.add_argument("--validation")
    summary.add_argument(
        "--snapshot",
        action="append",
        default=[],
        metavar="SOURCE_ID=PATH",
        help="supply one UTF-8 source snapshot before summary validation",
    )
    summary.add_argument("--max-bytes", type=int, default=33_554_432)
    summary.add_argument("--out")
