"""Declared paths and compiler footprints reject aliases without granting authority."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.ownership_paths import (
    compiler_output_paths,
    is_under_authority_path,
    normalize_authority_path,
    observed_authority_paths,
    require_declared_output_footprint,
    require_manifest_authority_paths,
    require_output_footprint,
)


class OwnershipPathTests(unittest.TestCase):
    def test_comparison_without_required_parent_guard_fails_closed(self) -> None:
        for platform, fd, handle in (("nt", None, None), ("posix", None, 17), ("posix", 17, None)):
            with self.subTest(platform=platform, fd=fd, handle=handle), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                parent = SimpleNamespace(path=root, fd=fd, handle=handle, stat_child=Mock())
                backend = SimpleNamespace(name=platform, supports_fd=set(), scandir=Mock())
                with (
                    patch("agent_lifecycle.contracts.ownership_paths._parent") as held,
                    patch("agent_lifecycle.contracts.ownership_paths.os", backend),
                ):
                    held.return_value.__enter__.return_value = (parent, "First")
                    with self.assertRaises(LifecycleError) as raised:
                        is_under_authority_path("First", "second", operation_root=root)
                self.assertEqual(raised.exception.code, "filesystem-policy-unavailable")
                parent.stat_child.assert_not_called()
                backend.scandir.assert_not_called()

    def test_windows_handle_backend_enumerates_the_guarded_parent_path(self) -> None:
        # Fault-injected backend dispatch complements the native case tests below.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Alias").write_text("one")
            parent = SimpleNamespace(path=root, fd=None, handle=17, stat_child=lambda _name: (root / "Alias").lstat())
            scan = Mock(wraps=os.scandir)
            backend = SimpleNamespace(name="nt", supports_fd=set(), scandir=scan)
            with (
                patch("agent_lifecycle.contracts.ownership_paths._parent") as held,
                patch("agent_lifecycle.contracts.ownership_paths.os", backend),
            ):
                held.return_value.__enter__.return_value = (parent, "alias")
                self.assertTrue(is_under_authority_path("alias", "Alias", operation_root=root))
            scan.assert_called_once_with(root)
            held.return_value.__exit__.assert_called_once()

    def test_alias_comparison_revalidates_links_identity_and_disappearance(self) -> None:
        for stage, fault, expected_code in (
            ("before", "reparse", "authority-input-symlink"),
            ("before", "symlink", "authority-input-symlink"),
            ("after", "reparse", "authority-input-symlink"),
            ("after", "symlink", "authority-input-symlink"),
            ("after", "identity", "ambiguous-authority-path"),
            ("after", "disappeared", "filesystem-policy-unavailable"),
        ):
            with self.subTest(stage=stage, fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "Alias").write_text("one")
                enumeration = SimpleNamespace(complete=False)

                @contextmanager
                def scan(directory, *, enumeration=enumeration):
                    with os.scandir(directory) as entries:
                        yield entries
                    enumeration.complete = True

                def stat_child(name, *, root=root, stage=stage, fault=fault, enumeration=enumeration):
                    info = (root / "Alias").lstat()
                    changed = stage == "before" or enumeration.complete
                    if changed and fault == "disappeared":
                        raise FileNotFoundError(name)
                    return SimpleNamespace(
                        st_dev=info.st_dev,
                        st_ino=info.st_ino + (changed and fault == "identity"),
                        st_mode=stat.S_IFLNK if changed and fault == "symlink" else info.st_mode,
                        st_file_attributes=0x400 if changed and fault == "reparse" else 0,
                    )

                parent = SimpleNamespace(path=root, fd=None, handle=17, stat_child=stat_child)
                backend = SimpleNamespace(name="nt", supports_fd=set(), scandir=scan)
                with (
                    patch("agent_lifecycle.contracts.ownership_paths._parent") as held,
                    patch("agent_lifecycle.contracts.ownership_paths.os", backend),
                ):
                    held.return_value.__enter__.return_value = (parent, "alias")
                    with self.assertRaises(LifecycleError) as raised:
                        is_under_authority_path("alias", "Alias", operation_root=root)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(enumeration.complete, stage == "after")

    def test_comparison_enumeration_has_a_10000_entry_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first").write_text("one")
            os.link(root / "first", root / "second")
            for size, expected_code in ((10000, "ambiguous-authority-path"), (10001, "filesystem-policy-unavailable")):
                with self.subTest(size=size):

                    @contextmanager
                    def scan(_directory, *, size=size):
                        yield (
                            SimpleNamespace(name=("first", "second")[index] if index < 2 else str(index))
                            for index in range(size)
                        )

                    backend = SimpleNamespace(name=os.name, supports_fd={scan}, scandir=scan)
                    with (
                        patch("agent_lifecycle.contracts.ownership_paths.os", backend),
                        self.assertRaises(LifecycleError) as raised,
                    ):
                        is_under_authority_path("first", "second", operation_root=root)
                    self.assertEqual(raised.exception.code, expected_code)

    def test_native_unicode_case_pairs_use_actual_directory_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "\u00c4pfel").write_text("one")
            insensitive = (root / "\u00e4PFEL").exists()
            self.assertEqual(is_under_authority_path("\u00e4PFEL", "\u00c4pfel", operation_root=root), insensitive)
            if not insensitive:
                (root / "\u00e4PFEL").write_text("two")
                self.assertFalse(is_under_authority_path("\u00e4PFEL", "\u00c4pfel", operation_root=root))

    def test_runtime_output_footprint_distinguishes_actual_case_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Plan").mkdir()
            insensitive = (root / "plan").exists()
            manifest = {"package": {"planArtifactRoot": "Plan"}}
            if insensitive:
                with self.assertRaises(LifecycleError) as raised:
                    require_output_footprint(manifest, ["plan/output.json"], repository_root=root)
                self.assertEqual(raised.exception.code, "plan-output-conflict")
            else:
                (root / "plan").mkdir()
                require_output_footprint(manifest, ["plan/output.json"], repository_root=root)

    def test_conflicting_literal_writers_reject_even_without_observed_changes(self) -> None:
        for second in ("src", "src/nested"):
            with self.subTest(second=second), self.assertRaises(LifecycleError) as raised:
                require_manifest_authority_paths(
                    {
                        "workstreams": [
                            {"id": "A", "writes": ["src"]},
                            {"id": "B", "writes": [second]},
                        ]
                    }
                )
            self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_exact_write_and_protected_grants_conflict_in_all_categories(self) -> None:
        for field in ("readOnly", "forbiddenWrites", "leadOwned"):
            value = [{"path": "src"}] if field == "leadOwned" else ["src"]
            with self.subTest(field=field), self.assertRaises(LifecycleError) as raised:
                require_manifest_authority_paths({field: value, "workstreams": [{"id": "A", "writes": ["src"]}]})
            self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_restrictive_duplicates_nested_restrictions_and_same_owner_are_preserved(self) -> None:
        require_manifest_authority_paths(
            {
                "readOnly": ["src/protected"],
                "forbiddenWrites": ["src/protected"],
                "workstreams": [{"id": "A", "writes": ["src", "src", "src/owned"]}],
            }
        )

    def test_declaration_aliases_use_actual_root_and_do_not_mutate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo").mkdir()
            insensitive = (root / "foo").exists()
            manifest = {"readOnly": ["Foo"], "workstreams": [{"id": "A", "writes": ["foo/child"]}]}
            if insensitive:
                with self.assertRaises(LifecycleError) as raised:
                    require_manifest_authority_paths(manifest, operation_root=root)
                self.assertEqual(raised.exception.code, "ambiguous-authority-path")
            else:
                require_manifest_authority_paths(manifest, operation_root=root)
            self.assertEqual(manifest["readOnly"], ["Foo"])
            self.assertEqual(manifest["workstreams"][0]["writes"], ["foo/child"])

    def test_case_distinct_task_grants_need_actual_alias_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"workstreams": [{"id": "A", "writes": ["Foo"]}, {"id": "B", "writes": ["foo"]}]}
            require_manifest_authority_paths(manifest)  # offline does not attest runtime semantics
            with self.assertRaises(LifecycleError) as raised:
                require_manifest_authority_paths(manifest, operation_root=root)
            self.assertEqual(raised.exception.code, "filesystem-policy-unavailable")
            (root / "Foo").mkdir()
            if (root / "foo").exists():
                with self.assertRaises(LifecycleError) as raised:
                    require_manifest_authority_paths(manifest, operation_root=root)
                self.assertEqual(raised.exception.code, "ambiguous-authority-path")
            else:
                (root / "foo").mkdir()
                require_manifest_authority_paths(manifest, operation_root=root)

    def test_actual_root_distinguishes_case_pairs_and_preserves_observed_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo").write_text("one")
            insensitive = (root / "foo").exists()
            self.assertEqual(is_under_authority_path("foo/child", "Foo", operation_root=root), insensitive)
            if insensitive:
                with self.assertRaises(LifecycleError) as raised:
                    observed_authority_paths(["Foo", "foo"], operation_root=root)
                self.assertEqual(raised.exception.code, "ambiguous-authority-path")
            else:
                (root / "foo").write_text("two")
                self.assertFalse(is_under_authority_path("foo", "Foo", operation_root=root))
                self.assertEqual(observed_authority_paths(["Foo", "foo"], operation_root=root), ["Foo", "foo"])

    def test_missing_alias_sensitive_names_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LifecycleError) as raised:
                is_under_authority_path("Gone/file", "gone", operation_root=Path(tmp))
            self.assertEqual(raised.exception.code, "filesystem-policy-unavailable")

    def test_explicit_root_does_not_use_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo").write_text("one")
            insensitive = (root / "foo").exists()
            with patch("pathlib.Path.cwd", side_effect=AssertionError("implicit cwd")):
                self.assertEqual(is_under_authority_path("foo", "Foo", operation_root=root), insensitive)

    def test_alias_comparison_rejects_symlinks_and_does_not_read_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "target").write_text("private")
            try:
                (root / "alias").symlink_to(root / "target")
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(LifecycleError) as raised:
                is_under_authority_path("alias", "target", operation_root=root)
            self.assertEqual(raised.exception.code, "authority-input-symlink")

    def test_hard_links_are_ambiguous_not_case_policy_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first").write_text("one")
            os.link(root / "first", root / "second")
            with self.assertRaises(LifecycleError) as raised:
                is_under_authority_path("first", "second", operation_root=root)
            self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_observed_nfd_is_preserved_but_collisions_are_rejected(self) -> None:
        observed = "src/cafe\u0301.py"
        self.assertEqual(observed_authority_paths([observed, observed]), [observed])
        with self.assertRaises(LifecycleError) as raised:
            observed_authority_paths([observed, "src/caf\u00e9.py"])
        self.assertEqual(raised.exception.code, "ambiguous-authority-path")

    def test_every_declared_authority_category_rejects_noncanonical_spelling(self) -> None:
        for field in ("writes", "readOnly", "forbiddenWrites", "leadOwned"):
            value = [{"path": "src/cafe\u0301.py"}] if field == "leadOwned" else ["src/cafe\u0301.py"]
            for manifest in ({field: value}, {"workstreams": [{"id": "WS-01", field: value}]}):
                with self.subTest(field=field), self.assertRaises(LifecycleError) as raised:
                    require_manifest_authority_paths(manifest)
                self.assertEqual(raised.exception.code, "noncanonical-authority-path")

    def test_declared_nfd_is_rejected_not_silently_normalized(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            normalize_authority_path("src/cafe\u0301.py")
        self.assertEqual(raised.exception.code, "noncanonical-authority-path")
        self.assertEqual(normalize_authority_path("src/caf\u00e9.py"), "src/caf\u00e9.py")

    def test_control_rejection_precedes_normalization(self) -> None:
        for value in ("src/\u202efile.py", "src/a\t.py", "src/\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(LifecycleError) as raised:
                normalize_authority_path(value)
            self.assertEqual(raised.exception.code, "authority-text-control")

    def test_declared_compiler_outputs_do_not_overlap_protected_root(self) -> None:
        for artifact in ("tasks/plan", "tasks/plan/runtime"):
            manifest = {
                "package": {"artifactRoot": artifact, "planArtifactRoot": "tasks/plan"},
                "workstreams": [{"id": "WS-01"}],
            }
            with self.subTest(artifact=artifact), self.assertRaises(LifecycleError) as raised:
                require_declared_output_footprint(manifest)
            self.assertEqual(raised.exception.code, "plan-output-conflict")

    def test_safe_legacy_common_parent_and_new_siblings(self) -> None:
        for artifact, plan in (("plans/p", "plans/p/.agent-plan/p"), ("work/p", "tasks/p")):
            manifest = {
                "package": {"artifactRoot": artifact, "planArtifactRoot": plan},
                "workstreams": [{"id": "WS-01"}],
            }
            require_declared_output_footprint(manifest)
            self.assertEqual(
                compiler_output_paths(manifest, small=True),
                [
                    f"{artifact}/workflow/small-model-packets/WS-01.small-model-packet.json",
                    f"{artifact}/workflow/small-model-packets/index.json",
                ],
            )

    def test_explicit_inventory_file_is_protected_outside_legacy_root(self) -> None:
        manifest = {"package": {"planArtifactRoot": "plans/p/.agent-plan/p"}, "planFiles": ["plans/p/overview.md"]}
        with self.assertRaises(LifecycleError) as raised:
            require_output_footprint(manifest, ["plans/p/overview.md/index.json"])
        self.assertEqual(raised.exception.code, "plan-output-conflict")


if __name__ == "__main__":
    unittest.main()
