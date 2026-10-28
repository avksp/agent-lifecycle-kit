"""Portable fixture-only native storage incident reproduction.

No storage implementation is imported by the baseline route. Reviewer and
auditor identities in this fixture are synthetic, never release acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")


def _hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_native_fixture(
    runtime: Path,
    root: Path,
) -> tuple[Path, str, str, str, dict[str, Any]]:
    sys.path[:0] = [str(runtime / "src"), str(runtime)]
    from agent_lifecycle.audit import build_implementation_audit_report
    from agent_lifecycle.changesets import capture_task_change_set
    from agent_lifecycle.contracts import canonical_bytes, canonical_digest, write_json_create
    from agent_lifecycle.workflow import commit_task_result, start_task
    from agent_lifecycle.workflow.plan_adoption import _build_tasks
    from agent_lifecycle.workflow.state import deadline_after, now_iso
    from tests.workflow.test_task_acceptance_audit_gate import (
        _write_bundle,
        _write_result_review,
    )

    root.mkdir()
    source = root / "src/example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "plans/\nwork/\nrun.state.json\nrun.state.json.storage/\nrun.state.json.v4-backup-*.json\nevents.jsonl\n",
        encoding="utf-8",
    )
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "fixture@example.invalid"],
        ["git", "config", "user.name", "Storage fixture only"],
        ["git", "add", ".gitignore", "src/example.py"],
        ["git", "commit", "-qm", "fixture baseline"],
    ):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    bundle = _write_bundle(
        root,
        phase="RUNNING",
        task_status="READY",
        audit_required=True,
    )
    state_path = Path(bundle["statePath"])
    state = json.loads(state_path.read_bytes())
    manifest_path = Path(bundle["manifestPath"])
    manifest = json.loads(manifest_path.read_bytes())
    fixture_task = state["tasks"][0]
    manifest["workstreams"][0]["artifactPaths"] = fixture_task["artifactPaths"]
    digest = canonical_digest(manifest)
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    lock_path = manifest_path.with_name("plan.lock.json")
    lock = json.loads(lock_path.read_bytes())
    lock["manifestHash"] = digest
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")
    bundle["planDigest"] = digest
    state["planDigest"] = digest
    state["tasks"] = _build_tasks(manifest, {fixture_task["id"]: fixture_task["packet"]})
    state.update(
        schemaVersion="agent-workflow-state.v4",
        sourceRevision=revision,
        packageRoot=".",
        operationLedger={},
        blocker=None,
        runStartedAt=now_iso(),
        budgets={"maxTaskAttempts": 2, "remediationMode": "ask"},
    )
    state["runDeadlineAt"] = deadline_after(state["runStartedAt"], 86_400)
    state_path.write_bytes(canonical_bytes(state) + b"\n")
    start_task(
        state_path,
        task_id="WS-01",
        operation_id="fixture-start",
        expected_revision=1,
        source_revision=revision,
        reason="fixture only",
    )
    source.write_text("value = 2\n", encoding="utf-8")
    result_path, review_path = _write_result_review(root, bundle)
    result_file = root / result_path
    result = json.loads(result_file.read_bytes())
    evidence = capture_task_change_set(
        root,
        baseline=revision,
        write_paths=["src/example.py"],
    )
    result["sourceRevision"] = revision
    result["changeSet"] = {
        "schemaVersion": "agent-task-change-set-claim.v1",
        **{
            key: evidence[key]
            for key in (
                "provider",
                "baselineSha",
                "fileSetHash",
                "diffHash",
                "snapshotHash",
            )
        },
    }
    result_file.write_bytes(canonical_bytes(result) + b"\n")
    review_file = root / review_path
    review = json.loads(review_file.read_bytes())
    review["resultHash"] = canonical_digest(result)
    review["summary"] = "Synthetic fixture-only review"
    review_file.write_bytes(canonical_bytes(review) + b"\n")
    commit_task_result(
        state_path,
        task_id="WS-01",
        operation_id="fixture-result",
        expected_revision=2,
        source_revision=revision,
        result_path=result_path,
        reason="fixture-only result",
    )
    state = json.loads(state_path.read_bytes())
    state["priorSnapshots"] = [
        {
            "runId": "run",
            "packageId": "package",
            "planRevision": 0,
            "planDigest": "0" * 64,
            "sourceRevision": revision,
            "tasks": [],
            "financialRole": (
                "HISTORICAL_ALREADY_INCLUDED_"  # Historical accounting role.
                "IN_CUMULATIVE_ACCOUNTING"
            ),
            "fixtureOnlyPadding": "",
        }
    ]
    needed = 1_048_000 - len(canonical_bytes(state)) - 1
    state["priorSnapshots"][0]["fixtureOnlyPadding"] = "h" * needed
    state_path.write_bytes(canonical_bytes(state) + b"\n")
    audit = build_implementation_audit_report(
        manifest_path=Path(bundle["manifestPath"]),
        state_path=state_path,
        task_id="WS-01",
        result_path=result_path,
        review_path=review_path,
        auditor_id="fixture-only-auditor",
    )
    if audit["status"] != "PASS" or audit["verdict"] != "ACCEPTED":
        raise AssertionError(audit)
    audit_path = "work/WS-01/attempt-1/implementation-audit.json"
    write_json_create(root / audit_path, audit)
    return state_path, review_path, audit_path, revision, audit


def _exercise(runtime: Path, root: Path, timeout: int) -> dict[str, Any]:
    state_path, review_path, audit_path, revision, audit = build_native_fixture(
        runtime,
        root,
    )
    before = {
        name: _hash(root / name)
        for name in (
            "run.state.json",
            "events.jsonl",
        )
    }
    argv = [
        sys.executable,
        "-B",
        "-m",
        "agent_lifecycle",
        "workflow",
        "task-accept",
        "--state",
        str(state_path),
        "--task",
        "WS-01",
        "--operation-id",
        "fixture-accept",
        "--expected-revision",
        "3",
        "--source-revision",
        revision,
        "--review",
        review_path,
        "--implementation-audit",
        audit_path,
        "--reason",
        "fixture only",
    ]
    env = dict(os.environ, PYTHONPATH=str(runtime / "src"))
    started = _stamp()
    child = subprocess.run(
        argv,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    after = {name: _hash(root / name) for name in before}
    outcome = {
        "fixtureOnly": True,
        "argv": argv,
        "startedAt": started,
        "endedAt": _stamp(),
        "exitCode": child.returncode,
        "stdout": child.stdout,
        "stderr": child.stderr,
        "before": before,
        "after": after,
        "auditStatus": audit["status"],
        "auditBytes": (root / audit_path).stat().st_size,
        "stateBytes": state_path.stat().st_size,
        "expected": "json-input-too-large",
        "reproduced": child.returncode != 0
        and "json-input-too-large" in child.stdout + child.stderr
        and before == after,
    }
    _save(root.parent / "native-red.json", outcome)
    return outcome


def candidate_accept_assertions(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    old_artifact_hashes: dict[str, str],
    new_artifact_hashes: dict[str, str],
) -> None:
    """Future V03 assertions, intentionally excluded from baseline selection.

    The native integration owner supplies actual migration/accept/adopt outputs;
    this helper neither fabricates them nor treats fixture identities as release
    review. Historical bodies must be obtained through the shared accessor.
    """
    assert before["schemaVersion"] == "agent-workflow-state.v4"
    assert after["schemaVersion"] == "agent-workflow-state.v5"
    assert old_artifact_hashes == new_artifact_hashes
    assert len(json.dumps(after).encode("utf-8")) <= 1_048_576
    for field in (
        "runStartedAt",
        "runDeadlineAt",
        "authorization",
        "usageTotals",
        "financialTotals",
        "unknownHolds",
    ):
        assert before.get(field) == after.get(field), field
    tasks = after["tasks"]
    accepted = {task["id"] for task in tasks if task["status"] == "ACCEPTED"}
    assert "WS-01" in accepted


def baseline(ref: str, out: Path, timeout: int) -> int:
    repository = Path(__file__).resolve().parents[2]
    out = out.absolute()
    out.mkdir(parents=True, exist_ok=False)
    product_paths = [
        "src/agent_lifecycle/contracts/workflow_storage_schemas.py",
        "src/agent_lifecycle/workflow/storage.py",
        "src/agent_lifecycle/workflow/storage_io.py",
    ]
    before = {name: _hash(repository / name) for name in product_paths}
    runtime = out / "runtime"
    runtime.mkdir()
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", ref],
        cwd=repository,
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(runtime, filter="data")
    revision = subprocess.check_output(
        ["git", "rev-parse", f"{ref}^{{commit}}"],
        cwd=repository,
        text=True,
    ).strip()
    argv = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "exercise",
        "--runtime",
        str(runtime),
        "--out-dir",
        str(out / "fixture"),
        "--timeout-seconds",
        str(timeout),
    ]
    started = _stamp()
    child = subprocess.run(
        argv,
        cwd=runtime,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    _save(
        out / "baseline.json",
        {
            "sourceRef": ref,
            "sourceRevision": revision,
            "sourceArchiveSha256": hashlib.sha256(archive).hexdigest(),
            "productFilesBefore": before,
            "argv": argv,
            "startedAt": started,
            "endedAt": _stamp(),
            "exitCode": child.returncode,
            "stdout": child.stdout,
            "stderr": child.stderr,
            "fixtureOnly": True,
            "actualProviderTokens": None,
            "actualUsd": None,
            "telemetryStatus": "UNAVAILABLE",
        },
    )
    return child.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "exercise"))
    parser.add_argument("--source-ref", default="v2.29.0")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    if args.mode == "baseline":
        return baseline(args.source_ref, args.out_dir, args.timeout_seconds)
    if args.runtime is None:
        parser.error("exercise requires --runtime")
    outcome = _exercise(args.runtime, args.out_dir, args.timeout_seconds)
    print(json.dumps({"reproduced": outcome["reproduced"]}))
    return 0 if outcome["reproduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
