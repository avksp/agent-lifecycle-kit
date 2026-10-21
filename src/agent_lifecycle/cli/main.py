"""Thin root CLI entrypoint for Agent Lifecycle Kit."""

from __future__ import annotations

import sys

from agent_lifecycle.cli.dispatch import dispatch, require_known_arguments
from agent_lifecycle.cli.errors import to_lifecycle_error
from agent_lifecycle.cli.parsers import build_parser
from agent_lifecycle.contracts import LifecycleError, canonical_bytes


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0].startswith("--measure"):
        return _measured_main(raw_argv)
    return _main(raw_argv)


def _measured_main(argv: list[str]) -> int:
    import argparse
    from pathlib import Path

    from agent_lifecycle.metrics.command_resources import run_measured_command

    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--measure-request", action="append", required=True)
    parser.add_argument("--measure-out", action="append", required=True)
    args, remaining = parser.parse_known_args(argv)
    if len(args.measure_request) != 1 or len(args.measure_out) != 1:
        parser.error("measurement flags must appear exactly once")
    try:
        return run_measured_command(
            Path(args.measure_request[0]),
            Path(args.measure_out[0]),
            remaining,
            lambda: _main(remaining),
        )
    except LifecycleError as exc:
        if exc.code == "command-measurement-publication-failed":
            sys.stderr.write(canonical_bytes(exc.to_json()).decode("utf-8") + "\n")
        else:
            _write(exc.to_json())
        return 2
    except Exception as exc:  # noqa: BLE001 - redact the measurement boundary
        _write(to_lifecycle_error(exc).to_json())
        return 2


def _main(raw_argv: list[str]) -> int:
    parser = build_parser(raw_argv)
    args, remainder = parser.parse_known_args(raw_argv)
    try:
        if args.command == "neutrality":
            from agent_lifecycle.neutrality.cli import main as neutrality_main

            return neutrality_main(remainder)
        require_known_arguments(args, remainder)
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
