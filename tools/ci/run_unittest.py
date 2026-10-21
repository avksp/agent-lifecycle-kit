"""Run an unchanged unittest discovery suite and retain monotonic timing evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import traceback
import unittest
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


class TimedResult(unittest.TextTestResult):
    """Observe result callbacks; leave unittest's execution and verdict intact."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.events = []
        self._active = None
        self._started_at = None

    def startTest(self, test):
        self._active = {"id": test.id(), "seconds": None, "completed": False}
        self.cases.append(self._active)
        self._started_at = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        try:
            super().stopTest(test)
        finally:
            self._active["seconds"] = time.perf_counter() - self._started_at
            self._active["completed"] = True
            self._active = None
            self._started_at = None

    def _event(self, test, outcome):
        self.events.append({
            "id": test.id(), "outcome": outcome,
            "caseIndex": len(self.cases) - 1 if self._active is not None else None,
        })

    def addSuccess(self, test):
        super().addSuccess(test)
        self._event(test, "success")

    def addError(self, test, err):
        super().addError(test, err)
        self._event(test, "error")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._event(test, "failure")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._event(test, "skip")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._event(test, "expectedFailure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._event(test, "unexpectedSuccess")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        outcome = "success" if err is None else (
            "failure" if issubclass(err[0], test.failureException) else "error"
        )
        self._event(subtest, "subtest:" + outcome)


def inventory(suite):
    """Inspect without flattening/rebuilding the suite that will be executed."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from inventory(item)
        else:
            cls = type(item)
            yield {"id": item.id(), "module": cls.__module__, "class": cls.__qualname__}


def coverage(discovered, result):
    remaining = Counter(item["id"] for item in discovered)
    for case in result.cases:
        remaining[case["id"]] -= 1
    unexpected = [name for name, count in remaining.items() if count < 0]
    fixture_skips = {
        event["id"] for event in result.events
        if event["outcome"] == "skip" and event["caseIndex"] is None
    }
    unstarted = []
    for item in discovered:
        if remaining[item["id"]] <= 0:
            continue
        remaining[item["id"]] -= 1
        explained = (
            f"setUpClass ({item['module']}.{item['class']})" in fixture_skips
            or f"setUpModule ({item['module']})" in fixture_skips
        )
        unstarted.append({"id": item["id"], "reason": "fixtureSkip" if explained else "unaccounted"})
    complete = (
        not unexpected and all(case["completed"] for case in result.cases)
        and all(item["reason"] == "fixtureSkip" for item in unstarted)
        and result.testsRun == len(result.cases)
    )
    return {"complete": complete, "unexpectedIds": unexpected, "notStarted": unstarted}


def run(args, report):
    payload = {
        "schemaVersion": "alk-ci-test-timings.v1", "status": "RUNNING",
        "startedAtUtc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "environment": {name: os.environ.get(name) for name in (
            "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_OS",
        )},
        "discovery": {"start": args.start, "top": args.top, "pattern": args.pattern},
    }
    json.dump(payload, report)
    report.flush()
    start = time.perf_counter()
    suite_start = None
    loader = unittest.TestLoader()
    result = None
    interrupted = None
    try:
        suite = loader.discover(args.start, pattern=args.pattern, top_level_dir=args.top)
        payload["inventory"] = list(inventory(suite))
        def make_result(*positional, **keywords):
            nonlocal result
            result = TimedResult(*positional, **keywords)
            return result

        runner = unittest.TextTestRunner(
            verbosity=2, resultclass=make_result, warnings=None if sys.warnoptions else "default",
        )
        suite_start = time.perf_counter()
        runner.run(suite)
    except BaseException as exc:  # noqa: BLE001 - retain partial evidence and return failure, including interrupt
        interrupted = type(exc).__name__
        traceback.print_exc()
    finished = time.perf_counter()
    elapsed = finished - start
    payload.update(status="FAIL", wallSeconds=elapsed, interrupted=interrupted, loaderErrors=list(loader.errors))
    if result is not None:
        accounted = coverage(payload["inventory"], result)
        cases_seconds = sum(case["seconds"] or 0 for case in result.cases)
        payload.update(
            cases=result.cases, events=result.events, coverage=accounted,
            suiteSeconds=finished - suite_start,
            unassignedSeconds=elapsed - cases_seconds,
            testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
            skips=len(result.skipped), expectedFailures=len(result.expectedFailures),
            unexpectedSuccesses=len(result.unexpectedSuccesses),
        )
        if (result.wasSuccessful() and accounted["complete"] and not loader.errors
                and not interrupted and payload["inventory"] and not result.shouldStop):
            payload["status"] = "PASS"
    report.seek(0)
    json.dump(payload, report, indent=2, allow_nan=False)
    report.write("\n")
    report.truncate()
    report.flush()
    return 0 if payload["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="tests")
    parser.add_argument("--top", default=".")
    parser.add_argument("--pattern", default="test*.py")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        # A prior report must never masquerade as this invocation's result.
        with output.open("x+", encoding="utf-8") as report:
            return run(args, report)
    except (OSError, ValueError) as exc:
        print(f"Timing report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
