"""Build the portable Agent Plugins package from the canonical ALK skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_plugin_package import build_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable Agent Plugins package.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True, help="fresh package directory")
    parser.add_argument("--archive", help="optional release archive path")
    args = parser.parse_args()

    result = build_package(
        root=Path(args.root).resolve(),
        version=args.version,
        output=Path(args.out),
        archive=Path(args.archive) if args.archive else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
