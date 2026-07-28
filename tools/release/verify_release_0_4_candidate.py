from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import file_identity, iter_payload_files, load_json, write_json

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.model_routing import validate_host_model_profile


EVIDENCE_SCHEMA = "agent-release-0-4-validation.v1"
REQUIRED_SCHEMAS = {
    "agent-host-model-selection-profile.v1",
    "agent-host-model-selection-receipt.v1",
    "agent-lifecycle-budget-exceeded-policy.v1",
    "agent-lifecycle-budget-decision-receipt.v1",
}
DEFAULT_HOSTS = ("codex", "opencode", "claude-code", "hermes")
REQUIRED_PASS_EVIDENCE = {
    "plan-check.json": "agent-plan-check.v1",
    "profile-contracts.json": "agent-lifecycle-unittest-report.v1",
    "cursor-compat.json": "agent-cursor-compat-evidence.v1",
    "workflow-budget.json": "agent-lifecycle-unittest-report.v1",
    "cli-ux.json": "agent-lifecycle-unittest-report.v1",
    "harness-model-selection.json": "agent-lifecycle-unittest-report.v1",
    "negative-suite-coverage.json": "agent-negative-suite-coverage.v1",
    "context-fit.json": "agent-task-packet-context-fit.v1",
    "neutrality-report.json": "agent-neutrality-report.v1",
}
ALLOWED_MODEL_LITERAL_PATHS = {
    "policy/neutrality.policy.json",
    "tests/model_routing/fixtures/release-0-4/cursor-glm-compat.json",
    "tests/model_routing/run_cursor_compat_check.py",
    "tests/model_routing/test_cursor_compat_check.py",
}
DENIED_PORTABLE_LITERALS = (
    "glm-5" ".2-max",
    "glm-5" ".2-high",
    "/Us" "ers/",
    "agent-lifecycle-kit-" "live-",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--final-proof")
    parser.add_argument("--required-hosts", default=",".join(DEFAULT_HOSTS))
    args = parser.parse_args()

    root = Path.cwd()
    manifest_path = Path(args.manifest)
    evidence_dir = Path(args.evidence_dir)
    final_proof_path = Path(args.final_proof) if args.final_proof else manifest_path.parent / "final/final-proof.json"
    required_hosts = [item.strip() for item in args.required_hosts.split(",") if item.strip()]

    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    manifest = load_json(manifest_path)
    manifest_digest = canonical_digest(manifest)
    _check_schema_registry(checks, blockers)
    _check_host_profiles(root, required_hosts, checks, blockers)
    _check_portable_model_leakage(root, checks, blockers)
    _check_budget_decision_contract(root, checks, blockers)
    _check_required_evidence(evidence_dir, checks, blockers)
    _check_final_proof(final_proof_path, manifest, manifest_digest, checks, blockers)

    payload = {
        "schemaVersion": EVIDENCE_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "manifest": file_identity(manifest_path),
        "manifestDigest": manifest_digest,
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), payload)
    return 0 if not blockers else 1


