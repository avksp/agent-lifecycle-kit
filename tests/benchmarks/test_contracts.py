from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_lifecycle.benchmarks.contracts import BUNDLED_SUITE_PATH, load_suite
from agent_lifecycle.contracts.compatibility import build_contract_policy, validate_contract_policy
from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class BenchmarkContractTests(unittest.TestCase):
    def test_benchmark_schemas_are_registered_and_additive(self) -> None:
        expected = {
            "agent-reference-task-suite.v1",
            "agent-reference-task-oracle.v1",
            "agent-reference-task-submission.v1",
            "agent-reference-task-evaluation.v1",
        }
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertTrue(expected.issubset(schema_ids))
        for schema_id in expected:
            self.assertTrue(get_schema(schema_id)["additionalProperties"])

    def test_evaluation_contract_is_public_and_non_promotional(self) -> None:
        policy = build_contract_policy()
        validation = validate_contract_policy(policy)

        self.assertEqual(validation["status"], "PASS")
        row = next(item for item in policy["cliOutputs"] if item["command"] == "benchmark evaluate")
        self.assertEqual(row["schemaVersion"], "agent-reference-task-evaluation.v1")
        schema = get_schema(row["schemaVersion"])
        self.assertFalse(schema["properties"]["productionPromotionClaimed"]["const"])

    def test_standard_suite_path_resolves_from_installed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            manifest = prefix / BUNDLED_SUITE_PATH
            manifest.parent.mkdir(parents=True)
            cwd = prefix / "cwd"
            cwd.mkdir()
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-reference-task-suite.v1",
                        "suiteId": "installed-suite",
                        "suiteVersion": "1.0.0",
                        "tasks": [
                            {
                                "id": "rt01-planning",
                                "family": "planning",
                                "tier": "S0",
                                "version": "1.0.0",
                                "taskPath": "rt01-planning/task.md",
                                "oraclePath": "rt01-planning/oracle.json",
                            }
                        ],
                        "productionPromotionClaimed": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with contextlib.chdir(cwd), mock.patch("agent_lifecycle.benchmarks.contracts.sys.prefix", str(prefix)):
                suite = load_suite(BUNDLED_SUITE_PATH)
            self.assertEqual(suite.payload["suiteId"], "installed-suite")


if __name__ == "__main__":
    unittest.main()
