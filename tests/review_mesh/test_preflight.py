"""Source/render/restriction refusal through the real external-job boundary."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.adapter_sessions.external_jobs import (
    load_external_job_response,
    run_external_job,
)
from agent_lifecycle.adapter_sessions.process_admission import JournalPreparationAdmission
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.review_mesh.preflight import reviewer_preflight
from tests.accounting.test_journal import PROOF, open_scope
from tests.adapter_sessions.test_external_jobs import _request
from tests.adapter_sessions.test_process_admission import (
    preparation_operation,
    qualified_context,
)


def reviewer_inputs(root, job_id="qualified-review"):
    (root / "source.txt").write_text("immutable reviewed source", encoding="utf-8")
    pins = {"source.txt": hashlib.sha256((root / "source.txt").read_bytes()).hexdigest()}
    packet, rendered = {"task": "bounded independent read"}, b"rendered bounded independent read"
    argv = [sys.executable, "-c", "print('complete response')"]
    request = _request(job_id)
    request["sourceSnapshotDigest"] = canonical_digest(pins)
    request["requestDigest"] = canonical_digest({
        k: v for k, v in request.items() if k != "requestDigest"
    })
    qualification = {
        "requestDigest": request["requestDigest"],
        "repositoryRootDigest": canonical_digest(str(root.resolve())),
        "inputTransport": "STDIN",
        "qualified": True, "sourceSnapshotDigest": canonical_digest(pins),
        "packetDigest": canonical_digest(packet),
        "renderedInputDigest": hashlib.sha256(rendered).hexdigest(),
        "renderedInputBytes": len(rendered), "inputComplete": True,
        "providerReady": True, "readOnlyEnforced": True,
        "restrictionBasis": "HOST_RESTRICTIONS",
        "allowedArgvDigest": canonical_digest(argv),
    }
    return pins, packet, rendered, argv, qualification, request


class ReviewerPreflightTests(unittest.TestCase):
    def test_portable_baselines_retain_missingness_and_never_activate_later_work(self):
        root = Path(__file__).resolve().parents[1] / "metrics/fixtures"
        names = (
            "release-2-21-accounting-baseline.json",
            "release-2-21-guided-comparison-pair.json",
            "release-2-21-audit-rounds-baseline.json",
            "release-2-21-legacy-tier-baseline.json",
        )
        records = []
        for name in names:
            value = json.loads((root / name).read_bytes())
            self.assertEqual(value["baselineDigest"], canonical_digest({
                k: v for k, v in value.items() if k != "baselineDigest"
            }))
            self.assertFalse(value["savingsPercentageClaimed"])
            self.assertFalse(value["productionPromotionClaimed"])
            self.assertEqual(value["modelTokens"], {"status": "UNAVAILABLE", "value": None})
            self.assertNotIn("/" + "Volumes/", str(value))
            self.assertNotIn("/" + "Users/", str(value))
            records.append(value)
        command, guided, audit, legacy = records
        self.assertEqual(len(command["after"]), 10)
        for workload in ("version", "release-accounting-normalized-source-v1"):
            self.assertEqual(sum(x["workloadId"] == workload for x in command["after"]), 5)
        self.assertEqual(len(command["afterRetainedFailureSamples"]), 1)
        self.assertEqual(guided["repetitionCount"], 5)
        self.assertTrue(all(x["stateByteParity"] and x["eventByteParity"]
                            for x in guided["repetitions"]))
        self.assertFalse(audit["release222ActivationReady"])
        self.assertFalse(legacy["release223ActivationReady"])
        self.assertTrue(all(not x["repeatedUnchangedFullReview"] for x in audit["rounds"]))

    def test_input_source_and_technical_refusals_start_zero_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                pins, packet, rendered, argv, original, request = reviewer_inputs(root)
                op = replace(preparation_operation(), input_digest=request["requestDigest"])
                def qualify(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = request["requestDigest"]
                    return context
                admission = JournalPreparationAdmission(journal, op, qualify, clock=lambda: 100)
                runner = Mock(side_effect=AssertionError("model started"))
                for key, bad in (("inputComplete", False), ("readOnlyEnforced", False),
                                 ("restrictionBasis", "PROMPT_ONLY"),
                                 ("providerReady", False), ("packetDigest", "0" * 64),
                                 ("renderedInputBytes", 1)):
                    qualification = {**original, key: bad}
                    def preflight():
                        return reviewer_preflight(
                            request=request,
                            repository_root=root, source_pins=pins, packet=packet,
                            rendered_input=rendered, argv=argv,
                            qualification=qualification, preparation=admission,
                        )
                    with self.assertRaises(LifecycleError):
                        run_external_job(
                            request, argv, env=dict(os.environ), cwd=root,
                            job_root=root / "jobs", process_runner=runner,
                            preparation=admission, review_preflight=preflight,
                            stdin_text=rendered.decode(),
                        )
                    self.assertEqual(journal.snapshot("run").journal_revision, 1)
                    self.assertFalse((root / "jobs").exists())
                runner.assert_not_called()

    def test_safe_complete_input_and_provider_neutral_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                pins, packet, rendered, argv, qualification, request = reviewer_inputs(root)
                admission = JournalPreparationAdmission(
                    journal, preparation_operation(), qualified_context, clock=lambda: 100,
                )
                qualification["api_key"] = "private-provider-secret"
                qualification["debug"] = str(root) * 10000
                result = reviewer_preflight(
                    request=request,
                    repository_root=root, source_pins=pins, packet=packet,
                    rendered_input=rendered, argv=argv,
                    qualification=qualification, preparation=admission,
                )
                self.assertEqual(result["status"], "PASS")
                self.assertLess(len(str(result)), 1000)
                self.assertNotIn(str(root), str(result))
                self.assertNotIn("private-provider-secret", str(result))
                self.assertEqual(result["modelCalls"], 0)
                unsafe = argv + ["--yolo"]
                qualification["allowedArgvDigest"] = canonical_digest(unsafe)
                self.assertEqual(reviewer_preflight(
                    request=request,
                    repository_root=root, source_pins=pins, packet=packet,
                    rendered_input=rendered, argv=unsafe,
                    qualification=qualification, preparation=admission,
                )["status"], "UNAVAILABLE")
                (root / "source.txt").write_text("changed subject", encoding="utf-8")
                self.assertEqual(reviewer_preflight(
                    request=request,
                    repository_root=root, source_pins=pins, packet=packet,
                    rendered_input=rendered, argv=argv,
                    qualification=qualification, preparation=admission,
                )["status"], "UNAVAILABLE")


    def test_actual_invocation_must_equal_preflight_before_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                pins, packet, rendered, argv, qualified, request = reviewer_inputs(root)
                op = replace(preparation_operation(), input_digest=request["requestDigest"])
                def qualify(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = request["requestDigest"]
                    return context
                admission = JournalPreparationAdmission(
                    journal, op, qualify, clock=lambda: 100,
                )
                def preflight():
                    return reviewer_preflight(
                        request=request, repository_root=root, source_pins=pins,
                        packet=packet, rendered_input=rendered, argv=argv,
                        qualification=qualified, preparation=admission,
                    )
                wrong = dict(request, jobId="different-job")
                wrong["requestDigest"] = canonical_digest({
                    k: v for k, v in wrong.items() if k != "requestDigest"
                })
                altered = dict(request, sourceSnapshotDigest="e" * 64)
                altered["requestDigest"] = canonical_digest({
                    k: v for k, v in altered.items() if k != "requestDigest"
                })
                variants = [
                    (request, argv + ["--yolo"], root, rendered.decode(), preflight),
                    (request, argv + ["other"], root, rendered.decode(), preflight),
                    (request, argv, root.parent, rendered.decode(), preflight),
                    (wrong, argv, root, rendered.decode(), preflight),
                    (altered, argv, root, rendered.decode(), preflight),
                    (request, argv, root, "changed", preflight),
                    (request, argv, root, None, preflight),
                    (request, argv, root, rendered[:-1].decode(), preflight),
                    (request, argv, root, rendered.decode(), lambda: {"status": "PASS"}),
                ]
                runner = Mock(side_effect=AssertionError("unchecked effect"))
                for req, args, cwd, text, check in variants:
                    with self.subTest(request=req["jobId"], argv=args, text=text):
                        with self.assertRaises(LifecycleError) as caught:
                            run_external_job(
                                req, args, env=dict(os.environ), cwd=cwd,
                                job_root=root / "jobs", preparation=admission,
                                review_preflight=check, stdin_text=text,
                                process_runner=runner,
                            )
                        self.assertEqual(caught.exception.code,
                                         "REVIEW_PREFLIGHT_UNAVAILABLE")
                        self.assertEqual(journal.snapshot("run").journal_revision, 1)
                        self.assertFalse((root / "jobs").exists())
                runner.assert_not_called()

    def test_qualified_actual_stdin_response_roundtrip_uses_one_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Journal(root / "usage.db", PROOF) as journal:
                open_scope(journal)
                pins, packet, rendered, _, qualified, request = reviewer_inputs(root)
                argv = [sys.executable, "-c", "import sys; print(sys.stdin.read())"]
                qualified["allowedArgvDigest"] = canonical_digest(argv)
                op = replace(preparation_operation(), input_digest=request["requestDigest"])
                def qualify(prefix):
                    context = qualified_context(prefix)
                    context["inputDigest"] = request["requestDigest"]
                    return context
                admission = JournalPreparationAdmission(
                    journal, op, qualify, clock=lambda: 100,
                )
                def preflight():
                    return reviewer_preflight(
                        request=request, repository_root=root, source_pins=pins,
                        packet=packet, rendered_input=rendered, argv=argv,
                        qualification=qualified, preparation=admission,
                    )
                first = run_external_job(
                    request, argv, env=dict(os.environ), cwd=root,
                    job_root=root / "jobs", preparation=admission,
                    review_preflight=preflight, stdin_text=rendered.decode(),
                )
                self.assertTrue(first["result"]["complete"])
                before = journal.snapshot("run")
                body = load_external_job_response(request, job_root=root / "jobs")
                self.assertEqual(body, {"stdout": rendered.decode() + "\n", "stderr": ""})
                self.assertEqual(journal.snapshot("run"), before)
                self.assertEqual(before.active_reservations, 100)
                self.assertNotIn(rendered.decode(), str(first))
