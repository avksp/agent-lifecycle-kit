from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from release_common import digest_value, file_identity, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    root = Path.cwd()
    paths = {
        "scanner": root / "src/agent_lifecycle/neutrality/scanner.py",
        "receipt": root / "src/agent_lifecycle/neutrality/receipt.py",
        "cli": root / "src/agent_lifecycle/neutrality/cli.py",
        "gate": root / "src/agent_lifecycle/neutrality/gate.py",
        "policy": Path(args.policy),
        "ci": root / ".github/workflows/ci.yml",
        "release": root / ".github/workflows/release.yml",
    }
    blockers = _validate(paths)
    body = {
        "schemaVersion": "agent-neutrality-scope-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "files": {name: file_identity(path) if path.exists() else None for name, path in paths.items()},
        "scope": "tracked-release",
        "legacyScopes": ["current-tree-complete", "full-repository"],
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), {**body, "validationDigest": digest_value(body)})
    return 0 if not blockers else 1


def _validate(paths: dict[str, Path]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name, path in paths.items():
        if not path.exists():
            blockers.append({"code": "neutrality-scope-source-missing", "source": name})
    if blockers:
        return blockers

    scanner = paths["scanner"].read_text(encoding="utf-8")
    receipt = paths["receipt"].read_text(encoding="utf-8")
    cli = paths["cli"].read_text(encoding="utf-8")
    gate = paths["gate"].read_text(encoding="utf-8")
    policy = json.loads(paths["policy"].read_text(encoding="utf-8"))

    required_scanner_markers = (
        'TRACKED_RELEASE_SCOPE = "tracked-release"',
        '"git", "ls-files", "-z", "--stage", "--cached"',
        '"100644", "100755"',
        '"120000"',
        '"160000"',
        '"recoveredReadRaces"',
    )
    _require_markers(blockers, "scanner", scanner, required_scanner_markers)
    _require_markers(
        blockers,
        "receipt",
        receipt,
        ("scopeBindingDigest", "deprecatedScope", "require_zero_completeness_counters"),
    )
    for name, source in (("cli", cli), ("gate", gate)):
        _require_markers(
            blockers,
            name,
            source,
            ("NEUTRALITY_SCOPE_CHOICES", "--include-local-artifacts", "require_zero_completeness_counters"),
        )
        try:
            ast.parse(source, filename=paths[name].as_posix())
        except SyntaxError:
            blockers.append({"code": "neutrality-scope-source-invalid", "source": name})

    roots = policy.get("localArtifactRoots")
    if not isinstance(roots, list) or not roots or not all(isinstance(item, str) and item for item in roots):
        blockers.append({"code": "neutrality-local-artifact-roots-invalid"})
    for name in ("ci", "release"):
        workflow = paths[name].read_text(encoding="utf-8")
        if "neutrality scan --scope tracked-release" not in workflow:
            blockers.append({"code": "neutrality-workflow-scope-stale", "source": name})
    return blockers


def _require_markers(
    blockers: list[dict[str, Any]],
    source_name: str,
    source: str,
    markers: tuple[str, ...],
) -> None:
    for marker in markers:
        if marker not in source:
            blockers.append(
                {"code": "neutrality-scope-contract-marker-missing", "source": source_name, "marker": marker}
            )


if __name__ == "__main__":
    raise SystemExit(main())
