from __future__ import annotations

import copy
import http.client
import io
import os
import re
import shutil
import stat
import tempfile
import unittest
import urllib.error
import urllib.parse
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tools.ci import qualify_pr_evidence as ci

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
STARTED = "2026-10-12T11:00:00Z"
UPLOADED = "2026-10-12T11:01:00Z"
COMPLETED = "2026-10-12T11:02:00Z"
MAIN = {"run": 400, "attempt": 2, "repository": 80, "sha": "1" * 40}
BASE, HEAD, SYNTHETIC, TREE = ("2" * 40, "3" * 40, "4" * 40, "5" * 40)
SOURCE = {
    "sha": MAIN["sha"],
    "tree": TREE,
    "parents": [BASE],
    "inputs": {name: ci.sha256(name.encode()) for name in ci.COMMON_INPUTS},
}
CHECKOUT = {**SOURCE, "sha": SYNTHETIC, "parents": [BASE, HEAD]}
REPO = {"id": MAIN["repository"], "full_name": ci.REPOSITORY, "default_branch": "main", "fork": False}
ACTOR = {"id": 14, "login": "ci-author", "type": "User"}
PR = {"run": 201, "attempt": 2, "workflow": 120, "head": HEAD, "number": 9}
PULL = {
    "number": PR["number"],
    "base": BASE,
    "head": HEAD,
    "baseRepo": REPO["id"],
    "headRepo": REPO["id"],
    "author": ACTOR["id"],
    "actor": ACTOR["login"],
    "triggeringActor": ACTOR["login"],
}
ENV = {
    "image": {"ImageOS": "image", "ImageVersion": "version", "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"},
    "architecture": "x86_64",
    "system": "Linux",
    "python": "Python 3.14.1",
    "implementation": "CPython",
    "interpreterSha256": "a" * 64,
    "dependencies": {"coverage": "7.17.2"},
    "dependencyInventorySha256": ci.sha256(ci.json_bytes([("coverage", "7.17.2")])),
    "tools": {"git": "git version", "uv": "uv 0.13.1"},
    "permissions": {"contents": "read"},
}
OBSERVED = {"status": "OBSERVED", "inputs": ENV, "sha256": ci.sha256(ci.json_bytes(ENV))}
UNAVAILABLE = {"status": "UNAVAILABLE", "reason": "runner image differs"}


