from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import digest_value, write_json


ADOPTION_DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "docs/guides/quickstart.md",
            "docs/guides/install-and-first-run.md",
            "docs/guides/commands-by-task.md",
            "docs/reference/project-comparison.md",
            "python -m pip install -e .",
        ),
    ),
    (
        "docs/README.md",
        (
            "Project comparison",
            "reference/project-comparison.md",
            "Managed adapter session support",
        ),
    ),
    (
        "docs/ru/README.md",
        (
            "сравнение проекта",
            "reference/project-comparison.md",
            "управляемые сессии адаптеров",
            "guides/install-and-first-run.md",
            "guides/commands-by-task.md",
        ),
    ),
    (
        "docs/guides/install-and-first-run.md",
        (
            "Install from a GitHub checkout",
            "Install the published package",
            "agent-lifecycle-kit=={target_version}",
            "agent-lifecycle version",
        ),
    ),
    (
        "docs/ru/guides/install-and-first-run.md",
        (
            "Установка из GitHub",
            "Установка опубликованного пакета",
            "agent-lifecycle-kit=={target_version}",
            "agent-lifecycle version",
        ),
    ),
    (
        "docs/adapters/support-matrix.md",
        (
            "Managed launch",
            "`WRAPPER_ONLY`",
            "managed-session-support.md",
        ),
    ),
    (
        "docs/ru/adapters/support-matrix.md",
        (
            "Управляемый запуск",
            "`WRAPPER_ONLY`",
            "managed-session-support.md",
        ),
    ),
    (
        "docs/reference/project-comparison.md",
        (
            "lifecycle controller",
            "not a runtime",
            "not a model broker",
            "Source of truth remains the frozen ALK plan",
        ),
    ),
    (
        "docs/ru/reference/project-comparison.md",
        (
            "не кодовый агент",
            "не платформа запуска моделей",
            "Источником правды остаётся зафиксированный план ALK",
        ),
    ),
)

FALSE_PUBLICATION_CLAIMS = (
    "PyPI publication is claimed",
    "public marketplace approval is claimed",
    "marketplace approval is claimed",
    "official directory approval is claimed",
    "публикация в PyPI заявлена",
    "одобрение публичного каталога заявлено",
    "одобрение маркетплейса заявлено",
)


def validate_publication_adoption(*, root: Path, target_version: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for relative, required_values in ADOPTION_DOC_RULES:
        check = _check_required_text(root=root, relative=relative, required_values=required_values, target_version=target_version)
        checks.append(check)
        if check["status"] != "PASS":
            blockers.append(
                {
                    "code": "publication-adoption-doc-missing",
                    "path": relative,
                    "missing": check["missing"],
                }
            )
    claim_check = _check_false_publication_claims(root=root)
    checks.append(claim_check)
    if claim_check["status"] != "PASS":
        blockers.append(
            {
                "code": "publication-adoption-false-claim",
                "matches": claim_check["matches"],
            }
        )
    status = "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": "agent-publication-adoption-validation.v1",
        "status": status,
        "targetVersion": target_version,
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": digest_value(body)}


def _check_required_text(
    *,
    root: Path,
    relative: str,
    required_values: tuple[str, ...],
    target_version: str,
) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        return {"name": "required-text", "status": "FAIL", "path": relative, "missing": list(required_values)}
    text = path.read_text(encoding="utf-8")
    expected = [value.format(target_version=target_version) for value in required_values]
    missing = [value for value in expected if value not in text]
    return {
        "name": "required-text",
        "status": "PASS" if not missing else "FAIL",
        "path": relative,
        "missing": missing,
    }


def _check_false_publication_claims(*, root: Path) -> dict[str, Any]:
    matches: list[dict[str, str]] = []
    for relative, _required in ADOPTION_DOC_RULES:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in FALSE_PUBLICATION_CLAIMS:
            if marker in text:
                matches.append({"path": relative, "marker": marker})
    return {
        "name": "false-publication-claims",
        "status": "PASS" if not matches else "FAIL",
        "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    evidence = validate_publication_adoption(root=Path(args.root), target_version=args.target_version)
    write_json(Path(args.evidence), evidence)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
