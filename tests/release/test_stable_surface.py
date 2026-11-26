from __future__ import annotations

import argparse
import copy
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.release_common import digest_value, load_json
from tools.release.validate_stable_surface import PYTHON_POLICY, SURFACE, observe_stable_exits, validate_stable_surface

from agent_lifecycle.cli.parsers import build_parser

ROOT = Path(__file__).resolve().parents[2]
REVIEWED_DIGEST = "181ee12e92fd295cf503c34916db6951bb12210c35501cfd54c8fc6dc408c2b9"


class StableSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exits = observe_stable_exits()
        cls.guide = (ROOT / "docs/guides/ai-sdlc-integration.md").read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.surface = load_json(ROOT / SURFACE)
        self.policy = load_json(ROOT / PYTHON_POLICY)

    def codes(self, digest: str | None = None, *, exits=None) -> set[str]:
        result = validate_stable_surface(
            self.surface,
            self.policy,
            digest or REVIEWED_DIGEST,
            guide=self.guide,
            observed_exits=self.exits if exits is None else exits,
        )
        return {row["code"] for row in result["blockers"]}

    def test_reviewed_inventory_matches_package_and_policy(self) -> None:
        self.assertEqual(self.codes(), set())

    def test_removed_flag_refuses_even_with_updated_digest(self) -> None:
        self.surface["commands"][1]["flags"].append("--retired-flag")
        self.assertIn("stable-flag-missing", self.codes(digest_value(self.surface)))

    def test_live_command_exit_drift_refuses(self) -> None:
        actual = subprocess.run

        def changed_exit(command, **kwargs):
            tail = command[4:]
            success = tail == ["version"]
            receipt_refusal = tail[:2] == ["workflow", "continue"] and tail[-1] == "2"
            error_refusal = tail[:2] == ["model", "route"] and "unreadable.json" in tail
            if success or receipt_refusal or error_refusal:
                code = "import sys; from agent_lifecycle.cli import main; main(sys.argv[1:]); raise SystemExit(9)"
                command = [*command[:2], "-c", code, *tail]
            return actual(command, **kwargs)

        with patch("tools.release.validate_stable_surface.subprocess.run", side_effect=changed_exit):
            exits = observe_stable_exits()
        self.assertEqual(9, exits["version"]["success"])
        self.assertEqual(9, exits["workflow continue"]["refusal"])
        self.assertEqual(9, exits["model route"]["refusal"])
        self.assertIn("stable-exit-changed", self.codes(exits=exits))

    def test_omitted_command_and_schema_refuse_even_after_repin(self) -> None:
        del self.surface["commands"][0]
        del self.surface["schemas"][0]
        codes = self.codes(digest_value(self.surface))
        self.assertIn("stable-command-classification-mismatch", codes)
        self.assertIn("stable-schema-classification-mismatch", codes)

    def test_preview_classification_reaches_each_leaf_and_parent_listing(self) -> None:
        parser = build_parser(["--help"])
        stable = {tuple(row["path"]) for row in self.surface["commands"]}

        def check_menu(current, prefix):
            options = next((a for a in current._actions if isinstance(a, argparse._SubParsersAction)), None)
            rendered = current.format_help()
            if options is None:
                self.assertEqual(prefix not in stable, "Preview interface." in rendered, prefix)
                return
            for name, child in options.choices.items():
                path = (*prefix, name)
                if not any(allowed[: len(path)] == path for allowed in stable):
                    entry, = [row for row in options._choices_actions if row.dest == name]
                    self.assertTrue(entry.help.startswith("[Preview]"), path)
                    self.assertRegex(rendered, re.escape(entry.metavar) + r"\s+\[Preview\]")
                check_menu(child, path)

        check_menu(parser, ())

    def test_new_required_schema_field_refuses(self) -> None:
        from agent_lifecycle.contracts.schemas import get_schema

        def changed(schema_id: str) -> dict:
            schema = copy.deepcopy(get_schema(schema_id))
            if schema_id == "agent-lifecycle-version.v1":
                schema["required"].append("mustBeNew")
            return schema

        with patch("tools.release.validate_stable_surface.get_schema", side_effect=changed):
            self.assertIn("stable-schema-new-required-field", self.codes())

    def test_renamed_command_refuses_even_with_updated_digest(self) -> None:
        self.surface["commands"][1]["path"][-1] = "retired-verify"
        self.assertIn("stable-command-missing", self.codes(digest_value(self.surface)))

    def test_unreviewed_edit_refuses_even_if_runtime_does_not_change(self) -> None:
        self.surface["introductionEvidence"] = "Changed without review"
        self.assertIn("stable-surface-digest-mismatch", self.codes())
