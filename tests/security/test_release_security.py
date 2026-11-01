from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import tokenize
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT_BYTES = 2 * 1024 * 1024
# Exact synthetic fixtures, public scope IDs and public schema/permission labels.
# New values or another path/key are checked; no file or directory is exempted.
_EXACT_NON_SECRET_LITERALS = {
    ".github/workflows/publish.yml": {
        "id-token": ("10fd874b68dad080ed706762c8e163dabb20514bddae38fb159c56f714a3b143",),
    },
    "CHANGELOG.md": {
        "@marker": ("698880936a0899a04706a06269fc377eab8727526edd097f72a697d2feb3b9ec",),
    },
    "docs/reference/managed-adapter-sessions.md": {
        "authorization": ("defa08b050cdaafcdd0c81b11328912b8f694ea449073d6fbc7e89ffe70215fb",),
    },
    "docs/reference/public-locators-and-redaction.md": {
        "@marker": ("62d1ebec031609251f17183cc52039a9c609383088ede57547937a11842065ba",),
    },
    "src/agent_lifecycle/host_protocol/sandbox_receipts.py": {
        "CREDENTIAL_PROXY_KEY": ("f237b27ee305fc18c6a27afd0a9b574435e136bdb3406dd61bd38ab229832db1",),
        "PARTIAL_CONTAINMENT_KEY": ("a214a8cd9f16fc1c624e12cc400757a828fc54dc4fd959191c74af631c0d7f3b",),
    },
    "tests/accounting/fixtures/release_216_accounting.json": {
        "scope_key": (
            "168df7002aba8402e481dccf1545bec911ca831b0f2a2278092768c5f645b41d",
            "b23a6a8439c0dde5515893e7c90c1e3233b8616e634470f20dc4928bcf3609bc",
            "d79d3458a58877cd8e48c18ebaf4c27b9d5c1a9cb5dfbdac769a7a21d8a1022e",
            "dd56de4137951d9c92681b03416ec15f886b4482a27e3a517d32f085244cbe5d",
        ),
    },
    "tests/accounting/test_journal.py": {
        "dispatch_key": ("168e23279fe806ae7b6a31fe58fdd568294ad826b1a57f0c891de90d37a07817",),
    },
    "tests/accounting/test_opening_balances.py": {
        "dispatch_key": ("9280d31d377e34b39b0a7d606967faca26a471f972b1afbf4173f37c031da8c9",),
    },
    "tests/adapter_sessions/test_env_policy.py": {
        "HOST_TOKEN": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
        "PROJECT_KEY": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/adapter_sessions/test_external_jobs.py": {
        "api_key": ("3748659281f36f9c811614eb1a919ccecc6210a546d4aed738e42021dbd4673b",),
    },
    "tests/adapter_sessions/test_secure_launcher.py": {
        "SAFE_TOKEN": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
        "SECRET": ("5cd3729e9124aa15005c6f91c6c237fe93f57c8e7aa8ae8fefa2fe127de8382b",),
    },
    "tests/adapter_sessions/test_session_contracts.py": {
        "@marker": ("cfbc8a06fc900b7ed17d68a526735ec0dd88d2ed5705ac8278599921b7697bf0",),
        "Authorization": ("31b03229dee8734241e465334988de2a645e9d4d629a4215a63b76afdb3e8575",),
    },
    "tests/adapters/fixtures/host_usage/redacted-secret.json": {
        "@marker": ("44e40dc3a0f5d9795367fe0793a996f377a6e6c1df59818aef001413d1488d96",),
    },
    "tests/benchmarks/fixtures/redaction-leak.json": {
        "@marker": ("e1908287962ab3801eeb76b5fabafef87a4c2e8fd31f4d320f49d92648bd2349",),
        "api_key": ("02a821f62daa76b0c1db8a71242029c9149f29708c8466a68f48180d7fafe3ad",),
    },
    "tests/benchmarks/test_evaluator.py": {
        "@marker": ("6df6862599a9393c9372b253e47c3b909a95f201859383b9bc099f08b9b44bf5",),
    },
    "tests/cli/test_import_security_boundaries.py": {
        "Cookie": ("6420fecfd1ef703e3e675cd820edef648a67742bc35c90bf05d675fbb17cb37a",),
    },
    "tests/cli/test_external_job_commands.py": {
        "api_key": ("a4a25ded08d6b7a0b3d0ed416af77edb1e49f1e04018827c7814279e4c2b5351",),
    },
    "tests/compiler/test_phase_packets.py": {
        "@marker": ("df5c542fdcd9c80952744c14b70867738b3f90e55b77f88f17b9f8817b309281",),
        "_secret": ("6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090",),
        "password": ("f52fbd32b2b3b86ff88ef6c490628285f482af15ddcb29541f94bcf526a3f6c7",),
    },
    "tests/context/test_checkpoints.py": {
        "api_key": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/contracts/test_finding_check_schemas.py": {
        "TOKEN": ("0d4fbf0cf833b45112726faa9104f18ef117316a717a34c2a119e7c694f2f498",),
    },
    "tests/contracts/test_lifecycle_control_schemas.py": {
        "TOKEN": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/contracts/test_preparation_policy.py": {
        "api_key": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/contracts/test_process_redaction.py": {
        "@marker": (
            "62222947b94101aeaf3122e9920be04208f049d9ea4559e8d6878d537d4c5225",
            "7ada5579a5b98207ff9e2baafb27819769964a8668fa6a975c01fc20ddd207e3",
            "f32b48194f7b773371afa934ba261efbe73df47020b33df863b9c07409750589",
        ),
        "token": ("d34c09fe275706e837a3af312d3fa6bdeb1df4aefca51ba5c61d64240ad93ad2",),
    },
    "tests/contracts/test_public_locators.py": {
        "@marker": (
            "3c92e874cc17aa409f5cdf1ad95fd0092d2c8d02b291f3d1816dd8066195dd15",
            "57a5619a2acaa71e1691c517b420197b6d54ae20edbb2adedacb164756f1ce01",
            "916bb2a4fa46f427b95cea4c95ace4ee2abb41c287a0a63dcac3b34f36d1ee71",
        ),
    },
    "tests/contracts/test_redaction.py": {
        "Cookie": (
            "6420fecfd1ef703e3e675cd820edef648a67742bc35c90bf05d675fbb17cb37a",
            "77d7f39b36df946b63da988f2921db83f6c125dd979e972fb168b76ec3e95615",
            "de83ee494e2551b15e86942bdd86cf79a318cdaa07e18442d75b28d5da0eeb0b",
        ),
        "Set-Cookie": (
            "3bac9674666f6eb0ff8c0afbfd19bca27223b55e30fadb83fd4c5e2ea7684d97",
            "f03791f81cef43a9a37adf49ff2e594fea34dc3e491b940320ed28441b56ef9e",
        ),
        "@marker": (
            "146c34ba19c7d49437339ea800879379800b28d5e8d5f255bc08813c6fd0d64e",
            "195943887e1026f5b3ca2a271fdba314d793c3db7fd634e9f3c889221c2c042d",
            "1ef5974230b269295c23f4a50d2ccdf7585e2180713308e5d89119042de009be",
            "2bba7c68636e96fa25605475f4d64854bf7e09970117d163d599cbfd174e978e",
            "30ecfeeffa117e93bb656f4a5e0a200367a632f661280b7c94116e890ea90404",
            "3512ef2ae488b1efff8895b1822c4586ac606eae9d3d81ecbf33ec5c05c1cb77",
            "5758ed478c833d75b5ecc8fc77b39fd105dfbc5979c7da0334976d5c32c4220f",
            "5de2cd690869b9bb18c6f0a64e26f4d12654302090260bd08fd5b9624c8d187b",
            "654d3ec44c01f96812d280ef4d5b71c4f3e2dc3de8f626af6786ecf266cb7093",
            "72dac60886fc07144bc9a8252b8592a600128aff67558b4b021e9d4b9bfd26f5",
            "7df8bde2ceb19d8d3f6b5332f7501868331319d4b7e892e4d600c8bd8727a55d",
            "880e48c65c8be415fa3f8c15e91034b3d7d6a3ba4b3ca046297810c1d7c0b9b0",
            "8c8d3ce7cbd24c118d7931490e3ed150a0ea6635145af24f9850975b4f4fbc86",
            "a52c723e2651f628fa168a8f429cb6189ac303bd4fc2adcc6051da8176d6e9a2",
            "ab08b24f1b6ae87febc97f1e8bb713b0719845ce9447740cbfb2f75e16df77d1",
            "b5537918242a6ccd11aa64d965fb85655a55c97e394d73c842ad481c078c2b46",
            "bc0cd971247d2538b31f82beac1d43218e27d52d0e80e79728033de638736011",
            "bc57fa94f27e939e72b35e13aa2074e5c9b0e72cb0ae89b32f500cf98f180a6a",
            "c357beb4f826cdad153bc0eef66d7eae47406a443c540c9dd12ff6f28d59ad48",
            "e24cbd5c1fa1838544d74dc91f01b0a818bea75d6135d222d1ad3d15fd4c0d84",
            "e415f0d4c0aa5466082913326cdfca95e3e1fb973835040d75c0c51f1c6b1029",
            "e6e8d48642f47497de3fc2d38c29484f2744a70c92d7494e5d2756632fba5846",
            "fbc0a8c3b2371360630a58e691f4b9e9585240350d7f82adec5506b051302a85",
        ),
        "API_KEY": ("580f8192d34c586e448bc70ba0f0aafd6a444f7806301a79f6939ca87357fb95",),
        "Authorization": (
            "0e35f6e9742e074dfd62e874de3c242c6d9b64c21bf9afbaf3d11f05579b4495",
            "ed85253568ad54e7465aedac24e273b73ad025e3fb8752d38b9c159a3a0337b6",
        ),
        "api_key": ("ad7717428b254412a3604368d973eb18ea61d22ef5beaffd9481bf3192cf4751",),
        "authorization": ("fbb7b5bf4ca348eeeebf8cc3660712859a5a1fbf18e83217a57ce203fb51d5c2",),
        "credential": (
            "0e9d220616f08345a714ee57d8516310770588484b5239844635f952965e34a6",
            "74405cf4aae4dacdb793e77554d1c6c202526c21cdd1f8b9345e4f8985a3d7d3",
        ),
        "password": ("0ae70fa044cf10a0fc3887b85fe3675acc620a7d15e588e5f1f47e8b27787e5f",),
        "refresh_token": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
        "token": ("aaa9352179250084a737940d1850c9b0a26613ac173d42adde9ecbd42494ae92",),
    },
    "tests/contracts/test_thread_bridge_schemas.py": {
        "api_key": ("e564b4081d7a9ea4b00dada53bdae70c99b87b6fce869f0c3dd4d2bfa1e53e1c",),
        "idempotency_key": ("d05b61bd4b70e0d9a197ac9360f8c24e4eaed5336d31aafd5e16d829c6576df3",),
        "token": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/diagnostics/test_bundles.py": {
        "apiKey": ("31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",),
    },
    "tests/release/test_agent_plugin_publication.py": {
        "id-token": ("10fd874b68dad080ed706762c8e163dabb20514bddae38fb159c56f714a3b143",),
    },
    "tests/evidence_index/test_external_context.py": {
        "@marker": ("d914caae9d47cfe33faeab66c7413d278a59bc3d88e467d8add21cf024c5fe86",),
        "API_KEY": (
            "05227ef63c38fea00e4d40f0ce08c8263b187db584631a14cf8e867712cfff3e",
            "31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",
            "b237083ae0bb9d4a1b44fe196a0376d5428c927f82befcbbb161176df0a13226",
        ),
    },
    "tests/host_protocol/test_adapter_capabilities.py": {
        "@marker": ("df5c542fdcd9c80952744c14b70867738b3f90e55b77f88f17b9f8817b309281",),
        "apiKey": ("31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",),
        "session-token": ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",),
    },
    "tests/host_protocol/test_receipts.py": {
        "@marker": ("25a8efe39f12d2be2cfb9bee1b8daca4796056a8b4424bc9f6f4fe84e30c9dae",),
    },
    "tests/imports/test_planning_imports.py": {
        "@marker": ("085f1b85f1b455ffd1613abc32be5fd6f898ca1b1f5a34545df37c8377724d83",),
    },
    "tests/imports/test_security_findings.py": {
        "password": ("6d229884c1268bb0ab32d8da315d0fe52f9147228bd830a37bc9fb28a954940d",),
    },
    "tests/live_hosts/test_common_budget.py": {
        "ALK_OTHER_PROVIDER_KEY": ("9c0ee26e4a1fbb028187486a7ea91f81f8ab81fcf467cba75107dbd3a64244d7",),
        "ALK_PROVIDER_KEY": ("31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",),
        "ALK_TEST_HOST_KEY": ("31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",),
    },
    "tests/metrics/test_audit_samples.py": {
        "Secret": ("32b56ed53348a8587f30c90e5c6406df95d3b8ab1130b1da62bcf492a8ed8a63",),
    },
    "tests/project/test_profile.py": {
        "apiKey": ("2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b",),
    },
    "tests/release/test_limited_usage_measurement.py": {
        "ALK_MEASUREMENT_SECRET": (
            "35443277fe297662cfc34d304b04f2f5fb2b853a8292901001ef6232de91a7a3",
            "45ba622476b2cbfe4405f4d4b5d4fa8085d88537ca3c74e0f8b09534ff45f4e6",
        ),
    },
    "tests/release/test_release_evidence_portability_validator.py": {
        "accessToken": ("f9b0078b5df596d2ea19010c001bbd009e651de2c57e8fb7e355f31eb9d3f739",),
        "token": ("23d11cf444616c2d2cc2a38e2440ad0510cf67e46b3739ed2371f20aadc90ebe",),
    },
    "tests/release/test_security_docs.py": {
        "@marker": ("0b7e496fb57860dcf5639dbaf93df1905cf6fa281282e0e4f95dc08a832c7c65",),
    },
    "tests/review_mesh/test_operator_templates.py": {
        "@marker": ("66aa42a887c62fdf53c2dc5f49cbea34a2c6dd5df77464f569cf877d74f3a741",),
    },
    "tests/review_mesh/test_preflight.py": {
        "api_key": ("50c7d8d1ce32d49c3ee3f6544a721646c07b97f3241745731f6af683f7f6b4d7",),
    },
    "tests/review_mesh/test_result_import.py": {
        "@marker": (
            "2bba7c68636e96fa25605475f4d64854bf7e09970117d163d599cbfd174e978e",
            "30ecfeeffa117e93bb656f4a5e0a200367a632f661280b7c94116e890ea90404",
            "654d3ec44c01f96812d280ef4d5b71c4f3e2dc3de8f626af6786ecf266cb7093",
            "72dac60886fc07144bc9a8252b8592a600128aff67558b4b021e9d4b9bfd26f5",
            "7df8bde2ceb19d8d3f6b5332f7501868331319d4b7e892e4d600c8bd8727a55d",
            "880e48c65c8be415fa3f8c15e91034b3d7d6a3ba4b3ca046297810c1d7c0b9b0",
            "a52c723e2651f628fa168a8f429cb6189ac303bd4fc2adcc6051da8176d6e9a2",
            "ab08b24f1b6ae87febc97f1e8bb713b0719845ce9447740cbfb2f75e16df77d1",
            "bc57fa94f27e939e72b35e13aa2074e5c9b0e72cb0ae89b32f500cf98f180a6a",
            "c357beb4f826cdad153bc0eef66d7eae47406a443c540c9dd12ff6f28d59ad48",
            "d9fc860436879d294f800e94610e0791268f6aff96004ba2788b2a4cdd05e38c",
            "e415f0d4c0aa5466082913326cdfca95e3e1fb973835040d75c0c51f1c6b1029",
            "e6e8d48642f47497de3fc2d38c29484f2744a70c92d7494e5d2756632fba5846",
        ),
        "Authorization": (
            "0e35f6e9742e074dfd62e874de3c242c6d9b64c21bf9afbaf3d11f05579b4495",
            "ed85253568ad54e7465aedac24e273b73ad025e3fb8752d38b9c159a3a0337b6",
        ),
        "api_key": (
            "cc0e7608b73ea73b08fd28b582c21ba4ce5a0b1c9202bf7d2dcc85366205b622",
            "e54b74eb9192b48055c48d2062bffdd23469ef7d70f960ff1293a47f86c8eba2",
        ),
        "authorization": ("fbb7b5bf4ca348eeeebf8cc3660712859a5a1fbf18e83217a57ce203fb51d5c2",),
        "client-secret": ("cc0e7608b73ea73b08fd28b582c21ba4ce5a0b1c9202bf7d2dcc85366205b622",),
        "credential": (
            "0e9d220616f08345a714ee57d8516310770588484b5239844635f952965e34a6",
            "74405cf4aae4dacdb793e77554d1c6c202526c21cdd1f8b9345e4f8985a3d7d3",
        ),
        "password": (
            "0ae70fa044cf10a0fc3887b85fe3675acc620a7d15e588e5f1f47e8b27787e5f",
            "cc0e7608b73ea73b08fd28b582c21ba4ce5a0b1c9202bf7d2dcc85366205b622",
        ),
        "token": ("cc0e7608b73ea73b08fd28b582c21ba4ce5a0b1c9202bf7d2dcc85366205b622",),
    },
    "tests/security/test_secret_guard_encodings.py": {
        "@marker": (
            "2b06660b6874dfc6671925e58b064c68b6a9b7b3ce62c529b9c6dc6742028c39",
            "6f5f93a0f1b5b59957c42e7ea1025c57b4797172d36ad055eea10322382d701c",
        ),
        "Authorization": ("bb771ea15592d28d06a52bd63ef38b173e3375bd9dcbe5511dc2cac98df29864",),
        "DB_PASSWORD": (
            "77055454ccccfed0057f2c87318a4b7adece2acc4d384547be5c1484c1362023",
            "fd9ce304dca27abb87af0a2856b97b5994229c7925110aa6dd76e6653616cc46",
        ),
    },
    "tests/workflow/fixtures/release_216_a5_routes.json": {
        "@marker": ("c4505d98ba0cce6ac9744a3a16dc48ce4d2a2c7a22d59c69a4684c78f975afab",),
    },
    "tests/workflow/test_artifact_builders.py": {
        "password": ("31160254d1297393d2ad00e1c01851aec834361e02c524b89fe06aff2879ce6a",),
    },
    "tools/release/validate_project_workflow_presets.py": {
        "credentials": ("a26075ed2e784cb181eaabb10acd083520d311bc68b4b7d00d57de825bb3ec86",),
    },
}
INTENTIONAL_LITERAL_FIXTURES: set[tuple[str, str, str]] = {
    (path, key, fingerprint)
    for path, fields in _EXACT_NON_SECRET_LITERALS.items()
    for key, fingerprints in fields.items()
    for fingerprint in fingerprints
}

