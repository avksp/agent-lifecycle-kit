from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from release_common import file_identity, write_json


DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "`VERIFIED` for Codex CLI 0.145.0",
            "`VERIFIED` for Claude Code 2.1.220",
            "`VERIFIED` for OpenCode CLI 1.18.9",
            "`VERIFIED` for Hermes Agent v0.19.0",
            "`VERIFIED` for qwen-code 0.21.0",
            "`EXPERIMENTAL` means",
            "bounded live host conformance",
            "usage/cost",
        ),
    ),
    (
        "docs/guides/README.ru.md",
        (
            "`VERIFIED` для Codex CLI 0.145.0",
            "`VERIFIED` для Claude Code 2.1.220",
            "`VERIFIED` для OpenCode CLI 1.18.9",
            "`VERIFIED` для Hermes Agent v0.19.0",
            "`VERIFIED` для qwen-code 0.21.0",
            "`EXPERIMENTAL` означает",
            "калибровки расхода",
        ),
    ),
    (
        "docs/adapters/support-matrix.md",
        (
            "authoritative current source-tree support claim",
            "Codex CLI 0.6.0 live evidence",
            "Claude Code 0.5.0 live evidence",
            "OpenCode GLM 5.2 live evidence",
            "Hermes GLM 5.2 live evidence",
            "qwen-code GLM 5.2 live evidence",
            "Cursor, Gemini CLI, and Kimi Code remain",
        ),
    ),
    (
        "docs/adapters/live-promotion-runbook.md",
        (
            "Source release",
            "Host-specific `VERIFIED`",
            "Public directory approval",
            "Production promotion",
            "validate_adapter_conformance.py",
            "validate_live_host_conformance.py",
            "validate_live_calibration.py",
            "validate_support_matrix.py",
        ),
    ),
    (
        "docs/guides/verified-adapter-release-checklist.md",
        (
            "remote tag",
            "GitHub Release object",
            "CI status",
            "Binary assets are intentionally omitted for a source release",
            "validate_adapter_conformance.py",
            "validate_docs_compat.py",
            "validate_support_matrix.py",
        ),
    ),
    (
        "release/notes/v0.12.1.md",
        (
            "Status: source release.",
            "Windows CI failure",
            "Updated package metadata to `0.12.1`",
        ),
    ),
)

ADAPTER_DOCS = (
    "docs/adapters/claude.md",
    "docs/adapters/codex.md",
    "docs/adapters/cursor.md",
    "docs/adapters/gemini-cli.md",
    "docs/adapters/hermes.md",
    "docs/adapters/kimi-code.md",
    "docs/adapters/opencode.md",
    "docs/adapters/qwen-code.md",
)

VERIFIED_ROW = re.compile(r"^\|[^|\n]+\|[^|\n]+\|\s*VERIFIED\s*\|", re.MULTILINE)
PRODUCTION_READY_CLAIM = re.compile(r"\b(production[- ]ready|production ready)\b", re.IGNORECASE)
VERIFIED_DOC_HOSTS = {"Codex", "Claude Code", "OpenCode", "Hermes", "qwen-code"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    for relative, required in DOC_RULES:
        checks.append(_check_doc(root, relative, required, blockers))
    for relative in ADAPTER_DOCS:
        checks.append(_check_adapter_doc(root, relative, blockers))

    evidence = {
        "schemaVersion": "agent-docs-compat-evidence.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _check_doc(root: Path, relative: str, required: tuple[str, ...], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    path = root / relative
    check: dict[str, Any] = {"path": relative, "status": "PASS", "required": list(required), "identity": None}
    if not path.is_file():
        blockers.append({"code": "docs-compat-file-missing", "message": f"{relative} is missing"})
        check["status"] = "FAIL"
        return check
    text = path.read_text(encoding="utf-8")
    check["identity"] = file_identity(path)
    missing = [phrase for phrase in required if phrase not in text]
    if missing:
        blockers.append({"code": "docs-compat-required-text-missing", "message": f"{relative} missing: {', '.join(missing)}"})
        check["status"] = "FAIL"
    if _contains_overclaim(relative, text, blockers):
        check["status"] = "FAIL"
    return check


def _check_adapter_doc(root: Path, relative: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    path = root / relative
    if relative == "docs/adapters/claude.md":
        required = ("`VERIFIED`", "Claude Code 2.1.220", "live conformance", "does not claim official")
    elif relative == "docs/adapters/codex.md":
        required = ("`VERIFIED`", "Codex CLI 0.145.0", "live conformance", "does not claim public")
    elif relative == "docs/adapters/opencode.md":
        required = ("`VERIFIED`", "OpenCode CLI `1.18.9`", "live conformance", "does not claim npm")
    elif relative == "docs/adapters/hermes.md":
        required = ("`VERIFIED`", "Hermes Agent `v0.19.0`", "live conformance", "does not claim public")
    elif relative == "docs/adapters/qwen-code.md":
        required = ("`VERIFIED`", "qwen-code `0.21.0`", "live conformance", "does not claim public")
    else:
        required = ("`EXPERIMENTAL`", "live", "conformance")
    check = _check_doc(root, relative, required, blockers)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if (
            "`VERIFIED`" in text
            and relative
            not in {
                "docs/adapters/claude.md",
                "docs/adapters/codex.md",
                "docs/adapters/opencode.md",
                "docs/adapters/hermes.md",
                "docs/adapters/qwen-code.md",
            }
            and "until live" not in text
            and "not `VERIFIED`" not in text
        ):
            blockers.append({"code": "docs-compat-adapter-verified-overclaim", "message": f"{relative} mentions VERIFIED without live-evidence qualifier"})
            check["status"] = "FAIL"
    return check


def _contains_overclaim(relative: str, text: str, blockers: list[dict[str, Any]]) -> bool:
    failed = False
    invalid_verified_rows = [
        row
        for row in VERIFIED_ROW.findall(text)
        if _verified_row_host(row) not in VERIFIED_DOC_HOSTS
    ]
    if invalid_verified_rows:
        blockers.append({"code": "docs-compat-verified-row", "message": f"{relative} contains a VERIFIED current-maturity row"})
        failed = True
    if "offline source release" in text.lower() and PRODUCTION_READY_CLAIM.search(text):
        blockers.append({"code": "docs-compat-production-ready-overclaim", "message": f"{relative} overclaims offline source release readiness"})
        failed = True
    return failed


def _verified_row_host(row: str) -> str:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return cells[0] if cells else ""


if __name__ == "__main__":
    raise SystemExit(main())
