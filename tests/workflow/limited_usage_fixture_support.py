"""Copy immutable Git seed bytes into independent declared-ledger test roots."""

from __future__ import annotations

import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

_IGNORE = b"work/\ntasks/\nrun.state.json\nevents.jsonl\nprofiles/\nadapters/\n"
_EXAMPLE = b"value = 1\n"


@lru_cache(maxsize=1)
def git_seed():
    """Cache bytes only, before any ledger, identity, admission or receipt exists."""
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="alk-declared-git-seed-") as directory:
        root = Path(directory)
        for arguments in (
            ["init", "-q"],
            ["config", "user.email", "fixture@example.invalid"],
            ["config", "user.name", "Local Fixture"],
        ):
            subprocess.run(["git", *arguments], cwd=root, check=True)
        (root / ".gitignore").write_bytes(_IGNORE)
        (root / "src").mkdir()
        (root / "src/example.py").write_bytes(_EXAMPLE)
        subprocess.run(["git", "add", ".gitignore", "src/example.py"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        files = tuple(
            (path.relative_to(root).as_posix(), path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file()
        )
    return revision, files, time.perf_counter() - started


def install_git_seed(root):
    """Write independent files, including Git objects/index; never share a directory."""
    if root.is_symlink() or any(root.iterdir()):
        raise ValueError("Declared fixture requires an empty ordinary directory")
    revision, files, _ = git_seed()
    for name, data in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return revision