def _check_schema_registry(checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    missing: list[str] = []
    for schema_id in sorted(REQUIRED_SCHEMAS):
        try:
            get_schema(schema_id)
        except LifecycleError:
            missing.append(schema_id)
    _record(
        checks,
        blockers,
        "schema-registry",
        not missing,
        "release-0-4-schema-missing",
        "release 0.4 schemas must be registered in the schema authority",
        {"missing": missing},
    )


def _check_host_profiles(root: Path, hosts: list[str], checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    non_placeholder: list[str] = []
    for host in hosts:
        path = root / "profiles" / "hosts" / f"{host}-live-profile.v1.json"
        if not path.is_file():
            missing.append(path.as_posix())
            continue
        try:
            payload = load_json(path)
            validation = validate_host_model_profile(payload)
        except (LifecycleError, SystemExit) as exc:
            invalid.append({"path": path.as_posix(), "error": str(exc)})
            continue
        if validation.get("profileSchemaVersion") != "agent-host-model-selection-profile.v1":
            invalid.append({"path": path.as_posix(), "error": "profile must use agent-host-model-selection-profile.v1"})
        for model_name in _provider_models(payload):
            if not (model_name.startswith("<") and model_name.endswith(">")):
                non_placeholder.append(path.as_posix())
                break
    _record(
        checks,
        blockers,
        "host-profile-coverage",
        not missing and not invalid and not non_placeholder,
        "release-0-4-host-profile-invalid",
        "all required host profiles must exist, validate, and use placeholder providerModel values",
        {"missing": missing, "invalid": invalid, "nonPlaceholder": sorted(set(non_placeholder))},
    )


def _check_portable_model_leakage(root: Path, checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    offenders: list[dict[str, str]] = []
    for rel in iter_payload_files(root):
        rel_text = rel.as_posix()
        if rel_text in ALLOWED_MODEL_LITERAL_PATHS:
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for literal in DENIED_PORTABLE_LITERALS:
            if literal in text:
                offenders.append({"path": rel_text, "literal": literal})
    _record(
        checks,
        blockers,
        "portable-model-leakage",
        not offenders,
        "release-0-4-portable-model-leak",
        "portable payload files must not include local paths or concrete Cursor GLM model names",
        {"offenders": offenders},
    )


def _check_budget_decision_contract(root: Path, checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    required = {
        root / "src/agent_lifecycle/workflow": [
            "agent-lifecycle-budget-decision-receipt.v1",
            "WAITING_FOR_BUDGET_DECISION",
            "BUDGET_DECISION_REQUIRED",
        ],
        root / "src/agent_lifecycle/cli": [
            "budget-decision",
            "budget-policy-check",
        ],
        root / "tests/workflow": [
            "NEG-R04-04",
            "NEG-R04-05",
            "NEG-R04-06",
            "NEG-R04-07",
            "NEG-R04-08",
            "NEG-R04-09",
            "NEG-R04-10",
        ],
    }
    missing: list[dict[str, str]] = []
    for path, values in required.items():
        text = _read_text_tree(path)
        for value in values:
            if value not in text:
                missing.append({"path": path.relative_to(root).as_posix(), "value": value})
    _record(
        checks,
        blockers,
        "budget-decision-coverage",
        not missing,
        "release-0-4-budget-decision-coverage-missing",
        "budget decision workflow, CLI, and negative-test coverage must be present",
        {"missing": missing},
    )


def _read_text_tree(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    if path.is_dir():
        parts: list[str] = []
        for child in sorted(path.rglob("*.py")):
            parts.append(child.read_text(encoding="utf-8"))
        return "\n".join(parts)
    return ""


def _check_required_evidence(evidence_dir: Path, checks: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> None:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    for name, schema in REQUIRED_PASS_EVIDENCE.items():
        path = evidence_dir / name
        if not path.is_file():
            missing.append(path.as_posix())
            continue
        try:
            payload = load_json(path)
        except SystemExit as exc:
            invalid.append({"path": path.as_posix(), "error": str(exc)})
            continue
        if payload.get("schemaVersion") != schema:
            invalid.append({"path": path.as_posix(), "error": f"expected {schema}"})
            continue
        if not _evidence_passed(payload):
            invalid.append({"path": path.as_posix(), "error": "evidence status is not PASS"})
    _record(
        checks,
        blockers,
        "required-release-evidence",
        not missing and not invalid,
        "release-0-4-evidence-missing-or-failed",
        "release candidate evidence must exist and pass",
        {"missing": missing, "invalid": invalid},
    )


def _check_final_proof(
    final_proof_path: Path,
    manifest: dict[str, Any],
    manifest_digest: str,
    checks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    details: dict[str, Any] = {"path": final_proof_path.as_posix()}
    if not final_proof_path.is_file():
        _record(
            checks,
            blockers,
            "formal-lifecycle-final-proof",
            False,
            "release-0-4-final-proof-missing",
            "release 0.4 candidate validation requires a formal lifecycle final proof",
            details,
        )
        return
    try:
        proof = load_json(final_proof_path)
    except SystemExit as exc:
        _record(
            checks,
            blockers,
            "formal-lifecycle-final-proof",
            False,
            "release-0-4-final-proof-invalid",
            "release 0.4 final proof must be a JSON object",
            {**details, "error": str(exc)},
        )
        return

    required_tasks = {
        item.get("id")
        for item in manifest.get("workstreams", [])
        if isinstance(item, dict) and item.get("required", True)
    }
    accepted_tasks = {
        item.get("id")
        for item in proof.get("acceptedTasks", [])
        if isinstance(item, dict)
    }
    invalid_reasons: list[str] = []
    if proof.get("schemaVersion") != "agent-run-final-proof.v1":
        invalid_reasons.append("schemaVersion")
    if proof.get("semanticStatus") != "READY_FOR_FINALIZATION":
        invalid_reasons.append("semanticStatus")
    if proof.get("productionPromotionClaimed") is not False:
        invalid_reasons.append("productionPromotionClaimed")
    package = manifest.get("package")
    if isinstance(package, dict) and proof.get("packageId") != package.get("id"):
        invalid_reasons.append("packageId")
    if proof.get("planRevision") != manifest.get("planRevision"):
        invalid_reasons.append("planRevision")
    if proof.get("planDigest") != manifest_digest:
        invalid_reasons.append("planDigest")
    missing_tasks = sorted(task for task in required_tasks - accepted_tasks if isinstance(task, str))
    if missing_tasks:
        invalid_reasons.append("acceptedTasks")
    details.update({"missingTasks": missing_tasks, "invalidReasons": invalid_reasons})
    _record(
        checks,
        blockers,
        "formal-lifecycle-final-proof",
        not invalid_reasons,
        "release-0-4-final-proof-invalid",
        "release 0.4 final proof must match the frozen manifest and accepted workstreams",
        details,
    )


def _evidence_passed(payload: dict[str, Any]) -> bool:
    if payload.get("status") == "PASS":
        return True
    if payload.get("schemaVersion") == "agent-plan-check.v1":
        manifest = payload.get("manifest")
        lock = payload.get("lock")
        return (
            isinstance(manifest, dict)
            and manifest.get("schemaVersion") == "agent-plan-validation.v1"
            and manifest.get("status") == "FROZEN"
            and isinstance(lock, dict)
            and lock.get("schemaVersion") == "agent-plan-lock-verification.v1"
        )
    if payload.get("schemaVersion") == "agent-lifecycle-unittest-report.v1":
        suite = payload.get("suite")
        return (
            payload.get("verdict") == "PASS"
            and isinstance(suite, dict)
            and isinstance(suite.get("testsRun"), int)
            and suite["testsRun"] > 0
            and suite.get("failures") == 0
            and suite.get("errors") == 0
        )
    counters = payload.get("counters")
    if isinstance(counters, dict):
        return all(isinstance(value, int) and value == 0 for value in counters.values())
    return False


def _provider_models(payload: dict[str, Any]) -> list[str]:
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        return []
    values: list[str] = []
    for binding in bindings.values():
        if not isinstance(binding, dict):
            continue
        model = binding.get("providerModel")
        if isinstance(model, str):
            values.append(model)
    return values


def _record(
    checks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    name: str,
    passed: bool,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    check: dict[str, Any] = {"name": name, "status": "PASS" if passed else "FAIL"}
    if details is not None:
        check["details"] = details
    checks.append(check)
    if not passed:
        blocker: dict[str, Any] = {"code": code, "message": message}
        if details is not None:
            blocker["details"] = details
        blockers.append(blocker)


if __name__ == "__main__":
    raise SystemExit(main())
