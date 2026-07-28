"""Thin root CLI entrypoint for Agent Lifecycle Kit."""

from __future__ import annotations

import sys

from agent_lifecycle.cli.dispatch import dispatch
from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.neutrality.cli import main as neutrality_main


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)
    if args.command == "neutrality":
        return neutrality_main(remainder)
    try:
        payload = dispatch(args, remainder)
    except LifecycleError as exc:
        _write(exc.to_json())
        return 2
    if payload is None:
        return 0
    _write(payload)
    return 0


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
