"""Actual legacy reads preserve historical bytes and refusal boundaries."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.accounting.legacy_source_usage import LegacySourceUsage
from agent_lifecycle.accounting.usage_types import UsageContext, serialize_source_registry
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.limited_usage import current_source_snapshot
from tests.workflow.test_limited_usage import DeclaredFixture


class LegacySourceUsageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture = DeclaredFixture(Path(directory.name).resolve())

    def test_translator_preserves_exact_sources_digests_and_unknown_balances(self):
        f = self.fixture
        context = f.selection()
        self.assertIsInstance(context, UsageContext)
        self.assertIsInstance(context.source, LegacySourceUsage)
        before = {p: p.read_bytes() for p in (f.root / "work/release-2-16").rglob("*.json")}
        snapshot = current_source_snapshot(context)
        projection = snapshot["projection"]
        self.assertEqual(serialize_source_registry(projection), snapshot["projectionBytes"])
        self.assertEqual(projection["balances"]["currentUnknownHolds"], snapshot["current"]["head"]["unknownHolds"])
        self.assertIsNone(projection["balances"]["actualTokens"])
        self.assertIsNone(projection["balances"]["actualInputTokens"])
        self.assertEqual("DECLARED_DERIVED_SOURCE_EVIDENCE_ONLY", projection["guarantee"])
        for row in projection["records"]:
            for field in ("headRef", "sourceRef"):
                reference = row[field]
                raw = (f.root / reference["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), reference["sha256"])
                self.assertEqual(len(raw), reference["bytes"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_different_frozen_package_does_not_register_a_ledger_route(self):
        f = self.fixture
        f.manifest["package"]["id"] = "portable-unit-package"
        f.state["packageId"] = "portable-unit-package"
        f.freeze()
        context = f.selection()
        with self.assertRaises(LifecycleError) as caught:
            current_source_snapshot(context)
        self.assertEqual("declared-ledger-route-unsupported", caught.exception.code)

    def test_changed_original_source_and_rebound_opening_are_not_translated_away(self):
        f = self.fixture
        original = (f.root / f.admission_ref["path"]).read_bytes()
        (f.root / f.admission_ref["path"]).write_bytes(original + b" ")
        with self.assertRaises(LifecycleError):
            current_source_snapshot(f.selection())
        (f.root / f.admission_ref["path"]).write_bytes(original)
        opening_path = f.root / f.policy["openingRef"]["path"]
        opening_path.write_bytes(opening_path.read_bytes() + b" ")
        with self.assertRaises(LifecycleError):
            f.selection()
