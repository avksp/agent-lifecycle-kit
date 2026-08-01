from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_lifecycle.contracts import canonical_digest, sha256_hex  # noqa: E402


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
    "evals",
    "fixtures",
    "docs",
    "policy",
    "profiles",
    "skills",
    "src",
    "templates",
    "tests",
    "tools/live_hosts",
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
    from agent_lifecycle.contracts import canonical_bytes as core_canonical_bytes

    return core_canonical_bytes(value)


def digest_value(value: Any) -> str:
    return canonical_digest(value)


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
        "sha256": sha256_hex(data),
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
        if any(_is_excluded_part(part) for part in rel.parts):
            continue
        if any(rel_text.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        if rel.suffix in {".pyc", ".pyo"}:
            continue
        output.append(rel)
    return output


def _is_excluded_part(part: str) -> bool:
    return part in EXCLUDED_PARTS or part.endswith(".egg-info")
