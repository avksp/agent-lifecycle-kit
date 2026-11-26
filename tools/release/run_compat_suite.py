"""Replay retained consumer cases on two exact, isolated wheel installations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.cli import test_external_consumer_contract as consumer_fixture  # noqa: E402
from tools.release.release_common import canonical_bytes, digest_value, load_json  # noqa: E402

FIXTURES = ROOT / "tests/cli/fixtures/external-consumer-cases.json"
_CASE_METHODS = {
    "readonly-projection": ("test_readonly_projection", 2),
    "guarded-action": ("test_guarded_action", 3),
    "stale-guards": ("test_stale_guards", 4),
    "missing-input": ("test_missing_required_input", 3),
    "unattested-usage": ("test_unattested_usage", 2),
    "critical-route": ("test_critical_model_route", 2),
    "lost-reply": ("test_lost_reply_reconciles_without_second_mutation", 4),
    "incompatible-contract": ("test_incompatible_version_or_schema_refuses_before_mutation", 4),
}
_INSTALLED_SCHEMA = "agent-installed-compatibility-receipt.v1"
_TABLE_SCHEMA = "agent-tested-versions.v1"
_INSTALL_PROBE = """
import hashlib, importlib.metadata as metadata, json, pathlib, sys
dist = metadata.distribution("agent-lifecycle-kit")
root = pathlib.Path(dist.locate_file("")).resolve()
if not root.is_relative_to(pathlib.Path(sys.prefix).resolve()):
    raise SystemExit("distribution is outside the isolated environment")
result = {}
for name in json.load(sys.stdin):
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size > 4 * 1024 * 1024:
        raise SystemExit("package member escaped installed root or exceeded its bound")
    result[name] = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
print(json.dumps({"version":dist.version,"members":result}))
"""


def _wheel_payload(wheel: Path) -> tuple[str, dict[str, str]]:
    if not wheel.is_file() or not 0 < wheel.stat().st_size <= 16 * 1024 * 1024:
        raise ValueError("Wheel does not meet the local size bound")
    with wheel.open("rb") as stream:
        wheel_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    members: dict[str, str] = {}
    with zipfile.ZipFile(wheel) as artifact:
        package_files = [
            row for row in artifact.infolist() if row.filename.startswith("agent_lifecycle/") and not row.is_dir()
        ]
        if len(package_files) > 2048 or sum(row.file_size for row in package_files) > 32 * 1024 * 1024:
            raise ValueError("Wheel payload exceeds installed comparison bound")
        for row in package_files:
            path = PurePosixPath(row.filename)
            if ".." in path.parts or "\\" in row.filename or row.filename in members:
                raise ValueError("Wheel contains ambiguous package members")
            if row.file_size > 4 * 1024 * 1024:
                raise ValueError("Wheel member exceeds comparison bound")
            members[row.filename] = hashlib.sha256(artifact.read(row)).hexdigest()
    if "agent_lifecycle/__init__.py" not in members:
        raise ValueError("Wheel does not contain ALK")
    return wheel_sha, members


def installed_identity(cli: Path, wheel: Path) -> dict[str, Any]:
    """Verify the exact wheel code against its companion interpreter's installation."""
    executable = cli.absolute()
    environment = executable.parent.parent
    python = executable.with_name("python.exe" if os.name == "nt" else "python")
    if not (environment / "pyvenv.cfg").is_file() or not python.is_file() or not executable.is_file():
        raise ValueError("CLI must have a companion interpreter in an independent environment")
    wheel_sha, members = _wheel_payload(wheel)
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP", "USERPROFILE")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="alk-wheel-identity-") as tmp:
        result = subprocess.run(
            [str(python), "-I", "-B", "-c", _INSTALL_PROBE],
            cwd=tmp,
            input=json.dumps(list(members)),
            capture_output=True,
            text=True,
            env=env,
            timeout=25,
            check=True,
        )
    observed = json.loads(result.stdout)
    if observed["members"] != members:
        raise ValueError("Installed ALK payload differs from the supplied wheel")
    with executable.open("rb") as stream:
        executable_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "version": observed["version"],
        "wheelSha256": wheel_sha,
        "cliSha256": executable_sha,
        "packageMemberCount": len(members),
        "installedPayloadDigest": digest_value(members),
    }


