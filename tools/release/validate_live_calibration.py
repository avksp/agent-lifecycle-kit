from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, load_json, write_json


TARGET_METRICS = ("billableTokens", "cumulativeContextBytes", "toolCalls", "wallSeconds")
USAGE_METRICS = ("billableTokens", "inputTokens", "outputTokens", "cumulativeContextBytes", "toolCalls", "wallSeconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--budget-targets", required=True)
    parser.add_argument("--receipt")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    targets_path = Path(args.budget_targets)
    receipt_path = Path(args.receipt) if args.receipt else None
    profile = load_json(profile_path)
    targets = load_json(targets_path)
    blockers: list[dict[str, Any]] = []
    aggregates: list[dict[str, Any]] = []
    host: str | None = None

    _validate_profile(profile, targets, blockers)
    if receipt_path is None or not receipt_path.is_file():
        blockers.append({"code": "missing-live-calibration-receipt", "message": "live calibration receipt is required"})
        receipt_identity = None
    else:
        receipt = load_json(receipt_path)
        receipt_identity = file_identity(receipt_path)
        host = _validate_receipt(profile, targets, receipt, blockers)
        aggregates = _aggregate_runs(profile, targets, receipt, blockers)

    evidence = {
        "schemaVersion": "agent-live-calibration-verification.v1",
        "status": "PASS" if not blockers else "FAIL",
        "profile": file_identity(profile_path),
        "profileDigest": digest_value(profile),
        "budgetTargets": file_identity(targets_path),
        "budgetTargetsDigest": digest_value(targets),
        "receipt": receipt_identity,
        "host": host,
        "aggregates": aggregates,
        "blockers": blockers,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _validate_profile(profile: dict[str, Any], targets: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if profile.get("schemaVersion") != "agent-lifecycle-live-calibration-profile.v1":
        blockers.append({"code": "invalid-live-calibration-profile", "message": "unsupported profile schemaVersion"})
    if profile.get("syntheticAcceptedForProductionPromotion") is not False:
        blockers.append({"code": "synthetic-live-calibration-allowed", "message": "synthetic calibration must not promote production"})
    for key in ("requiredHosts", "requiredScenarios", "requiredCohorts", "usageMetrics"):
        if not _strings(profile.get(key)):
            blockers.append({"code": "invalid-live-calibration-profile", "message": f"{key} must be a non-empty string array"})
    if int(profile.get("minimumRunsPerScenarioCohort", 0)) < 1:
        blockers.append({"code": "invalid-live-calibration-profile", "message": "minimumRunsPerScenarioCohort must be positive"})
    if set(profile.get("requiredScenarios", [])) != set(targets.get("corpus", [])):
        blockers.append({"code": "live-calibration-corpus-mismatch", "message": "profile scenarios must match budget target corpus"})
    if set(profile.get("requiredCohorts", [])) != set(targets.get("cohorts", [])):
        blockers.append({"code": "live-calibration-cohort-mismatch", "message": "profile cohorts must match budget target cohorts"})


def _validate_receipt(
    profile: dict[str, Any],
    targets: dict[str, Any],
    receipt: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> str | None:
    if receipt.get("schemaVersion") != profile.get("requiredReceiptSchemaVersion"):
        blockers.append({"code": "invalid-live-calibration-receipt", "message": "unsupported receipt schemaVersion"})
    if receipt.get("status") != "PASS":
        blockers.append({"code": "live-calibration-not-pass", "message": "receipt status must be PASS"})
    host = receipt.get("host")
    if host not in profile.get("requiredHosts", []):
        blockers.append({"code": "live-calibration-host-unsupported", "message": "receipt host is not in requiredHosts"})
    if receipt.get("profileId") != profile.get("profileId"):
        blockers.append({"code": "live-calibration-profile-mismatch", "message": "receipt profileId mismatch"})
    if receipt.get("profileDigest") != digest_value(profile):
        blockers.append({"code": "live-calibration-profile-digest-mismatch", "message": "receipt profileDigest mismatch"})
    if receipt.get("budgetTargetsDigest") != digest_value(targets):
        blockers.append({"code": "live-calibration-budget-digest-mismatch", "message": "receipt budgetTargetsDigest mismatch"})
    if receipt.get("syntheticReplayUsed") is not False:
        blockers.append({"code": "synthetic-live-calibration-receipt", "message": "receipt must not use synthetic replay"})
    if int(receipt.get("liveModelInvocations", 0)) < 1:
        blockers.append({"code": "missing-live-model-invocations", "message": "receipt must include live model invocations"})
    if receipt.get("qualityRegressionCount") not in (0, None):
        blockers.append({"code": "live-calibration-quality-regression", "message": "quality regressions are not allowed"})
    return host if isinstance(host, str) else None


def _aggregate_runs(
    profile: dict[str, Any],
    targets: dict[str, Any],
    receipt: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    runs = receipt.get("runs")
    if not isinstance(runs, list):
        blockers.append({"code": "invalid-live-calibration-runs", "message": "runs must be an array"})
        return []
    if receipt.get("liveModelInvocations") != len(runs):
        blockers.append({"code": "live-invocation-count-mismatch", "message": "liveModelInvocations must equal runs length"})

    required_scenarios = list(profile.get("requiredScenarios", []))
    required_cohorts = list(profile.get("requiredCohorts", []))
    minimum = int(profile.get("minimumRunsPerScenarioCohort", 1))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {(scenario, cohort): [] for scenario in required_scenarios for cohort in required_cohorts}

    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            blockers.append({"code": "invalid-live-calibration-run", "message": f"run {index} must be an object"})
            continue
        scenario = run.get("scenarioId")
        cohort = run.get("cohort")
        if (scenario, cohort) not in grouped:
            blockers.append({"code": "live-calibration-coverage-extra", "message": f"unexpected scenario/cohort: {scenario}/{cohort}"})
            continue
        if run.get("usageAttested") is not True:
            blockers.append({"code": "live-usage-unattested", "message": f"run {index} usage is not attested"})
        if run.get("qualityStatus") != "PASS":
            blockers.append({"code": "live-calibration-quality-regression", "message": f"run {index} quality did not pass"})
        usage = run.get("usage")
        if not isinstance(usage, dict):
            blockers.append({"code": "invalid-live-calibration-usage", "message": f"run {index} usage must be an object"})
            continue
        for metric in USAGE_METRICS:
            if not _nonnegative_number(usage.get(metric)):
                blockers.append({"code": "invalid-live-calibration-usage", "message": f"run {index} usage.{metric} must be non-negative"})
        grouped[(str(scenario), str(cohort))].append(run)

    aggregates: list[dict[str, Any]] = []
    for scenario in required_scenarios:
        tier = scenario.split("-", 1)[0]
        scenario_item = {"scenarioId": scenario, "sddTier": tier, "cohorts": []}
        for cohort in required_cohorts:
            samples = grouped[(scenario, cohort)]
            if len(samples) < minimum:
                blockers.append({"code": "live-calibration-coverage-missing", "message": f"{scenario}/{cohort} has too few samples"})
            p95 = {metric: _percentile([float(run["usage"][metric]) for run in samples], 0.95) for metric in TARGET_METRICS if samples}
            _validate_budget_targets(targets, tier, scenario, cohort, p95, blockers)
            scenario_item["cohorts"].append({"name": cohort, "sampleCount": len(samples), "p95": p95})
        aggregates.append(scenario_item)
    return aggregates


def _validate_budget_targets(
    targets: dict[str, Any],
    tier: str,
    scenario: str,
    cohort: str,
    p95: dict[str, float],
    blockers: list[dict[str, Any]],
) -> None:
    target = targets.get("absoluteP95Targets", {}).get(tier, {})
    hard = targets.get("hardCeilings", {}).get(tier, {})
    for metric, value in p95.items():
        if value > float(target.get(metric, 0)):
            blockers.append({"code": "live-calibration-p95-budget-exceeded", "message": f"{scenario}/{cohort}/{metric} exceeds p95 target"})
        if value > float(hard.get(metric, 0)):
            blockers.append({"code": "live-calibration-hard-budget-exceeded", "message": f"{scenario}/{cohort}/{metric} exceeds hard ceiling"})


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile)))
    return ordered[index]


def _strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


def _nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


if __name__ == "__main__":
    raise SystemExit(main())
