"""Exercise real compact CLI publication, refusal and rollback boundaries."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli import compact_plan_commands as command
from agent_lifecycle.contracts import canonical_bytes, canonical_digest, load_json_object
from agent_lifecycle.planning.validation import validate_plan_manifest
from tests.cli.helpers import _run_cli

_FIXTURES = Path(__file__).resolve().parents[1] / "planning/fixtures"
_SOURCE = "tasks/compact-example/compact-input.json"
_OUTPUT = "tasks/compact-example/plan.manifest.json"


def _prepare(root: Path, tier: str = "S0") -> bytes:
    raw = (_FIXTURES / ("compact-" + tier.lower() + "-plan.json")).read_bytes()
    path = root / _SOURCE
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return raw


def _invoke(root: Path, *, explain: bool = False, source: str = _SOURCE, output: str = _OUTPUT) -> tuple[int, dict]:
    args = ["plan", "compact-explain" if explain else "compact-compile", "--input", source]
    if not explain:
        args.extend(["--out", output])
    return _run_cli([*args, "--repository-root", str(root)])


@contextmanager
def _windows_descriptor_ctime_disagreement():
    """Inject Windows fd/path ctime semantics while retaining real files."""
    actual_fstat = os.fstat
    actual_identity = command._identity
    descriptor_stats = []

    def fstat(fd):
        info = actual_fstat(fd)
        descriptor_stats.append(info)
        return info

    def identity(info):
        value = actual_identity(info)
        if any(info is row for row in descriptor_stats):
            return (*value[:-1], value[-1] + 1_000_000)
        return value

    with (
        patch.object(command.os, "fstat", side_effect=fstat),
        patch.object(command, "_identity", side_effect=identity),
        patch.object(command, "_FD_PATH_IDENTITY_FIELDS", 5),
    ):
        yield


class CompactPlanCommandTests(unittest.TestCase):
    def test_profiles_are_read_only_and_keep_all_authority_gates(self) -> None:
        code, value = _run_cli(["plan", "package-profiles"])
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "READ_ONLY")
        self.assertFalse(value["authorityClaimed"])
        self.assertEqual(
            value["profileDigest"], canonical_digest({k: v for k, v in value.items() if k != "profileDigest"})
        )
        self.assertIn("acceptance-criteria.md", value["draftCompletionPrerequisites"][0])
        self.assertIn("planFiles", value["draftCompletionPrerequisites"][0])
        for profile in value["profiles"]:
            self.assertTrue(profile["independentReviewRequired"])
            self.assertTrue(profile["reviewedLockRequired"])
            self.assertTrue(profile["separateAuthorizationRequired"])
            if profile["compactSupported"]:
                self.assertTrue(
                    any(
                        "acceptance-criteria.md" in entry and "planFiles" in entry
                        for entry in profile["requiredArtifacts"]
                    )
                )

    def test_each_tier_creates_only_canonical_draft_and_preserves_source(self) -> None:
        for tier in ("S0", "S1"):
            with self.subTest(tier=tier), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw = _prepare(root, tier)
                code, explanation = _invoke(root, explain=True)
                self.assertEqual(code, 0)
                self.assertEqual(explanation["status"], "PASS")
                self.assertFalse((root / _OUTPUT).exists())
                code, value = _invoke(root)
                self.assertEqual(code, 0, value)
                emitted = (root / _OUTPUT).read_bytes()
                manifest = load_json_object(emitted)
                self.assertEqual(emitted, canonical_bytes(manifest) + b"\n")
                self.assertEqual(manifest["status"], "DRAFT")
                self.assertEqual(validate_plan_manifest(manifest, require_completeness=True)["status"], "DRAFT")
                self.assertEqual(explanation["manifestDigest"], value["manifestDigest"])
                self.assertFalse(value["authorityClaimed"])
                self.assertEqual((root / _SOURCE).read_bytes(), raw)
                self.assertEqual(
                    {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}, {_SOURCE, _OUTPUT}
                )

    def test_existing_output_and_late_competing_output_are_preserved(self) -> None:
        for late in (False, True):
            with self.subTest(late=late), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw = _prepare(root)
                output = root / _OUTPUT
                sentinel = b"existing authority must remain"
                original = command._require_same_source

                def competing(*args, original=original, output=output, sentinel=sentinel):
                    original(*args)
                    output.write_bytes(sentinel)

                if not late:
                    output.write_bytes(sentinel)
                with patch.object(command, "_require_same_source", side_effect=competing if late else original):
                    code, value = _invoke(root)
                self.assertEqual(code, 2)
                self.assertEqual(value["code"], "compact-plan-output-exists")
                self.assertEqual(output.read_bytes(), sentinel)
                self.assertEqual((root / _SOURCE).read_bytes(), raw)

    def test_invalid_duplicate_oversized_and_high_risk_inputs_never_publish(self) -> None:
        for kind in ("duplicate", "oversized", "unknown", "risk", "missing-tier"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw = _prepare(root)
                value = load_json_object(raw)
                if kind == "duplicate":
                    raw = b'{"tier":"S0",' + raw.lstrip()[1:]
                elif kind == "oversized":
                    raw = b" " * 65537
                else:
                    if kind == "unknown":
                        value["approval"] = True
                    elif kind == "risk":
                        value["riskFlags"]["security"] = True
                    else:
                        del value["tier"]
                    raw = canonical_bytes(value)
                (root / _SOURCE).write_bytes(raw)
                code, _ = _invoke(root)
                self.assertEqual(code, 2)
                self.assertFalse((root / _OUTPUT).exists())
                self.assertEqual((root / _SOURCE).read_bytes(), raw)

    def test_explain_reports_full_s2_without_writes_and_checks_filesystem_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = load_json_object(_prepare(root))
            source["riskFlags"]["security"] = True
            (root / _SOURCE).write_bytes(canonical_bytes(source))
            code, value = _invoke(root, explain=True)
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "FAIL")
            self.assertEqual(value["resolvedTier"], "S2")
            self.assertFalse((root / _OUTPUT).exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            (root / _SOURCE).rename(root / _SOURCE.replace("compact-input", "COMPACT-INPUT"))
            code, _ = _invoke(root, explain=True)
            self.assertEqual(code, 2)
            self.assertFalse((root / _OUTPUT).exists())

    def test_links_and_output_outside_declared_root_refuse_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _prepare(root)
            original = root / _SOURCE
            alias = original.with_name("alias.json")
            try:
                os.link(original, alias)
            except OSError as exc:
                self.skipTest(f"Host cannot create hard links: {exc}")
            self.assertEqual(_invoke(root)[0], 2)
            alias.unlink()
            try:
                alias.symlink_to(original.name)
            except OSError as exc:
                self.skipTest(f"Host cannot create symlinks: {exc}")
            self.assertEqual(_invoke(root, source=alias.relative_to(root).as_posix())[0], 2)
            self.assertEqual(_invoke(root, output="new-directory/plan.manifest.json")[0], 2)
            self.assertFalse((root / "new-directory").exists())
            self.assertFalse((root / _OUTPUT).exists())
            self.assertEqual(original.read_bytes(), raw)

    def test_source_replacement_after_creation_rolls_output_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _prepare(root)
            original = command._require_same_source
            calls = 0

            def replace_after_publication(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    replacement = (root / _SOURCE).with_name("replacement.json")
                    replacement.write_bytes(raw)
                    replacement.replace(root / _SOURCE)
                return original(*args)

            with patch.object(command, "_require_same_source", side_effect=replace_after_publication):
                code, value = _invoke(root)
            self.assertEqual(code, 2)
            self.assertEqual(value["code"], "compact-plan-source-changed")
            self.assertFalse((root / _OUTPUT).exists())
            self.assertEqual((root / _SOURCE).read_bytes(), raw)

    def test_late_replacement_with_matching_prefix_or_all_prepared_bytes_survives_rollback(self) -> None:
        self._assert_late_replacement_with_matching_prefix_or_all_prepared_bytes_survives_rollback()

    def test_windows_descriptor_ctime_foreign_output_retained(self) -> None:
        with _windows_descriptor_ctime_disagreement():
            self._assert_late_replacement_with_matching_prefix_or_all_prepared_bytes_survives_rollback()

    def _assert_late_replacement_with_matching_prefix_or_all_prepared_bytes_survives_rollback(self) -> None:
        for prefix in (0, 17, None):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                raw = _prepare(root)
                original = command._require_same_source
                calls = 0
                foreign = None

                def replace_output(*args, prefix=prefix, root=root, raw=raw, original=original):
                    nonlocal calls, foreign
                    calls += 1
                    if calls == 2:
                        output = root / _OUTPUT
                        prepared = output.read_bytes()
                        foreign = prepared if prefix is None else prepared[:prefix]
                        replacement = output.with_name("foreign.json")
                        replacement.write_bytes(foreign)
                        self.assertNotEqual(replacement.stat().st_ino, output.stat().st_ino)
                        replacement.replace(output)
                        (root / _SOURCE).write_bytes(raw + b" ")
                    return original(*args)

                with patch.object(command, "_require_same_source", side_effect=replace_output):
                    code, value = _invoke(root)
                self.assertEqual(code, 2)
                self.assertEqual(value["code"], "compact-plan-source-changed")
                self.assertIsNotNone(foreign)
                self.assertEqual((root / _OUTPUT).read_bytes(), foreign)

    def test_partial_write_is_removed_without_new_output_directories(self) -> None:
        self._assert_partial_write_is_removed_without_new_output_directories()

    def test_windows_descriptor_ctime_partial_rollback(self) -> None:
        with _windows_descriptor_ctime_disagreement():
            self._assert_partial_write_is_removed_without_new_output_directories()

    def _assert_partial_write_is_removed_without_new_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _prepare(root)
            actual_fdopen = os.fdopen

            class BrokenWriter:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.stream.close()

                def write(self, data):
                    self.stream.write(data[:17])
                    self.stream.flush()
                    raise OSError("controlled partial write failure")

                def fileno(self):
                    return self.stream.fileno()

            def faulty_fdopen(fd, mode, *args, **kwargs):
                stream = actual_fdopen(fd, mode, *args, **kwargs)
                return BrokenWriter(stream) if mode == "wb" else stream

            directories = {p.relative_to(root) for p in root.rglob("*") if p.is_dir()}
            with patch.object(command.os, "fdopen", side_effect=faulty_fdopen):
                code, _ = _invoke(root)
            self.assertEqual(code, 2)
            self.assertFalse((root / _OUTPUT).exists())
            self.assertEqual((root / _SOURCE).read_bytes(), raw)
            self.assertEqual({p.relative_to(root) for p in root.rglob("*") if p.is_dir()}, directories)
