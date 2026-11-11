"""Collect and qualify bounded GitHub Actions evidence for this repository's CI."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.metadata
import io
import json
import math
import os
import platform
import re
import stat
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard, cast

REPOSITORY = "avksp/agent-lifecycle-kit"
WORKFLOW = ".github/workflows/ci.yml"
POLICY = "policy/python-quality.json"
BUILD_REQUIREMENTS = "tools/ci/build-requirements.txt"
FIXTURE = "fixtures/release-2-16-tests.zip"
MAIN_DIST = "work/ci/main-dist"
MAIN_REF = "refs/heads/main"
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_INDEX = 262144
MAX_AGE = timedelta(hours=24)
PYTHONS = ("3.11", "3.12", "3.13", "3.14", "3.15")
PLATFORMS = ("ubuntu-latest", "macos-latest", "windows-latest")
ROLES = ("ci", "foundation", "quality")
JOB_IDS = {"ci": "test", "foundation": "foundation", "quality": "quality"}
PREPARE = "Prepare sealed cell environment"
RECORD = "Record complete suite evidence"
CELL_UPLOAD = "Upload complete suite evidence"
PROBE = "Check compatibility and current quality"
PROBE_UPLOAD = "Upload compatibility observation"
CANDIDATE_JOB = "Main PR evidence candidate"
CANDIDATE_UPLOAD = "Upload qualified candidate inputs"
CANDIDATE_GENERATION = "Qualify exact PR run attempt"
UPLOAD_LOG = "Record optional upload "
DECISION_JOB = "Main CI mode"
DECISION_STEP = "Decide one main CI mode"
MAIN_CHECKS_JOB = "Main integration and packaging"
MAIN_CHECKS_UPLOAD = "Upload main checks evidence"
TERMINAL_JOB = "Main CI qualification"
TERMINAL_STEP = "Validate main CI outcome"
TERMINAL_UPLOAD = "Upload main CI qualification"
BACKEND = "Select verified accounting Git backend for Windows 3.15"
BACKEND_AFTER = "Verify accounting Git backend and PATH after tests"
STRICT_MYPY = "Check strict types in reduced contract modules"
QUALITY_RUN = "Run bounded runtime and selected tooling quality evidence"
QUALITY_VALIDATE = "Validate quality evidence"
COMMON_INPUTS = (
    WORKFLOW,
    ".github/workflows/codeql.yml",
    "tools/ci/qualify_pr_evidence.py",
    "uv.lock",
    "pyproject.toml",
    BUILD_REQUIREMENTS,
    POLICY,
    FIXTURE,
    "tools/ci/run_unittest.py",
    "tools/release/run_python_quality.py",
    "tools/release/validate_python_quality.py",
)
MAIN_GATES = (
    "Validate repository hygiene",
    "Require Node projection syntax and export smoke",
    "Run security tests directly",
    "Validate model routing profile",
    "Run neutrality scan",
    "Validate module and package architecture",
    "Validate workflow transition contract",
    "Validate standard-library runtime boundary",
    "Validate architecture complexity",
)
SUITE_STEPS = {
    "ci": (*MAIN_GATES, "Run stdlib tests", "Retain test timing evidence"),
    "foundation": ("Run foundation and neutrality negative tests",),
    "quality": (QUALITY_RUN, STRICT_MYPY, QUALITY_VALIDATE),
}
PATTERNS = {"ci": "test*.py", "foundation": "test_*.py", "quality": "test*.py"}
QUALITY_STEPS = ("runner", "strict-mypy", "validator")
CANDIDATE_PATH = Path("work/ci/reuse-candidate.json")


class ProofError(ValueError):
    """A bounded input is missing, inconsistent, or unsupported."""


class ProviderUnavailable(ProofError):
    """A provider read failed without establishing a proof mismatch."""


class ApplicabilityChanged(ProofError):
    """A well-formed original producer attempt no longer qualifies."""


class EnvironmentMismatch(ProofError):
    """A current cell could not reproduce the producer environment."""


def require(condition: Any, reason: str) -> None:
    if not condition:
        raise ProofError(reason)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_hex(value: Any, width: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{width}}}", value) is not None


def positive_id(value: Any) -> TypeGuard[int]:
    return type(value) is int and value > 0


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    def number(value: str) -> float:
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=number, parse_constant=number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProofError("invalid bounded JSON") from exc


def obj(value: Any, label: str, fields: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or (fields is not None and set(value) != fields):
        raise ProofError(f"invalid {label} object")
    return value


def read_bytes(path: Path, maximum: int = MAX_FILE) -> bytes:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, "evidence file is not ordinary")
    require(0 < metadata.st_size <= maximum, "evidence file size exceeded")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) == metadata.st_size, "evidence file size changed")
    return raw


def read_object(path: Path, maximum: int = MAX_FILE) -> dict[str, Any]:
    return obj(strict_json(read_bytes(path, maximum)), "file")


def write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def write_object(path: Path, body: dict[str, Any]) -> str:
    raw = json_bytes(body)
    write_bytes(path, raw)
    return sha256(raw)


def native_output(name: str, value: str) -> None:
    require("\n" not in value and "\r" not in value, "invalid job output")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def native_env(name: str, value: str) -> None:
    require("\n" not in value and "\r" not in value, "invalid job environment value")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def command_output(root: Path, argv: list[str]) -> str:
    return subprocess.check_output(argv, cwd=root, encoding="utf-8", timeout=20).strip()


def git(root: Path, *args: str) -> str:
    return command_output(root, ["git", *args])


def git_identity(root: Path, revision: str) -> dict[str, Any]:
    fields = git(root, "show", "-s", "--format=%H %T %P", revision).split()
    require(len(fields) >= 2 and all(is_hex(value, 40) for value in fields), "invalid checked Git source")
    return {"sha": fields[0], "tree": fields[1], "parents": fields[2:]}


def source(root: Path) -> dict[str, Any]:
    require(not git(root, "status", "--porcelain", "--untracked-files=no"), "tracked checkout is dirty")
    return {
        **git_identity(root, "HEAD"),
        "inputs": {name: sha256(read_bytes(root / name)) for name in COMMON_INPUTS},
    }


def release_source(root: Path, revision: str) -> dict[str, Any]:
    identity = git_identity(root, revision)
    inputs = {}
    for name in COMMON_INPUTS:
        blob = f"{revision}:{name}"
        size = int(git(root, "cat-file", "-s", blob))
        require(0 < size <= MAX_FILE, "release source input exceeds its bound")
        raw = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root, timeout=20)
        require(len(raw) == size, "release source blob size differs")
        inputs[name] = sha256(raw)
    return {**identity, "inputs": inputs}


def source_shape(value: Any) -> dict[str, Any]:
    checked = obj(value, "source", {"sha", "tree", "parents", "inputs"})
    require(is_hex(checked["sha"], 40) and is_hex(checked["tree"], 40), "invalid source SHA")
    parents = checked["parents"]
    require(isinstance(parents, list) and all(is_hex(value, 40) for value in parents), "invalid source parents")
    inputs = obj(checked["inputs"], "source inputs", set(COMMON_INPUTS))
    require(all(is_hex(value, 64) for value in inputs.values()), "invalid source input digest")
    return checked


def cell_key(role: str, cell: str) -> str:
    return f"{role}/{cell}"


def cells() -> dict[str, tuple[str, str, str]]:
    return {
        cell_key(role, f"{os_name}-py{version}"): (role, f"{os_name}-py{version}", name)
        for role in ROLES
        for os_name in (PLATFORMS if role == "ci" else ("ubuntu-latest",))
        for version in PYTHONS
        for name in (
            f"{os_name} / py{version}"
            if role == "ci"
            else f"foundation / py{version}"
            if role == "foundation"
            else f"Python quality / {version}",
        )
    }


CELLS = cells()


def is_windows315(role: str, cell: str) -> bool:
    return role == "ci" and cell == "windows-latest-py3.15"


def probe_name(key: str) -> str:
    return f"probe / {key}"


def cell_python(root: Path) -> Path:
    return root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def build_inputs(python: str) -> list[str]:
    return [
        "uv",
        "pip",
        "install",
        "--python",
        python,
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "-r",
        BUILD_REQUIREMENTS,
    ]


def prepare(root: Path, setup_python: str, role: str) -> None:
    outer = Path(setup_python)
    require(outer.is_absolute() and outer.is_file(), "invalid setup-python interpreter")
    require(outer.resolve() == Path(sys.executable).resolve(), "setup interpreter does not match invocation")
    venv = cell_python(root)
    require(not (root / ".venv").exists(), "cell environment must start absent")
    if role == "quality":
        subprocess.run(
            [setup_python, "-m", "pip", "install", "--disable-pip-version-check", "uv==0.12.5"], cwd=root, check=True
        )
    expected_uv = "0.12.5" if role == "quality" else "0.13.1"
    require(command_output(root, ["uv", "--version"]).split()[:2] == ["uv", expected_uv], "unexpected uv version")
    subprocess.run(
        ["uv", "sync", "--locked", "--group", "quality", "--python", setup_python, "--no-install-project"],
        cwd=root,
        check=True,
    )
    require(venv.is_file(), "sealed cell interpreter is absent")
    subprocess.run(build_inputs(str(venv)), cwd=root, check=True)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv), "--no-deps", "--no-build-isolation", "-e", "."],
        cwd=root,
        check=True,
    )
    scripts = venv.parent
    scripts_value = str(scripts)
    require(
        scripts.is_absolute() and "\n" not in scripts_value and "\r" not in scripts_value,
        "invalid sealed cell script directory",
    )
    console_script = scripts / ("agent-lifecycle.exe" if os.name == "nt" else "agent-lifecycle")
    require(console_script.is_file(), "sealed cell console script is absent")
    native_env("CELL_VENV_PYTHON", str(venv))
    with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as stream:
        stream.write(scripts_value + "\n")


def env_snapshot(root: Path, role: str, cell: str) -> dict[str, Any]:
    image = {key: os.environ.get(key) for key in ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH")}
    expected_os = "Windows" if cell.startswith("windows-") else "macOS" if cell.startswith("macos-") else "Linux"
    require(all(image.values()) and image["RUNNER_OS"] == expected_os, "required runner image facts unavailable")
    require(Path(sys.executable).absolute() == cell_python(root), "unexpected effective cell interpreter")
    require(platform.python_version().startswith(cell.split("-py")[-1] + "."), "unexpected Python cell")
    require(Path(sys.prefix).resolve() == (root / ".venv").resolve(), "unexpected interpreter prefix")
    dependencies = sorted(
        (dist.metadata["Name"].lower().replace("_", "-"), dist.version)
        for dist in importlib.metadata.distributions(path=[str(path) for path in _venv_site_paths(root)])
    )
    require(
        len(dependencies) == len(dict(dependencies)) and all(all(row) for row in dependencies),
        "ambiguous cell dependency inventory",
    )
    pinned = {"setuptools": "84.2.1", "wheel": "0.48.0", "packaging": "26.3"}
    pinned.update(obj(read_object(root / POLICY).get("toolchain"), "toolchain"))
    require(
        all(dict(dependencies).get(name) == version for name, version in pinned.items()),
        "installed quality or build input differs from policy",
    )
    uv = command_output(root, ["uv", "--version"])
    require(uv.split()[:2] == ["uv", "0.12.5" if role == "quality" else "0.13.1"], "unexpected effective uv")
    tools = {"git": git(root, "--version"), "uv": uv}
    if role in {"ci", "main"}:
        tools["node"] = command_output(root, ["node", "--version"])
    if is_windows315(role, cell):
        backend = Path(os.environ.get("ALK_ACCOUNTING_GIT_EXECUTABLE", ""))
        require(backend.is_absolute() and backend.is_file() and not backend.is_symlink(), "accounting Git unavailable")
        tools["accountingGit"] = sha256(backend.read_bytes())
    return {
        "image": image,
        "architecture": platform.machine(),
        "system": platform.system(),
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "interpreterSha256": sha256(Path(getattr(sys, "_base_executable", None) or sys.executable).read_bytes()),
        "dependencyInventorySha256": sha256(json_bytes(dependencies)),
        "dependencies": dict(dependencies),
        "tools": tools,
        "permissions": {"contents": "read"},
    }


def _venv_site_paths(root: Path) -> list[Path]:
    venv = root / ".venv"
    if os.name == "nt":
        return [venv / "Lib/site-packages"]
    return list(venv.glob("lib/python*/site-packages"))


def observed_environment(root: Path, role: str, cell: str) -> dict[str, Any]:
    try:
        snapshot = env_snapshot(root, role, cell)
        return {"status": "OBSERVED", "sha256": sha256(json_bytes(snapshot)), "inputs": snapshot}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)[:160]}


def observed_matches(observation: dict[str, Any], expected: str) -> bool:
    return observation.get("status") == "OBSERVED" and observation.get("sha256") == expected


def invocation(event: str) -> dict[str, Any]:
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    repository = os.environ.get("GITHUB_REPOSITORY_ID", "")
    head = os.environ.get("GITHUB_SHA")
    require(
        all(
            value.isascii() and value.isdecimal() and len(value) <= 18 and int(value) > 0
            for value in (run, attempt, repository)
        ),
        "invalid native invocation identity",
    )
    require(
        os.environ.get("GITHUB_EVENT_NAME") == event and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
        "unexpected CI event or repository",
    )
    require(is_hex(head, 40), "invalid invocation SHA")
    return {"run": int(run), "attempt": int(attempt), "repository": int(repository), "sha": head}


def main_context(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    run = invocation("push")
    checked = source(root)
    require(
        os.environ.get("GITHUB_REF") == MAIN_REF and run["sha"] == checked["sha"],
        "expected an exact push-main checkout",
    )
    return run, checked


def pr_context() -> dict[str, Any]:
    event = read_object(Path(os.environ["GITHUB_EVENT_PATH"]))
    pull = obj(event.get("pull_request"), "pull request event")
    base, head = obj(pull.get("base"), "PR base"), obj(pull.get("head"), "PR head")
    author = obj(pull.get("user"), "PR author")
    number = event.get("number")
    require(
        positive_id(number)
        and pull.get("number") == number
        and is_hex(base.get("sha"), 40)
        and is_hex(head.get("sha"), 40),
        "invalid PR event inputs",
    )
    require(os.environ.get("GITHUB_REF") == f"refs/pull/{number}/merge", "unexpected PR merge ref")
    return {
        "number": number,
        "base": base["sha"],
        "head": head["sha"],
        "baseRepo": obj(base.get("repo"), "PR base repo").get("id"),
        "headRepo": obj(head.get("repo"), "PR head repo").get("id"),
        "author": author.get("id"),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "triggeringActor": os.environ.get("GITHUB_TRIGGERING_ACTOR"),
    }


def utc_time(value: Any) -> datetime:
    require(isinstance(value, str) and len(value) <= 40, "missing provider timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProofError("invalid provider timestamp") from exc
    require(parsed.tzinfo is not None, "provider timestamp has no timezone")
    return parsed


def fresh(value: Any, now: datetime) -> bool:
    return now - MAX_AGE <= utc_time(value) <= now


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class GitHub:
    """A single bounded, non-redirecting client for provider reads and archive bytes."""

    def __init__(self, repository: str, token: str, *, now: datetime | None = None) -> None:
        require(repository == REPOSITORY and bool(token), "provider repository or read token unavailable")
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token
        self.now = now or datetime.now(UTC)
        self.deadline = time.monotonic() + 180
        self.auth_requests = 0
        self.total_requests = 0
        self.input_bytes = 0
        self.opener = urllib.request.build_opener(_NoRedirect)

    def _request(self, url: str, *, authenticated: bool) -> Any:
        self.total_requests += 1
        self.auth_requests += int(authenticated)
        require(self.total_requests <= 80 and self.auth_requests <= 48, "provider request budget exceeded")
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "provider verification deadline exceeded")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        return self.opener.open(urllib.request.Request(url, headers=headers), timeout=min(10, remaining))

    def _read(self, response: Any, maximum: int) -> bytes:
        maximum = min(maximum, MAX_TOTAL - self.input_bytes)
        result = bytearray()
        while True:
            require(time.monotonic() < self.deadline, "provider read deadline exceeded")
            chunk = response.read1(min(65536, maximum + 1 - len(result)))
            if not chunk:
                return bytes(result)
            require(len(result) + len(chunk) <= maximum, "provider response exceeds its byte budget")
            self.input_bytes += len(chunk)
            result.extend(chunk)

    def json(self, path: str) -> Any:
        try:
            with self._request(self.base + path, authenticated=True) as response:
                return strict_json(self._read(response, MAX_FILE))
        except (OSError, http.client.HTTPException) as exc:
            raise ProviderUnavailable(
                f"provider JSON unavailable ({getattr(exc, 'code', type(exc).__name__)})"
            ) from exc

    def archive(self, artifact: dict[str, Any], expected: set[str]) -> dict[str, bytes]:
        url = f"{self.base}/actions/artifacts/{artifact['id']}/zip"
        require(artifact.get("archive_download_url") == url, "unexpected archive API origin")
        try:
            raw = self._download_archive(url)
        except (OSError, http.client.HTTPException) as exc:
            raise ProviderUnavailable(f"archive unavailable ({getattr(exc, 'code', type(exc).__name__)})") from exc
        require(
            len(raw) == artifact["size_in_bytes"] and "sha256:" + sha256(raw) == artifact.get("digest"),
            "server archive size or digest mismatch",
        )
        members = archive_members(raw, expected, MAX_TOTAL - self.input_bytes)
        self.input_bytes += sum(map(len, members.values()))
        return members

    def _download_archive(self, url: str) -> bytes:
        try:
            with self._request(url, authenticated=True) as response:
                return self._read(response, MAX_FILE)
        except urllib.error.HTTPError as exc:
            with exc:
                if exc.code != 302:
                    raise ProviderUnavailable(f"archive redirect unavailable ({exc.code})") from exc
                location = exc.headers.get("Location")
        if location is None:
            raise ProofError("archive storage redirect missing")
        storage_url(location)
        with self._request(location, authenticated=False) as response:
            return self._read(response, MAX_FILE)


def storage_url(value: str) -> None:
    url = urllib.parse.urlsplit(value)
    host = url.hostname or ""
    allowed = re.fullmatch(r"productionresultssa[a-z0-9]+\.blob\.core\.windows\.net", host) or host in {
        "pipelines.actions.githubusercontent.com",
        "results-receiver.actions.githubusercontent.com",
    }
    require(
        url.scheme == "https" and allowed and url.netloc == host and not url.fragment and bool(url.path),
        "unexpected archive storage origin",
    )


def archive_members(raw: bytes, expected: set[str], available: int) -> dict[str, bytes]:
    try:
        # Check the end record before ZipFile allocates central directory entries.
        end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
        require(0 <= end <= len(raw) - 22, "missing bounded ZIP end record")
        _, disk, central_disk, disk_rows, rows, size, offset, comment = struct.unpack_from("<4s4H2LH", raw, end)
        require(
            disk == central_disk == 0
            and disk_rows == rows == len(expected) <= 64
            and offset + size == end
            and end + 22 + comment == len(raw),
            "invalid ZIP directory bounds",
        )
        cursor = offset
        for _ in range(rows):
            require(
                cursor + 46 <= end and raw[cursor : cursor + 4] == b"PK\x01\x02",
                "invalid ZIP central directory entry",
            )
            name_size, extra_size, comment_size = struct.unpack_from("<3H", raw, cursor + 28)
            cursor += 46 + name_size + extra_size + comment_size
        require(cursor == end, "ZIP directory count does not match its entries")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows = archive.infolist()
            require(
                0 < len(rows) <= 64 and len(rows) == len(expected) and {row.filename for row in rows} == expected,
                "unexpected archive member inventory",
            )
            require(sum(row.file_size for row in rows) <= available, "aggregate archive member budget exceeded")
            members: dict[str, bytes] = {}
            for row in rows:
                kind = stat.S_IFMT(row.external_attr >> 16)
                require(
                    row.orig_filename == row.filename
                    and not row.is_dir()
                    and kind in {0, stat.S_IFREG}
                    and not row.flag_bits & 1
                    and 0 < row.file_size <= MAX_FILE,
                    "archive member is not ordinary bounded JSON",
                )
                with archive.open(row) as stream:
                    data = stream.read(MAX_FILE + 1)
                require(len(data) == row.file_size, "archive member size differs")
                strict_json(data)
                members[row.filename] = data
            return members
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError) as exc:
        raise ProofError("invalid archive") from exc


def provider_rows(payload: Any, name: str) -> list[dict[str, Any]]:
    envelope = obj(payload, name)
    rows = envelope.get(name)
    require(
        isinstance(rows, list) and len(rows) <= 100 and envelope.get("total_count") == len(rows),
        f"incomplete provider {name}",
    )
    return [obj(row, name) for row in cast(list[Any], rows)]


def only(rows: list[Any], label: str) -> Any:
    require(len(rows) == 1, f"missing or ambiguous {label}")
    return rows[0]


def workflow_id(api: GitHub, filename: str, name: str) -> int:
    workflow = obj(api.json(f"/actions/workflows/{filename}"), "workflow")
    identifier = workflow.get("id")
    require(
        positive_id(identifier)
        and workflow.get("path") == f".github/workflows/{filename}"
        and workflow.get("name") == name
        and workflow.get("state") == "active",
        "unexpected workflow identity",
    )
    return cast(int, identifier)


def provider_run(
    run: dict[str, Any],
    *,
    workflow: int,
    path: str,
    event: str,
    head: str,
    repository: int,
    run_id: int,
    attempt: int,
    completed: bool = True,
) -> None:
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("workflow_id") == workflow
        and run.get("event") == event
        and run.get("path") == path
        and run.get("head_sha") == head
        and obj(run.get("repository"), "run repository").get("id") == repository
        and obj(run.get("head_repository"), "run head repository").get("id") == repository,
        "provider run identity differs",
    )
    if completed:
        require(run.get("status") == "completed" and run.get("conclusion") == "success", "run attempt did not pass")


def provider_jobs(api: GitHub, run: int, attempt: int) -> dict[str, dict[str, Any]]:
    endpoint = f"/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100"
    rows = provider_rows(api.json(endpoint), "jobs")
    jobs: dict[str, dict[str, Any]] = {}
    ids: set[int] = set()
    for row in rows:
        name, identifier = row.get("name"), row.get("id")
        require(
            isinstance(name, str) and name not in jobs and positive_id(identifier) and identifier not in ids,
            "duplicate or invalid job identity",
        )
        require(row.get("run_id") == run and row.get("run_attempt") == attempt, "cross-attempt job")
        require(row.get("check_run_url") == f"{api.base}/check-runs/{identifier}", "unexpected Actions check identity")
        jobs[cast(str, name)] = row
        ids.add(cast(int, identifier))
    return jobs


def job_step(job: dict[str, Any], name: str, conclusion: str = "success") -> dict[str, Any]:
    steps = job.get("steps")
    require(isinstance(steps, list) and len(steps) <= 100, "missing bounded provider steps")
    selected = only([step for step in cast(list[Any], steps) if obj(step, "step").get("name") == name], name)
    require(
        selected.get("status") == "completed"
        and selected.get("conclusion") == conclusion
        and positive_id(selected.get("number")),
        f"provider step did not report {conclusion}: {name}",
    )
    return obj(selected, "step")


def successful_job(jobs: dict[str, dict[str, Any]], name: str, head: str) -> dict[str, Any]:
    job = obj(jobs.get(name), "job")
    require(
        job.get("head_sha") == head and job.get("status") == "completed" and job.get("conclusion") == "success",
        f"expected successful job: {name}",
    )
    return job


def suite_job(jobs: dict[str, dict[str, Any]], role: str, cell: str, name: str, head: str) -> dict[str, Any]:
    job = successful_job(jobs, name, head)
    for step in (PREPARE, "Restore versioned release test fixture", *SUITE_STEPS[role], RECORD, CELL_UPLOAD):
        job_step(job, step)
    if is_windows315(role, cell):
        job_step(job, BACKEND)
        job_step(job, BACKEND_AFTER)
    return job


def artifact_rows(api: GitHub, run: int) -> dict[str, dict[str, Any]]:
    rows = provider_rows(api.json(f"/actions/runs/{run}/artifacts?per_page=100"), "artifacts")
    artifacts: dict[str, dict[str, Any]] = {}
    ids: set[int] = set()
    for row in rows:
        name, identifier = row.get("name"), row.get("id")
        require(
            isinstance(name, str) and name not in artifacts and positive_id(identifier) and identifier not in ids,
            "duplicate or invalid artifact identity",
        )
        artifacts[cast(str, name)] = row
        ids.add(cast(int, identifier))
    return artifacts


def joined_artifact(
    artifacts: dict[str, dict[str, Any]],
    name: str,
    job: dict[str, Any],
    upload: str,
    *,
    run: int,
    repository: int,
    head: str,
    now: datetime,
    optional_upload: bool = False,
) -> dict[str, Any]:
    row = obj(artifacts.get(name), "artifact")
    identity = obj(row.get("workflow_run"), "artifact run")
    size, digest = row.get("size_in_bytes"), row.get("digest")
    require(
        row.get("name") == name
        and row.get("expired") is False
        and positive_id(size)
        and size <= MAX_FILE
        and isinstance(digest, str)
        and digest.startswith("sha256:")
        and is_hex(digest[7:], 64)
        and identity.get("id") == run
        and identity.get("repository_id") == repository
        and identity.get("head_repository_id") == repository
        and identity.get("head_sha") == head
        and row.get("job_id") in {None, job["id"]}
        and identity.get("job_id") in {None, job["id"]},
        "artifact metadata identity differs",
    )
    if optional_upload:
        steps = job.get("steps")
        require(isinstance(steps, list), "upload steps unavailable")
        step = only(
            [
                obj(step, "upload step")
                for step in cast(list[Any], steps)
                if obj(step, "upload step").get("name") == upload
            ],
            upload,
        )
        require(
            step.get("status") == "completed" and step.get("conclusion") in {"success", "failure"},
            "optional upload did not complete",
        )
    else:
        step = job_step(job, upload)
    created = utc_time(row.get("created_at"))
    require(
        fresh(row.get("created_at"), now)
        and utc_time(row.get("expires_at")) > now
        and utc_time(step.get("started_at")) <= created <= utc_time(step.get("completed_at")),
        "artifact is stale or outside its upload step",
    )
    return row


def artifact_name(prefix: str, run: int, attempt: int, key: str | None = None) -> str:
    suffix = "-" + key.replace("/", "-") if key else ""
    return f"alk-{prefix}-{run}-{attempt}{suffix}"


def inventory_report(raw: bytes, role: str, run: dict[str, Any]) -> dict[str, Any]:
    timing = obj(strict_json(raw), "test timing")
    facts = obj(timing.get("environment"), "test invocation")
    coverage = obj(timing.get("coverage"), "timing completeness")
    discovered = timing.get("inventory")
    cases = timing.get("cases")
    unstarted = coverage.get("notStarted")
    require(
        timing.get("schemaVersion") == "alk-ci-test-timings.v1"
        and timing.get("status") == "PASS"
        and timing.get("discovery") == {"start": "tests", "top": ".", "pattern": PATTERNS[role]}
        and timing.get("interrupted") is None
        and timing.get("loaderErrors") == []
        and timing.get("failures") == timing.get("errors") == timing.get("unexpectedSuccesses") == 0
        and facts.get("GITHUB_SHA") == run["sha"]
        and facts.get("GITHUB_RUN_ID") == str(run["run"])
        and facts.get("GITHUB_RUN_ATTEMPT") == str(run["attempt"])
        and facts.get("GITHUB_JOB") == JOB_IDS[role]
        and coverage.get("complete") is True
        and coverage.get("unexpectedIds") == []
        and isinstance(discovered, list)
        and 0 < len(discovered) <= 20000
        and isinstance(cases, list)
        and len(cases) == timing.get("testsRun")
        and isinstance(unstarted, list)
        and len(cases) + len(unstarted) == len(discovered),
        "test report did not prove complete successful discovery",
    )
    inventory = [obj(item, "discovered test").get("id") for item in cast(list[Any], discovered)]
    executed = [obj(item, "executed test") for item in cast(list[Any], cases)]
    skipped = [obj(item, "fixture skip") for item in cast(list[Any], unstarted)]
    require(
        all(isinstance(test, str) and 0 < len(test) <= 500 for test in inventory)
        and all(item.get("completed") is True and isinstance(item.get("id"), str) for item in executed)
        and all(item.get("reason") == "fixtureSkip" and isinstance(item.get("id"), str) for item in skipped)
        and Counter(inventory) == Counter(item["id"] for item in (*executed, *skipped)),
        "test roster differs from actual successful invocation",
    )
    return {
        "schemaVersion": "alk-ci-suite-inventory.v1",
        "status": "PASS",
        "discovery": timing["discovery"],
        "inventory": inventory,
        "testsRun": len(executed),
        "fixtureSkipped": [item["id"] for item in skipped],
        "skips": timing.get("skips"),
        "startedAt": timing.get("startedAtUtc"),
        "wallSeconds": timing.get("wallSeconds"),
        "timingSha256": sha256(raw),
    }


def verify_inventory(raw: bytes, role: str, step: dict[str, Any]) -> dict[str, Any]:
    report = obj(
        strict_json(raw),
        "suite inventory",
        {
            "schemaVersion",
            "status",
            "discovery",
            "inventory",
            "testsRun",
            "fixtureSkipped",
            "skips",
            "startedAt",
            "wallSeconds",
            "timingSha256",
        },
    )
    names, skipped = report["inventory"], report["fixtureSkipped"]
    require(
        report["schemaVersion"] == "alk-ci-suite-inventory.v1"
        and report["status"] == "PASS"
        and report["discovery"] == {"start": "tests", "top": ".", "pattern": PATTERNS[role]}
        and isinstance(names, list)
        and 0 < len(names) <= 20000
        and isinstance(skipped, list)
        and len(skipped) <= len(names)
        and all(isinstance(name, str) and 0 < len(name) <= 500 for name in (*names, *skipped))
        and not (Counter(skipped) - Counter(names))
        and positive_id(report["testsRun"])
        and report["testsRun"] + len(skipped) == len(names)
        and type(report["skips"]) is int
        and 0 <= report["skips"] <= len(names)
        and type(report["wallSeconds"]) in {int, float}
        and 0 <= report["wallSeconds"] <= 21600
        and is_hex(report["timingSha256"], 64),
        "suite inventory is incomplete",
    )
    # Provider timestamps have second precision, while the test runner records microseconds.
    started = utc_time(report["startedAt"])
    require(
        utc_time(step["started_at"]) <= started < utc_time(step["completed_at"]) + timedelta(seconds=1),
        "suite timing is outside its job step",
    )
    return report


def release_digest(body: dict[str, Any], field: str) -> bool:
    return body.get(field) == sha256(
        json.dumps(
            {key: value for key, value in body.items() if key != field},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def quality_members(root: Path, timing_path: Path, base: str) -> tuple[bytes, dict[str, str]]:
    run_raw = read_bytes(root / "work/python-quality/run.json")
    validation_raw = read_bytes(root / "work/python-quality/validation.json")
    run, validation = obj(strict_json(run_raw), "quality run"), obj(strict_json(validation_raw), "quality validation")
    require(
        run.get("schemaVersion") == "agent-python-quality-run.v1"
        and run.get("status") == "PASS"
        and run.get("sourceRevision") == base
        and "qualifiedCoverage" not in run
        and release_digest(run, "runDigest")
        and validation.get("status") == "PASS"
        and release_digest(validation, "validationDigest")
        and validation.get("runDigest") == run.get("runDigest"),
        "fresh quality validation does not match its invocation",
    )
    commands = run.get("commands")
    require(
        isinstance(commands, list) and all(obj(row, "quality command").get("status") == "PASS" for row in commands),
        "quality commands were incomplete",
    )
    ids = [row.get("id") for row in cast(list[Any], commands)]
    require(ids.count("coverage") == ids.count("coverage-json") == 1, "fresh coverage commands are missing")
    directory = (root / str(run.get("runDirectory"))).resolve()
    require(
        directory.parent == (root / "work/python-quality/raw").resolve()
        and timing_path.resolve() == directory / "test-timings.json",
        "quality timing is outside its invocation",
    )
    require(
        obj(run.get("artifacts"), "quality artifacts").get("coverage")
        == (directory / "coverage.json").relative_to(root).as_posix(),
        "quality coverage JSON is outside its invocation",
    )
    coverage = read_bytes(directory / "coverage.json")
    obj(strict_json(coverage), "coverage JSON")
    return coverage, {"runSha256": sha256(run_raw), "validationSha256": sha256(validation_raw)}


def record_suite(root: Path, role: str, cell: str, timing: Path | None, out: Path) -> None:
    key = cell_key(role, cell)
    require(key in CELLS and os.environ.get("GITHUB_JOB") == JOB_IDS[role], "unexpected suite identity")
    event = os.environ.get("GITHUB_EVENT_NAME")
    require(event in {"pull_request", "push", "workflow_dispatch"}, "unsupported suite event")
    run = invocation(str(event))
    checked = source(root)
    require(run["sha"] == checked["sha"], "suite checkout differs from invocation")
    pr = pr_context() if event == "pull_request" else None
    if pr is None:
        require(os.environ.get("GITHUB_REF") == MAIN_REF, "full fallback must use main")
    if event == "workflow_dispatch":
        control_context(root)
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF")
    require(workflow_ref == f"{REPOSITORY}/{WORKFLOW}@{os.environ['GITHUB_REF']}", "suite workflow ref differs")
    workflow_sha = os.environ.get("GITHUB_WORKFLOW_SHA")
    require(is_hex(workflow_sha, 40), "suite workflow SHA unavailable")
    members: dict[str, bytes] = {}
    quality = None
    if role == "quality":
        run_receipt = read_object(root / "work/python-quality/run.json")
        timing = root / str(run_receipt.get("runDirectory")) / "test-timings.json"
        coverage, quality = quality_members(root, timing, pr["base"] if pr else run["sha"])
        members["coverage.json"] = coverage
    require(timing is not None, "suite timing path required")
    assert timing is not None
    members["tests.json"] = json_bytes(inventory_report(read_bytes(timing), role, run))
    receipt = {
        "schemaVersion": "alk-ci-cell-evidence.v1",
        "status": "PASS",
        "role": role,
        "cell": cell,
        "job": JOB_IDS[role],
        "invocation": run,
        "event": event,
        "pr": pr,
        "source": checked,
        "workflowRef": workflow_ref,
        "workflowSha": workflow_sha,
        "environment": observed_environment(root, role, cell),
        "members": {name: sha256(raw) for name, raw in members.items()},
        "quality": quality,
    }
    for name, raw in members.items():
        write_bytes(out.parent / name, raw)
    write_object(out, receipt)


def repository_identity(api: GitHub, repository: int) -> None:
    repo = obj(api.json(""), "repository")
    require(
        repo.get("id") == repository
        and repo.get("full_name") == REPOSITORY
        and repo.get("default_branch") == "main"
        and repo.get("fork") is False,
        "repository identity differs",
    )


def trusted_pr(api: GitHub, checked: dict[str, Any], repository: int) -> dict[str, Any]:
    associated = api.json(f"/commits/{checked['sha']}/pulls?per_page=100")
    require(isinstance(associated, list) and len(associated) == 1, "missing or ambiguous merged PR association")
    association = obj(associated[0], "associated PR")
    number = association.get("number")
    require(positive_id(number) and association.get("merge_commit_sha") == checked["sha"], "merge association differs")
    pull = obj(api.json(f"/pulls/{number}"), "merged PR")
    base, head = obj(pull.get("base"), "PR base"), obj(pull.get("head"), "PR head")
    base_repo = obj(base.get("repo"), "PR base repo")
    head_repo = obj(head.get("repo"), "PR head repo")
    actor = obj(pull.get("user"), "PR author")
    login = actor.get("login")
    require(
        pull.get("number") == number
        and pull.get("merged") is True
        and pull.get("state") == "closed"
        and pull.get("merge_commit_sha") == checked["sha"]
        and fresh(pull.get("merged_at"), api.now)
        and base.get("ref") == "main"
        and base_repo.get("id") == head_repo.get("id") == repository
        and base_repo.get("full_name") == head_repo.get("full_name") == REPOSITORY
        and head_repo.get("fork") is False
        and is_hex(base.get("sha"), 40)
        and is_hex(head.get("sha"), 40)
        and base["sha"] != head["sha"]
        and checked["parents"] in ([base["sha"]], [base["sha"], head["sha"]])
        and actor.get("type") == "User"
        and positive_id(actor.get("id"))
        and isinstance(login, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login)
        and login.lower() != "dependabot"
        and pull.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"},
        "unsupported, stale or untrusted merged PR",
    )
    permission = obj(api.json(f"/collaborators/{login}/permission"), "collaborator permission")
    permission_user = obj(permission.get("user"), "collaborator")
    require(
        permission.get("permission") in {"write", "maintain", "admin"}
        and permission_user.get("login") == login
        and permission_user.get("id") == actor["id"]
        and permission_user.get("type") == "User",
        "PR author write access unproved",
    )
    return {
        "number": number,
        "base": base["sha"],
        "head": head["sha"],
        "baseRepo": repository,
        "headRepo": repository,
        "author": actor["id"],
        "actor": login,
        "triggeringActor": login,
    }


def run_actor(run: dict[str, Any], pull: dict[str, Any]) -> None:
    for key in ("actor", "triggering_actor"):
        actor = obj(run.get(key), key)
        require(
            actor.get("login") == pull["actor"] and actor.get("id") == pull["author"] and actor.get("type") == "User",
            "PR run actor differs from trusted author",
        )


def pr_attempt(api: GitHub, workflow: int, pull: dict[str, Any], repository: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"event": "pull_request", "head_sha": pull["head"], "per_page": 100})
    listed = only(provider_rows(api.json(f"/actions/workflows/{workflow}/runs?{query}"), "workflow_runs"), "PR run")
    identifier, attempt = listed.get("id"), listed.get("run_attempt")
    require(positive_id(identifier) and positive_id(attempt), "invalid PR run or attempt")
    checked = obj(api.json(f"/actions/runs/{identifier}/attempts/{attempt}"), "PR attempt")
    for run in (listed, checked):
        provider_run(
            run,
            workflow=workflow,
            path=WORKFLOW,
            event="pull_request",
            head=pull["head"],
            repository=repository,
            run_id=identifier,
            attempt=attempt,
        )
        require(fresh(run.get("updated_at"), api.now), "stale PR run")
        run_actor(run, pull)
        associations = run.get("pull_requests")
        require(isinstance(associations, list) and len(associations) <= 1, "ambiguous PR run association")
        if associations:
            association = obj(associations[0], "run PR association")
            head = obj(association.get("head"), "associated head")
            base = obj(association.get("base"), "associated base")
            require(
                association.get("number") == pull["number"]
                and head.get("sha") == pull["head"]
                and base.get("sha") == pull["base"]
                and obj(head.get("repo"), "associated head repository").get("id") == repository
                and obj(base.get("repo"), "associated base repository").get("id") == repository,
                "PR run association disagrees",
            )
    return {"run": identifier, "attempt": attempt, "workflow": workflow, "head": pull["head"], "number": pull["number"]}


def verify_pr_checkout(api: GitHub, checked: dict[str, Any], candidate: dict[str, Any], pull: dict[str, Any]) -> None:
    commit = obj(api.json(f"/git/commits/{candidate['sha']}"), "PR checkout commit")
    parents = commit.get("parents")
    require(
        commit.get("sha") == candidate["sha"]
        and obj(commit.get("tree"), "PR checkout tree").get("sha") == checked["tree"]
        and isinstance(parents, list)
        and len(parents) == 2
        and [obj(parent, "PR checkout parent").get("sha") for parent in parents] == [pull["base"], pull["head"]]
        and candidate["parents"] == [pull["base"], pull["head"]]
        and candidate["tree"] == checked["tree"]
        and candidate["inputs"] == checked["inputs"],
        "synthetic PR checkout, tested tree or locked inputs differ",
    )


def verify_observation(value: Any, *, available: bool) -> dict[str, Any]:
    observation = obj(value, "observed environment")
    if not available and observation.get("status") == "UNAVAILABLE":
        return obj(observation, "unavailable environment", {"status", "reason"})
    observation = obj(observation, "observed environment", {"status", "inputs", "sha256"})
    require(
        observation["status"] == "OBSERVED"
        and is_hex(observation["sha256"], 64)
        and sha256(json_bytes(observation["inputs"])) == observation["sha256"],
        "environment identity unavailable",
    )
    inputs = obj(
        observation["inputs"],
        "environment inputs",
        {
            "image",
            "architecture",
            "system",
            "python",
            "implementation",
            "interpreterSha256",
            "dependencyInventorySha256",
            "dependencies",
            "tools",
            "permissions",
        },
    )
    require(inputs["permissions"] == {"contents": "read"}, "cell workload permissions differ")
    require(
        all(inputs[key] for key in ("architecture", "system", "python", "implementation"))
        and is_hex(inputs["interpreterSha256"], 64)
        and is_hex(inputs["dependencyInventorySha256"], 64),
        "environment inventory incomplete",
    )
    image = obj(inputs["image"], "image inputs", {"ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH"})
    require(all(isinstance(fact, str) and fact for fact in image.values()), "runner image facts missing")
    dependencies = obj(inputs["dependencies"], "dependency inventory")
    require(
        bool(dependencies)
        and all(isinstance(version, str) and version for version in dependencies.values())
        and sha256(json_bytes(sorted(dependencies.items()))) == inputs["dependencyInventorySha256"],
        "installed dependency inventory differs",
    )
    tools = obj(inputs["tools"], "effective tools")
    require(
        all(isinstance(version, str) and version for version in tools.values()) and {"git", "uv"} <= set(tools),
        "effective tools unavailable",
    )
    return observation


def cell_evidence(
    members: dict[str, bytes],
    key: str,
    pr: dict[str, Any],
    pull: dict[str, Any],
    main: dict[str, Any],
    job: dict[str, Any],
    artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    role, cell, _ = CELLS[key]
    receipt = obj(
        strict_json(members["cell-evidence.json"]),
        "cell evidence",
        {
            "schemaVersion",
            "status",
            "role",
            "cell",
            "job",
            "invocation",
            "event",
            "pr",
            "source",
            "workflowRef",
            "workflowSha",
            "environment",
            "members",
            "quality",
        },
    )
    tested = source_shape(receipt["source"])
    expected_members = {name: sha256(raw) for name, raw in members.items() if name != "cell-evidence.json"}
    require(
        receipt["schemaVersion"] == "alk-ci-cell-evidence.v1"
        and receipt["status"] == "PASS"
        and receipt["role"] == role
        and receipt["cell"] == cell
        and receipt["job"] == JOB_IDS[role]
        and receipt["event"] == "pull_request"
        and receipt["pr"] == pull
        and receipt["invocation"]
        == {"run": pr["run"], "attempt": pr["attempt"], "repository": main["repository"], "sha": tested["sha"]}
        and receipt["workflowRef"] == f"{REPOSITORY}/{WORKFLOW}@refs/pull/{pull['number']}/merge"
        and receipt["workflowSha"] == tested["sha"]
        and receipt["members"] == expected_members,
        "cell evidence or member hashes differ",
    )
    observation = verify_observation(receipt["environment"], available=True)
    step_name = {"ci": "Run stdlib tests", "foundation": SUITE_STEPS["foundation"][0], "quality": QUALITY_RUN}[role]
    tests = verify_inventory(members["tests.json"], role, job_step(job, step_name))
    quality = receipt["quality"]
    if role == "quality":
        quality = obj(quality, "producer quality proof", {"runSha256", "validationSha256"})
        require(all(is_hex(digest, 64) for digest in quality.values()), "quality proof hashes invalid")
        obj(strict_json(members["coverage.json"]), "coverage JSON")
    else:
        require(quality is None, "unexpected producer quality receipt")
    return tested, {
        "job": job["id"],
        "artifact": artifact["id"],
        "archiveSha256": artifact["digest"][7:],
        "receiptSha256": sha256(members["cell-evidence.json"]),
        "testsSha256": expected_members["tests.json"],
        "testsRun": tests["testsRun"],
        "environmentSha256": observation["sha256"],
        "coverageSha256": expected_members.get("coverage.json"),
        "quality": quality,
    }


def recheck_pr(api: GitHub, pr: dict[str, Any], repository: int) -> None:
    current = obj(api.json(f"/actions/runs/{pr['run']}"), "current PR run")
    current_attempt = current.get("run_attempt")
    require(positive_id(current_attempt), "invalid current PR attempt")
    provider_run(
        current,
        workflow=pr["workflow"],
        path=WORKFLOW,
        event="pull_request",
        head=pr["head"],
        repository=repository,
        run_id=pr["run"],
        attempt=cast(int, current_attempt),
        completed=False,
    )
    status, conclusion = current.get("status"), current.get("conclusion")
    require(
        status in {"queued", "in_progress", "completed", "waiting", "pending", "requested"}
        and (conclusion is None or isinstance(conclusion, str)),
        "invalid current PR status",
    )
    updated = utc_time(current.get("updated_at"))
    if (
        current_attempt != pr["attempt"]
        or status != "completed"
        or conclusion != "success"
        or not api.now - MAX_AGE <= updated <= api.now
    ):
        raise ApplicabilityChanged("current PR attempt no longer qualifies")


def find_candidate(
    api: GitHub, main: dict[str, Any], checked: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bytes]]:
    repository = main["repository"]
    repository_identity(api, repository)
    pull = trusted_pr(api, checked, repository)
    workflow = workflow_id(api, "ci.yml", "ci")
    pr = pr_attempt(api, workflow, pull, repository)
    jobs = provider_jobs(api, pr["run"], pr["attempt"])
    artifacts = artifact_rows(api, pr["run"])
    require(
        {name for name, job in jobs.items() if job.get("conclusion") == "success"}
        == {name for _, _, name in CELLS.values()},
        "PR successful job inventory is incomplete or unexpected",
    )
    rows: dict[str, Any] = {}
    coverages: dict[str, bytes] = {}
    tested = None
    for key, (role, cell, name) in CELLS.items():
        job = suite_job(jobs, role, cell, name, pr["head"])
        artifact = joined_artifact(
            artifacts,
            artifact_name("pr-ci", pr["run"], pr["attempt"], key),
            job,
            CELL_UPLOAD,
            run=pr["run"],
            repository=repository,
            head=pr["head"],
            now=api.now,
        )
        expected = {"cell-evidence.json", "tests.json"}
        if role == "quality":
            expected.add("coverage.json")
        members = api.archive(artifact, expected)
        checkout, rows[key] = cell_evidence(members, key, pr, pull, main, job, artifact)
        if tested is None:
            verify_pr_checkout(api, checked, checkout, pull)
            tested = checkout
        require(tested == checkout, "PR cells do not share the exact checkout")
        if role == "quality":
            coverages[key] = members["coverage.json"]
    recheck_pr(api, pr, repository)
    require(api.auth_requests <= 40 and api.total_requests <= 65, "positive provider budget exceeded")
    return {
        "status": "CANDIDATE",
        "pr": pr,
        "tested": tested,
        "cells": rows,
        "provider": {"authenticated": api.auth_requests, "total": api.total_requests},
    }, coverages


def candidate(root: Path, repository: str, main_sha: str, out: Path) -> None:
    main, checked = main_context(root)
    require(main_sha == checked["sha"] and repository == REPOSITORY, "candidate invocation source differs")
    try:
        api = GitHub(repository, os.environ.get("GH_TOKEN", ""))
        proof, _coverages = find_candidate(api, main, checked)
    except ProofError as exc:
        proof, _coverages = {"status": "UNAVAILABLE", "reason": str(exc)}, {}
    except (TypeError, KeyError, IndexError):
        proof, _coverages = {"status": "UNAVAILABLE", "reason": "provider or PR evidence fields are malformed"}, {}
    index = {"schemaVersion": "alk-ci-qualification-index.v1", "main": main, "source": checked, **proof}
    raw = json_bytes(index)
    require(len(raw) <= MAX_INDEX, "candidate index exceeds its bound")
    write_bytes(out, raw)
    native_output("status", index["status"])
    native_output("sha256", sha256(raw))
    print(index["status"], index.get("reason", index.get("provider")))


def verified_index(path: Path, digest: str, main: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    return verified_index_bytes(read_bytes(path, MAX_INDEX), digest, main, checked)


def verified_index_bytes(raw: bytes, digest: str, main: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    require(
        len(raw) <= MAX_INDEX and is_hex(digest, 64) and sha256(raw) == digest, "trusted candidate index digest differs"
    )
    index = obj(strict_json(raw), "candidate index")
    common = {"schemaVersion", "main", "source", "status"}
    require(
        index.get("schemaVersion") == "alk-ci-qualification-index.v1"
        and index.get("main") == main
        and source_shape(index.get("source")) == checked,
        "candidate index is outside the current main invocation",
    )
    if index.get("status") == "UNAVAILABLE":
        obj(index, "unavailable candidate", common | {"reason"})
        require(isinstance(index["reason"], str) and 0 < len(index["reason"]) <= 500, "invalid fallback cause")
        return index
    obj(index, "qualified candidate", common | {"pr", "tested", "cells", "provider"})
    require(index["status"] == "CANDIDATE", "unsupported candidate status")
    pr = obj(index["pr"], "candidate PR identity", {"run", "attempt", "workflow", "head", "number"})
    tested = source_shape(index["tested"])
    require(
        bool(checked["parents"])
        and all(positive_id(pr[key]) for key in ("run", "attempt", "workflow", "number"))
        and is_hex(pr["head"], 40)
        and tested["parents"] == [checked["parents"][0], pr["head"]]
        and tested["inputs"] == checked["inputs"]
        and tested["tree"] == checked["tree"],
        "candidate's original attempt or tested checkout differs",
    )
    provider = obj(index["provider"], "candidate provider budget", {"authenticated", "total"})
    require(
        positive_id(provider["authenticated"])
        and positive_id(provider["total"])
        and provider["authenticated"] <= 40
        and provider["total"] <= 65,
        "candidate provider budget differs",
    )
    rows = obj(index["cells"], "candidate cells", set(CELLS))
    jobs: set[int] = set()
    artifacts: set[int] = set()
    for key, data in rows.items():
        row = obj(
            data,
            "candidate cell",
            {
                "job",
                "artifact",
                "archiveSha256",
                "receiptSha256",
                "testsSha256",
                "testsRun",
                "environmentSha256",
                "coverageSha256",
                "quality",
            },
        )
        require(
            all(positive_id(row[field]) for field in ("job", "artifact", "testsRun"))
            and row["job"] not in jobs
            and row["artifact"] not in artifacts
            and all(
                is_hex(row[field], 64)
                for field in (
                    "archiveSha256",
                    "receiptSha256",
                    "testsSha256",
                    "environmentSha256",
                )
            ),
            "invalid candidate cell identity",
        )
        jobs.add(row["job"])
        artifacts.add(row["artifact"])
        if CELLS[key][0] == "quality":
            quality = obj(row["quality"], "quality producer", {"runSha256", "validationSha256"})
            require(
                is_hex(row["coverageSha256"], 64) and all(is_hex(value, 64) for value in quality.values()),
                "invalid candidate coverage identity",
            )
        else:
            require(row["coverageSha256"] is None and row["quality"] is None, "unexpected quality data")
    return index


class QualityInputs:
    def __init__(self, index: Path, digest: str, cell: str, coverage: Path) -> None:
        self.index = index
        self.digest = digest
        self.cell = cell
        self.coverage = coverage


def add_quality_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--qualified-proof-index", type=Path)
    parser.add_argument("--qualified-proof-sha256")
    parser.add_argument("--qualified-proof-cell")
    parser.add_argument("--qualified-coverage", type=Path)


def quality_arguments(args: argparse.Namespace) -> QualityInputs | None:
    values = (
        args.qualified_proof_index,
        args.qualified_proof_sha256,
        args.qualified_proof_cell,
        args.qualified_coverage,
    )
    if all(value is None for value in values):
        return None
    require(all(value is not None for value in values), "all four qualified coverage inputs are required")
    return QualityInputs(*values)


def qualification_binding(root: Path, policy: Path, args: QualityInputs) -> tuple[bytes, dict[str, Any]]:
    main, checked = main_context(root)
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_JOB") == "probe-quality"
        and os.environ.get("QUALIFIED_INDEX_SHA256") == args.digest
        and os.environ.get("CI_CELL") == args.cell
        and policy.resolve() == root / POLICY,
        "qualification inputs are not bound to the current quality job",
    )
    key = cell_key("quality", args.cell)
    require(key in CELLS, "unexpected qualified quality cell")
    index = verified_index(args.index, args.digest, main, checked)
    require(index["status"] == "CANDIDATE", "candidate was not qualified for a probe")
    row = index["cells"][key]
    raw = read_bytes(args.coverage)
    require(sha256(raw) == row["coverageSha256"], "qualified coverage JSON digest differs")
    obj(strict_json(raw), "qualified coverage")
    observed = observed_environment(root, "quality", args.cell)
    if not observed_matches(observed, row["environmentSha256"]):
        raise EnvironmentMismatch("quality cell environment changed at consumption")
    return raw, {
        "indexSha256": args.digest,
        "cell": key,
        "coverageSha256": row["coverageSha256"],
        "environmentSha256": row["environmentSha256"],
        "main": main,
        "sourceTree": checked["tree"],
        "policySha256": checked["inputs"][POLICY],
        "producer": {**index["pr"], "job": row["job"], "artifact": row["artifact"]},
    }


def coverage_input(candidate_path: Path, cell: str) -> Path:
    return candidate_path.parent / "qualified-coverage" / f"quality-{cell}.json"


def quality_commands(python: str, candidate_path: Path, digest: str, cell: str, main_sha: str) -> dict[str, list[str]]:
    extra = [
        "--qualified-proof-index",
        str(candidate_path),
        "--qualified-proof-sha256",
        digest,
        "--qualified-proof-cell",
        cell,
        "--qualified-coverage",
        str(coverage_input(candidate_path, cell)),
    ]
    return {
        "runner": [
            python,
            "tools/release/run_python_quality.py",
            "--policy",
            POLICY,
            "--package-root",
            "src/agent_lifecycle",
            "--tests-root",
            "tests",
            "--test-top-level",
            ".",
            "--base-sha",
            main_sha,
            "--work-root",
            "work/python-quality/raw",
            "--evidence",
            "work/python-quality/run.json",
            *extra,
        ],
        "strict-mypy": [
            python,
            "-m",
            "mypy",
            "--strict",
            "src/agent_lifecycle/contracts/preparation_policy.py",
            "src/agent_lifecycle/contracts/agent_plugin_qualification_schemas.py",
        ],
        "validator": [
            python,
            "tools/release/validate_python_quality.py",
            "--policy",
            POLICY,
            "--run-receipt",
            "work/python-quality/run.json",
            "--work-root",
            "work/python-quality/raw",
            "--evidence",
            "work/python-quality/validation.json",
            *extra,
        ],
    }


def probe_quality(root: Path, candidate_path: Path, digest: str, cell: str, main_sha: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for name, argv in quality_commands(str(cell_python(root)), candidate_path, digest, cell, main_sha).items():
        result = subprocess.run(argv, cwd=root, check=False)
        results.append({"id": name, "returncode": result.returncode, "argv": argv})
        if name != "strict-mypy" and result.returncode == 3:
            return {"status": "MISMATCH", "commands": results, "receipts": None, "changedAfterChecks": False}
        require(result.returncode == 0, f"current quality probe failed: {name}")
    try:
        _, binding = qualification_binding(
            root, root / POLICY, QualityInputs(candidate_path, digest, cell, coverage_input(candidate_path, cell))
        )
    except EnvironmentMismatch:
        return {"status": "MISMATCH", "commands": results, "receipts": None, "changedAfterChecks": True}
    runner_raw = read_bytes(root / "work/python-quality/run.json")
    validator_raw = read_bytes(root / "work/python-quality/validation.json")
    runner = obj(strict_json(runner_raw), "current quality runner")
    validator = obj(strict_json(validator_raw), "current quality validator")
    require(
        runner.get("status") == validator.get("status") == "PASS"
        and runner.get("qualifiedCoverage") == validator.get("qualifiedCoverage") == binding
        and validator.get("runDigest") == runner.get("runDigest"),
        "current quality receipts do not bind coverage",
    )
    return {
        "status": "PASS",
        "commands": results,
        "changedAfterChecks": False,
        "receipts": {"runner": sha256(runner_raw), "validator": sha256(validator_raw), "binding": binding},
    }


def native_candidate() -> tuple[str, str]:
    require(os.environ.get("CANDIDATE_GENERATION_OUTCOME") == "success", "candidate generation did not succeed")
    status, digest = os.environ.get("CANDIDATE_STATUS"), os.environ.get("QUALIFIED_INDEX_SHA256")
    require(status in {"CANDIDATE", "UNAVAILABLE"} and is_hex(digest, 64), "candidate native outputs are invalid")
    return cast(str, status), cast(str, digest)


def optional_upload_succeeded(job: dict[str, Any]) -> bool:
    steps = job.get("steps")
    require(isinstance(steps, list), "optional upload outcome log unavailable")
    marker = only(
        [
            obj(step, "upload outcome log")
            for step in cast(list[Any], steps)
            if str(obj(step, "upload outcome log").get("name", "")).startswith(UPLOAD_LOG)
        ],
        "raw upload outcome log",
    )
    require(
        marker.get("name") in {UPLOAD_LOG + "success", UPLOAD_LOG + "failure"}, "invalid raw optional upload outcome"
    )
    job_step(job, marker["name"])
    return cast(bool, marker["name"] == UPLOAD_LOG + "success")


def listed_artifact(
    artifacts: dict[str, dict[str, Any]],
    name: str,
    identity: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    if name not in artifacts:
        raise ProviderUnavailable("optional artifact absent: " + name)
    row = obj(artifacts[name], "optional artifact")
    run = obj(row.get("workflow_run"), "optional artifact run")
    require(
        positive_id(row.get("id"))
        and row.get("name") == name
        and row.get("expired") is False
        and positive_id(row.get("size_in_bytes"))
        and row["size_in_bytes"] <= MAX_FILE
        and row.get("digest", "").startswith("sha256:")
        and is_hex(row["digest"][7:], 64)
        and run.get("id") == identity["run"]
        and run.get("repository_id") == identity["repository"]
        and run.get("head_repository_id") == identity["repository"]
        and run.get("head_sha") == identity["sha"]
        and fresh(row.get("created_at"), now)
        and utc_time(row.get("expires_at")) > now,
        "optional artifact identity differs",
    )
    return row


def current_archive(
    api: GitHub,
    main: dict[str, Any],
    jobs: dict[str, dict[str, Any]] | None,
    artifacts: dict[str, dict[str, Any]],
    key: str | None,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any] | None, bool]:
    candidate_input = key is None
    name = artifact_name("main-candidate" if candidate_input else "main-probe", main["run"], main["attempt"], key)
    row = listed_artifact(artifacts, name, main, api.now)
    job = None
    sender_success = False
    if jobs is not None:
        job = successful_job(jobs, CANDIDATE_JOB if candidate_input else probe_name(cast(str, key)), main["sha"])
        job_step(job, CANDIDATE_GENERATION if candidate_input else PROBE)
        sender_success = optional_upload_succeeded(job)
        joined_artifact(
            artifacts,
            name,
            job,
            CANDIDATE_UPLOAD if candidate_input else PROBE_UPLOAD,
            run=main["run"],
            repository=main["repository"],
            head=main["sha"],
            now=api.now,
            optional_upload=True,
        )
    expected = {"reuse-candidate.json"} if candidate_input else {"probe.json"}
    return api.archive(row, expected), row, job, sender_success


def original_coverage(api: GitHub, index: dict[str, Any], key: str) -> bytes:
    pr, cell = index["pr"], index["cells"][key]
    artifacts = artifact_rows(api, pr["run"])
    identity = {"run": pr["run"], "repository": index["main"]["repository"], "sha": pr["head"]}
    row = listed_artifact(artifacts, artifact_name("pr-ci", pr["run"], pr["attempt"], key), identity, api.now)
    require(
        row["id"] == cell["artifact"] and row["digest"] == "sha256:" + cell["archiveSha256"],
        "original quality archive identity differs",
    )
    members = api.archive(row, {"cell-evidence.json", "tests.json", "coverage.json"})
    require(
        sha256(members["cell-evidence.json"]) == cell["receiptSha256"]
        and sha256(members["tests.json"]) == cell["testsSha256"]
        and sha256(members["coverage.json"]) == cell["coverageSha256"],
        "original quality member bytes differ",
    )
    return members["coverage.json"]


def unavailable_probe(payload: Any, key: str, main: dict[str, Any], checked: dict[str, Any], digest: str) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "UNAVAILABLE":
        return False
    row = obj(
        payload,
        "unavailable probe",
        {
            "schemaVersion",
            "status",
            "main",
            "source",
            "cell",
            "indexSha256",
            "environment",
            "producer",
            "quality",
            "reason",
        },
    )
    require(
        row["schemaVersion"] == "alk-ci-probe.v1"
        and row["main"] == main
        and row["source"] == checked
        and row["cell"] == key
        and row["indexSha256"] == digest
        and row["producer"] is None
        and row["quality"] is None
        and row["environment"] is None
        and isinstance(row["reason"], str)
        and 0 < len(row["reason"]) <= 500,
        "unavailable probe is not source-bound",
    )
    return True


def validate_probe_without_index(
    payload: Any, key: str, main: dict[str, Any], checked: dict[str, Any], digest: str
) -> None:
    if unavailable_probe(payload, key, main, checked, digest):
        return
    row = obj(
        payload,
        "unbound observed probe",
        {
            "schemaVersion",
            "status",
            "main",
            "cell",
            "indexSha256",
            "environment",
            "producer",
            "quality",
        },
    )
    require(
        row["schemaVersion"] == "alk-ci-probe.v1"
        and row["main"] == main
        and row["cell"] == key
        and row["indexSha256"] == digest
        and row["status"] in {"MATCH", "MISMATCH"},
        "observed probe identity differs",
    )
    producer = obj(
        row["producer"],
        "observed producer",
        {
            "job",
            "artifact",
            "archiveSha256",
            "receiptSha256",
            "testsSha256",
            "testsRun",
            "environmentSha256",
            "coverageSha256",
            "quality",
        },
    )
    require(
        all(positive_id(producer[field]) for field in ("job", "artifact", "testsRun"))
        and all(
            is_hex(producer[field], 64)
            for field in ("archiveSha256", "receiptSha256", "testsSha256", "environmentSha256")
        ),
        "observed producer inventory is invalid",
    )
    if CELLS[key][0] == "quality":
        quality_producer = obj(producer["quality"], "observed quality producer", {"runSha256", "validationSha256"})
        require(
            is_hex(producer["coverageSha256"], 64) and all(is_hex(value, 64) for value in quality_producer.values()),
            "observed coverage producer is invalid",
        )
    else:
        require(
            producer["coverageSha256"] is None and producer["quality"] is None, "unexpected observed coverage producer"
        )
    observation = verify_observation(row["environment"], available=False)
    if CELLS[key][0] != "quality" or not observed_matches(observation, producer["environmentSha256"]):
        require(
            row["quality"] is None
            and row["status"]
            == ("MATCH" if observed_matches(observation, producer["environmentSha256"]) else "MISMATCH"),
            "observed probe compatibility status differs",
        )
        return
    quality = obj(row["quality"], "observed quality", {"status", "commands", "receipts", "changedAfterChecks"})
    commands = quality["commands"]
    require(
        isinstance(commands, list)
        and 0 < len(commands) <= len(QUALITY_STEPS)
        and type(quality["changedAfterChecks"]) is bool,
        "observed quality command inventory invalid",
    )
    first = obj(commands[0], "observed command").get("argv")
    require(
        isinstance(first, list)
        and first
        and isinstance(first[0], str)
        and Path(first[0]).is_absolute()
        and first[0].endswith("/.venv/bin/python"),
        "observed quality interpreter invalid",
    )
    expected = quality_commands(cast(list[Any], first)[0], CANDIDATE_PATH, digest, CELLS[key][1], main["sha"])
    for name, command in zip(QUALITY_STEPS, commands, strict=False):
        command = obj(command, "observed quality command", {"id", "returncode", "argv"})
        require(
            command["id"] == name and command["argv"] == expected[name] and type(command["returncode"]) is int,
            "observed quality command differs",
        )
    complete = len(commands) == 3 and all(command["returncode"] == 0 for command in commands)
    if quality["status"] == "MISMATCH":
        mismatch = (
            complete
            if quality["changedAfterChecks"]
            else (
                all(command["returncode"] == 0 for command in commands[:-1])
                and commands[-1]["id"] in {"runner", "validator"}
                and commands[-1]["returncode"] == 3
            )
        )
        require(
            row["status"] == "MISMATCH" and quality["receipts"] is None and mismatch,
            "observed quality mismatch is invalid",
        )
        return
    receipts = obj(quality["receipts"], "observed quality receipts", {"runner", "validator", "binding"})
    binding = obj(
        receipts["binding"],
        "observed coverage binding",
        {
            "indexSha256",
            "cell",
            "coverageSha256",
            "environmentSha256",
            "main",
            "sourceTree",
            "policySha256",
            "producer",
        },
    )
    require(
        quality["status"] == "PASS"
        and row["status"] == "MATCH"
        and complete
        and quality["changedAfterChecks"] is False
        and is_hex(receipts["runner"], 64)
        and is_hex(receipts["validator"], 64)
        and binding["indexSha256"] == digest
        and binding["main"] == main
        and binding["cell"] == key
        and binding["sourceTree"] == checked["tree"]
        and binding["policySha256"] == checked["inputs"][POLICY]
        and binding["coverageSha256"] == producer["coverageSha256"]
        and binding["environmentSha256"] == producer["environmentSha256"],
        "observed quality proof is malformed",
    )
    origin = obj(
        binding["producer"],
        "observed original attempt",
        {"run", "attempt", "workflow", "head", "number", "job", "artifact"},
    )
    require(
        all(positive_id(origin[field]) for field in ("run", "attempt", "workflow", "number", "job", "artifact"))
        and is_hex(origin["head"], 40)
        and origin["job"] == producer["job"]
        and origin["artifact"] == producer["artifact"]
        and is_hex(producer["coverageSha256"], 64),
        "observed original coverage identity differs",
    )


def probe(root: Path, role: str, cell: str, candidate_path: Path, out: Path) -> None:
    main, checked = main_context(root)
    key = cell_key(role, cell)
    require(key in CELLS and os.environ.get("GITHUB_JOB") == f"probe-{role}", "unexpected current probe cell")
    status, digest = native_candidate()
    require(status == "CANDIDATE", "probes require an applicable native candidate")
    try:
        api = GitHub(REPOSITORY, os.environ.get("GH_TOKEN", ""))
        jobs = provider_jobs(api, main["run"], main["attempt"])
        artifacts = artifact_rows(api, main["run"])
        members, _, _, sender_success = current_archive(api, main, jobs, artifacts, None)
        raw = members["reuse-candidate.json"]
        index = verified_index_bytes(raw, digest, main, checked)
        require(index["status"] == status, "candidate differs from native status")
        if not sender_success:
            raise ProviderUnavailable("candidate sender reported upload failure")
        coverage = original_coverage(api, index, key) if role == "quality" else None
    except ProviderUnavailable as exc:
        write_object(
            out,
            {
                "schemaVersion": "alk-ci-probe.v1",
                "status": "UNAVAILABLE",
                "main": main,
                "source": checked,
                "cell": key,
                "indexSha256": digest,
                "environment": None,
                "producer": None,
                "quality": None,
                "reason": str(exc)[:500],
            },
        )
        return
    write_bytes(candidate_path, raw)
    if coverage is not None:
        write_bytes(coverage_input(candidate_path, cell), coverage)
    row = index["cells"][key]
    environment = observed_environment(root, role, cell)
    match = observed_matches(environment, row["environmentSha256"])
    quality = None
    if match and role == "quality":
        quality = probe_quality(root, candidate_path, digest, cell, main["sha"])
        match = quality["status"] == "PASS"
    write_object(
        out,
        {
            "schemaVersion": "alk-ci-probe.v1",
            "status": "MATCH" if match else "MISMATCH",
            "main": main,
            "cell": key,
            "indexSha256": digest,
            "environment": environment,
            "producer": row,
            "quality": quality,
        },
    )


def needs_outcomes(value: Any, expected: set[str]) -> dict[str, str]:
    needs = obj(value, "workflow needs", expected)
    outcomes = {key: obj(row, "job needs").get("result") for key, row in needs.items()}
    require(
        all(outcome in {"success", "skipped", "failure", "cancelled"} for outcome in outcomes.values()),
        "missing native needs outcome",
    )
    return cast(dict[str, str], outcomes)


def probe_result(payload: Any, key: str, index: dict[str, Any], digest: str) -> bool:
    probe_row = obj(
        payload,
        "probe",
        {
            "schemaVersion",
            "status",
            "main",
            "cell",
            "indexSha256",
            "environment",
            "producer",
            "quality",
        },
    )
    require(
        probe_row["schemaVersion"] == "alk-ci-probe.v1"
        and probe_row["status"] in {"MATCH", "MISMATCH"}
        and probe_row["main"] == index["main"]
        and probe_row["cell"] == key
        and probe_row["indexSha256"] == digest
        and probe_row["producer"] == index["cells"][key],
        "probe identity differs",
    )
    expected = index["cells"][key]["environmentSha256"]
    actual = verify_observation(probe_row["environment"], available=False)
    match = observed_matches(actual, expected)
    quality = probe_row["quality"]
    if not match or CELLS[key][0] != "quality":
        require(
            quality is None and probe_row["status"] == ("MATCH" if match else "MISMATCH"),
            "unexpected probe quality or compatibility status",
        )
        return match

    quality = obj(quality, "probe quality", {"status", "commands", "receipts", "changedAfterChecks"})
    commands = quality["commands"]
    late = quality["changedAfterChecks"]
    require(
        isinstance(commands, list) and 0 < len(commands) <= len(QUALITY_STEPS) and type(late) is bool,
        "invalid current quality command count or mismatch indicator",
    )
    first = obj(commands[0], "quality runner").get("argv")
    require(
        isinstance(first, list)
        and first
        and isinstance(first[0], str)
        and Path(first[0]).is_absolute()
        and first[0].endswith("/.venv/bin/python"),
        "invalid current quality interpreter",
    )
    expected_commands = quality_commands(
        cast(list[str], first)[0], CANDIDATE_PATH, digest, CELLS[key][1], index["main"]["sha"]
    )
    for name, command in zip(QUALITY_STEPS, commands, strict=False):
        command = obj(command, "quality command", {"id", "returncode", "argv"})
        require(
            command["id"] == name and type(command["returncode"]) is int and command["argv"] == expected_commands[name],
            "invalid current quality command",
        )
    completed = len(commands) == len(QUALITY_STEPS) and all(command["returncode"] == 0 for command in commands)
    if quality["status"] == "MISMATCH":
        expected_mismatch = (
            completed
            if late
            else all(command["returncode"] == 0 for command in commands[:-1])
            and commands[-1]["id"] in {"runner", "validator"}
            and commands[-1]["returncode"] == 3
        )
        require(
            probe_row["status"] == "MISMATCH" and quality["receipts"] is None and expected_mismatch,
            "invalid late quality mismatch",
        )
        return False
    require(
        quality["status"] == "PASS" and probe_row["status"] == "MATCH" and completed and not late,
        "missing fresh quality command success",
    )
    receipts = obj(quality["receipts"], "quality receipts", {"runner", "validator", "binding"})
    row = index["cells"][key]
    require(
        is_hex(receipts["runner"], 64)
        and is_hex(receipts["validator"], 64)
        and receipts["binding"]
        == {
            "indexSha256": digest,
            "cell": key,
            "coverageSha256": row["coverageSha256"],
            "environmentSha256": row["environmentSha256"],
            "main": index["main"],
            "sourceTree": index["source"]["tree"],
            "policySha256": index["source"]["inputs"][POLICY],
            "producer": {**index["pr"], "job": row["job"], "artifact": row["artifact"]},
        },
        "fresh quality receipts do not bind the exact coverage bytes",
    )
    return True


def transport_failure(transport: dict[str, Any], phase: str, cell: str | None, reason: str) -> None:
    transport["failures"].append({"phase": phase, "cell": cell, "reason": reason[:500]})


def decide(root: Path, _candidate_path: Path, _probes: Path, out: Path, needs: Any) -> None:
    main, checked = main_context(root)
    outcomes = needs_outcomes(needs, {"candidate", *(f"probe-{role}" for role in ROLES)})
    require(outcomes["candidate"] == "success", "candidate job must report success")
    status, digest = native_candidate()
    expected_probe = "success" if status == "CANDIDATE" else "skipped"
    require(all(outcomes[f"probe-{role}"] == expected_probe for role in ROLES), "current probe job failed or skipped")
    transport: dict[str, Any] = {
        "generationOutcome": "success",
        "candidateStatus": status,
        "expectedIndexSha256": digest,
        "indexVerified": False,
        "missingCells": [],
        "unavailableCells": [],
        "failures": [],
    }
    api = GitHub(REPOSITORY, os.environ.get("GH_TOKEN", ""))
    jobs = None
    artifacts = None
    try:
        jobs = provider_jobs(api, main["run"], main["attempt"])
    except ProviderUnavailable as exc:
        transport_failure(transport, "metadata", None, str(exc))
    try:
        artifacts = artifact_rows(api, main["run"])
    except ProviderUnavailable as exc:
        transport_failure(transport, "metadata", None, str(exc))
    if jobs is not None:
        candidate_job = successful_job(jobs, CANDIDATE_JOB, main["sha"])
        job_step(candidate_job, CANDIDATE_GENERATION)
        if not optional_upload_succeeded(candidate_job):
            transport_failure(transport, "sender", None, "candidate sender reported upload failure")
        for key in CELLS:
            if status == "CANDIDATE":
                job = successful_job(jobs, probe_name(key), main["sha"])
                job_step(job, PROBE)
                if not optional_upload_succeeded(job):
                    transport_failure(transport, "sender", key, "probe sender reported upload failure")
            else:
                require(
                    probe_name(key) not in jobs or jobs[probe_name(key)].get("conclusion") == "skipped",
                    "unexpected probe without an applicable candidate",
                )
    index = None
    if artifacts is not None:
        try:
            members, _, _, _ = current_archive(api, main, jobs, artifacts, None)
        except ProviderUnavailable as exc:
            transport_failure(transport, "index", None, str(exc))
        else:
            index = verified_index_bytes(members["reuse-candidate.json"], digest, main, checked)
            require(index["status"] == status, "candidate status differs from native output")
            transport["indexVerified"] = True
    bindings: dict[str, Any] = {}
    if status == "CANDIDATE":
        for key in CELLS:
            if artifacts is None:
                transport["missingCells"].append(key)
                continue
            try:
                members, artifact, probe_job, _ = current_archive(api, main, jobs, artifacts, key)
            except ProviderUnavailable as exc:
                transport["missingCells"].append(key)
                transport_failure(transport, "probe", key, str(exc))
                continue
            raw = members["probe.json"]
            report = strict_json(raw)
            matched: bool | None
            if unavailable_probe(report, key, main, checked, digest):
                matched = False
                transport["unavailableCells"].append(key)
                transport_failure(transport, "probe", key, report["reason"])
            elif index is not None:
                matched = probe_result(report, key, index, digest)
            else:
                validate_probe_without_index(report, key, main, checked, digest)
                matched = None
            bindings[key] = {
                "job": probe_job["id"] if probe_job is not None else None,
                "artifact": artifact["id"] if probe_job is not None else None,
                "sha256": sha256(raw),
                "matched": matched,
            }
    elif artifacts is not None:
        prefix = artifact_name("main-probe", main["run"], main["attempt"]) + "-"
        require(not any(name.startswith(prefix) for name in artifacts), "unexpected artifacts without probes")
    mismatched = [key for key, row in bindings.items() if row["matched"] is False]
    mode = "FULL"
    reason = "reuse evidence unavailable"
    if transport["failures"]:
        reason = transport["failures"][0]["reason"]
    elif status == "UNAVAILABLE":
        require(index is not None, "unavailable candidate bytes missing without a transport cause")
        reason = cast(dict[str, Any], index)["reason"]
    elif mismatched:
        reason = "environment mismatch: " + ", ".join(mismatched)
    else:
        require(index is not None and len(bindings) == len(CELLS), "incomplete reuse without transport cause")
        mode, reason = "QUALIFIED_REUSE", "all compatibility probes passed"
    if index is not None and status == "CANDIDATE":
        try:
            recheck_pr(api, index["pr"], main["repository"])
        except (ProviderUnavailable, ApplicabilityChanged) as exc:
            mode, reason = "FULL", f"PR applicability changed: {exc}"
            transport_failure(transport, "pr", None, reason)
    decision = {
        "schemaVersion": "alk-ci-decision.v1",
        "mode": mode,
        "reason": reason[:500],
        "main": main,
        "source": checked,
        "indexSha256": digest,
        "pr": index.get("pr") if index else None,
        "probeProviderUnavailable": jobs is None,
        "probes": bindings,
        "transport": transport,
    }
    decision_proof(decision, main, checked)
    decision_digest = write_object(out, decision)
    native_output("mode", mode)
    native_output("sha256", decision_digest)
    print(mode, reason)


def control_context(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    run = invocation("workflow_dispatch")
    checked = source(root)
    event = read_object(Path(os.environ["GITHUB_EVENT_PATH"]))
    require(
        os.environ.get("GITHUB_REF") == MAIN_REF
        and run["sha"] == checked["sha"]
        and obj(event.get("inputs"), "manual control inputs").get("source_sha") == run["sha"],
        "manual control requires the exact checked main SHA",
    )
    return run, checked


def package_argv(python: str) -> list[str]:
    return ["uv", "build", "--python", python, "--no-build-isolation", "--no-create-gitignore", "--out-dir", MAIN_DIST]


def package_artifacts(root: Path, directory: Path) -> dict[str, dict[str, Any]]:
    directory = directory.absolute()
    require(
        directory.is_relative_to(root) and directory.resolve() == directory and directory.is_dir(),
        "package output directory is unsafe or absent",
    )
    output = list(directory.iterdir())
    require(len(output) == 2, "expected exactly two fresh distribution files")
    wheel = only([path for path in output if path.name.endswith(".whl")], "wheel")
    sdist = only([path for path in output if path.name.endswith(".tar.gz")], "sdist")
    result = {}
    for kind, path in (("wheel", wheel), ("sdist", sdist)):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", path.name), "invalid distribution name")
        raw = read_bytes(path, MAX_TOTAL)
        result[kind] = {"name": path.name, "bytes": len(raw), "sha256": sha256(raw)}
    return result


def build_package(root: Path, out: Path) -> None:
    _, checked = (
        control_context(root) if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" else main_context(root)
    )
    require(not os.path.lexists(root / MAIN_DIST), "main distribution directory must start absent")
    python = str(cell_python(root))
    environment = env_snapshot(root, "main", "ubuntu-latest-py3.14")
    argv = package_argv(python)
    subprocess.run(argv, cwd=root, check=True)
    require(source(root) == checked, "source changed during package build")
    write_object(
        out,
        {
            "schemaVersion": "alk-ci-main-build.v1",
            "status": "PASS",
            "source": checked,
            "environment": environment,
            "argv": argv,
            "returncode": 0,
            "artifacts": package_artifacts(root, root / MAIN_DIST),
        },
    )


def package_receipt(value: Any, checked: dict[str, Any]) -> dict[str, Any]:
    receipt = obj(
        value,
        "main package build",
        {
            "schemaVersion",
            "status",
            "source",
            "environment",
            "argv",
            "returncode",
            "artifacts",
        },
    )
    argv = receipt["argv"]
    require(
        receipt["schemaVersion"] == "alk-ci-main-build.v1"
        and receipt["status"] == "PASS"
        and type(receipt["returncode"]) is int
        and receipt["returncode"] == 0
        and receipt["source"] == checked
        and isinstance(argv, list)
        and len(argv) == len(package_argv(""))
        and isinstance(argv[3], str)
        and Path(argv[3]).is_absolute()
        and argv == package_argv(argv[3]),
        "main build receipt does not identify the exact successful build",
    )
    environment = obj(receipt["environment"], "main build environment")
    verify_observation(
        {"status": "OBSERVED", "inputs": environment, "sha256": sha256(json_bytes(environment))}, available=True
    )
    artifacts = obj(receipt["artifacts"], "main distribution artifacts", {"wheel", "sdist"})
    for kind, suffix in (("wheel", ".whl"), ("sdist", ".tar.gz")):
        item = obj(artifacts[kind], "distribution artifact", {"name", "bytes", "sha256"})
        require(
            isinstance(item["name"], str)
            and item["name"].endswith(suffix)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", item["name"])
            and positive_id(item["bytes"])
            and is_hex(item["sha256"], 64),
            "distribution artifact identity differs",
        )
    return receipt


def load_package_build(
    root: Path, directory: Path, receipt_path: Path, expected_sha: str, python: str
) -> dict[str, Any]:
    raw = read_bytes(receipt_path)
    checked = source(root)
    require(is_hex(expected_sha, 40) and expected_sha == checked["sha"], "prebuilt source does not match HEAD")
    receipt = package_receipt(strict_json(raw), checked)
    require(
        receipt["argv"] == package_argv(python)
        and receipt["environment"] == env_snapshot(root, "main", "ubuntu-latest-py3.14"),
        "prebuilt interpreter or backend inputs differ",
    )
    require(directory.absolute() == root / MAIN_DIST, "prebuilt distribution directory differs from build argv")
    artifacts = package_artifacts(root, directory)
    require(receipt["artifacts"] == artifacts, "prebuilt package bytes differ")
    return {
        "receiptSha256": sha256(raw),
        "sourceSha": expected_sha,
        "sourceTree": checked["tree"],
        "artifacts": artifacts,
    }


def main_checks_evidence(build_raw: bytes, smoke_raw: bytes, checked: dict[str, Any]) -> dict[str, Any]:
    build = package_receipt(strict_json(build_raw), checked)
    smoke = obj(strict_json(smoke_raw), "main packaging smoke")
    identity = {
        "receiptSha256": sha256(build_raw),
        "sourceSha": checked["sha"],
        "sourceTree": checked["tree"],
        "artifacts": build["artifacts"],
    }
    require(
        smoke.get("schemaVersion") == "agent-packaging-smoke-evidence.v1"
        and smoke.get("status") == "PASS"
        and smoke.get("prebuilt") == identity
        and smoke.get("blockers") == [],
        "main packaging smoke proof differs",
    )
    checks = smoke.get("artifactChecks")
    require(isinstance(checks, list) and len(checks) == 2, "main isolated artifact consumers missing")
    for kind, check in zip(("wheel", "sdist"), cast(list[Any], checks), strict=True):
        check = obj(check, "package check")
        require(
            check.get("kind") == kind
            and check.get("status") == "PASS"
            and check.get("artifactIdentity") == build["artifacts"][kind]
            and obj(check.get("runtimeInventory"), "runtime package inventory").get("status") == "PASS",
            "main smoke did not consume the built artifact",
        )
    commands = smoke.get("commands")
    require(
        isinstance(commands, list)
        and all(obj(row, "smoke command").get("returncode") == 0 for row in commands)
        and len(commands) >= 14,
        "missing successful installed-consumer commands",
    )
    return {"build": identity, "smokeSha256": sha256(smoke_raw)}


def decision_proof(value: Any, main: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict) and "transport" not in value:
        return legacy_decision_proof(value, main, checked)
    proof = obj(
        value,
        "transport decision",
        {
            "schemaVersion",
            "mode",
            "reason",
            "main",
            "source",
            "indexSha256",
            "pr",
            "probeProviderUnavailable",
            "probes",
            "transport",
        },
    )
    require(
        proof["schemaVersion"] == "alk-ci-decision.v1"
        and proof["mode"] in {"FULL", "QUALIFIED_REUSE"}
        and proof["main"] == main
        and proof["source"] == checked
        and is_hex(proof["indexSha256"], 64)
        and isinstance(proof["reason"], str)
        and 0 < len(proof["reason"]) <= 500
        and type(proof["probeProviderUnavailable"]) is bool,
        "transport decision identity differs",
    )
    transport = obj(
        proof["transport"],
        "decision transport",
        {
            "generationOutcome",
            "candidateStatus",
            "expectedIndexSha256",
            "indexVerified",
            "missingCells",
            "unavailableCells",
            "failures",
        },
    )
    require(
        transport["generationOutcome"] == "success"
        and transport["candidateStatus"] in {"CANDIDATE", "UNAVAILABLE"}
        and transport["expectedIndexSha256"] == proof["indexSha256"]
        and type(transport["indexVerified"]) is bool,
        "transport generation binding differs",
    )
    rows = obj(proof["probes"], "observed probe bindings")
    require(set(rows) <= set(CELLS), "unexpected observed probe cell")
    for field in ("missingCells", "unavailableCells"):
        names = transport[field]
        require(
            isinstance(names, list)
            and all(isinstance(name, str) for name in names)
            and len(names) == len(set(names))
            and set(names) <= set(CELLS),
            "invalid missing evidence inventory",
        )
    failures = transport["failures"]
    require(isinstance(failures, list) and len(failures) <= 60, "invalid transport failure inventory")
    for data in failures:
        failure = obj(data, "transport failure", {"phase", "cell", "reason"})
        require(
            failure["phase"] in {"metadata", "index", "sender", "probe", "pr"}
            and (failure["cell"] is None or failure["cell"] in CELLS)
            and isinstance(failure["reason"], str)
            and 0 < len(failure["reason"]) <= 500,
            "invalid transport failure",
        )
    if transport["candidateStatus"] == "UNAVAILABLE":
        require(
            proof["mode"] == "FULL"
            and proof["pr"] is None
            and not rows
            and not transport["missingCells"]
            and not transport["unavailableCells"],
            "inapplicable candidate has unexpected probes",
        )
    else:
        require(
            set(transport["missingCells"]) == set(CELLS) - set(rows)
            and set(transport["unavailableCells"]) <= set(rows),
            "missing probe bindings differ",
        )
    if not transport["indexVerified"]:
        require(
            proof["mode"] == "FULL" and proof["pr"] is None and bool(failures),
            "unverified index gained reuse authority",
        )
    elif transport["candidateStatus"] == "CANDIDATE":
        pr = obj(proof["pr"], "verified decision PR", {"run", "attempt", "workflow", "head", "number"})
        require(
            all(positive_id(pr[field]) for field in ("run", "attempt", "workflow", "number"))
            and is_hex(pr["head"], 40),
            "invalid verified decision PR",
        )
    joins = []
    for key, data in rows.items():
        row = obj(data, "observed probe binding", {"job", "artifact", "sha256", "matched"})
        require(
            is_hex(row["sha256"], 64) and (type(row["matched"]) is bool or row["matched"] is None),
            "invalid observed probe binding",
        )
        require(row["matched"] is not None or not transport["indexVerified"], "verified index has unknown matches")
        if proof["probeProviderUnavailable"]:
            require(row["job"] is None and row["artifact"] is None, "unavailable metadata gained provider IDs")
        else:
            require(positive_id(row["job"]) and positive_id(row["artifact"]), "observed provider IDs missing")
            joins.append((row["job"], row["artifact"]))
        if key in transport["unavailableCells"]:
            require(row["matched"] is False, "unavailable probe gained a match")
    require(
        len({job for job, _ in joins}) == len({artifact for _, artifact in joins}) == len(joins),
        "duplicate observed provider IDs",
    )
    if proof["mode"] == "QUALIFIED_REUSE":
        require(
            transport["candidateStatus"] == "CANDIDATE"
            and transport["indexVerified"]
            and not proof["probeProviderUnavailable"]
            and not failures
            and not transport["missingCells"]
            and not transport["unavailableCells"]
            and set(rows) == set(CELLS)
            and all(row["matched"] is True for row in rows.values()),
            "incomplete transport cannot qualify reuse",
        )
    elif transport["missingCells"] or transport["unavailableCells"] or proof["probeProviderUnavailable"]:
        require(bool(failures), "unavailable evidence has no retained cause")
    return proof


def legacy_decision_proof(value: Any, main: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    proof = obj(
        value,
        "main decision",
        {
            "schemaVersion",
            "mode",
            "reason",
            "main",
            "source",
            "indexSha256",
            "pr",
            "probeProviderUnavailable",
            "probes",
        },
    )
    require(
        proof["schemaVersion"] == "alk-ci-decision.v1"
        and proof["mode"] in {"FULL", "QUALIFIED_REUSE"}
        and type(proof["probeProviderUnavailable"]) is bool
        and (not proof["probeProviderUnavailable"] or proof["mode"] == "FULL")
        and proof["main"] == main
        and proof["source"] == checked
        and is_hex(proof["indexSha256"], 64)
        and isinstance(proof["reason"], str)
        and bool(proof["reason"]),
        "main decision identity differs",
    )
    if proof["pr"] is None:
        require(
            proof["mode"] == "FULL" and proof["probes"] == {} and not proof["probeProviderUnavailable"],
            "decision without a candidate must use FULL without probes",
        )
        return proof
    pr = obj(proof["pr"], "decision PR attempt", {"run", "attempt", "workflow", "head", "number"})
    require(
        all(positive_id(pr[field]) for field in ("run", "attempt", "workflow", "number")) and is_hex(pr["head"], 40),
        "invalid decision PR attempt",
    )
    probes = obj(proof["probes"], "decided probe inventory", set(CELLS))
    for data in probes.values():
        row = obj(data, "decided probe", {"job", "artifact", "sha256", "matched"})
        require(
            is_hex(row["sha256"], 64) and type(row["matched"]) is bool,
            "invalid decided probe",
        )
        if proof["probeProviderUnavailable"]:
            require(row["job"] is None and row["artifact"] is None, "unavailable probe join includes provider IDs")
        else:
            require(positive_id(row["job"]) and positive_id(row["artifact"]), "invalid decided probe provider IDs")
        require(proof["mode"] == "FULL" or row["matched"] is True, "reuse decision includes mismatch")
    if not proof["probeProviderUnavailable"]:
        require(
            len({row["job"] for row in probes.values()})
            == len({row["artifact"] for row in probes.values()})
            == len(CELLS),
            "duplicate decided probe identities",
        )
    return proof


def transport_graph(
    api: GitHub,
    main: dict[str, Any],
    decision: dict[str, Any],
    jobs: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    transport = decision["transport"]
    reuse = decision["mode"] == "QUALIFIED_REUSE"
    candidate_job = successful_job(jobs, CANDIDATE_JOB, main["sha"])
    job_step(candidate_job, CANDIDATE_GENERATION)
    candidate_sender = optional_upload_succeeded(candidate_job)
    index = None
    try:
        members, _, _, _ = current_archive(api, main, jobs, artifacts, None)
    except ProviderUnavailable:
        require(not reuse, "qualified candidate archive is unavailable")
    else:
        index = verified_index_bytes(members["reuse-candidate.json"], decision["indexSha256"], main, decision["source"])
        require(index["status"] == transport["candidateStatus"], "current candidate status differs")
    if reuse:
        require(index is not None and candidate_sender, "reuse candidate sender did not succeed")
    for key in CELLS:
        if transport["candidateStatus"] == "UNAVAILABLE":
            require(
                probe_name(key) not in jobs or jobs[probe_name(key)].get("conclusion") == "skipped",
                "inapplicable candidate produced unexpected probe work",
            )
            continue
        job = successful_job(jobs, probe_name(key), main["sha"])
        job_step(job, PROBE)
        sender = optional_upload_succeeded(job)
        try:
            members, artifact, _, _ = current_archive(api, main, jobs, artifacts, key)
        except ProviderUnavailable:
            require(not reuse, "qualified probe archive is unavailable")
            continue
        raw = members["probe.json"]
        payload = strict_json(raw)
        unavailable = unavailable_probe(payload, key, main, decision["source"], decision["indexSha256"])
        matched = False
        if not unavailable:
            if index is None:
                validate_probe_without_index(payload, key, main, decision["source"], decision["indexSha256"])
            else:
                matched = probe_result(payload, key, index, decision["indexSha256"])
        if key in decision["probes"]:
            binding = decision["probes"][key]
            require(sha256(raw) == binding["sha256"], "current probe differs from observed decision bytes")
            if binding["job"] is not None:
                require(
                    binding["job"] == job["id"] and binding["artifact"] == artifact["id"],
                    "current probe provider join differs",
                )
        if reuse:
            require(sender and matched and not unavailable, "qualified probe is incomplete")


def main_job_graph(
    api: GitHub,
    main: dict[str, Any],
    decision: dict[str, Any],
    jobs: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run, attempt, head = main["run"], main["attempt"], main["sha"]
    identity = {"run": run, "repository": main["repository"], "head": head, "now": api.now}
    job_step(successful_job(jobs, DECISION_JOB, head), DECISION_STEP)
    if "transport" not in decision:
        job_step(successful_job(jobs, CANDIDATE_JOB, head), CANDIDATE_UPLOAD)
    checks = successful_job(jobs, MAIN_CHECKS_JOB, head)
    for name in (
        *MAIN_GATES,
        "Validate CI security and test discovery",
        "Validate skill parity",
        "Build exact main distributions",
        "Smoke-test those distributions",
        MAIN_CHECKS_UPLOAD,
    ):
        job_step(checks, name)
    main_artifact = joined_artifact(
        artifacts,
        artifact_name("main-checks", run, attempt),
        checks,
        MAIN_CHECKS_UPLOAD,
        **identity,
    )
    active_names = {name for name, row in jobs.items() if row.get("conclusion") == "success"}
    suites: dict[str, Any] = {}
    if decision["mode"] == "FULL":
        for key, (role, cell, name) in CELLS.items():
            job = suite_job(jobs, role, cell, name, head)
            artifact = joined_artifact(
                artifacts,
                artifact_name("main-full", run, attempt, key),
                job,
                CELL_UPLOAD,
                **identity,
            )
            suites[key] = {"job": job["id"], "artifact": artifact["id"], "archiveSha256": artifact["digest"][7:]}
    else:
        require(
            all(name not in jobs or jobs[name].get("conclusion") == "skipped" for _, _, name in CELLS.values())
            and not any(name.startswith(f"alk-main-full-{run}-{attempt}-") for name in artifacts),
            "a complete suite ran in qualified reuse mode",
        )
    if "transport" in decision:
        transport_graph(api, main, decision, jobs, artifacts)
    else:
        expected_probes = decision["probes"]
        for key in CELLS:
            if key not in expected_probes:
                require(probe_name(key) not in active_names, "unexpected compatibility probe")
                continue
            job = successful_job(jobs, probe_name(key), head)
            job_step(job, PROBE)
            artifact = joined_artifact(
                artifacts,
                artifact_name("main-probe", run, attempt, key),
                job,
                PROBE_UPLOAD,
                **identity,
            )
            if decision["probeProviderUnavailable"]:
                member = api.archive(artifact, {"probe.json"})["probe.json"]
                require(sha256(member) == expected_probes[key]["sha256"], "fallback probe bytes differ")
            else:
                require(
                    job["id"] == expected_probes[key]["job"] and artifact["id"] == expected_probes[key]["artifact"],
                    "decided probe does not match exact current job",
                )
    return {
        "mainChecksJob": checks["id"],
        "mainChecksArtifact": main_artifact["id"],
        "mainChecksArchiveSha256": main_artifact["digest"][7:],
        "freshSuites": suites,
    }


def terminal(root: Path, decision_path: Path, checks_dir: Path, out: Path, needs: Any) -> None:
    main, checked = main_context(root)
    expected_needs = {"decide", "main-checks", *JOB_IDS.values()}
    if isinstance(needs, dict) and "candidate" in needs:
        expected_needs.add("candidate")
    outcomes = needs_outcomes(needs, expected_needs)
    require(outcomes["decide"] == outcomes["main-checks"] == "success", "main decision or integration did not pass")
    raw = read_bytes(decision_path, MAX_INDEX)
    digest = os.environ["MAIN_DECISION_SHA256"]
    require(is_hex(digest, 64) and sha256(raw) == digest, "trusted main decision digest differs")
    decision = decision_proof(strict_json(raw), main, checked)
    require(decision["mode"] == os.environ["MAIN_MODE"], "decision differs from native main mode")
    if "transport" in decision:
        status, expected_digest = native_candidate()
        require(
            outcomes.get("candidate") == "success"
            and decision["transport"]["candidateStatus"] == status
            and decision["indexSha256"] == expected_digest,
            "terminal native candidate binding differs",
        )
    expected = "success" if decision["mode"] == "FULL" else "skipped"
    require(all(outcomes[job] == expected for job in JOB_IDS.values()), "full family results differ from main mode")
    api = GitHub(REPOSITORY, os.environ.get("GH_TOKEN", ""))
    jobs = provider_jobs(api, main["run"], main["attempt"])
    artifacts = artifact_rows(api, main["run"])
    graph = main_job_graph(api, main, decision, jobs, artifacts)
    require(
        checks_dir.is_dir()
        and not checks_dir.is_symlink()
        and {path.name for path in checks_dir.iterdir()} == {"main-package-build.json", "main-packaging-smoke.json"},
        "unexpected main checks file inventory",
    )
    checks = main_checks_evidence(
        read_bytes(checks_dir / "main-package-build.json"),
        read_bytes(checks_dir / "main-packaging-smoke.json"),
        checked,
    )
    write_object(
        out,
        {
            "schemaVersion": "alk-ci-main-qualification.v1",
            "status": "PASS",
            "main": main,
            "source": checked,
            "decision": decision,
            "decisionSha256": digest,
            "outcomes": outcomes,
            "graph": graph,
            "checks": checks,
            "completeSuitesRun": len(graph["freshSuites"]),
        },
    )
    print(decision["mode"], len(graph["freshSuites"]), "fresh full suites")


def verified_push_run(api: GitHub, workflow: int, path: str, head: str, repository: int) -> tuple[int, int]:
    query = urllib.parse.urlencode({"event": "push", "branch": "main", "head_sha": head, "per_page": 100})
    listing = provider_rows(api.json(f"/actions/workflows/{workflow}/runs?{query}"), "workflow_runs")
    listed = only(listing, "push-main run")
    identifier, attempt = listed.get("id"), listed.get("run_attempt")
    require(positive_id(identifier) and positive_id(attempt), "invalid push-main attempt")
    exact = obj(api.json(f"/actions/runs/{identifier}/attempts/{attempt}"), "push-main attempt")
    for run in (listed, exact):
        provider_run(
            run,
            workflow=workflow,
            path=path,
            event="push",
            head=head,
            repository=repository,
            run_id=identifier,
            attempt=attempt,
        )
        require(
            run.get("head_branch") == "main" and fresh(run.get("updated_at"), api.now),
            "wrong branch or stale push-main proof",
        )
    return int(identifier), int(attempt)


def verified_main(api: GitHub, checked: dict[str, Any], repository: int) -> dict[str, Any]:
    repository_identity(api, repository)
    workflow = workflow_id(api, "ci.yml", "ci")
    head = checked["sha"]
    run, attempt = verified_push_run(api, workflow, WORKFLOW, head, repository)
    main = {"run": run, "attempt": attempt, "repository": repository, "sha": head}
    jobs = provider_jobs(api, run, attempt)
    artifacts = artifact_rows(api, run)
    job = successful_job(jobs, TERMINAL_JOB, head)
    job_step(job, TERMINAL_STEP)
    artifact = joined_artifact(
        artifacts,
        artifact_name("main-qualification", run, attempt),
        job,
        TERMINAL_UPLOAD,
        run=run,
        repository=repository,
        head=head,
        now=api.now,
    )
    members = api.archive(artifact, {"qualification.json"})
    proof = obj(
        strict_json(members["qualification.json"]),
        "main qualification",
        {
            "schemaVersion",
            "status",
            "main",
            "source",
            "decision",
            "decisionSha256",
            "outcomes",
            "graph",
            "checks",
            "completeSuitesRun",
        },
    )
    require(
        proof["schemaVersion"] == "alk-ci-main-qualification.v1"
        and proof["status"] == "PASS"
        and proof["main"] == main
        and proof["source"] == checked,
        "main qualification identity differs",
    )
    decision = decision_proof(proof["decision"], main, checked)
    require(sha256(json_bytes(decision)) == proof["decisionSha256"], "recorded main decision digest differs")
    graph = main_job_graph(api, main, decision, jobs, artifacts)
    require(
        proof["graph"] == graph and proof["completeSuitesRun"] == len(graph["freshSuites"]),
        "main qualification does not match actual jobs",
    )
    outcomes = needs_outcomes(
        {name: {"result": result} for name, result in obj(proof["outcomes"], "outcomes").items()},
        {"decide", "main-checks", *JOB_IDS.values(), *({"candidate"} if "transport" in decision else set())},
    )
    if "transport" in decision:
        require(outcomes["candidate"] == "success", "recorded native candidate generation did not succeed")
    expected = "success" if decision["mode"] == "FULL" else "skipped"
    require(
        outcomes["decide"] == outcomes["main-checks"] == "success"
        and all(outcomes[name] == expected for name in JOB_IDS.values()),
        "invalid recorded main outcomes",
    )
    checks = obj(artifacts.get(artifact_name("main-checks", run, attempt)), "main checks artifact")
    members = api.archive(checks, {"main-package-build.json", "main-packaging-smoke.json"})
    require(
        main_checks_evidence(members["main-package-build.json"], members["main-packaging-smoke.json"], checked)
        == proof["checks"],
        "main checks package proof differs",
    )

    codeql_path = ".github/workflows/codeql.yml"
    codeql = workflow_id(api, "codeql.yml", "codeql")
    codeql_run, codeql_attempt = verified_push_run(api, codeql, codeql_path, head, repository)
    codeql_jobs = provider_jobs(api, codeql_run, codeql_attempt)
    require(set(codeql_jobs) == {"CodeQL / Python"}, "unexpected main CodeQL job inventory")
    analysis = successful_job(codeql_jobs, "CodeQL / Python", head)
    job_step(analysis, "Run github/codeql-action/analyze@1fc58d04a4d4374f921bdac573c3811c240f9c26")
    for identifier, number, workflow_number, path in (
        (run, attempt, workflow, WORKFLOW),
        (codeql_run, codeql_attempt, codeql, codeql_path),
    ):
        current = obj(api.json(f"/actions/runs/{identifier}"), "current main attempt")
        provider_run(
            current,
            workflow=workflow_number,
            path=path,
            event="push",
            head=head,
            repository=repository,
            run_id=identifier,
            attempt=number,
        )
        require(current.get("head_branch") == "main", "current push-main branch differs")
    return {
        "verifiedSha": head,
        "mode": decision["mode"],
        "main": main,
        "mainQualification": {"job": job["id"], "artifact": artifact["id"], "archiveSha256": artifact["digest"][7:]},
        "codeql": {"run": codeql_run, "attempt": codeql_attempt, "job": analysis["id"]},
    }


def verify_release(root: Path, tag: str, expected: str, *, require_head: bool = True) -> None:
    require(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) and is_hex(expected, 40), "invalid release source binding")
    ref = f"refs/tags/{tag}"
    require(git(root, "rev-parse", "--verify", f"{ref}^{{commit}}") == expected, "checked release tag differs")
    if require_head:
        require(git(root, "rev-parse", "HEAD") == expected, "checked release source differs")
    lines = git(root, "ls-remote", "--exit-code", "origin", ref, ref + "^{}").splitlines()
    refs: dict[str, str] = {}
    for line in lines:
        sha, remote_ref = line.split("\t")
        require(
            is_hex(sha, 40) and remote_ref in {ref, ref + "^{}"} and remote_ref not in refs,
            "unexpected remote tag identity",
        )
        refs[remote_ref] = sha
    require(ref in refs and refs.get(ref + "^{}", refs[ref]) == expected, "remote release tag moved")
    subprocess.run(["git", "merge-base", "--is-ancestor", expected, "origin/main"], cwd=root, check=True)


def verify_main(root: Path, repository: str, source_sha: str, out: Path) -> None:
    release = invocation("release")
    require(release["sha"] == source_sha, "release event source differs")
    require(
        git(root, "rev-parse", "HEAD") == git(root, "rev-parse", "origin/main"),
        "publication verifier must run from the checked main branch",
    )
    verify_release(root, os.environ["RELEASE_TAG"], source_sha, require_head=False)
    checked = release_source(root, source_sha)
    api = GitHub(repository, os.environ.get("GH_TOKEN", ""))
    proof = verified_main(api, checked, release["repository"])
    write_object(out, proof)
    native_output("verified_sha", proof["verifiedSha"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("prepare")
    setup.add_argument("--setup-python", required=True)
    setup.add_argument("--role", choices=(*ROLES, "main"), required=True)
    record = sub.add_parser("record")
    inspect_probe = sub.add_parser("probe")
    for action in (record, inspect_probe):
        action.add_argument("--role", choices=ROLES, required=True)
        action.add_argument("--cell", required=True)
        action.add_argument("--out", type=Path, required=True)
    record.add_argument("--test-receipt", type=Path)
    inspect_probe.add_argument("--candidate", type=Path, required=True)
    qualify = sub.add_parser("candidate")
    publish = sub.add_parser("verify-main")
    for action in (qualify, publish):
        action.add_argument("--repository", required=True)
        action.add_argument("--out", type=Path, required=True)
    qualify.add_argument("--main-sha", required=True)
    publish.add_argument("--source-sha", required=True)
    selection = sub.add_parser("decide")
    selection.add_argument("--candidate", type=Path, required=True)
    selection.add_argument("--probes", type=Path, required=True)
    final = sub.add_parser("terminal")
    final.add_argument("--decision", type=Path, required=True)
    final.add_argument("--checks", type=Path, required=True)
    for action in (selection, final, sub.add_parser("build-package")):
        action.add_argument("--out", type=Path, required=True)
    release = sub.add_parser("verify-release")
    release.add_argument("--tag", required=True)
    release.add_argument("--source-sha", required=True)
    sub.add_parser("verify-control")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        if args.command == "prepare":
            prepare(root, args.setup_python, args.role)
        elif args.command == "record":
            record_suite(root, args.role, args.cell, args.test_receipt, args.out)
        elif args.command == "candidate":
            candidate(root, args.repository, args.main_sha, args.out)
        elif args.command == "probe":
            probe(root, args.role, args.cell, args.candidate, args.out)
        elif args.command == "decide":
            decide(root, args.candidate, args.probes, args.out, strict_json(os.environ["CI_NEEDS_JSON"].encode()))
        elif args.command == "terminal":
            terminal(root, args.decision, args.checks, args.out, strict_json(os.environ["CI_NEEDS_JSON"].encode()))
        elif args.command == "build-package":
            build_package(root, args.out)
        elif args.command == "verify-main":
            verify_main(root, args.repository, args.source_sha, args.out)
        elif args.command == "verify-release":
            verify_release(root, args.tag, args.source_sha)
        elif args.command == "verify-control":
            control_context(root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"CI evidence failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