INTENTIONAL_PATH_FIXTURES = {
    "tests/context/test_checkpoints.py:" + "/" + "Volumes/",
}
sys.path.insert(0, str(ROOT / "src"))


class ReleaseSecurityTests(unittest.TestCase):
    def test_temporary_plan_artifacts_are_not_tracked(self) -> None:
        tracked_plan_paths = [path for path in _git_ls_files() if path == "plans" or path.startswith("plans/")]
        self.assertEqual(tracked_plan_paths, [])

    def test_tracked_text_files_do_not_contain_local_paths_or_secret_markers(self) -> None:
        from agent_lifecycle.contracts.redaction import contains_bare_secret_token

        forbidden = (
            "/" + "Volumes/",
            "/" + "Users/",
            "BEGIN " + "RSA PRIVATE KEY",
            "BEGIN " + "OPENSSH PRIVATE KEY",
            "BEGIN " + "PRIVATE KEY",
            "github" + "_pat_",
            "gh" + "p_",
            "xo" + "xb-",
        )
        offenders: list[str] = []
        for rel_path in _git_ls_files():
            path = ROOT / rel_path
            if not path.is_file():
                continue
            try:
                text = _tracked_text(path)
            except (OSError, UnicodeError, ValueError):
                offenders.append(f"{rel_path}:unsupported-text")
                continue
            if text is None:
                continue
            if contains_bare_secret_token(text):
                offenders.append(f"{rel_path}:bare-token")
            try:
                literals = _sensitive_literals(text, path.suffix)
            except (ValueError, RecursionError):
                offenders.append(f"{rel_path}:unsupported-literal-depth")
                continue
            for key, fingerprint in literals:
                if (rel_path, key, fingerprint) not in INTENTIONAL_LITERAL_FIXTURES:
                    offenders.append(f"{rel_path}:sensitive-literal")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{rel_path}:{marker}")

        unexpected = set(offenders).difference(INTENTIONAL_PATH_FIXTURES)
        self.assertEqual(unexpected, set())

    def test_tracked_guard_refuses_each_bare_family_without_echoing_values(self) -> None:
        cases = [
            ("api", "sk-" + "A" * 20),
            ("project-api", "sk-proj-" + "B" * 20),
            ("jwt", "ey" + "J" + "A" * 8 + "." + "B" * 8 + "." + "C" * 8),
            ("github", "gh" + "o_" + "D" * 20),
            ("gitlab", "glpat-" + "E" * 20),
            ("npm", "npm_" + "F" * 20),
            ("payment", "rk_test_" + "G" * 16),
            ("hugging-face", "hf_" + "H" * 20),
            ("google", "AI" + "za" + "I" * 35),
            ("slack", "xox" + "a-" + "J" * 16),
            ("aws", "AK" + "IA" + "K" * 16),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=["probe.py"]):
                for family, value in cases:
                    with self.subTest(family=family):
                        (root / "probe.py").write_text("# " + value, encoding="utf-8")
                        with self.assertRaises(AssertionError) as caught:
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                        self.assertTrue(value not in str(caught.exception))

    def test_tracked_guard_keeps_legacy_rules_and_exact_path_exception(self) -> None:
        markers = [
            "/" + "Volumes/",
            "/" + "Users/",
            "BEGIN " + "RSA PRIVATE KEY",
            "BEGIN " + "OPENSSH PRIVATE KEY",
            "BEGIN " + "PRIVATE KEY",
            "github" + "_pat_",
            "gh" + "p_",
            "xo" + "xb-",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=["probe.py"]):
                for index, value in enumerate(markers):
                    with self.subTest(marker=index):
                        (root / "probe.py").write_text(value, encoding="utf-8")
                        with self.assertRaises(AssertionError):
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                (root / "probe.py").write_text("feature = 'ordinary-placeholder'", encoding="utf-8")
                self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
            for relative, allowed in (("tests/context/test_checkpoints.py", True), ("tests/context/other.py", False)):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("/" + "Volumes/", encoding="utf-8")
                with patch(__name__ + ".ROOT", root), patch(__name__ + "._git_ls_files", return_value=[relative]):
                    if allowed:
                        self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()
                    else:
                        with self.assertRaises(AssertionError):
                            self.test_tracked_text_files_do_not_contain_local_paths_or_secret_markers()

    def test_verified_adapters_keep_host_bound_evidence_and_no_public_approval_claim(self) -> None:
        for path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("maturity") != "VERIFIED":
                continue
            live_range = payload.get("liveTestedHostRange")
            self.assertIsInstance(live_range, dict, path.as_posix())
            self.assertFalse(live_range["productionPromotionClaimed"])
            self.assertFalse(live_range["publicDirectoryApprovalClaimed"])
            self.assertGreaterEqual(len(live_range["evidence"]), 3)
            self.assertTrue(payload.get("modelRouting", {}).get("liveVerified"))


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=10,
    )
    return result.stdout.splitlines()