def _replay(cli: Path, fixtures: dict[str, Any], identity: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the existing consumer oracles with an installed console script."""
    if identity["version"] not in fixtures["testedVersions"]:
        raise ValueError("Fixture version negotiation does not include the installation")

    class InstalledConsumerCase(consumer_fixture.ExternalConsumerContractTests):
        @classmethod
        def setUpClass(cls) -> None:
            cls.executable = str(cli.absolute())

    rows = []
    InstalledConsumerCase.setUpClass()
    for fixture in fixtures["cases"]:
        method_name, _ = _CASE_METHODS[fixture["id"]]
        case = InstalledConsumerCase(method_name)
        result = unittest.TestResult()
        case.run(result)
        if not result.wasSuccessful() or result.skipped:
            raise ValueError(f"Installed case failed: {fixture['id']}: {result.errors + result.failures}")
        calls = case.consumer.calls
        first = json.loads(calls[0]["stdout"])
        if first["version"] != identity["version"] or any(
            row["executableSha256"] != identity["cliSha256"] or not row["cleanupConfirmed"] for row in calls
        ):
            raise ValueError("Consumer subprocess identity or cleanup was not stable")
        rows.append(
            {
                "caseId": fixture["id"],
                "status": "PASS",
                "calls": [{k: row[k] for k in ("exitCode", "stdoutSha256", "outcome")} for row in calls],
            }
        )
    return rows


def _comparison(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[str]:
    def projection(rows: list[dict[str, Any]]) -> dict[str, list[tuple[int, str]]]:
        observed = {}
        for row in rows:
            case_id = row["caseId"]
            calls = row["calls"]
            if (
                case_id not in _CASE_METHODS
                or case_id in observed
                or row["status"] != "PASS"
                or not isinstance(calls, list)
                or len(calls) != _CASE_METHODS[case_id][1]
            ):
                raise ValueError("Installed compatibility receipt has invalid case observations")
            observed[case_id] = [_call_outcome(call) for call in calls]
        return observed

    left, right = projection(baseline), projection(candidate)
    if left != right or set(left) != set(_CASE_METHODS):
        raise ValueError("Installed compatibility case or command outcomes differ")
    return sorted(left)


def _call_outcome(call: dict[str, Any]) -> tuple[int, str]:
    digest = call["stdoutSha256"]
    if (
        type(call["exitCode"]) is not int
        or call["outcome"] != "RECEIVED"
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("Installed compatibility receipt has an invalid command observation")
    return call["exitCode"], call["outcome"]


def tested_version_table(receipt: dict[str, Any]) -> dict[str, Any]:
    """Project only observed versions and covered cases from an accepting receipt."""
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    if receipt.get("receiptDigest") != digest_value(body) or receipt.get("schemaVersion") != _INSTALLED_SCHEMA:
        raise ValueError("Invalid compatibility receipt binding")
    if receipt.get("status") != "PASS":
        raise ValueError("The compatibility run has no passing observation")
    cases = _comparison(receipt["baseline"]["cases"], receipt["candidate"]["cases"])
    versions = (
        []
        if receipt["developmentCandidate"]
        else [
            receipt["baseline"]["identity"]["version"],
            receipt["candidate"]["identity"]["version"],
        ]
    )
    if versions and len(set(versions)) != 2:
        raise ValueError("A tested-version table needs distinct installed versions")
    return {
        "schemaVersion": _TABLE_SCHEMA,
        "testedVersions": versions,
        "cases": cases,
        "evidenceBoundary": "INSTALLED_PORTABLE_CASES",
        "stablePromiseStatus": "PENDING_ACTIVATION",
    }


def materialize_table(receipt_path: Path, verified_table: Path, destination: Path) -> None:
    table = tested_version_table(load_json(receipt_path))
    expected = canonical_bytes(table) + b"\n"
    if not table["testedVersions"] or verified_table.read_bytes() != expected:
        raise ValueError("Only a matching versioned table can be materialized")
    with destination.open("xb") as stream:
        stream.write(expected)


def execute_replay(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    if args.baseline_cli.parent.parent.resolve() == args.candidate_cli.parent.parent.resolve():
        raise ValueError("Baseline and candidate must use disjoint environments")
    if args.fixtures.read_bytes() != FIXTURES.read_bytes():
        raise ValueError("Consumer input differs from the authoritative retained inventory")
    fixtures = load_json(args.fixtures)
    baseline = installed_identity(args.baseline_cli, args.baseline_wheel)
    candidate = installed_identity(args.candidate_cli, args.candidate_wheel)
    if baseline["wheelSha256"] == candidate["wheelSha256"]:
        raise ValueError("The candidate is the same wheel as the baseline")
    body = {
        "schemaVersion": _INSTALLED_SCHEMA,
        "status": "PASS",
        "developmentCandidate": args.development_candidate,
        "fixtureDigest": digest_value(fixtures),
        "surfaceDigest": digest_value(load_json(args.surface)),
        "baseline": {"identity": baseline, "cases": _replay(args.baseline_cli, fixtures, baseline)},
        "candidate": {"identity": candidate, "cases": _replay(args.candidate_cli, fixtures, candidate)},
        "modelCallsStarted": False,
    }
    receipt = {**body, "receiptDigest": digest_value(body)}
    return receipt, tested_version_table(receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in (
        "baseline-cli",
        "candidate-cli",
        "baseline-wheel",
        "candidate-wheel",
        "fixtures",
        "surface",
        "out",
        "table-out",
        "materialize-table",
        "verified-table",
        "destination",
    ):
        parser.add_argument(f"--{flag}", type=Path)
    parser.add_argument("--development-candidate", action="store_true")
    args = parser.parse_args()
    try:
        if args.materialize_table:
            if not args.verified_table or not args.destination:
                parser.error("materialization requires --verified-table and --destination")
            materialize_table(args.materialize_table, args.verified_table, args.destination)
        else:
            required = (
                "baseline_cli",
                "candidate_cli",
                "baseline_wheel",
                "candidate_wheel",
                "fixtures",
                "surface",
                "out",
                "table_out",
            )
            if any(getattr(args, name) is None for name in required):
                parser.error("paired replay requires both CLI and wheel paths, fixtures, surface and outputs")
            receipt, table = execute_replay(args)
            if args.out.exists() or args.table_out.exists() or args.out.resolve() == args.table_out.resolve():
                raise ValueError("Compatibility evidence outputs must be distinct and fresh")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("xb") as stream:
                stream.write(canonical_bytes(receipt) + b"\n")
            with args.table_out.open("xb") as stream:
                stream.write(canonical_bytes(table) + b"\n")
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        parser.exit(1, f"compatibility: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
