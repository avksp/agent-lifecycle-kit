from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

EXCLUDED_PREFIXES = (
    "release/",
    "plans/standalone-v1/workflow/",
    "plans/standalone-v1/evidence/",
)

PAYLOAD_ROOTS = (
    ".github/workflows",
    ".agents/plugins",
    ".claude-plugin",
    ".codex-plugin",
    ".cursor-plugin",
    "adapters",
    "conformance",
    "docs",
    "policy",
    "profiles",
    "skills",
    "src",
    "tests",
    "tools/release",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "opencode.json",
    "README.md",
    "SECURITY.md",
    "skills.sh.json",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "uv.lock",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def iter_payload_files(root: Path = Path(".")) -> list[Path]:
    files: list[Path] = []
    for item in PAYLOAD_ROOTS:
        path = root / item
        if path.is_file():
            files.append(path.relative_to(root))
        elif path.is_dir():
            files.extend(_iter_dir(path, root))
    return sorted(set(files), key=lambda p: p.as_posix())


def require_contains(path: Path, values: Iterable[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [value for value in values if value not in text]
    if missing:
        raise SystemExit(f"{path} is missing required values: {', '.join(missing)}")


def _iter_dir(path: Path, root: Path) -> list[Path]:
    output: list[Path] = []
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        rel = child.relative_to(root)
        rel_text = rel.as_posix()
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if any(rel_text.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        if rel.suffix in {".pyc", ".pyo"}:
            continue
        output.append(rel)
    return output
