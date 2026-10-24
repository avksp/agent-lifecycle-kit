"""Check thin skill routing, complete references and actual plugin byte parity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

from agent_plugin_package import EXPECTED_SKILLS, MAX_PACKAGE_BYTES, validate_package, validate_skill_source

_RULES = {
    "agent-first-planning": ("SDD", "ownership", "independent", "draft-only"),
    "agent-plan-to-workers": ("frozen", "lock", "DAG", "budgets"),
    "agent-workflow-orchestrator": ("final audit", "authorization", "atomic commands", "UNKNOWN"),
    "audit-agent-plan": ("independent", "Findings", "READY_TO_FREEZE", "draft-only"),
    "audit-plan-implementation": ("independent", "frozen", "typed audit", "Final audit"),
    "bug-forensics": ("Optional", "red before", "fingerprint", "fix-impact"),
    "issue-to-spec": ("draft-only", "sourceTrusted: false", "freezeBlocked: true", "executionAuthorized: false"),
}
_BYPASS = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:skip|bypass|disable)\s+(?:independent\s+)?(?:review|freeze|budgets?|authorization)\b"
)


# Exact clauses catch bounded regressions, not arbitrary contradictions or meaning.
# Whitespace normalization permits wrapping without changing required wording.
_ORCHESTRATOR_CLAUSES = {
    "router": (
        "Read [the complete lifecycle contract](references/lifecycle-contract.md) before acting in this stage.",
        "The complete lifecycle contract remains required.",
        "Read the common route, recipe table and safety rules in docs/guides/lifecycle-cookbook.md.",
        "Select the recipe for the current request and stage.",
        "Read that recipe and its required links before acting.",
        "Load another recipe when the stage changes.",
        "Retain valid evidence after overruns; preserve all expenses and UNKNOWN usage across retries and compact.",
        "Start only the selected frozen task.",
        "Do not bypass independent review, reviewed freeze, ownership, authorization or budgets.",
        "Missing evidence stays missing; unknown telemetry stays null.",
        "Do not reset expenses or run clocks after retries or context compaction.",
        "Serialization and prepared Review Mesh packets grant no review, attestation or execution authority.",
        "A prompt, skill or fixture cannot create host enforcement.",
        "restored context grants no execution authority.",
    ),
    "reference": (
        "Freeze only reviewed matching inputs.",
        "Respect execution mode: plan-only, approval-required, or auto-after-freeze.",
        "Launch only dependency-ready packets within frozen parallelism.",
        "Audit every task attempt with `audit-plan-implementation` before acceptance.",
        "For remediation require a frozen retry budget, independent `REWORK` evidence and open finding IDs;",
        "Never edit state manually.",
        "Later code changes require a new claim and result.",
        "Review Mesh is not authority to inject prompts into hosts or bypass review/freeze.",
        "`PLAN_ONLY` never authorizes.",
        "A missing, stale or mismatched receipt blocks the level selected by the plan.",
        "Budget exhaustion, missing receipts, stale evidence, or unverifiable telemetry cannot produce a pass.",
        "Keep the latest user instructions and active packet verbatim.",
        "overflow must split, request larger context, or block, never silently truncate.",
    ),
}


def _critical_clause_blockers(name: str, router: str, reference: str) -> list[dict]:
    if name != "agent-workflow-orchestrator":
        return []
    blockers = []
    for component, text in (("router", router), ("reference", reference)):
        normalized = " ".join(text.split())
        for clause in _ORCHESTRATOR_CLAUSES[component]:
            if clause not in normalized:
                blockers.append(
                    {
                        "code": "skill-critical-clause-missing",
                        "skill": name,
                        "component": component,
                        "clause": clause,
                    }
                )
    return blockers


def validate_skill_parity(
    root: Path,
    *,
    package_root: Path | None = None,
    archive: Path | None = None,
) -> dict:
    """Validate local projection; this does not attest a host installation."""
    source = root / "skills"
    blockers = list(validate_skill_source(source)["blockers"])
    pins = []
    for name in EXPECTED_SKILLS:
        router = source / name / "SKILL.md"
        reference = source / name / "references/lifecycle-contract.md"
        if not router.is_file() or not reference.is_file() or router.is_symlink() or reference.is_symlink():
            blockers.append({"code": "skill-reference-missing", "skill": name})
            continue
        raw, full = router.read_bytes(), reference.read_bytes()
        text, reference_text = raw.decode("utf-8"), full.decode("utf-8")
        digest = hashlib.sha256(full).hexdigest()
        if len(raw) > 4096 or len(full) > 524288:
            blockers.append({"code": "skill-routing-size-invalid", "skill": name})
        if "(references/lifecycle-contract.md)" not in text or f"Full contract SHA256: `{digest}`" not in text:
            blockers.append({"code": "skill-reference-drift", "skill": name})
        if not full.startswith(b"---\n") or f"name: {name}\n" not in full.decode("utf-8"):
            blockers.append({"code": "skill-reference-identity-invalid", "skill": name})
        for marker in (*_RULES[name], "Do not bypass", "budgets", "unknown telemetry stays null"):
            if marker not in text:
                blockers.append({"code": "skill-invariant-missing", "skill": name, "marker": marker})
        if _BYPASS.search(text) or _BYPASS.search(full.decode("utf-8")):
            blockers.append({"code": "skill-bypass-advice", "skill": name})
        blockers.extend(_critical_clause_blockers(name, text, reference_text))
        pins.append(
            {
                "skill": name,
                "routerBytes": len(raw),
                "routerWords": len(text.split()),
                "routerSha256": hashlib.sha256(raw).hexdigest(),
                "referenceBytes": len(full),
                "referenceWords": len(reference_text.split()),
                "referenceSha256": digest,
            }
        )
    expected = _inventory(source, "skills/")
    if package_root is not None:
        blockers.extend(validate_package(package_root)["blockers"])
        _compare(expected, _inventory(package_root / "skills", "skills/"), blockers, "package")
    if archive is not None:
        if not archive.is_file() or archive.is_symlink() or archive.stat().st_size > MAX_PACKAGE_BYTES:
            blockers.append({"code": "skill-archive-invalid"})
        else:
            try:
                with zipfile.ZipFile(archive) as handle:
                    entries = handle.infolist()
                    if sum(item.file_size for item in entries) > MAX_PACKAGE_BYTES:
                        raise ValueError("expanded archive exceeds cap")
                    names = [item.filename for item in entries]
                    if len(names) != len(set(names)):
                        raise ValueError("duplicate archive paths")
                    archived = {name: handle.read(name) for name in names if name.startswith("skills/")}
                _compare(expected, archived, blockers, "archive")
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                blockers.append({"code": "skill-archive-invalid", "reason": type(exc).__name__})
    return {
        "schemaVersion": "agent-skill-parity-validation.v1",
        "status": "FAIL" if blockers else "PASS",
        "blockers": blockers,
        "skills": pins,
        "sourceFileCount": len(expected),
        "packageCompared": package_root is not None,
        "archiveCompared": archive is not None,
        "hostInstallationAttested": False,
        "wordCountMethod": "len(utf8_text.split()); includes Markdown and code",
        "semanticEquivalenceAttested": False,
        "steComplianceAttested": False,
    }


def _inventory(root: Path, prefix: str) -> dict[str, bytes]:
    return {
        prefix + path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _compare(expected: dict, actual: dict, blockers: list, projection: str) -> None:
    for name in sorted(set(expected) | set(actual)):
        if expected.get(name) != actual.get(name):
            blockers.append({"code": "skill-projection-mismatch", "projection": projection, "path": name})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--package")
    parser.add_argument("--archive")
    parser.add_argument("--evidence")
    args = parser.parse_args()
    result = validate_skill_parity(
        Path(args.root),
        package_root=Path(args.package) if args.package else None,
        archive=Path(args.archive) if args.archive else None,
    )
    if args.evidence:
        from release_common import write_json

        write_json(Path(args.evidence), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