def _is_binary(path: Path) -> bool:
    with path.open("rb") as stream:
        data = stream.read(4096)
    return not data.startswith((b"\xff\xfe", b"\xfe\xff")) and b"\0" in data


def _tracked_text(path: Path) -> str | None:
    with path.open("rb") as stream:
        prefix = stream.read(4096)
        utf16 = prefix.startswith((b"\xff\xfe", b"\xfe\xff"))
        if not utf16 and b"\0" in prefix:
            return None
        raw = prefix + stream.read(MAX_TEXT_BYTES + 1 - len(prefix))
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("Text exceeds decode bound")
    return raw.decode("utf-16" if utf16 else "utf-8-sig")


def _sensitive_literals(text: str, suffix: str) -> set[tuple[str, str]]:
    """Share credential categories; inspect static values without executing code."""
    from agent_lifecycle.contracts.redaction import REDACTED_VALUE, is_sensitive_key

    if suffix == ".py":
        try:
            candidates = _python_literal_pairs(ast.parse(text))
        except SyntaxError:
            candidates = [*_config_pairs(text), ("@text", text)]
        with suppress(tokenize.TokenError, IndentationError):
            candidates.extend(
                ("@text", item.string.lstrip("# "))
                for item in tokenize.generate_tokens(io.StringIO(text).readline)
                if item.type == tokenize.COMMENT
            )
    elif suffix == ".json":
        try:
            pending = [json.loads(text)]
        except json.JSONDecodeError:
            # Broken JSON is data, not executable source: use the conservative
            # shared classifier so a syntax error cannot hide a credential.
            return (
                {("@marker", hashlib.sha256(text.encode()).hexdigest())}
                if _shared_secret_marker(text, raw_data=True)
                else set()
            )
        candidates = []
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                candidates.extend((key, value) for key, value in item.items() if isinstance(value, str))
                candidates.extend(("@text", value) for value in item.values() if isinstance(value, str))
                pending.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str):
                candidates.append(("@text", item))
    else:
        candidates = list(_config_pairs(text)) + [("@text", unit) for unit in _text_units(text)]
    result = set()
    for key, value in candidates:
        if not isinstance(value, str) or not value:
            continue
        if is_sensitive_key(key) and value != REDACTED_VALUE:
            result.add((key, hashlib.sha256(value.encode()).hexdigest()))
        if key == "@text":
            result.update((key, hashlib.sha256(value.encode()).hexdigest()) for key, value in _config_pairs(value))
            if _shared_secret_marker(value):
                result.add(("@marker", hashlib.sha256(value.encode()).hexdigest()))
    return result


