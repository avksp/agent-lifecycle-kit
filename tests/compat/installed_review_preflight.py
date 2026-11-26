"""Run Preview review preflight cases through a versioned console script."""

from __future__ import annotations

import argparse
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from agent_lifecycle.contracts import canonical_bytes, canonical_digest  # noqa: E402
from tests.cli.test_plan_review_admission import PlanReviewAdmissionTests, ReviewAdmissionFixture  # noqa: E402


def default_off_parity(baseline: Path, candidate: Path, owned: Path) -> dict:
    rows = []
    for name, executable in (("baseline", baseline), ("candidate", candidate)):
        root = (owned / name).resolve()
        root.mkdir()
        fixture = ReviewAdmissionFixture(root, str(executable.absolute()))
        code, lock = fixture.lock(strict=False)
        if code or lock.get("status") != "PASS":
            raise ValueError("Default-off lock intake failed")
        inventory = fixture.inventory()
        # Only the caller-created budget clock varies; it is unused by this route.
        del inventory["budget.json"]
        rows.append({"receipt": lock, "inventory": inventory})
    if rows[0] != rows[1]:
        raise ValueError("Default-off candidate receipt or inventory drifted")
    return rows[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-cli", type=Path, required=True)
    parser.add_argument("--candidate-cli", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.scratch_root.mkdir(parents=True)
    if args.baseline_cli.parent.parent.resolve() == args.candidate_cli.parent.parent.resolve():
        parser.error("Use disjoint installed CLI environments")

    class InstalledCases(PlanReviewAdmissionTests):
        executable = str(args.candidate_cli.absolute())
        scratch_root = args.scratch_root

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstalledCases)
    cases = [test.id().rsplit(".", 1)[-1] for test in suite]
    captured = io.StringIO()
    result = unittest.TextTestRunner(stream=captured, verbosity=2).run(suite)
    print(captured.getvalue(), end="")
    if not result.wasSuccessful() or result.skipped:
        return 1
    parity = default_off_parity(args.baseline_cli, args.candidate_cli, args.scratch_root)
    body = {
        "schemaVersion": "agent-installed-review-preflight-evidence.v1",
        "status": "PASS",
        "evidenceId": "EV5305",
        "cases": cases,
        "testsRun": result.testsRun,
        "defaultOffComparison": parity,
        "modelCallsStarted": False,
        "authorityClaimed": False,
    }
    with args.out.open("xb") as stream:
        stream.write(canonical_bytes({**body, "evidenceDigest": canonical_digest(body)}) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
