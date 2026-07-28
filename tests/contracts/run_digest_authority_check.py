from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "release"))

from agent_lifecycle.contracts import canonical_bytes, canonical_digest  # noqa: E402
import release_common  # noqa: E402


CASES: list[dict[str, Any]] = [
    {"name": "key-order", "value": {"b": 2, "a": 1}},
    {"name": "unicode", "value": {"text": "provider-neutral"}},
    {"name": "nested", "value": {"items": [{"id": "B"}, {"id": "A"}], "enabled": True}},
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)

    checks = [_parity_check(case["name"], case["value"]) for case in CASES]
    checks.append(_negative_divergent_case())
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    evidence = {
        "schemaVersion": "agent-digest-authority-evidence.v1",
        "status": status,
        "canonicalAuthority": "agent_lifecycle.contracts",
        "releaseHelper": "tools/release/release_common.py",
        "checks": checks,
        "productionPromotionClaimed": False,
    }
    path = Path(args.evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _parity_check(name: str, value: Any) -> dict[str, Any]:
    expected_bytes = canonical_bytes(value)
    actual_bytes = release_common.canonical_bytes(value)
    expected_digest = canonical_digest(value)
    actual_digest = release_common.digest_value(value)
    return {
        "id": name,
        "status": "PASS" if expected_bytes == actual_bytes and expected_digest == actual_digest else "FAIL",
        "coreDigest": expected_digest,
        "releaseDigest": actual_digest,
    }


def _negative_divergent_case() -> dict[str, Any]:
    value = {"b": 2, "a": 1}
    divergent = json.dumps(value, ensure_ascii=True, sort_keys=False, separators=(", ", ": ")).encode("utf-8")
    return {
        "id": "divergent-canonicalizer-rejected",
        "status": "PASS" if divergent != canonical_bytes(value) else "FAIL",
        "coreDigest": canonical_digest(value),
    }


if __name__ == "__main__":
    raise SystemExit(main())
