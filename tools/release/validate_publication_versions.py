from __future__ import annotations

import argparse
from pathlib import Path

from publication_contract import validate_publication_tree
from release_common import write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    evidence = validate_publication_tree(
        root=Path(args.root),
        target_version=args.target_version,
        target_ref=args.target_ref,
    )
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
