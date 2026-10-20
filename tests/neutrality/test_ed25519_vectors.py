from __future__ import annotations

import importlib.util
import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import ed25519 as shared_ed25519
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
    def test_private_scalar_work_does_not_branch_on_scalar_bits(self) -> None:
        for scalar in (0, 1, 2**252 - 1, 2**254 + 8):
            with self.subTest(scalar=scalar), patch.object(shared_ed25519, "_extended_add", wraps=shared_ed25519._extended_add) as add:
                with patch.object(shared_ed25519, "_extended_double", wraps=shared_ed25519._extended_double) as double:
                    shared_ed25519._scalar_mult(shared_ed25519.B, scalar)
                self.assertEqual(add.call_count, 256)
                self.assertEqual(double.call_count, 256)
        # Generic multiplication must NOT reduce Q: this is the subgroup guard.
        order_two = (0, shared_ed25519.P - 1)
        self.assertNotEqual(shared_ed25519._encode_point(shared_ed25519._scalar_mult(order_two, shared_ed25519.Q)), (1).to_bytes(32, "little"))

    def test_weak_r_points_are_refused_even_with_a_valid_issuer(self) -> None:
        public_key = ed25519.publickey_from_seed(bytes(range(32)))
        for encoded in (bytes(32), (1).to_bytes(32, "little"), (ed25519.P - 1).to_bytes(32, "little")):
            with self.subTest(point=encoded.hex()):
                self.assertFalse(ed25519.verify(public_key, b"", encoded + bytes(32)))

    def test_legacy_exports_use_the_same_algorithm_objects(self) -> None:
        for name in ("publickey_from_seed", "sign", "verify", "fingerprint", "_decode_point", "_scalar_mult"):
            self.assertIs(getattr(ed25519, name), getattr(shared_ed25519, name))
        self.assertEqual((ed25519.P, ed25519.Q, ed25519.B),
                         (shared_ed25519.P, shared_ed25519.Q, shared_ed25519.B))

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

    def test_weak_and_mixed_order_public_keys_are_rejected(self) -> None:
        identity = (1).to_bytes(32, "little")
        signature = identity + bytes(32)
        weak_keys = [identity, (ed25519.P - 1).to_bytes(32, "little"), bytes(32)]
        for key in weak_keys:
            for message in (b"", b"review", b"fresh claimed assignment"):
                with self.subTest(public_key=key.hex(), message=message):
                    self.assertFalse(ed25519.verify(key, message, signature))
        mixed = shared_ed25519._encode_point(shared_ed25519._extended_add(
            shared_ed25519._extended_from_affine(shared_ed25519.B),
            shared_ed25519._extended_from_affine((0, ed25519.P - 1)),
        ))
        for index in range(64):
            message = str(index).encode()
            challenge = shared_ed25519._hint(identity + mixed + message) % ed25519.Q
            if challenge % 2 == 0:
                break
        else:
            self.fail("no deterministic mixed-order witness")
        forged = identity + challenge.to_bytes(32, "little")
        self.assertFalse(ed25519.verify(mixed, message, forged))

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
