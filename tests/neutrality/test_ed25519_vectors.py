from __future__ import annotations

import importlib.util
import json
import random
import unittest
from pathlib import Path

from agent_lifecycle.neutrality import ed25519


ROOT = Path(__file__).resolve().parents[2]


def _reference_module():
    path = ROOT / "tests/neutrality/reference_ed25519.py"
    spec = importlib.util.spec_from_file_location("ed25519_affine_reference", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("reference Ed25519 module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Ed25519VectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = _reference_module()
        cls.fixture = json.loads(
            (ROOT / "tests/neutrality/fixtures/rfc8032-ed25519.json").read_text(encoding="utf-8")
        )

    def test_rfc8032_vectors_are_byte_exact(self) -> None:
        for vector in self.fixture["vectors"]:
            with self.subTest(vector=vector["id"]):
                seed = bytes.fromhex(vector["seed"])
                message = bytes.fromhex(vector["message"])
                public_key = bytes.fromhex(vector["publicKey"])
                signature = bytes.fromhex(vector["signature"])
                self.assertEqual(ed25519.publickey_from_seed(seed), public_key)
                self.assertEqual(ed25519.sign(seed, message), signature)
                self.assertTrue(ed25519.verify(public_key, message, signature))

    def test_differential_randomized_against_frozen_affine_reference(self) -> None:
        randomizer = random.Random(8032)
        for index in range(8):
            seed = randomizer.randbytes(32)
            message = randomizer.randbytes(index * 7)
            with self.subTest(index=index):
                expected_public = self.reference.publickey_from_seed(seed)
                expected_signature = self.reference.sign(seed, message)
                self.assertEqual(ed25519.publickey_from_seed(seed), expected_public)
                self.assertEqual(ed25519.sign(seed, message), expected_signature)
                self.assertTrue(ed25519.verify(expected_public, message, expected_signature))
                self.assertFalse(ed25519.verify(expected_public, message + b"x", expected_signature))

    def test_strict_malformed_inputs_remain_rejected(self) -> None:
        seed = bytes(range(32))
        public_key = ed25519.publickey_from_seed(seed)
        signature = ed25519.sign(seed, b"accepted receipt fixture")
        self.assertTrue(ed25519.verify(public_key, b"accepted receipt fixture", signature))
        self.assertFalse(ed25519.verify(public_key, b"accepted receipt fixture", signature[:-1] + bytes([signature[-1] ^ 1])))
        self.assertFalse(ed25519.verify(ed25519.P.to_bytes(32, "little"), b"", signature))
        self.assertFalse(ed25519.verify(public_key, b"", bytes(32) + ed25519.Q.to_bytes(32, "little")))
        with self.assertRaises(ValueError):
            ed25519._decode_point(bytes([1]) + bytes(30) + bytes([0x80]))


if __name__ == "__main__":
    unittest.main()
