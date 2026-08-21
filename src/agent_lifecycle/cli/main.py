"""Thin root CLI entrypoint for Agent Lifecycle Kit."""

from __future__ import annotations

import sys

from agent_lifecycle.cli.dispatch import dispatch
from agent_lifecycle.cli.errors import to_lifecycle_error
from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.contracts import LifecycleError, canonical_bytes


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)
    try:
        if args.command == "neutrality":
            from agent_lifecycle.neutrality.cli import main as neutrality_main

            return neutrality_main(remainder)
        payload = dispatch(args, remainder)
    except LifecycleError as exc:
        _write(exc.to_json())
        return 2
    except Exception as exc:  # noqa: BLE001 - the root boundary must redact unknown failures
        _write(to_lifecycle_error(exc).to_json())
        return 2
    if payload is None:
        return 0
    if isinstance(payload, str):
        _write_text(payload)
        return 0
    _write(payload)
    return 0


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")


def _write_text(payload: str) -> None:
    sys.stdout.write(payload.rstrip("\n") + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
