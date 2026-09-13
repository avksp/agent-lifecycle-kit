from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, authority_io
from agent_lifecycle.contracts.quality_modes import MODES, max_mode, mode_index
from agent_lifecycle.contracts.token_estimation import estimate_tokens
from agent_lifecycle.contracts.validation import load_bounded_literal_profile


class ArchitecturePrimitiveTests(unittest.TestCase):
    def test_literal_profile_cap_counts_bytes_including_exact_boundary(self) -> None:
        for size in (32767, 32768, 32769):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                path = root / "profile.py"
                base = "PROFILE = {'text': 'é'}\n#".encode()
                data = base + b"x" * (size - len(base))
                path.write_bytes(data)
                self.assertEqual(len(data), size)
                if size <= 32768:
                    self.assertEqual(
                        load_bounded_literal_profile(path, root=root, error_prefix="custom-profile"),
                        {"text": "é"},
                    )
                else:
                    with self.assertRaises(LifecycleError) as raised:
                        load_bounded_literal_profile(path, root=root, error_prefix="custom-profile")
                    self.assertEqual(raised.exception.code, "custom-profile-too-large")

    def test_literal_profile_rejects_actual_execution_and_malformed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "profile.py"
            marker = root / "executed"
            malicious = f"PROFILE = __import__('pathlib').Path({str(marker)!r}).write_text('executed')\n"
            for data, suffix in (
                (malicious.encode(), "not-literal"),
                (b"PROFILE = dict(value=1)\n", "not-literal"),
                (b"PROFILE = []\n", "not-literal"),
                (b"PROFILE = {}\nraise RuntimeError('executed')\n", "not-literal"),
                (b"PROFILE = {\n", "invalid"),
                (b"PROFILE = {'text': '\xff'}\n", "invalid"),
            ):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    with self.assertRaises(LifecycleError) as raised:
                        load_bounded_literal_profile(path, root=root, error_prefix="custom-profile")
                    self.assertEqual(raised.exception.code, f"custom-profile-{suffix}")
                    self.assertFalse(marker.exists())

    def test_literal_profile_rejects_escape_symlinks_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "root"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_bytes(b"PROFILE = {}\n")
            target = root / "target.py"
            target.write_bytes(b"PROFILE = {}\n")
            (root / "leaf.py").symlink_to(target)
            (root / "linked").symlink_to(root, target_is_directory=True)
            for path, suffix in (
                (outside, "missing"),
                (Path("../outside.py"), "missing"),
                (Path("missing.py"), "missing"),
                (Path("leaf.py"), "path"),
                (Path("linked/target.py"), "path"),
                (root, "path"),
            ):
                with self.subTest(path=path), self.assertRaises(LifecycleError) as raised:
                    load_bounded_literal_profile(path, root=root, error_prefix="custom-profile")
                self.assertEqual(raised.exception.code, f"custom-profile-{suffix}")
            self.assertEqual(outside.read_bytes(), b"PROFILE = {}\n")

    def test_literal_profile_rejects_deterministic_mutation_during_guarded_read(self) -> None:
        for mutation in ("replace", "rewrite"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                path = root / "profile.py"
                data = b"PROFILE = {'value': 1}\n"
                changed = data.replace(b"1", b"2")
                path.write_bytes(data)
                replacement = root / "replacement.py"
                replacement.write_bytes(changed)
                original_open = authority_io._Directory.open_child
                touched = []

                def mutate(
                    parent,
                    name,
                    *,
                    mutation=mutation,
                    path=path,
                    replacement=replacement,
                    changed=changed,
                    touched=touched,
                    original_open=original_open,
                ):
                    # The backend has already captured the original stat identity.
                    if mutation == "replace":
                        parent.replace_child(replacement.name, name)
                    else:
                        before = path.stat()
                        path.write_bytes(changed)
                        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
                    touched.append(name)
                    return original_open(parent, name)

                with (
                    patch.object(authority_io._Directory, "open_child", mutate),
                    self.assertRaises(LifecycleError) as raised,
                ):
                    load_bounded_literal_profile(path, root=root, error_prefix="custom-profile")
                self.assertEqual(raised.exception.code, "custom-profile-path")
                self.assertEqual(touched, [path.name])
                self.assertEqual(path.read_bytes(), changed)

    def test_shared_primitives_are_deterministic(self) -> None:
        self.assertGreater(estimate_tokens({"text": "bounded"}), 0)
        self.assertEqual(max_mode("light", "strict"), "strict")
        self.assertEqual(mode_index(MODES[-1]), len(MODES) - 1)

    def test_literal_profile_loader_does_not_execute_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.py").write_text("PROFILE = {'status': 'PASS'}\n", encoding="utf-8")
            profile = load_bounded_literal_profile(Path("profile.py"), root=root, error_prefix="test-profile")
        self.assertEqual(profile, {"status": "PASS"})


if __name__ == "__main__":
    unittest.main()
