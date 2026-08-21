#!/usr/bin/env python3
"""Validate bounded Python quality evidence against the reviewed policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from release_common import digest_value, write_json
except ImportError:  # pragma: no cover - package imports use the relative path
    from .release_common import digest_value, write_json


SCHEMA = "agent-python-quality-validation.v1"
POLICY_SCHEMA = "agent-python-quality-policy.v1"
MYPY_ERROR_RE = re.compile(r"^(?P<path>.+?):\d+: error: .*?(?:\s+\[(?P<code>[A-Za-z0-9_-]+)\])?$")


def validate_quality(
    *,
    repository_root: Path,
    policy_path: Path,
    run_receipt_path: Path,
    work_root: Path,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    try:
        policy = _read_object(policy_path)
        blockers.extend(_validate_policy(policy))
        run = _read_object(run_receipt_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        body = _body(blockers + [{"code": "quality-input-invalid", "message": str(exc)}])
        return {**body, "validationDigest": digest_value(body)}

    if run.get("schemaVersion") != "agent-python-quality-run.v1":
        blockers.append({"code": "quality-run-schema-invalid"})
    if run.get("status") != "PASS":
        blockers.append({"code": "quality-run-failed"})
    toolchain = policy.get("toolchain", {})
    if run.get("toolchain") != toolchain:
        blockers.append({"code": "quality-toolchain-policy-mismatch"})
    for command in run.get("commands", []):
        if isinstance(command, dict) and command.get("status") != "PASS":
            blockers.append({"code": "quality-command-not-passing", "id": command.get("id")})

    changed_paths = set(run.get("changedPaths", []))
    ruff = policy.get("ruff", {})
    for name, key in (
        ("correctness", "correctnessBaseline"),
        ("migration", "migrationBaseline"),
        ("lineLength", "lineLengthBaseline"),
    ):
        artifact = _artifact_path(repository_root, run, _artifact_key(name))
        current = _ruff_counts(artifact, repository_root, blockers, name)
        baseline_items = ruff.get(key, [])
        baseline = _baseline_counts(baseline_items, repository_root, blockers, name)
        blockers.extend(_source_digest_blockers(baseline_items, current, repository_root, changed_paths, name))
        blockers.extend(_compare_counts(name, current, baseline, changed_paths))

    format_path = _artifact_path(repository_root, run, "ruffFormat")
    format_current = _format_counts(format_path, repository_root, blockers)
    format_items = ruff.get("formatBaseline", [])
    format_baseline = _baseline_counts(format_items, repository_root, blockers, "format")
    blockers.extend(_source_digest_blockers(format_items, format_current, repository_root, changed_paths, "format"))
    blockers.extend(_compare_counts("format", format_current, format_baseline, changed_paths))

    mypy_path = _artifact_path(repository_root, run, "mypy")
    mypy_current = _mypy_counts(mypy_path, repository_root, blockers)
    mypy_items = policy.get("mypy", {}).get("baseline", [])
    mypy_baseline = _baseline_counts(mypy_items, repository_root, blockers, "mypy")
    blockers.extend(_source_digest_blockers(mypy_items, mypy_current, repository_root, changed_paths, "mypy"))
    blockers.extend(_compare_counts("mypy", mypy_current, mypy_baseline, changed_paths))
    strict_clean = set(policy.get("mypy", {}).get("strictClean", []))
    blockers.extend(
        {"code": "strict-clean-mypy-finding", "path": path, "errorCode": code, "count": count}
        for (path, code), count in mypy_current.items()
        if path in strict_clean and count
    )

    coverage_path = _artifact_path(repository_root, run, "coverage")
    blockers.extend(_validate_coverage(policy, coverage_path))
    blockers.extend(_validate_intentional_findings(policy, ruff, repository_root))
    body = _body(blockers)
    body.update({
        "changedPaths": sorted(changed_paths),
        "runDigest": run.get("runDigest"),
        "summary": {
            "ruffCorrectness": len(_safe_json_findings(_artifact_path(repository_root, run, "ruffCorrectness"))),
            "ruffMigration": len(_safe_json_findings(_artifact_path(repository_root, run, "ruffMigration"))),
            "mypy": sum(mypy_current.values()),
        },
    })
    return {**body, "validationDigest": digest_value(body)}


def _validate_policy(policy: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if policy.get("schemaVersion") != POLICY_SCHEMA:
        blockers.append({"code": "quality-policy-schema-invalid"})
    allowed = {"schemaVersion", "revision", "toolchain", "ruff", "mypy", "coverage", "limits", "productionPromotionClaimed"}
    blockers.extend({"code": "quality-policy-unknown-key", "key": key} for key in set(policy) - allowed)
    toolchain = policy.get("toolchain")
    if not isinstance(toolchain, dict) or set(toolchain) != {"ruff", "mypy", "coverage"}:
        blockers.append({"code": "quality-toolchain-invalid"})
    ruff = policy.get("ruff")
    required_ruff = {
        "targetVersion", "lineLength", "sourceRoots", "firstParty", "correctnessSelectors",
        "migrationSelectors", "intentionalFindings", "correctnessBaseline", "migrationBaseline",
        "formatBaseline", "lineLengthBaseline",
    }
    if not isinstance(ruff, dict) or set(ruff) != required_ruff:
        blockers.append({"code": "quality-ruff-policy-invalid"})
    mypy = policy.get("mypy")
    if not isinstance(mypy, dict) or set(mypy) != {"strictClean", "baseline"}:
        blockers.append({"code": "quality-mypy-policy-invalid"})
    coverage = policy.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != {"minimumStatementLinePercent", "baseline"}:
        blockers.append({"code": "quality-coverage-policy-invalid"})
    limits = policy.get("limits")
    if not isinstance(limits, dict) or set(limits) != {"maxWallSeconds", "maxOutputBytes", "maxBaselineEntries"}:
        blockers.append({"code": "quality-limits-policy-invalid"})
    if isinstance(limits, dict) and (
        not isinstance(limits.get("maxWallSeconds"), int)
        or limits.get("maxWallSeconds", 0) < 1
        or limits.get("maxWallSeconds", 0) > 3600
        or not isinstance(limits.get("maxOutputBytes"), int)
        or limits.get("maxOutputBytes", 0) < 4096
        or limits.get("maxOutputBytes", 0) > 64 * 1024 * 1024
    ):
        blockers.append({"code": "quality-limits-unbounded"})
    if isinstance(ruff, dict):
        for key in ("correctnessBaseline", "migrationBaseline", "formatBaseline", "lineLengthBaseline"):
            blockers.extend(_validate_baseline_shape(ruff.get(key), key))
        blockers.extend(_validate_intentional_shape(ruff.get("intentionalFindings")))
    if isinstance(mypy, dict):
        blockers.extend(_validate_baseline_shape(mypy.get("baseline"), "mypy.baseline"))
    return blockers


def _validate_baseline_shape(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"code": "quality-baseline-not-array", "baseline": label}]
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("code"), str):
            blockers.append({"code": "quality-baseline-entry-invalid", "baseline": label})
            continue
        key = (item["path"], item["code"])
        if key in seen:
            blockers.append({"code": "quality-baseline-duplicate", "baseline": label, "path": item["path"], "errorCode": item["code"]})
        seen.add(key)
        if not isinstance(item.get("count"), int) or item["count"] < 0:
            blockers.append({"code": "quality-baseline-count-invalid", "baseline": label, "path": item["path"]})
        if not isinstance(item.get("sourceDigest"), str) or len(item["sourceDigest"]) != 64:
            blockers.append({"code": "quality-baseline-digest-invalid", "baseline": label, "path": item["path"]})
    return blockers


def _validate_intentional_shape(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"code": "quality-intentional-not-array"}]
    blockers = []
    for item in value:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("path", "code", "owner", "reason")):
            blockers.append({"code": "quality-intentional-entry-invalid"})
    return blockers


def _ruff_counts(path: Path | None, root: Path, blockers: list[dict[str, Any]], label: str) -> Counter[tuple[str, str]]:
    if path is None or not path.exists():
        blockers.append({"code": "quality-artifact-missing", "artifact": label})
        return Counter()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blockers.append({"code": "quality-artifact-invalid", "artifact": label, "message": str(exc)})
        return Counter()
    if not isinstance(value, list):
        blockers.append({"code": "quality-artifact-invalid", "artifact": label})
        return Counter()
    counts: Counter[tuple[str, str]] = Counter()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str) or not isinstance(item.get("code"), str):
            blockers.append({"code": "ruff-finding-invalid", "artifact": label})
            continue
        path_value = _normal_path(item["filename"], root)
        if path_value is None:
            blockers.append({"code": "quality-path-outside-repository", "path": item["filename"]})
            continue
        counts[(path_value, item["code"])] += 1
    return counts


def _format_counts(path: Path | None, root: Path, blockers: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    if path is None or not path.exists():
        blockers.append({"code": "quality-artifact-missing", "artifact": "format"})
        return Counter()
    counts: Counter[tuple[str, str]] = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Would reformat:" not in line:
            continue
        raw = line.split("Would reformat:", 1)[1].strip()
        path_value = _normal_path(raw, root)
        if path_value:
            counts[(path_value, "FORMAT")] += 1
    return counts


def _mypy_counts(path: Path | None, root: Path, blockers: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    if path is None or not path.exists():
        blockers.append({"code": "quality-artifact-missing", "artifact": "mypy"})
        return Counter()
    counts: Counter[tuple[str, str]] = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = MYPY_ERROR_RE.match(line)
        if not match:
            continue
        path_value = _normal_path(match.group("path"), root)
        if path_value is None:
            blockers.append({"code": "quality-path-outside-repository", "path": match.group("path")})
            continue
        counts[(path_value, match.group("code") or "UNKNOWN")] += 1
    return counts


def _baseline_counts(value: Any, root: Path, blockers: list[dict[str, Any]], label: str) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    if not isinstance(value, list):
        return counts
    for item in value:
        if not isinstance(item, dict):
            continue
        path_value = _normal_path(item.get("path", ""), root)
        if path_value is not None:
            counts[(path_value, str(item.get("code")))] = int(item.get("count", 0))
    return counts


def _compare_counts(
    label: str,
    current: Counter[tuple[str, str]],
    baseline: Counter[tuple[str, str]],
    changed_paths: set[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for key, count in sorted(current.items()):
        old = baseline.get(key)
        path, code = key
        if old is None:
            blockers.append({"code": "new-quality-finding", "kind": label, "path": path, "errorCode": code, "count": count})
        elif count > old:
            blockers.append({"code": "quality-finding-growth", "kind": label, "path": path, "errorCode": code, "baseline": old, "actual": count})
        if count and path in changed_paths:
            blockers.append({"code": "changed-path-quality-finding", "kind": label, "path": path, "errorCode": code, "count": count})
    return blockers


def _source_digest_blockers(
    entries: Any,
    current: Counter[tuple[str, str]],
    root: Path,
    changed_paths: set[str],
    label: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return blockers
    for item in entries:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        code = item.get("code")
        if not isinstance(path, str) or not isinstance(code, str) or not current.get((_normal_path(path, root) or "", code)):
            continue
        normalized = _normal_path(path, root)
        if normalized is None:
            continue
        expected = item.get("sourceDigest")
        actual = _file_digest(root / normalized)
        if actual is None or actual == expected or normalized in changed_paths:
            continue
        blockers.append({
            "code": "quality-baseline-source-drift",
            "kind": label,
            "path": normalized,
            "errorCode": code,
        })
    return blockers


def _validate_coverage(policy: dict[str, Any], path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return [{"code": "coverage-artifact-missing"}]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        totals = value["totals"]
        percent = float(totals["percent_covered"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [{"code": "coverage-artifact-invalid", "message": str(exc)}]
    minimum = float(policy.get("coverage", {}).get("minimumStatementLinePercent", 0))
    if percent < minimum:
        return [{"code": "coverage-floor-failed", "actual": percent, "minimum": minimum}]
    return []


def _validate_intentional_findings(policy: dict[str, Any], ruff: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    allowed = {(item.get("path"), item.get("code")): item for item in ruff.get("intentionalFindings", []) if isinstance(item, dict)}
    return [
        {"code": "intentional-finding-missing-owner", "path": path, "errorCode": code}
        for (path, code) in allowed
        if not allowed[(path, code)].get("owner") or not allowed[(path, code)].get("reason")
    ]


def _artifact_key(name: str) -> str:
    return {
        "correctness": "ruffCorrectness",
        "migration": "ruffMigration",
        "lineLength": "ruffLineLength",
    }[name]


def _artifact_path(root: Path, run: dict[str, Any], key: str) -> Path | None:
    value = run.get("artifacts", {}).get(key)
    if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
        return None
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        return None
    return path


def _normal_path(value: str, root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(root.resolve())
        except ValueError:
            return None
    text = path.as_posix()
    if text.startswith("../") or text == "..":
        return None
    return text


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _safe_json_findings(path: Path | None) -> list[Any]:
    if path is None or not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _body(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--run-receipt", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = validate_quality(
        repository_root=Path.cwd().resolve(),
        policy_path=args.policy,
        run_receipt_path=args.run_receipt,
        work_root=args.work_root,
    )
    write_json(args.evidence, result)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
