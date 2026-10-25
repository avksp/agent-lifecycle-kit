from __future__ import annotations

import io
import json
import stat
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from . import run_packaging_smoke as smoke
from .run_packaging_smoke import (
    ROOT,
    _check_runtime_members,
    _portable_argv,
    _portable_path,
    _runtime_inventory,
    _stream_identity,
)


class PackagingSmokePortabilityTests(unittest.TestCase):
    def test_external_executable_paths_are_reduced_to_stable_labels(self) -> None:
        external_python = "/" + "Users/example/venv/bin/python3.12"
        self.assertEqual(
            _portable_argv([external_python, "-m", "build"]),
            ["python", "-m", "build"],
        )
        self.assertEqual(
            _portable_argv(["/private/tmp/venv/bin/agent-lifecycle", "version"]),
            ["agent-lifecycle", "version"],
        )
        self.assertEqual(
            _portable_argv([r"C:\Users\example\venv\Scripts\python.exe", "-m", "build"]),
            ["python", "-m", "build"],
        )

    def test_repository_paths_remain_relative(self) -> None:
        self.assertEqual(_portable_path(ROOT / "dist"), "dist")

    def test_process_output_is_represented_only_by_identity(self) -> None:
        identity = _stream_identity("sensitive process output")

        self.assertEqual(identity["bytes"], 24)
        self.assertEqual(len(identity["sha256"]), 64)
        self.assertNotIn("output", identity)

    def _export(self, root: Path) -> dict[str, bytes]:
        package = root / "src/agent_lifecycle"
        package.mkdir(parents=True)
        files = {"agent_lifecycle/__init__.py": b"VALUE = 1\n", "agent_lifecycle/py.typed": b""}
        for name, data in files.items():
            (root / "src" / name).write_bytes(data)
        stale = root / "build/lib/agent_lifecycle/stale_generated.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("raise RuntimeError('stale generated module')\n")
        return files

    def _archives(self, dist: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
        wheel, sdist = dist / "fixture.whl", dist / "fixture.tar.gz"
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with tarfile.open(sdist, "w:gz") as archive:
            for name, data in files.items():
                member = tarfile.TarInfo("fixture/src/" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return wheel, sdist

    def test_stale_generated_module_is_rejected_against_export_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self._export(root)
            expected = _runtime_inventory(root)
            self.assertFalse((root / ".git").exists())
            self.assertNotIn("agent_lifecycle/stale_generated.py", expected)
            wheel, sdist = self._archives(root, files)
            self.assertEqual(_check_runtime_members("wheel", wheel, expected)["status"], "PASS")
            self.assertEqual(_check_runtime_members("sdist", sdist, expected)["status"], "PASS")
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("agent_lifecycle/stale_generated.py", b"raise RuntimeError('stale')\n")
            result = _check_runtime_members("wheel", wheel, expected)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["unexpected"], ["agent_lifecycle/stale_generated.py"])

    def test_changed_missing_and_zip_sdist_members_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self._export(root)
            expected = _runtime_inventory(root)
            files["agent_lifecycle/__init__.py"] = b"VALUE = 'changed'\n"
            del files["agent_lifecycle/py.typed"]
            wheel, sdist = self._archives(root, files)
            for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
                result = _check_runtime_members(kind, artifact, expected)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["changed"], ["agent_lifecycle/__init__.py"])
                self.assertEqual(result["missing"], ["agent_lifecycle/py.typed"])
            zipped = root / "fixture.zip"
            with zipfile.ZipFile(zipped, "w") as archive:
                for name in expected:
                    archive.writestr("fixture/src/" + name, (root / "src" / name).read_bytes())
            self.assertEqual(_check_runtime_members("sdist", zipped, expected)["status"], "PASS")

    def test_duplicate_or_link_members_cannot_bypass_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self._export(root)
            expected = _runtime_inventory(root)
            wheel, sdist = self._archives(root, files)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(wheel, "a") as archive:
                    archive.writestr("agent_lifecycle/__init__.py", files["agent_lifecycle/__init__.py"])
            self.assertEqual(_check_runtime_members("wheel", wheel, expected)["status"], "FAIL")
            with zipfile.ZipFile(wheel, "w") as archive:
                link = zipfile.ZipInfo("agent_lifecycle/__init__.py")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, "outside.py")
            self.assertEqual(_check_runtime_members("wheel", wheel, expected)["status"], "FAIL")
            with tarfile.open(sdist, "w:gz") as archive:
                link = tarfile.TarInfo("fixture/src/agent_lifecycle/__init__.py")
                link.type = tarfile.SYMTYPE
                link.linkname = "outside.py"
                archive.addfile(link)
            self.assertEqual(_check_runtime_members("sdist", sdist, expected)["status"], "FAIL")

    def test_default_build_and_runtime_guard_precede_installed_consumers(self) -> None:
        for inject_stale in (False, True):
            with self.subTest(inject_stale=inject_stale), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                files = self._export(root)
                dist, evidence = root / "dist", root / "evidence.json"
                seen = []

                def build(
                    argv,
                    commands,
                    blockers,
                    *,
                    seen=seen,
                    dist=dist,
                    files=files,
                    inject_stale=inject_stale,
                    **kwargs,
                ):
                    seen.append(argv)
                    wheel, _ = self._archives(dist, files)
                    if inject_stale:
                        with zipfile.ZipFile(wheel, "a") as archive:
                            archive.writestr("agent_lifecycle/stale_generated.py", b"STALE = True\n")
                    return 0

                def consume(kind, *args):
                    return {"kind": kind, "status": "PASS"}

                argv = ["smoke", "--dist-dir", str(dist), "--evidence", str(evidence)]
                with (
                    mock.patch.object(smoke, "ROOT", root),
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(smoke, "_run_command", side_effect=build),
                    mock.patch.object(smoke, "_check_artifact", side_effect=consume) as check,
                ):
                    self.assertEqual(smoke.main(), 1 if inject_stale else 0)
                self.assertNotIn("--wheel", seen[0])
                self.assertNotIn("--sdist", seen[0])
                self.assertEqual(seen[0][1:3], ["-m", "build"])
                self.assertEqual(
                    [call.args[0] for call in check.call_args_list], ["sdist"] if inject_stale else ["wheel", "sdist"]
                )
                result = json.loads(evidence.read_bytes())
                self.assertEqual(result["status"], "FAIL" if inject_stale else "PASS")


if __name__ == "__main__":
    unittest.main()
