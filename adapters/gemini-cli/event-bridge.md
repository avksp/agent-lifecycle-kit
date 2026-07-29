# gemini-cli event bridge

This is an EXPERIMENTAL bounded event bridge for Gemini CLI `stream-json`
output. It translates host-operation invocations into portable
`agent-host-operation-receipt.v1` receipts through
`tools/live_hosts/gemini_cli_harness.py` and `adapters/gemini-cli/runner.py`.

This bridge does not promote Gemini CLI to `VERIFIED`. Unsupported or
unattested operations still fail closed until host-specific live conformance,
live calibration and lifecycle proof evidence are accepted.
