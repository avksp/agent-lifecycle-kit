from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.display_identity import digest_display_prefixes


class DisplayIdentityTests(unittest.TestCase):
    def test_collisions_expand_with_full_identities_and_stable_order(self) -> None:
        first, second = "a" * 63 + "0", "a" * 63 + "1"
        values = [second, first, first, "b" * 64]
        rendered = digest_display_prefixes(values)
        self.assertEqual(list(rendered), sorted(set(values)))
        self.assertEqual(rendered[first], first)
        self.assertEqual(rendered[second], second)
        self.assertEqual(rendered["b" * 64], "b" * 12)
        self.assertEqual(values, [second, first, first, "b" * 64])

    def test_short_inputs_and_invalid_prefix_lengths_are_not_authority(self) -> None:
        for values in (["a" * 12], ["A" * 64], [None]):
            with self.subTest(values=values), self.assertRaises(LifecycleError):
                digest_display_prefixes(values)
        for length in (True, 0, 3, 65, "12"):
            with self.subTest(length=length), self.assertRaises(LifecycleError):
                digest_display_prefixes(["a" * 64], minimum_length=length)
