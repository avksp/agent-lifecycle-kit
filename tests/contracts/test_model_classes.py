"""Keep Source contract initialization independent of the routing layer."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest


class ModelClassBoundaryTests(unittest.TestCase):
    def test_source_schema_initializes_without_loading_model_routing(self) -> None:
        code = '''
import builtins
original_import = builtins.__import__
def contract_only_import(name, *args, **kwargs):
    if name.startswith("agent_lifecycle.model_routing"):
        raise AssertionError("Source contract initialization required model routing")
    return original_import(name, *args, **kwargs)
builtins.__import__ = contract_only_import
from agent_lifecycle.contracts.model_classes import ALLOWED_MODEL_CLASSES
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.contracts.scoped_usage_schemas import (
    SCOPED_USAGE_SCHEMAS, SOURCE_USAGE_POLICY, SOURCE_USAGE_RECEIPT,
)
policy_classes = get_schema(SOURCE_USAGE_POLICY)["properties"]["allowedModelClasses"]["items"]["enum"]
receipt_classes = get_schema(SOURCE_USAGE_RECEIPT)["properties"]["modelClass"]["enum"]
assert set(policy_classes) == ALLOWED_MODEL_CLASSES - {"no-model"}
assert policy_classes == receipt_classes
'''
        result = subprocess.run(
            [sys.executable, "-c", code], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
