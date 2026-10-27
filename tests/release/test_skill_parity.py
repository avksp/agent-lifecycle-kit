from __future__ import annotations

import hashlib
import re
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))

from agent_plugin_package import REQUIRED_DOCUMENTS, build_package  # noqa: E402
from validate_skill_parity import validate_skill_parity  # noqa: E402

from agent_lifecycle.cli.parsers import build_parser  # noqa: E402


def _copy_source(root: Path) -> None:
    shutil.copytree(ROOT / "skills", root / "skills")
    for relative in REQUIRED_DOCUMENTS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


class SkillParityTests(unittest.TestCase):
    def test_actual_built_plugin_and_zip_keep_every_source_and_reference_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, archive = Path(tmp) / "plugin", Path(tmp) / "plugin.zip"
            build_package(root=ROOT, version="2.19.0", output=output, archive=archive)
            result = validate_skill_parity(ROOT, package_root=output, archive=archive)
            self.assertEqual(result["status"], "PASS", result)
            self.assertFalse(result["hostInstallationAttested"])
            reference = output / "skills/agent-first-planning/references/lifecycle-contract.md"
            reference.write_bytes(reference.read_bytes() + b"drift\n")
            result = validate_skill_parity(ROOT, package_root=output, archive=archive)
            self.assertIn("skill-projection-mismatch", {item["code"] for item in result["blockers"]})

    def test_missing_drifted_and_bypass_advice_fail_closed(self):
        for defect in ("missing", "drift", "bypass", "invariant"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _copy_source(root)
                reference = root / "skills/agent-first-planning/references/lifecycle-contract.md"
                router = reference.parent.parent / "SKILL.md"
                if defect == "missing":
                    reference.unlink()
                elif defect == "drift":
                    reference.write_bytes(reference.read_bytes() + b"changed\n")
                elif defect == "bypass":
                    router.write_text(router.read_text() + "\nBypass independent review.\n")
                else:
                    router.write_text(router.read_text().replace("SDD", "planning"))
                self.assertEqual(validate_skill_parity(root)["status"], "FAIL")

    def test_orchestrator_clause_mutations_fail_even_when_keywords_and_hashes_survive(self):
        mutations = (
            ("router", "Start only the selected frozen task.", "Start any selected frozen task."),
            ("router", "Do not bypass independent review,", "Do not bypass optional independent review,"),
            ("router", "unknown telemetry stays null", "unknown telemetry stays null unless estimated"),
            ("router", "Do not\nreset expenses", "You may\nreset expenses"),
            ("router", "preserve all expenses", "preserve some expenses"),
            (
                "router",
                "The complete lifecycle contract remains required.",
                "The complete lifecycle contract is optional.",
            ),
            ("router", "Select the recipe for the current request", "Select any recipe for the current request"),
            ("router", "Read that recipe and its required links before acting.", "Read that recipe after acting."),
            ("reference", "Freeze only reviewed matching inputs.", "Freeze any reviewed matching inputs."),
            ("reference", "`PLAN_ONLY` never authorizes.", "`PLAN_ONLY` sometimes authorizes."),
            ("reference", "independent `REWORK` evidence", "optional `REWORK` evidence"),
            ("reference", "before\n    acceptance.", "after\n    acceptance."),
            ("reference", "cannot produce a pass.", "can produce a pass."),
            ("reference", "never silently truncate.", "silently truncate if needed."),
        )
        for component, old, new in mutations:
            with self.subTest(component=component, mutation=old), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _copy_source(root)
                skill = root / "skills/agent-workflow-orchestrator"
                router, reference = skill / "SKILL.md", skill / "references/lifecycle-contract.md"
                target = router if component == "router" else reference
                original = target.read_bytes()
                old_bytes, new_bytes = old.encode("utf-8"), new.encode("utf-8")
                self.assertEqual(original.count(old_bytes), 1)
                before_digest = hashlib.sha256(reference.read_bytes()).hexdigest()
                changed = original.replace(old_bytes, new_bytes)
                target.write_bytes(changed)
                self.assertEqual(target.read_bytes(), changed)
                self.assertEqual(changed.count(b"\n"), original.count(b"\n"))
                self.assertEqual(changed.count(b"\r"), original.count(b"\r"))
                # Repin altered reference bytes so a hash mismatch cannot mask the clause regression.
                after_digest = hashlib.sha256(reference.read_bytes()).hexdigest()
                router_before = router.read_bytes()
                self.assertEqual(router_before.count(before_digest.encode("ascii")), 1)
                repinned = router_before.replace(before_digest.encode("ascii"), after_digest.encode("ascii"))
                router.write_bytes(repinned)
                self.assertEqual(router.read_bytes(), repinned)
                self.assertEqual(repinned.count(b"\n"), router_before.count(b"\n"))
                self.assertEqual(repinned.count(b"\r"), router_before.count(b"\r"))
                result = validate_skill_parity(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual({item["code"] for item in result["blockers"]}, {"skill-critical-clause-missing"})
                self.assertTrue(all(item["component"] == component for item in result["blockers"]))

    def test_counts_are_deterministic_bytes_and_whitespace_words_not_semantic_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_source(root)
            router = root / "skills/agent-workflow-orchestrator/SKILL.md"
            # Non-ASCII input distinguishes UTF-8 bytes from characters; whitespace is explicit.
            router.write_bytes(router.read_bytes() + "\n# café\t中文  δ\n".encode())
            result = validate_skill_parity(root)
            self.assertEqual(result, validate_skill_parity(root))
            self.assertEqual(result["status"], "PASS", result)
            self.assertFalse(result["semanticEquivalenceAttested"])
            self.assertFalse(result["steComplianceAttested"])
            self.assertIn("includes Markdown and code", result["wordCountMethod"])
            for item in result["skills"]:
                for prefix, relative in (("router", "SKILL.md"), ("reference", "references/lifecycle-contract.md")):
                    raw = (root / "skills" / item["skill"] / relative).read_bytes()
                    self.assertEqual(item[prefix + "Bytes"], len(raw))
                    self.assertEqual(item[prefix + "Words"], len(re.findall(r"\S+", raw.decode("utf-8"))))
                    self.assertEqual(item[prefix + "Sha256"], hashlib.sha256(raw).hexdigest())

    def test_pilot_keeps_original_full_reference_and_accepts_line_wrapping(self):
        skill = ROOT / "skills/agent-workflow-orchestrator"
        digest = "b3ec79e0280c06fa1057845ce7cae24f87682a0662d6f670e79d98ee2406bc35"
        self.assertEqual(hashlib.sha256((skill / "references/lifecycle-contract.md").read_bytes()).hexdigest(), digest)
        self.assertIn("Contract origin: `ec59da9e956c67d34e823dcad362d66901ec3348`", (skill / "SKILL.md").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_source(root)
            router = root / "skills/agent-workflow-orchestrator/SKILL.md"
            router.write_text(
                router.read_text().replace(
                    "Start only the selected frozen task.", "Start only\n the selected frozen task."
                )
            )
            self.assertEqual(validate_skill_parity(root)["status"], "PASS")

    def test_six_role_meaning_mutations_reject_without_keyword_or_hash_failures(self):
        mutations = {
            "agent-first-planning": (
                ("router", "Never implement during planning.", "Sometimes implement during planning."),
                (
                    "reference",
                    "require independent\n   specification review before plan freeze.",
                    "require independent\n   specification review after plan freeze.",
                ),
            ),
            "agent-plan-to-workers": (
                ("router", "Compilation grants no execution permission.", "Compilation grants execution permission."),
                (
                    "reference",
                    "Reject unfrozen, mismatched, or stale plan inputs.",
                    "Accept unfrozen, mismatched, or stale plan inputs.",
                ),
            ),
            "audit-agent-plan": (
                ("router", "Findings first; no self-review.", "Findings first; allow self-review."),
                (
                    "reference",
                    "Do not accept self-review as independent review.",
                    "You may accept self-review as independent review.",
                ),
            ),
            "audit-plan-implementation": (
                (
                    "router",
                    "Semantic review must precede the actual typed audit;",
                    "Semantic review may follow the actual typed audit;",
                ),
                (
                    "reference",
                    "Do not accept worker self-certification without independent review.",
                    "You may accept worker self-certification without independent review.",
                ),
            ),
            "bug-forensics": (
                (
                    "router",
                    "Optional defect profile, disabled unless the reviewed task opts in.",
                    "Optional defect profile, enabled unless the reviewed task opts out.",
                ),
                (
                    "reference",
                    "Reproduction must be red before any code modification.",
                    "Reproduction may be red after any code modification.",
                ),
            ),
            "issue-to-spec": (
                (
                    "router",
                    "Do not freeze, start execution, create branches, commit or open a PR.",
                    "You may freeze, start execution, create branches, commit or open a PR.",
                ),
                ("reference", "it must not start execution", "it may start execution"),
            ),
        }
        for name, cases in mutations.items():
            common = (
                ("router", "unknown telemetry stays null.", "unknown telemetry stays null unless estimated."),
                ("router", "Do not\nreset expenses", "You may\nreset expenses"),
                ("router", "Do not bypass independent review,", "Do not bypass optional independent review,"),
            )
            for component, old, new in (*cases, *common):
                with self.subTest(skill=name, clause=old), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _copy_source(root)
                    skill = root / "skills" / name
                    reference = skill / "references/lifecycle-contract.md"
                    router = skill / "SKILL.md"
                    before = hashlib.sha256(reference.read_bytes()).hexdigest()
                    path = router if component == "router" else reference
                    text = path.read_text(encoding="utf-8")
                    self.assertEqual(text.count(old), 1)
                    path.write_text(text.replace(old, new), encoding="utf-8")
                    after = hashlib.sha256(reference.read_bytes()).hexdigest()
                    router.write_text(router.read_text().replace(before, after), encoding="utf-8")
                    result = validate_skill_parity(root)
                    self.assertEqual({x["code"] for x in result["blockers"]}, {"skill-critical-clause-missing"}, result)
                    self.assertTrue(all(x["skill"] == name and x["component"] == component for x in result["blockers"]))

    def test_all_roles_accept_benign_wrapping_and_repinned_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_source(root)
            for skill in (root / "skills").iterdir():
                router, reference = skill / "SKILL.md", skill / "references/lifecycle-contract.md"
                before = hashlib.sha256(reference.read_bytes()).hexdigest()
                # Keep the frontmatter identity and literal hash-marker contract intact.
                head, body = reference.read_text().split("---\n", 2)[1:]
                reference.write_text("---\n" + head + "---\n" + body.replace(" ", "  "))
                text = router.read_text().replace(before, hashlib.sha256(reference.read_bytes()).hexdigest())
                router.write_text(text.replace("unknown telemetry stays null.", "unknown telemetry\n stays null."))
            self.assertEqual(validate_skill_parity(root)["status"], "PASS")

    def test_resource_missing_and_projection_drift_refuse_with_valid_skill_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            _copy_source(root)
            package, archive = Path(tmp) / "package", Path(tmp) / "package.zip"
            build_package(root=root, version="2.28.0", output=package, archive=archive)
            for relative in REQUIRED_DOCUMENTS:
                with self.subTest(path=relative):
                    target = root / relative
                    raw = target.read_bytes()
                    target.unlink()
                    result = validate_skill_parity(root)
                    self.assertIn({"code": "required-resource-invalid", "path": relative}, result["blockers"])
                    target.write_bytes(raw)
                    target = package / relative
                    target.write_bytes(raw + b"drift\n")
                    result = validate_skill_parity(root, package_root=package)
                    self.assertIn(
                        {"code": "skill-projection-mismatch", "projection": "package", "path": relative},
                        result["blockers"],
                    )
                    target.write_bytes(raw)
            import zipfile

            altered = Path(tmp) / "altered.zip"
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(altered, "w") as out:
                for entry in source.infolist():
                    if entry.filename != REQUIRED_DOCUMENTS[0]:
                        out.writestr(entry, source.read(entry))
            result = validate_skill_parity(root, archive=altered)
            self.assertIn({"code": "required-resource-invalid", "path": REQUIRED_DOCUMENTS[0]}, result["blockers"])
            self.assertTrue(
                any(
                    x["code"] == "skill-projection-mismatch" and x["projection"] == "archive"
                    for x in result["blockers"]
                )
            )

    def test_skill_relative_resources_resolve_without_consumer_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_source(root)
            router = root / "skills/agent-plan-to-workers/SKILL.md"
            before = router.read_text()
            router.write_text(before + "\nRead [resource](../../docs/reference/safe-artifact-authoring.md).\n")
            self.assertEqual(validate_skill_parity(root)["status"], "PASS")
            for target in ("../../../outside.md", "/outside.md", "../../docs/missing.md"):
                with self.subTest(target=target):
                    router.write_text(before + f"\nRead [resource]({target}).\n")
                    result = validate_skill_parity(root)
                    self.assertIn("skill-resource-link-invalid", {x["code"] for x in result["blockers"]})

    def test_cookbook_composed_init_examples_use_existing_projection_and_apply_arguments(self):
        parser = build_parser()
        for name in ("docs/guides/lifecycle-cookbook.md", "docs/ru/guides/lifecycle-cookbook.md"):
            document = (ROOT / name).read_text(encoding="utf-8")
            blocks = [
                block
                for block in re.findall(r"```bash\n(.*?)```", document, re.S)
                if block.startswith("agent-lifecycle workflow init")
            ]
            with self.subTest(path=name):
                self.assertEqual(len(blocks), 2)
                projection, apply = [parser.parse_args(shlex.split(block.replace("\\\n", " "))[1:]) for block in blocks]
                self.assertFalse(projection.apply)
                self.assertIsNone(projection.projected_target_digest)
                self.assertTrue(apply.apply)
                self.assertEqual(apply.projected_target_digest, "<full-binding-digest>")
                self.assertEqual(apply.operation_id, "initial-adoption")
                for key in ("manifest", "state", "run_id", "package_id"):
                    self.assertEqual(getattr(projection, key), getattr(apply, key))
                self.assertEqual(apply.manifest, "tasks/release-x/plan.manifest.json")
                self.assertIn("<artifactRoot>/workflow/task-packets", document)
                self.assertIn("AWAITING_AUTHORIZATION", document)
