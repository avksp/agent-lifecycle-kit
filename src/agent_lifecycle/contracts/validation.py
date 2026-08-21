"""Bounded validation primitives shared by literal project profiles."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError


def load_bounded_literal_profile(
    path: Path,
    *,
    root: Path,
    error_prefix: str,
    max_bytes: int = 32768,
) -> dict[str, Any]:
    """Load one contained ``PROFILE = <literal>`` file without executing code."""

    lexical_root = root.absolute()
    candidate = path if path.is_absolute() else lexical_root / path
    try:
        lexical_candidate = candidate.absolute()
        lexical_candidate.relative_to(lexical_root)
        resolved_root = lexical_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise LifecycleError(f"{error_prefix}-missing", "literal profile is unavailable") from exc
    if _contains_symlink(lexical_root, lexical_candidate) or candidate.is_symlink():
        raise LifecycleError(f"{error_prefix}-path", "literal profile must not contain symlinks")
    if not resolved.is_file():
        raise LifecycleError(f"{error_prefix}-path", "literal profile must be a regular file")
    try:
        if resolved.stat().st_size > max_bytes:
            raise LifecycleError(f"{error_prefix}-too-large", "literal profile exceeds its size limit")
        source = resolved.read_text(encoding="utf-8")
    except LifecycleError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise LifecycleError(f"{error_prefix}-invalid", "literal profile cannot be read") from exc
    try:
        tree = ast.parse(source, filename=resolved.as_posix())
    except (SyntaxError, ValueError) as exc:
        raise LifecycleError(f"{error_prefix}-invalid", "literal profile cannot be parsed") from exc
    statements = list(tree.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        raise LifecycleError(f"{error_prefix}-not-literal", "literal profile must contain only PROFILE")
    assignment = statements[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name) or assignment.targets[0].id != "PROFILE":
        raise LifecycleError(f"{error_prefix}-not-literal", "literal profile must assign PROFILE")
    try:
        profile = ast.literal_eval(assignment.value)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise LifecycleError(f"{error_prefix}-not-literal", "PROFILE must be a Python literal") from exc
    if not isinstance(profile, dict):
        raise LifecycleError(f"{error_prefix}-not-literal", "PROFILE must evaluate to an object")
    return profile


def _contains_symlink(root: Path, candidate: Path) -> bool:
    """Reject symlinked path components between a trusted root and a file."""

    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False
