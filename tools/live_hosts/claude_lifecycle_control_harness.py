"""Bounded Claude lifecycle-control qualification harness.

The default mode is an offline copy-preview check. Live qualification is
operator-authorized, uses argv-only process execution, and accepts external
host evidence only through an explicit matrix file. Without that evidence the
harness returns ``NO_RECOMMENDATION`` and never claims enforcement.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.host_protocol.lifecycle_control_qualification import (
    build_fixture_evidence,
    build_qualification_receipt,
    validate_qualification_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "adapters/claude/lifecycle-control.template.json"
POLICY = ROOT / "policy/adapter-lifecycle-control.json"
HARNESS_SCHEMA = "agent-claude-lifecycle-control-harness-report.v1"
VERSION_PATTERN = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])")
HOST_PROBE_TIMEOUT_SECONDS = 10.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded Claude lifecycle-control qualification checks.")
    parser.add_argument("--mode", choices=["fixture-check", "live-qualification"], required=True)
    parser.add_argument("--template", default=TEMPLATE.as_posix())
    parser.add_argument("--policy", default=POLICY.as_posix())
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--expected-host-version", default="2.1.226")
    parser.add_argument("--matrix", help="Operator-produced live evidence matrix in JSON format.")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--worktree")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    if args.mode == "fixture-check":
        report = run_fixture_check(Path(args.template), Path(args.policy), Path(args.receipt))
    else:
        report = run_live_qualification(
            template_path=Path(args.template),
            policy_path=Path(args.policy),
            claude_bin=args.claude_bin,
            expected_host_version=args.expected_host_version,
            matrix_path=Path(args.matrix) if args.matrix else None,
            allow_live=args.allow_live,
            worktree=Path(args.worktree) if args.worktree else None,
            receipt_path=Path(args.receipt),
        )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


def run_fixture_check(template_path: Path, policy_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Validate the copy-preview candidate without starting a host process."""

    blockers = validate_candidate_template(template_path)
    policy, policy_blockers = _read_json_with_blocker(policy_path, "adapter lifecycle-control policy", "control-policy")
    blockers.extend(policy_blockers)
    host_version = _template_host_version(template_path)
    positive, negative = build_fixture_evidence(
        host="claude-code",
        host_version=host_version,
        operation="file-edit",
    )
    receipt = build_qualification_receipt(
        adapter_id="claude",
        host="claude-code",
        host_version=host_version,
        expected_host_version=host_version,
        operation="file-edit",
        declared_level="GUIDANCE_ONLY",
        supported_level="GUIDANCE_ONLY",
        positive_evidence=positive,
        negative_evidence=negative,
        evidence_refs=["fixture:claude-lifecycle-control"],
        live_evidence=False,
    )
    validation = validate_qualification_receipt(receipt, expected_host_version=host_version)
    blockers.extend(validation.get("blockers", []))
    if receipt.get("status") != "NO_RECOMMENDATION":
        blockers.append({"code": "candidate-fixture-overclaim"})
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    body = {
        "schemaVersion": HARNESS_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "mode": "fixture-check",
        "adapterId": "claude",
        "host": "claude-code",
        "hostVersion": host_version,
        "qualificationStatus": receipt.get("status"),
        "syntheticReplayUsed": True,
        "liveCallsStarted": False,
        "policyDigest": policy.get("policyDigest"),
        "receipt": {"path": receipt_path.as_posix(), "sha256": _sha256_file(receipt_path)},
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def run_live_qualification(
    *,
    template_path: Path,
    policy_path: Path,
    claude_bin: str,
    expected_host_version: str,
    matrix_path: Path | None,
    allow_live: bool,
    worktree: Path | None,
    receipt_path: Path,
    runner: Callable[[list[str], Path | None], tuple[int, str, str, float]] | None = None,
    clean_checker: Callable[[Path], bool] | None = None,
) -> dict[str, Any]:
    """Run an explicitly authorized version probe and validate external evidence."""

    blockers = validate_candidate_template(template_path)
    policy, policy_blockers = _read_json_with_blocker(policy_path, "adapter lifecycle-control policy", "control-policy")
    blockers.extend(policy_blockers)
    live_calls_started = False
    version_output = ""
    if not allow_live:
        blockers.append({"code": "control-qualification-live-authorization-required"})
    if worktree is None:
        blockers.append({"code": "control-qualification-clean-worktree-required"})
    elif (clean_checker is not None and not clean_checker(worktree)) or (
        clean_checker is None and not _clean_worktree(worktree)
    ):
        blockers.append({"code": "control-qualification-dirty-worktree"})

    observed_version = None
    if allow_live and not blockers:
        result = (runner or _run_command)([claude_bin, "--version"], worktree)
        live_calls_started = True
        returncode, stdout, stderr, _wall_seconds = result
        version_output = stdout + "\n" + stderr
        if returncode != 0:
            blockers.append({"code": "control-qualification-host-probe-failed", "returncode": returncode})
        match = VERSION_PATTERN.search(version_output)
        observed_version = match.group(1) if match else None
        if observed_version != expected_host_version:
            blockers.append(
                {
                    "code": "control-qualification-host-version-mismatch",
                    "expected": expected_host_version,
                    "actual": observed_version,
                }
            )

    if matrix_path is not None and not blockers:
        matrix, matrix_blockers = _read_json_with_blocker(matrix_path, "live qualification matrix", "matrix")
        blockers.extend(matrix_blockers)
        positive = matrix.get("positiveEvidence")
        negative = matrix.get("negativeEvidence")
        if not isinstance(positive, list) or not isinstance(negative, list):
            blockers.append({"code": "control-qualification-matrix-shape"})
            receipt = _build_unavailable_receipt(
                host_version=observed_version or expected_host_version,
                expected_host_version=expected_host_version,
            )
        else:
            try:
                receipt = build_qualification_receipt(
                    adapter_id="claude",
                    host="claude-code",
                    host_version=observed_version or expected_host_version,
                    expected_host_version=expected_host_version,
                    operation=str(matrix.get("operation", "file-edit")),
                    declared_level=str(matrix.get("declaredLevel", "GUIDANCE_ONLY")),
                    supported_level=str(matrix.get("supportedLevel", "ENFORCED")),
                    positive_evidence=positive,
                    negative_evidence=negative,
                    evidence_refs=[item for item in matrix.get("evidenceRefs", []) if isinstance(item, str)],
                    live_evidence=True,
                )
            except LifecycleError as exc:
                blockers.append({"code": "control-qualification-matrix-invalid", "errorCode": exc.code})
                receipt = _build_unavailable_receipt(
                    host_version=observed_version or expected_host_version,
                    expected_host_version=expected_host_version,
                )
            else:
                validation = validate_qualification_receipt(
                    receipt,
                    expected_host_version=expected_host_version,
                    require_live=True,
                )
                blockers.extend(validation.get("blockers", []))
    else:
        receipt = _build_unavailable_receipt(
            host_version=observed_version or expected_host_version,
            expected_host_version=expected_host_version,
        )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    body = {
        "schemaVersion": HARNESS_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "mode": "live-qualification",
        "adapterId": "claude",
        "host": "claude-code",
        "expectedHostVersion": expected_host_version,
        "observedHostVersion": observed_version,
        "qualificationStatus": receipt.get("status"),
        "syntheticReplayUsed": any(
            item.get("syntheticReplayUsed") is True
            for item in list(receipt.get("positiveEvidence", [])) + list(receipt.get("negativeEvidence", []))
            if isinstance(item, dict)
        ),
        "liveCallsStarted": live_calls_started,
        "hostOutputDigest": canonical_digest({"output": version_output}) if version_output else None,
        "policyDigest": policy.get("policyDigest"),
        "receipt": {"path": receipt_path.as_posix(), "sha256": _sha256_file(receipt_path)},
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def validate_candidate_template(path: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    try:
        template = read_json_object(path, label="Claude lifecycle-control candidate")
    except (LifecycleError, OSError, ValueError, TypeError) as exc:
        return [{"code": "candidate-template-read-failed", "type": type(exc).__name__}]
    if template.get("schemaVersion") != "agent-lifecycle-control-candidate.v1":
        blockers.append({"code": "candidate-template-schema"})
    if template.get("adapterId") != "claude" or template.get("host") != "claude-code":
        blockers.append({"code": "candidate-template-host"})
    if template.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "candidate-template-production-claim"})
    preview = template.get("copyPreview")
    if (
        not isinstance(preview, dict)
        or preview.get("writesOperatorSettings") is not False
        or preview.get("automatic") is not False
    ):
        blockers.append({"code": "candidate-template-copy-preview"})
    events = template.get("supportedEvents")
    if not isinstance(events, list) or set(events) != {"pre-action", "post-action", "stop"}:
        blockers.append({"code": "candidate-template-events"})
    operations = template.get("operations")
    if not isinstance(operations, dict) or set(operations) != set(
        ("file-edit", "shell-command", "task-accept", "run-finalize")
    ):
        blockers.append({"code": "candidate-template-operations"})
    else:
        for operation, entry in operations.items():
            if not isinstance(entry, dict) or entry.get("declaredLevel") not in {
                "OFF",
                "GUIDANCE_ONLY",
                "OBSERVED",
                "ENFORCED",
            }:
                blockers.append({"code": "candidate-template-operation-level", "operation": operation})
            if isinstance(entry, dict) and entry.get("qualifiedLevel") == "ENFORCED":
                blockers.append({"code": "candidate-template-enforced-overclaim", "operation": operation})
            if isinstance(entry, dict) and entry.get("qualificationStatus") != "NO_RECOMMENDATION":
                blockers.append({"code": "candidate-template-qualification-status", "operation": operation})
    return blockers


def _template_host_version(path: Path) -> str:
    try:
        template = read_json_object(path, label="Claude lifecycle-control candidate")
    except LifecycleError:
        return "unknown"
    version = template.get("hostVersion")
    return version if isinstance(version, str) and version else "unknown"


def _run_command(command: list[str], cwd: Path | None) -> tuple[int, str, str, float]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=HOST_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, _text_output(exc.stdout), _text_output(exc.stderr), round(time.monotonic() - started, 3)
    return result.returncode, result.stdout, result.stderr, round(time.monotonic() - started, 3)


def _read_json_with_blocker(path: Path, label: str, category: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return read_json_object(path, label=label), []
    except LifecycleError as exc:
        return {}, [{"code": f"control-qualification-{category}-read-failed", "errorCode": exc.code}]


def _build_unavailable_receipt(*, host_version: str, expected_host_version: str) -> dict[str, Any]:
    positive, negative = build_fixture_evidence(
        host="claude-code",
        host_version=host_version or "unknown",
        operation="file-edit",
        source="live-preflight-only",
    )
    return build_qualification_receipt(
        adapter_id="claude",
        host="claude-code",
        host_version=host_version or "unknown",
        expected_host_version=expected_host_version or "unknown",
        operation="file-edit",
        declared_level="GUIDANCE_ONLY",
        supported_level="GUIDANCE_ONLY",
        positive_evidence=positive,
        negative_evidence=negative,
        evidence_refs=["live-preflight-only"],
        live_evidence=False,
        unavailable=True,
    )


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _clean_worktree(path: Path) -> bool:
    result = subprocess.run(["git", "-C", str(path), "status", "--short"], text=True, capture_output=True, check=False)
    return result.returncode == 0 and not result.stdout.strip()


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "HARNESS_SCHEMA",
    "main",
    "run_fixture_check",
    "run_live_qualification",
    "validate_candidate_template",
]


if __name__ == "__main__":
    raise SystemExit(main())
