from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.ownership_paths import require_declared_output_footprint
from agent_lifecycle.imports import (
    import_external_agent,
    import_external_dialect,
    import_external_workflow,
    validate_external_import_result,
)


class ExternalDialectTests(unittest.TestCase):
    def test_workflow_dialect_is_imported_as_a_reviewable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "workflow.json"
            source.write_text(
                json.dumps(
                    {
                        "title": "Review workflow",
                        "steps": ["inspect changes", "run tests"],
                        "validation": ["all checks pass"],
                    }
                ),
                encoding="utf-8",
            )

            result = import_external_dialect(source, family="workflow", package_id="external-draft")
            validation = validate_external_import_result(result)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(result["candidatePlan"]["schemaVersion"], "agent-plan-manifest.v1")
            self.assertEqual(result["candidatePlan"]["status"], "DRAFT")
            self.assertFalse(result["candidatePlan"]["externalImport"]["executesInput"])
            self.assertTrue(result["requiresReview"])
            require_declared_output_footprint(result["candidatePlan"])
            self.assertEqual(result["candidatePlan"]["package"]["planArtifactRoot"], "imported/plan")

    def test_workflow_aliases_preserve_review_semantics_and_source_provenance(self) -> None:
        cases = [
            (
                "json",
                json.dumps({"title": "Service checks", "steps": ["Keep status endpoint"], "checks": ["HTTP 200"]}),
            ),
            (
                "json",
                json.dumps(
                    {"name": "Service checks", "jobs": [{"run": "Keep status endpoint"}], "validations": ["HTTP 200"]}
                ),
            ),
            ("yaml", "title: Service checks\nsteps:\n  - Keep status endpoint\nvalidation:\n  - HTTP 200\n"),
        ]
        for extension, content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / ("workflow." + extension)
                source.write_text(content, encoding="utf-8")
                result = import_external_workflow(source, profile_id="review-team.v1")
                self.assertEqual(validate_external_import_result(result)["status"], "PASS")
                candidate = result["candidatePlan"]
                self.assertEqual(candidate["package"]["title"], "Service checks")
                self.assertEqual(len(candidate["specification"]["requirements"]), 1)
                self.assertIn("Keep status endpoint", candidate["specification"]["requirements"][0]["description"])
                self.assertEqual(candidate["externalImport"]["validationHints"], ["HTTP 200"])
                self.assertEqual(candidate["externalImport"]["workHints"][0]["kind"], "workflow-step")
                self.assertEqual(candidate["workstreams"][0]["writes"], [])
                self.assertEqual(result["source"]["label"], source.name)
                self.assertEqual(result["source"]["inputBytes"], len(source.read_bytes()))
                self.assertEqual(result["source"]["digest"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(candidate["importState"]["sourceDigest"], result["source"]["digest"])
                self.assertEqual(
                    candidate["importState"]["nativeDialectProfileDigest"], result["nativeDialectProfileDigest"]
                )
                self.assertEqual(result["dialectProfile"]["profileId"], "review-team.v1")
                self.assertFalse(result["sourceTrusted"])
                self.assertTrue(result["freezeBlocked"])

    def test_agent_hints_preserve_requirements_without_portable_host_defaults(self) -> None:
        payload = {
            "title": "Service reviewer",
            "role": "Review service behavior",
            "policies": ["Keep status endpoint"],
            "provider": "provider-canary",
            "model": "model-canary",
            "auth": "host-managed-login",
            "environment": {"SERVICE_MODE": "staging"},
            "tools": ["read-only-tool-canary"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "agent.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            result = import_external_agent(source)
            self.assertEqual(validate_external_import_result(result)["status"], "PASS")
            candidate = result["candidatePlan"]
            descriptions = [item["description"] for item in candidate["specification"]["requirements"]]
            self.assertEqual(len(descriptions), 2)
            self.assertIn("Review service behavior", descriptions[0])
            self.assertIn("Keep status endpoint", descriptions[1])
            hints = candidate["externalImport"]["hostLocalHints"]
            for key in ("provider", "model", "auth"):
                self.assertEqual(
                    hints[key], {"redacted": True, "valueDigest": canonical_digest({"value": payload[key]})}
                )
                self.assertNotIn(payload[key], json.dumps(result))
                self.assertNotIn(key, candidate)
            self.assertEqual(hints["environmentKeys"], ["SERVICE_MODE"])
            self.assertEqual(
                hints["toolHints"],
                [{"redacted": True, "valueDigest": canonical_digest({"value": payload["tools"][0]})}],
            )
            self.assertNotIn(payload["tools"][0], json.dumps(result))
            self.assertFalse(candidate["externalImport"]["portableProviderDefaults"])
            self.assertFalse(candidate["externalImport"]["executesInput"])
            self.assertEqual(candidate["status"], "DRAFT")
            self.assertTrue(candidate["importState"]["freezeBlocked"])
            self.assertEqual(candidate["importState"]["sourceDigest"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_workflow_mapping_refuses_extra_steps_without_a_partial_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "workflow.json"
            source.write_text(json.dumps({"steps": [f"Review endpoint {i}" for i in range(10)]}), encoding="utf-8")
            result = import_external_workflow(source, target_tokens=100000)
            self.assertEqual(result["status"], "FAIL")
            self.assertIsNone(result["candidatePlan"])
            self.assertEqual(result["candidateLifecycleStatus"], "BLOCKED")
            self.assertTrue(result["freezeBlocked"])
            self.assertTrue(any(b.get("field") == "requirements" and b.get("count") == 10 for b in result["blockers"]))

    def test_ninth_recognized_item_is_never_silently_discarded(self) -> None:
        items = [f"Review item {i}" for i in range(9)]
        cases = [("workflow", {key: items}, "requirements") for key in ("steps", "jobs", "tasks")]
        cases += [
            ("workflow", {"steps": ["Review input"], key: items}, "validationHints")
            for key in ("validation", "validations", "checks")
        ]
        cases += [("agent", {key: items}, "requirements") for key in ("policies", "policy", "rules", "instructions")]
        cases.append(("agent", {"role": "Reviewer", "policies": items[:8]}, "requirements"))
        for family, payload, field in cases:
            with self.subTest(family=family, payload=payload), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "input.json"
                source.write_text(json.dumps(payload), encoding="utf-8")
                result = import_external_dialect(source, family=family, target_tokens=100000)
                self.assertEqual(result["status"], "FAIL")
                self.assertIsNone(result["candidatePlan"])
                blocker = next(b for b in result["blockers"] if b.get("field") == field)
                self.assertEqual((blocker["count"], blocker["cap"]), (9, 8))
                self.assertFalse(result["sourceTrusted"])
                self.assertTrue(result["requiresReview"])

    def test_yaml_like_count_refusal_and_exact_eight_item_boundary(self) -> None:
        for family, key in (("workflow", "steps"), ("agent", "policies")):
            for count in (8, 9):
                with self.subTest(family=family, count=count), tempfile.TemporaryDirectory() as tmp:
                    source = Path(tmp) / "input.yaml"
                    source.write_text(key + ":\n" + "".join(f"  - Item {i}\n" for i in range(count)), encoding="utf-8")
                    result = import_external_dialect(source, family=family, target_tokens=100000)
                    self.assertEqual(result["status"], "PASS" if count == 8 else "FAIL")
                    if count == 8:
                        self.assertEqual(len(result["candidatePlan"]["specification"]["requirements"]), 8)
                    else:
                        self.assertIsNone(result["candidatePlan"])

    def test_rendered_character_boundary_and_final_negation_are_preserved(self) -> None:
        marker = "UNIQUE_ITEM_MARKER"
        for family, field in (("workflow", "steps"), ("agent", "policies"), ("agent", "role")):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "input.json"
                source.write_text(json.dumps({field: marker if field == "role" else [marker]}), encoding="utf-8")
                baseline = import_external_dialect(source, family=family, target_tokens=100000)
                description = baseline["candidatePlan"]["specification"]["requirements"][0]["description"]
                self.assertEqual(description.count(marker), 1)
                overhead = len(description) - len(marker)
                tail = " only after approval"
                for delta in (-1, 0, 1):
                    raw = "界" * (180 - overhead - len(tail) + delta) + tail
                    source.write_text(
                        json.dumps({field: raw if field == "role" else [raw]}, ensure_ascii=False), encoding="utf-8"
                    )
                    result = import_external_dialect(source, family=family, target_tokens=100000)
                    self.assertEqual(result["status"], "FAIL" if delta == 1 else "PASS")
                    if delta <= 0:
                        actual = result["candidatePlan"]["specification"]["requirements"][0]["description"]
                        self.assertIn(raw, actual)
                        self.assertEqual(len(actual), 180 + delta)
                    else:
                        self.assertIsNone(result["candidatePlan"])
                raw = "A" * 190 + " DO_NOT_DEPLOY_WITHOUT_APPROVAL"
                source.write_text(json.dumps({field: raw if field == "role" else [raw]}), encoding="utf-8")
                result = import_external_dialect(source, family=family, target_tokens=100000)
                self.assertEqual(result["status"], "FAIL")
                self.assertIsNone(result["candidatePlan"])
                self.assertNotIn("DO_NOT_DEPLOY_WITHOUT_APPROVAL", json.dumps(result))

    def test_validation_hint_character_boundary(self) -> None:
        for size in (179, 180, 181):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "input.json"
                hint = "界" * size
                source.write_text(
                    json.dumps({"steps": ["Review input"], "checks": [hint]}, ensure_ascii=False), encoding="utf-8"
                )
                result = import_external_dialect(source, family="workflow", target_tokens=100000)
                self.assertEqual(result["status"], "FAIL" if size > 180 else "PASS")
                if size <= 180:
                    self.assertEqual(result["candidatePlan"]["externalImport"]["validationHints"], [hint])
                else:
                    self.assertIsNone(result["candidatePlan"])


if __name__ == "__main__":
    unittest.main()
