from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NEGATIVE_ID_RE = re.compile(r"\bNEG-R03-(\d{2})\b")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--tests-root", required=True)
    parser.add_argument("--expected-range", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    expected = _expected_ids(args.expected_range)
    catalog_ids = _ids_in_text(Path(args.catalog).read_text(encoding="utf-8"))
    test_refs = _test_refs(Path(args.tests_root))
    covered = []
    missing = []
    for neg_id in expected:
        refs = test_refs.get(neg_id, [])
        item = {"id": neg_id, "inCatalog": neg_id in catalog_ids, "testRefs": refs}
        if item["inCatalog"] and refs:
            covered.append(item)
        else:
            missing.append(item)
    status = "PASS" if not missing else "FAIL"
    evidence = {
        "schemaVersion": "agent-negative-suite-coverage.v1",
        "status": status,
        "expectedRange": args.expected_range,
        "coveredScenarios": covered,
        "missingScenarios": missing,
    }
    path = Path(args.evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def _expected_ids(value: str) -> list[str]:
    match = re.fullmatch(r"NEG-R03-(\d{2})\.\.NEG-R03-(\d{2})", value)
    if match is None:
        raise SystemExit("expected range must look like NEG-R03-01..NEG-R03-20")
    start, end = (int(item) for item in match.groups())
    if start < 1 or end < start:
        raise SystemExit("expected range is invalid")
    return [f"NEG-R03-{index:02d}" for index in range(start, end + 1)]


def _ids_in_text(text: str) -> set[str]:
    return {f"NEG-R03-{match.group(1)}" for match in NEGATIVE_ID_RE.finditer(text)}


def _test_refs(root: Path) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for path in sorted(root.rglob("test*.py")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for neg_id in _ids_in_text(text):
            refs.setdefault(neg_id, []).append(path.as_posix())
    return refs


if __name__ == "__main__":
    raise SystemExit(main())