def _python_literal_pairs(tree: ast.AST) -> list[tuple[str, object]]:
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidates.append(("@text", node.value))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    candidates.append((key.value, _literal_string(value)))
        elif isinstance(node, ast.keyword) and node.arg is not None:
            candidates.append((node.arg, _literal_string(node.value)))
        elif isinstance(node, ast.arguments):
            positional = node.posonlyargs + node.args
            for key, value in zip(positional[len(positional) - len(node.defaults) :], node.defaults, strict=True):
                candidates.append((key.arg, _literal_string(value)))
            for key, value in zip(node.kwonlyargs, node.kw_defaults, strict=True):
                candidates.append((key.arg, _literal_string(value)))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    key = target.id
                elif isinstance(target, ast.Attribute):
                    key = target.attr
                elif isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                    key = target.slice.value
                else:
                    continue
                if isinstance(key, str):
                    candidates.append((key, _literal_string(node.value)))
    return candidates


def _literal_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _config_pairs(text: str):
    from agent_lifecycle.contracts.redaction import REDACTED_VALUE, is_sensitive_key

    for line in text.splitlines():
        for separator in ("=", ":"):
            key, found, value = line.strip().partition(separator)
            key = key.strip().removeprefix("export ").strip("\"'`")
            value = value.strip().rstrip(",")
            if not found or not re.fullmatch(r"[A-Za-z_][\w-]*", key) or not is_sensitive_key(key) or not value:
                continue
            if value.startswith(('"', "'")):
                try:
                    literal = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    continue
            else:
                literal = value.split(" #", 1)[0].strip()
            if isinstance(literal, str) and literal:
                if literal == REDACTED_VALUE:
                    continue
                if re.fullmatch(r"\$\{[A-Za-z_]\w*\}", literal) or re.fullmatch(
                    r"\$\{\{\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\}\}", literal
                ):
                    continue  # Only explicit variable references, never arbitrary '$' values.
                yield key, literal


def _shared_secret_marker(value: str, *, raw_data: bool = False) -> bool:
    from agent_lifecycle.contracts.redaction import redact_text_with_stats

    # Remove assignment delimiters so conservative assignment redaction does not
    # classify source expressions as credentials. Bearer/PEM/provider rules stay
    # owned by the common policy. URL lexing only selects data for that policy.
    neutral = value if raw_data else value.translate(str.maketrans({"=": " ", ":": " "}))
    if redact_text_with_stats(neutral)[2]["secretLikeMarkersRedacted"]:
        return True
    return any(
        redact_text_with_stats(match.group())[2]["secretLikeMarkersRedacted"]
        for match in re.finditer(r"https?://[^\s\"'<>]+", value)
    )


def _text_units(text: str):
    """Keep exact marker exceptions stable across unrelated document edits."""
    pem = []
    for line in text.splitlines():
        line = line.strip()
        yield line
        if "-----BEGIN " in line:
            pem = [line]
        elif pem:
            pem.append(line)
            if "-----END " in line:
                yield "\n".join(pem)
                pem = []


if __name__ == "__main__":
    unittest.main()