def zipped(members: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return target.getvalue()


def provider_step(name: str, number: int) -> dict:
    return {
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "number": number,
        "started_at": STARTED,
        "completed_at": COMPLETED,
    }


def provider_job(name: str, identifier: int, steps: list[str], run: dict, head: str) -> dict:
    return {
        "name": name,
        "id": identifier,
        "run_id": run["run"],
        "run_attempt": run["attempt"],
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "check_run_url": f"https://api.github.com/repos/{ci.REPOSITORY}/check-runs/{identifier}",
        "steps": [provider_step(step, number) for number, step in enumerate(steps, 1)],
    }


def provider_artifact(name: str, identifier: int, raw: bytes, run: dict, head: str, job: int) -> dict:
    return {
        "name": name,
        "id": identifier,
        "expired": False,
        "size_in_bytes": len(raw),
        "job_id": job,
        "created_at": UPLOADED,
        "expires_at": "2026-10-13T11:00:00Z",
        "digest": "sha256:" + ci.sha256(raw),
        "archive_download_url": f"https://api.github.com/repos/{ci.REPOSITORY}/actions/artifacts/{identifier}/zip",
        "workflow_run": {
            "id": run["run"],
            "repository_id": REPO["id"],
            "head_repository_id": REPO["id"],
            "head_sha": head,
        },
    }


class ProviderFixture:
    """Serve the same bounded REST route without contacting a provider."""

    def __init__(self) -> None:
        self.api = ci.GitHub(ci.REPOSITORY, "unit-token", now=NOW)
        self.api.opener = self
        self.requests: list[tuple[str, str | None]] = []
        self.artifacts: list[dict] = []
        self.jobs: list[dict] = []
        self.archives: dict[str, bytes] = {}
        self.run = {
            "id": PR["run"],
            "run_attempt": PR["attempt"],
            "workflow_id": PR["workflow"],
            "head_sha": HEAD,
            "event": "pull_request",
            "path": ci.WORKFLOW,
            "status": "completed",
            "conclusion": "success",
            "updated_at": COMPLETED,
            "repository": REPO,
            "head_repository": REPO,
            "actor": ACTOR,
            "triggering_actor": ACTOR,
            "pull_requests": [],
        }
        self.pull = {
            "number": PR["number"],
            "state": "closed",
            "merged": True,
            "merged_at": COMPLETED,
            "merge_commit_sha": MAIN["sha"],
            "author_association": "OWNER",
            "user": ACTOR,
            "base": {"sha": BASE, "ref": "main", "repo": REPO},
            "head": {"sha": HEAD, "ref": "candidate", "repo": REPO},
        }
        self.job_listing = {"total_count": len(ci.CELLS), "jobs": self.jobs}
        self.artifact_listing = {"total_count": len(ci.CELLS), "artifacts": self.artifacts}
        self.routes = {
            "": REPO,
            f"/commits/{MAIN['sha']}/pulls?per_page=100": [self.pull],
            f"/pulls/{PR['number']}": self.pull,
            f"/collaborators/{ACTOR['login']}/permission": {"permission": "write", "user": ACTOR},
            "/actions/workflows/ci.yml": {"id": PR["workflow"], "path": ci.WORKFLOW, "name": "ci", "state": "active"},
            f"/actions/workflows/{PR['workflow']}/runs?event=pull_request&head_sha={HEAD}&per_page=100": {
                "total_count": 1,
                "workflow_runs": [self.run],
            },
            f"/actions/runs/{PR['run']}/attempts/{PR['attempt']}": self.run,
            f"/actions/runs/{PR['run']}/attempts/{PR['attempt']}/jobs?per_page=100": self.job_listing,
            f"/actions/runs/{PR['run']}/artifacts?per_page=100": self.artifact_listing,
            f"/actions/runs/{PR['run']}": self.run,
            f"/git/commits/{SYNTHETIC}": {
                "sha": SYNTHETIC,
                "tree": {"sha": TREE},
                "parents": [{"sha": BASE}, {"sha": HEAD}],
            },
        }
        for number, (key, (role, cell, name)) in enumerate(ci.CELLS.items(), 1):
            self._cell(number, key, role, cell, name)

    def _cell(self, number: int, key: str, role: str, cell: str, name: str) -> None:
        steps = [ci.PREPARE, "Restore versioned release test fixture", *ci.SUITE_STEPS[role], ci.RECORD, ci.CELL_UPLOAD]
        if ci.is_windows315(role, cell):
            steps.extend((ci.BACKEND, ci.BACKEND_AFTER))
        job = provider_job(name, 1000 + number, steps, PR, HEAD)
        self.jobs.append(job)
        tests = {
            "schemaVersion": "alk-ci-suite-inventory.v1",
            "status": "PASS",
            "discovery": {"start": "tests", "top": ".", "pattern": ci.PATTERNS[role]},
            "inventory": ["example.Test.test_case", "example.Test.test_skipped"],
            "testsRun": 1,
            "fixtureSkipped": ["example.Test.test_skipped"],
            "skips": 1,
            "startedAt": STARTED,
            "wallSeconds": 12.25,
            "timingSha256": "d" * 64,
        }
        members = {"tests.json": ci.json_bytes(tests)}
        quality = None
        if role == "quality":
            members["coverage.json"] = ci.json_bytes({"totals": {"percent_covered": 95}, "fixture": cell})
            quality = {"runSha256": "e" * 64, "validationSha256": "f" * 64}
        receipt = {
            "schemaVersion": "alk-ci-cell-evidence.v1",
            "status": "PASS",
            "role": role,
            "cell": cell,
            "job": ci.JOB_IDS[role],
            "invocation": {"run": PR["run"], "attempt": PR["attempt"], "repository": REPO["id"], "sha": SYNTHETIC},
            "event": "pull_request",
            "pr": PULL,
            "source": CHECKOUT,
            "workflowRef": f"{ci.REPOSITORY}/{ci.WORKFLOW}@refs/pull/{PR['number']}/merge",
            "workflowSha": SYNTHETIC,
            "environment": OBSERVED,
            "members": {member: ci.sha256(raw) for member, raw in members.items()},
            "quality": quality,
        }
        members["cell-evidence.json"] = ci.json_bytes(receipt)
        raw = zipped(list(members.items()))
        identifier = 2000 + number
        self.artifacts.append(
            provider_artifact(
                ci.artifact_name("pr-ci", PR["run"], PR["attempt"], key),
                identifier,
                raw,
                PR,
                HEAD,
                job["id"],
            )
        )
        self.archives[str(identifier)] = raw

    def open(self, request, *, timeout):
        assert 0 < timeout <= 10
        self.requests.append((request.full_url, request.get_header("Authorization")))
        url = request.full_url
        if url.startswith(self.api.base):
            path = url[len(self.api.base) :]
            if path.endswith("/zip"):
                identifier = path.split("/")[-2]
                headers = {"Location": f"https://productionresultssa1.blob.core.windows.net/results/{identifier}"}
                raise urllib.error.HTTPError(url, 302, "redirect", headers, io.BytesIO())
            return io.BytesIO(ci.json_bytes(self.routes[path]))
        return io.BytesIO(self.archives[url.rsplit("/", 1)[1]])


class CurrentFixture(ProviderFixture):
    def __init__(self, status="CANDIDATE") -> None:
        super().__init__()
        self.blocked = set()
        self.interrupted = set()
        evidence, _ = ci.find_candidate(self.api, MAIN, SOURCE)
        self.index = {"schemaVersion": "alk-ci-qualification-index.v1", "main": MAIN, "source": SOURCE, **evidence}
        if status == "UNAVAILABLE":
            self.index = {
                "schemaVersion": "alk-ci-qualification-index.v1",
                "main": MAIN,
                "source": SOURCE,
                "status": "UNAVAILABLE",
                "reason": "no exact PR association",
            }
        self.digest = ci.sha256(ci.json_bytes(self.index))
        self.api = ci.GitHub(ci.REPOSITORY, "unit-token", now=NOW)
        self.api.opener = self
        self.requests = []
        self.blocked = set()
        self.interrupted = set()
        self.current_jobs = []
        self.current_artifacts = []
        self.reports = {}
        self.routes[f"/actions/runs/{MAIN['run']}/attempts/{MAIN['attempt']}/jobs?per_page=100"] = {
            "total_count": 0,
            "jobs": self.current_jobs,
        }
        self.routes[f"/actions/runs/{MAIN['run']}/artifacts?per_page=100"] = {
            "total_count": 0,
            "artifacts": self.current_artifacts,
        }
        candidate_job = provider_job(
            ci.CANDIDATE_JOB,
            7000,
            [ci.CANDIDATE_GENERATION, ci.CANDIDATE_UPLOAD, ci.UPLOAD_LOG + "success"],
            MAIN,
            MAIN["sha"],
        )
        self.current_jobs.append(candidate_job)
        self.add_artifact(None, 8000, {"reuse-candidate.json": self.index}, candidate_job)
        if status == "CANDIDATE":
            for number, key in enumerate(ci.CELLS, 1):
                quality = None
                if key.startswith("quality/"):
                    quality = {
                        "status": "PASS",
                        "changedAfterChecks": False,
                        "commands": [
                            {"id": name, "returncode": 0, "argv": argv}
                            for name, argv in ci.quality_commands(
                                "/runner/.venv/bin/python",
                                ci.CANDIDATE_PATH,
                                self.digest,
                                ci.CELLS[key][1],
                                MAIN["sha"],
                            ).items()
                        ],
                        "receipts": {
                            "runner": "d" * 64,
                            "validator": "e" * 64,
                            "binding": quality_binding(self.index, self.digest, key),
                        },
                    }
                report = {
                    "schemaVersion": "alk-ci-probe.v1",
                    "status": "MATCH",
                    "main": MAIN,
                    "cell": key,
                    "indexSha256": self.digest,
                    "environment": OBSERVED,
                    "producer": self.index["cells"][key],
                    "quality": quality,
                }
                self.reports[key] = report
                job = provider_job(
                    ci.probe_name(key),
                    7100 + number,
                    [ci.PROBE, ci.PROBE_UPLOAD, ci.UPLOAD_LOG + "success"],
                    MAIN,
                    MAIN["sha"],
                )
                self.current_jobs.append(job)
                self.add_artifact(key, 8100 + number, {"probe.json": report}, job)
        self.sync_counts()

    def reset_api(self):
        self.api = ci.GitHub(ci.REPOSITORY, "unit-token", now=NOW)
        self.api.opener = self
        self.requests = []

    def sync_counts(self):
        self.routes[f"/actions/runs/{MAIN['run']}/attempts/{MAIN['attempt']}/jobs?per_page=100"]["total_count"] = len(
            self.current_jobs
        )
        self.routes[f"/actions/runs/{MAIN['run']}/artifacts?per_page=100"]["total_count"] = len(self.current_artifacts)

    def name(self, key):
        return ci.artifact_name("main-candidate" if key is None else "main-probe", MAIN["run"], MAIN["attempt"], key)

    def artifact(self, key):
        return next(row for row in self.current_artifacts if row["name"] == self.name(key))

    def job(self, key):
        return next(
            row for row in self.current_jobs if row["name"] == (ci.CANDIDATE_JOB if key is None else ci.probe_name(key))
        )

    def add_artifact(self, key, identifier, members, job):
        raw = zipped([(name, ci.json_bytes(body)) for name, body in members.items()])
        self.archives[str(identifier)] = raw
        self.current_artifacts.append(provider_artifact(self.name(key), identifier, raw, MAIN, MAIN["sha"], job["id"]))

    def remove(self, key):
        self.current_artifacts.remove(self.artifact(key))
        self.sync_counts()

    def update_report(self, key):
        row = self.artifact(key)
        raw = zipped([("probe.json", ci.json_bytes(self.reports[key]))])
        row.update(digest="sha256:" + ci.sha256(raw), size_in_bytes=len(raw))
        self.archives[str(row["id"])] = raw

    def open(self, request, *, timeout):
        if request.full_url in self.blocked:
            raise urllib.error.URLError("unit transport unavailable")
        if request.full_url.rsplit("/", 1)[-1] in self.interrupted and not request.full_url.startswith(self.api.base):
            raise http.client.IncompleteRead(b"partial archive")
        return super().open(request, timeout=timeout)

    def add_main_full(self):
        for number, (key, (role, cell, name)) in enumerate(ci.CELLS.items(), 1):
            steps = [
                ci.PREPARE,
                "Restore versioned release test fixture",
                *ci.SUITE_STEPS[role],
                ci.RECORD,
                ci.CELL_UPLOAD,
            ]
            if ci.is_windows315(role, cell):
                steps.extend((ci.BACKEND, ci.BACKEND_AFTER))
            job = provider_job(name, 9000 + number, steps, MAIN, MAIN["sha"])
            self.current_jobs.append(job)
            raw = zipped([("fresh.json", b"{}")])
            self.current_artifacts.append(
                provider_artifact(
                    ci.artifact_name("main-full", MAIN["run"], MAIN["attempt"], key),
                    10000 + number,
                    raw,
                    MAIN,
                    MAIN["sha"],
                    job["id"],
                )
            )
        for name, identifier, steps in (
            (ci.DECISION_JOB, 12000, [ci.DECISION_STEP]),
            (
                ci.MAIN_CHECKS_JOB,
                12001,
                [
                    *ci.MAIN_GATES,
                    "Validate CI security and test discovery",
                    "Validate skill parity",
                    "Build exact main distributions",
                    "Smoke-test those distributions",
                    ci.MAIN_CHECKS_UPLOAD,
                ],
            ),
        ):
            self.current_jobs.append(provider_job(name, identifier, steps, MAIN, MAIN["sha"]))
        raw = zipped([("main-package-build.json", b"{}"), ("main-packaging-smoke.json", b"{}")])
        self.current_artifacts.append(
            provider_artifact(
                ci.artifact_name("main-checks", MAIN["run"], MAIN["attempt"]), 12002, raw, MAIN, MAIN["sha"], 12001
            )
        )
        self.sync_counts()


def valid_index() -> tuple[dict, dict[str, bytes]]:
    fixture = ProviderFixture()
    evidence, coverage = ci.find_candidate(fixture.api, MAIN, SOURCE)
    return {"schemaVersion": "alk-ci-qualification-index.v1", "main": MAIN, "source": SOURCE, **evidence}, coverage


def quality_binding(index: dict, digest: str, key: str) -> dict:
    row = index["cells"][key]
    return {
        "indexSha256": digest,
        "cell": key,
        "coverageSha256": row["coverageSha256"],
        "environmentSha256": row["environmentSha256"],
        "main": MAIN,
        "sourceTree": TREE,
        "policySha256": SOURCE["inputs"][ci.POLICY],
        "producer": {**index["pr"], "job": row["job"], "artifact": row["artifact"]},
    }


class CiEvidenceReuseTests(unittest.TestCase):
    def test_prepare_publishes_console_scripts_for_later_step_lookup(self):
        real_run = ci.subprocess.run
        for role in ("ci", "foundation", "quality", "main"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                venv = ci.cell_python(root)
                console = venv.parent / ("agent-lifecycle.exe" if ci.os.name == "nt" else "agent-lifecycle")
                env_file, path_file = root / "github-env", root / "github-path"
                env_file.write_text("PRIOR=yes\n", encoding="utf-8")
                path_file.write_text("prior-registered\n", encoding="utf-8")
                calls = []

                def install(argv, **kwargs):
                    calls.append(argv)
                    self.assertEqual(env_file.read_text(encoding="utf-8"), "PRIOR=yes\n")
                    self.assertEqual(path_file.read_text(encoding="utf-8"), "prior-registered\n")
                    if argv[:2] == ["uv", "sync"]:
                        venv.parent.mkdir(parents=True)
                        venv.write_text("prepared interpreter", encoding="utf-8")
                    if "-e" in argv:
                        console.write_text("prepared console script", encoding="utf-8")
                        console.chmod(0o700)

                expected_uv = "0.12.5" if role == "quality" else "0.13.1"
                with (
                    mock.patch.dict(os.environ, {"GITHUB_ENV": str(env_file), "GITHUB_PATH": str(path_file)}),
                    mock.patch.object(ci, "command_output", return_value="uv " + expected_uv),
                    mock.patch.object(ci.subprocess, "run", side_effect=install),
                ):
                    ci.prepare(root, ci.sys.executable, role)
                self.assertEqual(
                    calls[-1],
                    ["uv", "pip", "install", "--python", str(venv), "--no-deps", "--no-build-isolation", "-e", "."],
                )
                self.assertEqual(path_file.read_text(encoding="utf-8"), "prior-registered\n" + str(venv.parent) + "\n")
                self.assertEqual(env_file.read_text(encoding="utf-8"), "PRIOR=yes\nCELL_VENV_PYTHON=" + str(venv) + "\n")
                child_env = dict(os.environ)
                child_env.pop("ALK_EXTERNAL_CONSUMER_EXECUTABLE", None)
                child_env.pop("PYTHONPATH", None)
                child_env["PATH"] = str(venv.parent) + os.pathsep + child_env.get("PATH", "")
                checked = real_run(
                    [ci.sys.executable, "-I", "-c", "import shutil; print(shutil.which('agent-lifecycle') or '')"],
                    cwd=root, env=child_env, text=True, capture_output=True, check=True, timeout=10,
                )
                self.assertEqual(Path(checked.stdout.strip()).resolve(), console.resolve())
                self.assertEqual(Path(shutil.which("agent-lifecycle", path=child_env["PATH"])).resolve(), console.resolve())

    def test_prepare_rejects_missing_cli_and_failed_install_before_native_exports(self):
        for defect in ("missing-cli", "editable-failure"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                venv = ci.cell_python(root)
                env_file, path_file = root / "github-env", root / "github-path"
                env_file.write_text("PRIOR=yes\n", encoding="utf-8")
                path_file.write_text("prior-registered\n", encoding="utf-8")

                def install(argv, **kwargs):
                    if argv[:2] == ["uv", "sync"]:
                        venv.parent.mkdir(parents=True)
                        venv.write_text("prepared interpreter", encoding="utf-8")
                    if "-e" in argv and defect == "editable-failure":
                        raise ci.subprocess.CalledProcessError(1, argv)

                expected = ci.subprocess.CalledProcessError if defect == "editable-failure" else ci.ProofError
                with (
                    mock.patch.dict(os.environ, {"GITHUB_ENV": str(env_file), "GITHUB_PATH": str(path_file)}),
                    mock.patch.object(ci, "command_output", return_value="uv 0.13.1"),
                    mock.patch.object(ci.subprocess, "run", side_effect=install),
                    self.assertRaises(expected),
                ):
                    ci.prepare(root, ci.sys.executable, "ci")
                self.assertEqual(env_file.read_text(encoding="utf-8"), "PRIOR=yes\n")
                self.assertEqual(path_file.read_text(encoding="utf-8"), "prior-registered\n")

    def test_prepare_rejects_reported_line_breaks_before_native_exports(self):
        for separator in ("\n", "\r"):
            with self.subTest(separator=repr(separator)), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                actual_venv = ci.cell_python(root)
                env_file, path_file = root / "github-env", root / "github-path"
                env_file.write_text("PRIOR=yes\n", encoding="utf-8")
                path_file.write_text("prior-registered\n", encoding="utf-8")
                reported_scripts = mock.MagicMock(spec=Path)
                reported_scripts.is_absolute.return_value = True
                reported_scripts.__str__.return_value = str(actual_venv.parent) + separator + "reported"
                reported_venv = mock.MagicMock(spec=Path)
                reported_venv.parent = reported_scripts
                reported_venv.is_file.return_value = True
                reported_venv.__str__.return_value = str(actual_venv) + separator + "reported"
                with (
                    mock.patch.dict(os.environ, {"GITHUB_ENV": str(env_file), "GITHUB_PATH": str(path_file)}),
                    mock.patch.object(ci, "cell_python", return_value=reported_venv),
                    mock.patch.object(ci, "command_output", return_value="uv 0.13.1"),
                    mock.patch.object(ci.subprocess, "run", return_value=mock.Mock(returncode=0)),
                    self.assertRaisesRegex(ci.ProofError, "invalid sealed cell script directory"),
                ):
                    ci.prepare(root, ci.sys.executable, "ci")
                self.assertEqual(env_file.read_text(encoding="utf-8"), "PRIOR=yes\n")
                self.assertEqual(path_file.read_text(encoding="utf-8"), "prior-registered\n")
                reported_scripts.__truediv__.assert_not_called()
                self.assertFalse((root / ".venv").exists())

    def test_positive_exact_attempt_squash_empty_run_association_and_budget(self) -> None:
        fixture = ProviderFixture()
        evidence, coverages = ci.find_candidate(fixture.api, MAIN, SOURCE)
        self.assertEqual(evidence["status"], "CANDIDATE")
        self.assertEqual(evidence["tested"], CHECKOUT)
        self.assertEqual(evidence["pr"], PR)
        self.assertEqual(set(evidence["cells"]), set(ci.CELLS))
        self.assertEqual(set(coverages), {key for key in ci.CELLS if key.startswith("quality/")})
        self.assertEqual(evidence["provider"], {"authenticated": 36, "total": 61})
        self.assertTrue(
            all(
                (authorization == "Bearer " + "unit-token") == url.startswith(fixture.api.base)
                for url, authorization in fixture.requests
            )
        )
        self.assertEqual(sum(url.endswith("/zip") for url, _ in fixture.requests), 25)
        self.assertFalse(any(re.search(r"/artifacts/\d+$", url) for url, _ in fixture.requests))

    def test_normal_merge_uses_the_same_tested_tree(self) -> None:
        fixture = ProviderFixture()
        evidence, _ = ci.find_candidate(fixture.api, MAIN, {**SOURCE, "parents": [BASE, HEAD]})
        self.assertEqual(evidence["tested"], CHECKOUT)

    def test_untrusted_stale_partial_mismatched_or_corrupt_evidence_is_refused(self) -> None:
        for case in (
            "fork",
            "permission",
            "trigger",
            "stale",
            "missing",
            "cross-attempt",
            "wrong-tree",
            "ambiguous",
            "wrong-job",
            "duplicate",
            "digest",
            "upload-window",
            "cancelled",
        ):
            with self.subTest(case=case):
                fixture = ProviderFixture()
                if case == "fork":
                    fixture.pull["head"] = {"sha": HEAD, "repo": {**REPO, "fork": True}}
                elif case == "permission":
                    fixture.routes[f"/collaborators/{ACTOR['login']}/permission"]["permission"] = "read"
                elif case == "trigger":
                    fixture.run["triggering_actor"] = {**ACTOR, "id": 66}
                elif case == "stale":
                    fixture.run["updated_at"] = "2026-10-01T11:00:00Z"
                elif case == "missing":
                    fixture.artifacts.pop()
                elif case == "cross-attempt":
                    fixture.jobs[0]["run_attempt"] = 1
                elif case == "wrong-tree":
                    fixture.routes[f"/git/commits/{SYNTHETIC}"]["tree"]["sha"] = "0" * 40
                elif case == "ambiguous":
                    fixture.routes[f"/commits/{MAIN['sha']}/pulls?per_page=100"].append(fixture.pull)
                elif case == "wrong-job":
                    fixture.artifacts[0]["job_id"] = fixture.jobs[1]["id"]
                elif case == "duplicate":
                    fixture.artifacts[1]["name"] = fixture.artifacts[0]["name"]
                elif case == "digest":
                    fixture.artifacts[0]["digest"] = "sha256:" + "0" * 64
                elif case == "upload-window":
                    fixture.artifacts[0]["created_at"] = "2026-10-12T10:59:59Z"
                elif case == "cancelled":
                    fixture.run["conclusion"] = "cancelled"
                with self.assertRaises(ci.ProofError):
                    ci.find_candidate(fixture.api, MAIN, SOURCE)

    def test_archive_and_json_are_closed_and_bounded(self) -> None:
        good = b'{"a":1}'
        link = zipfile.ZipInfo("proof.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = (
            [("../proof.json", good)],
            [("proof.json", b'{"x":1,"x":2}')],
            [("proof.json", b'{"x":1e999}')],
            [("proof.json", good), ("proof.json", good)],
            [("proof.json", good), ("extra.json", good)],
            [(link, good)],
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for index, members in enumerate(cases):
                with self.subTest(index=index), self.assertRaises(ci.ProofError):
                    ci.archive_members(zipped(members), {"proof.json"}, 1024)
        with self.assertRaises(ci.ProofError):
            ci.archive_members(zipped([("proof.json", good)]), {"proof.json"}, 4)
        self.assertEqual(ci.archive_members(zipped([("proof.json", good)]), {"proof.json"}, 1024), {"proof.json": good})

    def test_provider_budget_counts_metadata_archive_and_members_together(self) -> None:
        payload = b'{"result":"verified"}'
        raw = zipped([("proof.json", payload)])
        api = ci.GitHub(ci.REPOSITORY, "unit-token", now=NOW)
        self.assertEqual(api._read(io.BytesIO(b"{}"), ci.MAX_FILE), b"{}")
        artifact = {
            "id": 9,
            "archive_download_url": f"{api.base}/actions/artifacts/9/zip",
            "size_in_bytes": len(raw),
            "digest": "sha256:" + ci.sha256(raw),
        }
        with mock.patch.object(
            api, "_download_archive", side_effect=lambda _url: api._read(io.BytesIO(raw), ci.MAX_FILE)
        ):
            self.assertEqual(api.archive(artifact, {"proof.json"}), {"proof.json": payload})
        self.assertEqual(api.input_bytes, 2 + len(raw) + len(payload))
        with (
            mock.patch.object(ci, "MAX_TOTAL", api.input_bytes + 1),
            self.assertRaisesRegex(ci.ProofError, "byte budget"),
        ):
            api._read(io.BytesIO(b"{}"), ci.MAX_FILE)

    def test_directory_count_verified_before_zip_member_allocation(self) -> None:
        raw = zipped([("proof.json", b"{}"), ("extra.json", b"{}")])
        unpack = ci.struct.unpack_from

        def reported_single_entry(fmt, buffer, offset):
            fields = unpack(fmt, buffer, offset)
            if fmt == "<4s4H2LH":
                return (*fields[:3], 1, 1, *fields[5:])
            return fields

        with (
            mock.patch.object(ci.struct, "unpack_from", side_effect=reported_single_entry),
            mock.patch.object(ci.zipfile, "ZipFile") as open_zip,
            self.assertRaisesRegex(ci.ProofError, "directory count"),
        ):
            ci.archive_members(raw, {"proof.json"}, 1024)
        open_zip.assert_not_called()

    def test_storage_origins_never_receive_authorization(self) -> None:
        for url in (
            "http://productionresultssa1.blob.core.windows.net/results/x",
            "https://productionresultssa1.blob.core.windows.net.example.test/x",
            urllib.parse.urlunsplit(("https", "@productionresultssa1.blob.core.windows.net", "/results/x", "", "")),
            "https://outside.test/x",
        ):
            with self.subTest(url=url), self.assertRaises(ci.ProofError):
                ci.storage_url(url)

    def test_qualified_consumers_bind_index_cell_attempt_policy_and_raw_coverage(self) -> None:
        index, coverage = valid_index()
        key = "quality/ubuntu-latest-py3.14"
        cell = ci.CELLS[key][1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            raw_index = root / "index.json"
            raw_coverage = root / "coverage.json"
            digest = ci.write_object(raw_index, index)
            raw_coverage.write_bytes(coverage[key])
            args = ci.QualityInputs(raw_index, digest, cell, raw_coverage)
            event = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_JOB": "probe-quality",
                "CI_CELL": cell,
                "QUALIFIED_INDEX_SHA256": digest,
            }
            with (
                mock.patch.dict(os.environ, event, clear=True),
                mock.patch.object(ci, "main_context", return_value=(MAIN, SOURCE)),
                mock.patch.object(ci, "observed_environment", return_value=OBSERVED),
            ):
                raw, binding = ci.qualification_binding(root, root / ci.POLICY, args)
                self.assertEqual(raw, coverage[key])
                self.assertEqual(binding, quality_binding(index, digest, key))
                with self.assertRaises(ci.ProofError):
                    ci.qualification_binding(root, root / "wrong-policy.json", args)
                for change in (("digest", "0" * 64), ("cell", "ubuntu-latest-py3.11")):
                    altered = copy.copy(args)
                    setattr(altered, *change)
                    with self.assertRaises(ci.ProofError):
                        ci.qualification_binding(root, root / ci.POLICY, altered)
                raw_coverage.write_bytes(coverage["quality/ubuntu-latest-py3.11"])
                with self.assertRaisesRegex(ci.ProofError, "coverage JSON digest"):
                    ci.qualification_binding(root, root / ci.POLICY, args)
                raw_coverage.write_bytes(coverage[key])
                with (
                    mock.patch.object(ci, "main_context", return_value=({**MAIN, "attempt": 3}, SOURCE)),
                    self.assertRaises(ci.ProofError),
                ):
                    ci.qualification_binding(root, root / ci.POLICY, args)
                with (
                    mock.patch.object(ci, "observed_environment", return_value=UNAVAILABLE),
                    self.assertRaises(ci.EnvironmentMismatch),
                ):
                    ci.qualification_binding(root, root / ci.POLICY, args)

    def decide_fixture(self, fixture, root, name="decision.json", needs=None):
        if needs is None:
            result = "success" if fixture.index["status"] == "CANDIDATE" else "skipped"
            needs = {"candidate": {"result": "success"}, **{f"probe-{role}": {"result": result} for role in ci.ROLES}}
        with (
            mock.patch.dict(
                os.environ,
                {
                    "GH_TOKEN": fixture.api.token,
                    "QUALIFIED_INDEX_SHA256": fixture.digest,
                    "CANDIDATE_STATUS": fixture.index["status"],
                    "CANDIDATE_GENERATION_OUTCOME": "success",
                },
            ),
            mock.patch.object(ci, "main_context", return_value=(MAIN, SOURCE)),
            mock.patch.object(ci, "native_output"),
            mock.patch.object(ci, "GitHub", return_value=fixture.api),
        ):
            ci.decide(root, root / "missing-index.json", root / "missing-probes", root / name, needs)
        return ci.decision_proof(ci.read_object(root / name), MAIN, SOURCE)

    def test_candidate_unavailable_requires_deliberate_probe_skip_and_full(self):
        fixture = CurrentFixture("UNAVAILABLE")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.decide_fixture(fixture, root)["mode"], "FULL")
            needs = {
                "candidate": {"result": "success"},
                **{f"probe-{role}": {"result": "skipped"} for role in ci.ROLES},
            }
            needs["probe-ci"]["result"] = "success"
            with self.assertRaises(ci.ProofError):
                self.decide_fixture(fixture, root, "bad.json", needs)

    def test_complete_probes_choose_reuse_and_one_late_mismatch_selects_global_full(self):
        fixture = CurrentFixture()
        key = "quality/ubuntu-latest-py3.14"
        fixture.reports[key]["status"] = "MISMATCH"
        fixture.reports[key]["quality"].update(status="MISMATCH", receipts=None)
        fixture.reports[key]["quality"]["commands"][-1]["returncode"] = 3
        fixture.update_report(key)
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
            self.assertEqual(decision["mode"], "FULL")
            self.assertFalse(decision["probes"][key]["matched"])

    def test_decide_candidate_archive_unavailable_selects_full_without_local_inputs(self):
        for failure in ("absent", "outage"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                if failure == "absent":
                    fixture.remove(None)
                else:
                    fixture.blocked.add(fixture.artifact(None)["archive_download_url"])
                root = Path(directory)
                decision = self.decide_fixture(fixture, root)
                self.assertEqual(decision["mode"], "FULL")
                self.assertFalse(decision["transport"]["indexVerified"])
                self.assertIsNone(decision["pr"])
                self.assertTrue(all(row["matched"] is None for row in decision["probes"].values()))
                self.assertFalse((root / "missing-index.json").exists())

    def test_decide_probe_archive_unavailable_selects_global_full(self):
        fixture = CurrentFixture()
        key = next(iter(ci.CELLS))
        fixture.blocked.add(fixture.artifact(key)["archive_download_url"])
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
        self.assertEqual(decision["mode"], "FULL")
        self.assertEqual(decision["transport"]["missingCells"], [key])
        self.assertNotIn(key, decision["probes"])
        self.assertEqual(len(decision["probes"]), 24)

    def test_partial_probe_transport_preserves_only_verified_rows(self):
        fixture = CurrentFixture()
        missing = list(ci.CELLS)[::3]
        for key in missing:
            fixture.remove(key)
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
        self.assertEqual(set(decision["transport"]["missingCells"]), set(missing))
        self.assertEqual(set(decision["probes"]), set(ci.CELLS) - set(missing))
        self.assertTrue(
            all(ci.positive_id(row["job"]) and ci.positive_id(row["artifact"]) for row in decision["probes"].values())
        )

    def test_partial_http_download_never_becomes_verified_json(self):
        fixture = CurrentFixture()
        fixture.interrupted.add(str(fixture.artifact(None)["id"]))
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
        self.assertFalse(decision["transport"]["indexVerified"])
        self.assertIn("IncompleteRead", decision["transport"]["failures"][0]["reason"])

    def test_probe_input_transport_unavailable_emits_source_bound_unavailable(self):
        key = "quality/ubuntu-latest-py3.14"
        for failed_input in ("candidate", "coverage"):
            with self.subTest(failed_input=failed_input), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                if failed_input == "candidate":
                    fixture.remove(None)
                else:
                    fixture.blocked.add(f"{fixture.api.base}/actions/runs/{PR['run']}/artifacts?per_page=100")
                root = Path(directory)
                with (
                    mock.patch.dict(
                        os.environ,
                        {
                            "GH_TOKEN": fixture.api.token,
                            "GITHUB_JOB": "probe-quality",
                            "CANDIDATE_STATUS": "CANDIDATE",
                            "QUALIFIED_INDEX_SHA256": fixture.digest,
                            "CANDIDATE_GENERATION_OUTCOME": "success",
                        },
                    ),
                    mock.patch.object(ci, "main_context", return_value=(MAIN, SOURCE)),
                    mock.patch.object(ci, "GitHub", return_value=fixture.api),
                    mock.patch.object(ci, "probe_quality") as static,
                ):
                    ci.probe(root, "quality", ci.CELLS[key][1], root / "index.json", root / "probe.json")
                report = ci.read_object(root / "probe.json")
                self.assertTrue(ci.unavailable_probe(report, key, MAIN, SOURCE, fixture.digest))
                self.assertIsNone(report["quality"])
                static.assert_not_called()

    def test_optional_sender_upload_failure_preserves_outcome_and_full_route(self):
        for key in (None, next(iter(ci.CELLS))):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                marker = fixture.job(key)["steps"][-1]
                marker["name"] = ci.UPLOAD_LOG + "failure"
                # REST conclusion remains success. The reviewed marker captures raw steps.outcome.
                self.assertEqual(marker["conclusion"], "success")
                decision = self.decide_fixture(fixture, Path(directory))
                self.assertEqual(decision["mode"], "FULL")
                self.assertTrue(
                    any(row["phase"] == "sender" and row["cell"] == key for row in decision["transport"]["failures"])
                )

    def test_available_corrupt_candidate_or_probe_still_fails(self):
        first, last = list(ci.CELLS)[0], list(ci.CELLS)[-1]
        for case in (
            "missing-probe-corrupt-index",
            "missing-probe-corrupt-probe",
            "missing-index-corrupt-probe",
            "missing-probe-static-failure",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                if case.startswith("missing-index"):
                    fixture.remove(None)
                else:
                    fixture.remove(first)
                if case.endswith("corrupt-index"):
                    fixture.artifact(None)["digest"] = "sha256:" + "0" * 64
                elif case.endswith("static-failure"):
                    fixture.reports[last]["quality"]["commands"][-1]["returncode"] = 1
                    fixture.update_report(last)
                else:
                    fixture.artifact(last)["digest"] = "sha256:" + "0" * 64
                with self.assertRaises(ci.ProofError):
                    self.decide_fixture(fixture, Path(directory))

    def test_actual_static_failure_and_setup_failure_never_become_full_success(self):
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                fixture.blocked.add(f"{fixture.api.base}/actions/runs/{MAIN['run']}/artifacts?per_page=100")
                needs = {
                    "candidate": {"result": "success"},
                    **{f"probe-{role}": {"result": "success"} for role in ci.ROLES},
                }
                needs["probe-quality"]["result"] = result
                with self.assertRaises(ci.ProofError):
                    self.decide_fixture(fixture, Path(directory), needs=needs)
        with mock.patch.dict(os.environ, {"CANDIDATE_GENERATION_OUTCOME": "failure"}):
            with self.assertRaises(ci.ProofError):
                ci.native_candidate()

    def test_full_transport_terminal_joins_fresh_suites_without_optional_reuse_artifacts(self):
        fixture = CurrentFixture()
        fixture.remove(None)
        missing = next(iter(ci.CELLS))
        fixture.remove(missing)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            decision = self.decide_fixture(fixture, root)
            fixture.add_main_full()
            fixture.reset_api()
            jobs = {row["name"]: row for row in fixture.current_jobs}
            artifacts = {row["name"]: row for row in fixture.current_artifacts}
            graph = ci.main_job_graph(fixture.api, MAIN, decision, jobs, artifacts)
            self.assertEqual(set(graph["freshSuites"]), set(ci.CELLS))
            main_checks = root / "checks"
            main_checks.mkdir()
            for name in ("main-package-build.json", "main-packaging-smoke.json"):
                (main_checks / name).write_bytes(b"{}")
            needs = {
                name: {"result": "success"} for name in ("candidate", "decide", "main-checks", *ci.JOB_IDS.values())
            }
            fixture.reset_api()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GH_TOKEN": fixture.api.token,
                        "MAIN_MODE": "FULL",
                        "MAIN_DECISION_SHA256": ci.sha256((root / "decision.json").read_bytes()),
                        "QUALIFIED_INDEX_SHA256": fixture.digest,
                        "CANDIDATE_STATUS": "CANDIDATE",
                        "CANDIDATE_GENERATION_OUTCOME": "success",
                    },
                ),
                mock.patch.object(ci, "main_context", return_value=(MAIN, SOURCE)),
                mock.patch.object(ci, "GitHub", return_value=fixture.api),
                mock.patch.object(ci, "main_checks_evidence", return_value={"fixture": "validated separately"}),
            ):
                ci.terminal(root, root / "decision.json", main_checks, root / "terminal.json", needs)
            self.assertEqual(ci.read_object(root / "terminal.json")["completeSuitesRun"], 25)
            jobs[ci.CELLS[missing][2]]["conclusion"] = "failure"
            with self.assertRaises(ci.ProofError):
                ci.main_job_graph(fixture.api, MAIN, decision, jobs, artifacts)

    def test_missing_probe_does_not_hide_corrupt_provider_recheck(self):
        for change, ordinary in (
            ({"head_sha": "0" * 40}, False),
            ({"updated_at": "invalid-time"}, False),
            ({"run_attempt": 3}, True),
            ({"conclusion": "cancelled"}, True),
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                fixture = CurrentFixture()
                fixture.remove(next(iter(ci.CELLS)))
                fixture.routes[f"/actions/runs/{PR['run']}"] = {**fixture.run, **change}
                if ordinary:
                    self.assertEqual(self.decide_fixture(fixture, Path(directory))["mode"], "FULL")
                else:
                    with self.assertRaises(ci.ProofError):
                        self.decide_fixture(fixture, Path(directory))

    def test_transport_full_cannot_be_promoted_to_qualified_reuse(self):
        fixture = CurrentFixture()
        fixture.remove(next(iter(ci.CELLS)))
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
        with self.assertRaises(ci.ProofError):
            ci.decision_proof({**decision, "mode": "QUALIFIED_REUSE"}, MAIN, SOURCE)

    def test_complete_transport_positive_keeps_exact_all_25_reuse_bindings(self):
        fixture = CurrentFixture()
        with tempfile.TemporaryDirectory() as directory:
            decision = self.decide_fixture(fixture, Path(directory))
        self.assertEqual(decision["mode"], "QUALIFIED_REUSE")
        legacy = {key: value for key, value in decision.items() if key != "transport"}
        self.assertEqual(ci.decision_proof(legacy, MAIN, SOURCE)["mode"], "QUALIFIED_REUSE")
        self.assertEqual(set(decision["probes"]), set(ci.CELLS))
        self.assertTrue(
            all(
                row["matched"] is True and ci.positive_id(row["job"]) and ci.positive_id(row["artifact"])
                for row in decision["probes"].values()
            )
        )
        self.assertEqual((fixture.api.auth_requests, fixture.api.total_requests), (29, 55))

    def test_current_transport_route_remains_inside_provider_budget(self):
        fixture = CurrentFixture()
        key = "quality/ubuntu-latest-py3.14"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GH_TOKEN": fixture.api.token,
                        "GITHUB_JOB": "probe-quality",
                        "CANDIDATE_STATUS": "CANDIDATE",
                        "QUALIFIED_INDEX_SHA256": fixture.digest,
                        "CANDIDATE_GENERATION_OUTCOME": "success",
                    },
                ),
                mock.patch.object(ci, "main_context", return_value=(MAIN, SOURCE)),
                mock.patch.object(ci, "GitHub", return_value=fixture.api),
                mock.patch.object(ci, "observed_environment", return_value=OBSERVED),
                mock.patch.object(ci, "probe_quality", return_value={"status": "PASS"}),
            ):
                ci.probe(root, "quality", ci.CELLS[key][1], root / "index.json", root / "probe.json")
            original = ProviderFixture()
            expected = original.archives[str(fixture.index["cells"][key]["artifact"])]
            expected = ci.archive_members(
                expected, {"cell-evidence.json", "tests.json", "coverage.json"}, ci.MAX_TOTAL
            )["coverage.json"]
            self.assertEqual(ci.coverage_input(root / "index.json", ci.CELLS[key][1]).read_bytes(), expected)
        self.assertEqual((fixture.api.auth_requests, fixture.api.total_requests), (5, 7))
        self.assertTrue(
            all(
                (authorization == "Bearer " + "unit-token") == url.startswith(fixture.api.base)
                for url, authorization in fixture.requests
            )
        )

    def test_workflow_optional_tolerance_is_an_exact_sender_allowlist(self):
        workflow = (ROOT / ci.WORKFLOW).read_text(encoding="utf-8")
        jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow.split("jobs:\n", 1)[1]))
        allowed = {"candidate", "probe-ci", "probe-foundation", "probe-quality"}
        for name, block in jobs.items():
            tolerances = block.count("continue-on-error:")
            self.assertEqual(tolerances, 1 if name in allowed else 0, name)
            if name in allowed:
                self.assertIn("        id: evidence-upload\n        continue-on-error: true", block)
                self.assertIn("steps.evidence-upload.outcome", block)
                self.assertIn("EVIDENCE_UPLOAD_OUTCOME:", block)
            if name.startswith("probe-") or name == "decide":
                self.assertNotIn("actions/download-artifact@", block)
        self.assertIn("generation_outcome: ${{ steps.candidate.outcome }}", jobs["candidate"])

    def test_publication_refuses_control_and_wrong_attempt_even_for_exact_source(self) -> None:
        fixture = ProviderFixture()
        push = {**fixture.run, "event": "push", "head_sha": MAIN["sha"], "head_branch": "main"}
        endpoint = (
            f"/actions/workflows/{PR['workflow']}/runs?event=push&branch=main&head_sha={MAIN['sha']}&per_page=100"
        )
        fixture.routes[endpoint] = {"total_count": 1, "workflow_runs": [push]}
        attempt = f"/actions/runs/{PR['run']}/attempts/{PR['attempt']}"
        fixture.routes[attempt] = push.copy()
        self.assertEqual(
            ci.verified_push_run(fixture.api, PR["workflow"], ci.WORKFLOW, MAIN["sha"], REPO["id"]),
            (PR["run"], PR["attempt"]),
        )
        for changes in (
            {"event": "workflow_dispatch"},
            {"event": "pull_request"},
            {"run_attempt": 1},
            {"head_branch": "other"},
            {"conclusion": "failure"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ci.ProofError):
                fixture.routes[attempt] = {**push, **changes}
                ci.verified_push_run(fixture.api, PR["workflow"], ci.WORKFLOW, MAIN["sha"], REPO["id"])

    def test_workflow_routes_preserve_pr_full_and_gate_push_families_on_one_decision(self) -> None:
        workflow = (ROOT / ci.WORKFLOW).read_text(encoding="utf-8")
        jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow.split("jobs:\n", 1)[1]))
        for name in ci.JOB_IDS.values():
            job = jobs[name]
            self.assertIn("needs: [decide, control]", job)
            self.assertIn("github.event_name == 'pull_request'", job)
            self.assertIn("github.event_name == 'push' && needs.decide.result == 'success'", job)
            self.assertIn("needs.decide.outputs.mode == 'FULL'", job)
            self.assertIn("github.event_name == 'workflow_dispatch' && needs.control.result == 'success'", job)
        for name in ("candidate", "probe-ci", "probe-foundation", "probe-quality", "decide", "main-qualification"):
            self.assertIn("github.event_name == 'push'", jobs[name])
        self.assertIn("needs: [candidate, probe-ci, probe-foundation, probe-quality]", jobs["decide"])
        self.assertIn("needs: [candidate, decide, main-checks, test, foundation, quality]", jobs["main-qualification"])
        self.assertIn("if: always()", jobs["main-qualification"])
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertEqual(len(ci.CELLS), 25)


if __name__ == "__main__":
    unittest.main()
