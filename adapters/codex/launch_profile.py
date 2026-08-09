"""Qualified local profile for Codex CLI 0.147.0."""

PROFILE = {
    "schemaVersion": "agent-local-host-launch-profile.v1",
    "status": "LOCAL_OPT_IN",
    "adapterId": "codex",
    "executable": "codex",
    "argvTemplate": ["exec", "--json", "Continue the frozen ALK task in this repository. Preserve review, audit, and finalization gates."],
    "versionProbeArgs": ["--version"],
    "env": {"allow": ["HOME", "PATH"], "allowPatterns": [], "projectPolicyAllowed": False},
    "timeoutSeconds": 300,
    "shell": False,
    "writesNativeConfig": False,
    "promptInjectionDefault": False,
    "publicSupportClaimed": False,
    "productionPromotionClaimed": False,
    "qualification": {
        "schemaVersion": "agent-host-launch-qualification-policy.v1",
        "expectedVersion": "0.147.0",
        "receiptFile": "codex-0.147.0.qualification.json",
        "requiredForManagedTask": True,
        "maxPreflightProcesses": 1,
        "modelCallsForPreflight": 0,
    },
}
