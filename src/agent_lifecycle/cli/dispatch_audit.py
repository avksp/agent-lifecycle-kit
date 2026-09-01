"""Narrow CLI dispatcher for read-only audit commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.audit import (
    build_final_implementation_audit,
    build_implementation_audit_report,
    build_ownership_report,
    build_package_audit,
    build_rework_delta_audit,
    require_package_audit_pass,
    require_review_verdict_pass,
    validate_review_verdict,
)
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create


def dispatch_audit(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch one audit command without owning workflow transitions."""

    if args.audit_command == "review-check":
        review = read_json_object(Path(args.review), label="task review")
        verdict = review.get("reviewVerdict", review)
        findings = review.get("findings", []) if isinstance(review.get("findings", []), list) else []
        return require_review_verdict_pass(validate_review_verdict(verdict, findings=findings))
    if args.audit_command == "implementation":
        payload = build_implementation_audit_report(
            manifest_path=Path(args.manifest),
            state_path=Path(args.state),
            task_id=args.task,
            result_path=args.result,
            review_path=args.review,
            evidence_paths=args.evidence,
            sandbox_receipt_paths=args.sandbox_receipt,
            review_mesh_quorum_paths=args.review_mesh_quorum,
            changed_paths=args.path or None,
            expected_revision=args.expected_revision,
            base=args.base,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        return _write_optional(args.out, payload)
    if args.audit_command == "delta":
        payload = build_rework_delta_audit(
            manifest_path=Path(args.manifest),
            lock_path=Path(args.lock),
            state_path=Path(args.state),
            task_id=args.task,
            dependency_report_path=Path(args.dependency_report),
            validation_selection_path=Path(args.validation_selection),
            finding_check_binding_paths=[Path(path) for path in args.finding_check_binding],
            finding_check_evidence_paths=[Path(path) for path in args.finding_check_evidence],
        )
        return _write_optional(args.out, payload)
    if args.audit_command == "final-implementation":
        payload = build_final_implementation_audit(
            manifest_path=Path(args.manifest),
            state_path=Path(args.state),
            report_paths=args.report,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        return _write_optional(args.out, payload)
    if args.audit_command == "package":
        payload = build_package_audit(
            plan_dir=Path(args.plan_dir),
            state_path=Path(args.state) if args.state else None,
            report_paths=args.report,
            changed_paths=args.path or None,
            base=args.base,
            require_frozen=args.require_frozen,
            require_implementation=args.require_implementation,
            completeness_profile_path=Path(args.completeness_profile) if args.completeness_profile else None,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        _write_optional(args.out, payload)
        if args.strict:
            require_package_audit_pass(payload)
        return payload
    if args.audit_command == "ownership":
        return _dispatch_ownership(args)
    raise LifecycleError("command-not-implemented", "audit command is not implemented")


def _dispatch_ownership(args: argparse.Namespace) -> dict[str, Any]:
    paths = args.path or changed_files(Path.cwd(), base=args.base)
    report = build_ownership_report(Path(args.manifest), paths, base=args.base)
    if args.fail_on_forbidden and report_has_category(report, {"forbidden"}):
        raise LifecycleError(
            "forbidden-write-detected", "ownership report contains forbidden writes", report["summary"]
        )
    if args.fail_on_unowned and report_has_category(report, {"unowned"}):
        raise LifecycleError("unowned-write-detected", "ownership report contains unowned writes", report["summary"])
    return report


def _write_optional(out: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if out:
        write_json_create(Path(out), payload)
    return payload


__all__ = ["dispatch_audit"]
