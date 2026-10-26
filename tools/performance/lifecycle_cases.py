"""Isolated local fixtures for real read-only lifecycle benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import agent_lifecycle
from agent_lifecycle.accounting.contracts import (
    BudgetPolicy,
    BudgetScope,
    EvidenceRef,
    OpeningBalance,
    Operation,
)
from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    read_json_object,
)
from agent_lifecycle.contracts.canonical import write_json_replace_private
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from agent_lifecycle.workflow.query import status

CASE_SCHEMA = "agent-lifecycle-performance-case.v1"
CASE_SIZES = {
    "workflow-status-small": 1,
    "workflow-status-growing": 100,
    "accounting-read-small": 1,
    "accounting-read-growing": 100,
}


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _workflow_fixture(root: Path, size: int) -> tuple[Callable[[], Any], dict[str, Any]]:
    path = root / "run.state.json"
    initialize_workflow_state(path, run_id="benchmark-run", package_id="benchmark-package")
    # This is an owned temporary fixture, never the caller's workflow state.
    state = read_json_object(path, label="benchmark state")
    state["tasks"] = [
        {
            "id": f"TASK-{index:03d}",
            "status": "PENDING",
            "attempt": 0,
            "required": True,
            "dependsOn": [],
        }
        for index in range(size)
    ]
    write_json_replace_private(path, state)
    validated = status(path)
    if (
        len(validated["tasks"]) != size
        or validated["phase"] != "AWAITING_AUTHORIZATION"
        or validated["nextAction"]["type"] != "request-execution-authorization"
    ):
        raise ValueError("Workflow fixture did not retain read-only authority")
    return lambda: status(path), {
        "tasks": size,
        "stateBytes": path.stat().st_size,
        "phase": "AWAITING_AUTHORIZATION",
        "setupValidationCalls": 1,
    }


def _accounting_fixture(root: Path, size: int, stack: ExitStack) -> tuple[Callable[[], Any], dict[str, Any]]:
    proof = EvidenceRef("benchmark:local-fixture-only", "a" * 64)
    unit = "benchmark:reported-tokens:v1"
    scope = BudgetScope("benchmark-scope", "benchmark-run", unit)
    cap = size + 1
    journal = stack.enter_context(Journal(root / "journal.sqlite", proof))
    opened = journal.open_scope(
        scope,
        BudgetPolicy("benchmark-policy", 1, cap, {"task": cap}, {}, proof),
        OpeningBalance(
            "benchmark-opening",
            "benchmark-source",
            unit,
            {"task": 0},
            0,
            (),
            proof,
            proof,
        ),
    )
    if opened != "OPENED":
        raise ValueError("Benchmark scope was not created")
    for index in range(size):
        operation = Operation(
            budget_scope_id=scope.budget_scope_id,
            operation_id=f"operation-{index}",
            dispatch_key=f"dispatch-{index}",
            run_id=scope.run_id,
            task_id="task",
            role="worker",
            attempt_id="benchmark-attempt",
            retry_ordinal=0,
            attribution_reason="local benchmark fixture, no host dispatch",
            policy_id="benchmark-policy",
            policy_revision=1,
            route_id="benchmark-fixture-only",
            source_id="benchmark-source",
            unit_definition_id=unit,
            upper_bound_tokens=1,
            permit_id=f"permit-{index}",
            input_digest="b" * 64,
            route_qualification=proof,
            issuer=proof,
            validity=proof,
        )
        if journal.reserve(operation) != "RESERVED":
            raise ValueError("Benchmark reservation was refused")
    expected = journal.events(scope.budget_scope_id)
    if len(expected) != size + 1:
        raise ValueError("Benchmark event count is unexpected")
    expected_digest = canonical_digest(expected)

    def read_events() -> list[dict[str, Any]]:
        # Digest and expected-count validation are part of the timed read.
        events = journal.events(scope.budget_scope_id)
        if len(events) != size + 1 or canonical_digest(events) != expected_digest:
            raise ValueError("Benchmark event history changed")
        return events

    return read_events, {
        "reservations": size,
        "events": size + 1,
        "setupValidationCalls": 1,
        "storage": "persistent-local-sqlite",
    }


def run_case(operation: str, *, source_root: Path) -> dict[str, Any]:
    """Prepare one private fixture, time one real read and verify invariance."""
    if operation not in CASE_SIZES:
        raise ValueError("Unknown lifecycle benchmark operation")
    package_file = Path(agent_lifecycle.__file__).resolve()
    if not package_file.is_relative_to((source_root / "src").resolve()):
        raise ValueError("Benchmark package does not match explicit source root")
    started = time.monotonic()
    size = CASE_SIZES[operation]
    with tempfile.TemporaryDirectory(prefix="alk-lifecycle-case-") as temporary:
        root = Path(temporary)
        with ExitStack() as stack:
            if operation.startswith("workflow-"):
                read, counts = _workflow_fixture(root, size)
            else:
                read, counts = _accounting_fixture(root, size, stack)
            before = _inventory(root)
            setup_seconds = time.monotonic() - started
            operation_started = time.monotonic()
            result = read()
            operation_seconds = time.monotonic() - operation_started
            validation_started = time.monotonic()
            after = _inventory(root)
            if before != after:
                raise ValueError("Read-only benchmark modified fixture artifacts")
            result_digest = canonical_digest(result)
            validation_seconds = time.monotonic() - validation_started
        # ExitStack closes the owned Journal before temporary files are removed.
    return {
        "schemaVersion": CASE_SCHEMA,
        "status": "PASS",
        "operation": operation,
        "setupWallSeconds": setup_seconds,
        "operationWallSeconds": operation_seconds,
        "validationWallSeconds": validation_seconds,
        "workerWallSeconds": time.monotonic() - started,
        "workload": {"operation": operation, "size": size, **counts},
        "fixtureArtifactsUnchanged": True,
        "fixtureInventoryDigest": canonical_digest(before),
        "resultDigest": result_digest,
        "syscallCount": None,
        "ioBytes": None,
        "providerTokens": None,
        "productionPromotionClaimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--operation", choices=sorted(CASE_SIZES), required=True)
    args = parser.parse_args()
    try:
        result = run_case(args.operation, source_root=args.source_root.resolve())
    except (LifecycleError, OSError, ValueError) as error:
        result = {"status": "FAIL", "blocker": type(error).__name__}
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
