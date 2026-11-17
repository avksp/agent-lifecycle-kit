# Verify an anchored run in CI

Run `agent-lifecycle audit verify-chain` from a trusted installer or checkout.
A repository checkout supplies evidence. The verifier owner supplies the trust
configuration and terminal anchor from a separate protected source.

## Prepare the inputs

Use an immutable copy of one completed strict run. Keep its paths relative to
the selected evidence root. Include the frozen manifest and lock, state and
its referenced storage, event journal, reports, execution receipts, and
required signature files. The first version supports one adopted strict plan
with one final outcome. If admissions from earlier attempts are missing, the
command reports `NOT_CHECKED`.

The bundle identifies the manifest, lock, state, journal and receipt chain.
Use `agent-chain-verification-bundle.v1`. The receipt chain uses raw SHA-256
digests of its selected files. It must include the files referred to by the
run and signature checks. It excludes the bundle and chain files themselves.

The trust configuration pins the canonical reviewer policy digest. It pins the
operator policy digest when applicable. The terminal anchor binds the run ID,
package, plan and source, terminal state revision and raw hashes of the bundle,
lock, state, journal, chain and trust configuration. Have the verifier owner
approve these values from the expected finished run. Save the configuration and
anchor outside the evidence root. Copying hashes from an untrusted submission
does not establish independence.

The command prints one JSON report and writes no files. Exit `0` means the
selected checks passed. Exit `1` names an evidence mismatch or an unsupported
check. Exit `2` means an input selector or required input is invalid or
unreadable. Disabled operator signatures are explicitly `NOT_APPLICABLE`.
A successful report is about the selected public inputs. Independent key
custody and host isolation require separate deployment evidence.

## Configure the job

Use a workflow whose definition and required status an untrusted PR cannot
alter. Replace the example repository and the full commit placeholder with
your verifier owner's protected repository and reviewed commit. Keep the
verifier wheel, trust configuration and anchor in that protected source.
Use the PR checkout only as evidence. [GitHub secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)

```yaml
name: Verify selected run
on: pull_request
permissions:
  contents: read
jobs:
  verify-run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          path: evidence
          persist-credentials: false
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: OWNER/protected-verifier-inputs
          ref: REPLACE_WITH_FULL_REVIEWED_COMMIT_SHA
          path: verifier
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
        with:
          python-version: "3.12"
      - run: |
          python -m venv "$RUNNER_TEMP/chain-verify"
          "$RUNNER_TEMP/chain-verify/bin/pip" install --no-index --no-deps \
            "$GITHUB_WORKSPACE/verifier/agent_lifecycle_kit-2.51.0-py3-none-any.whl"
          "$RUNNER_TEMP/chain-verify/bin/agent-lifecycle" audit verify-chain \
            --repository-root "$GITHUB_WORKSPACE/evidence" \
            --bundle receipts/bundle.json \
            --trust-config "$GITHUB_WORKSPACE/verifier/trust.json" \
            --anchor "$GITHUB_WORKSPACE/verifier/anchor.json"
```

Keep the evidence checkout read-only during verification. Give the verifier
process no model credentials, secret environment or write permission on the
evidence. The verification process uses no network. Checkout and environment
setup happen before verification. Configure the protected required workflow or
required status in repository settings after the verifier owner confirms the
trust inputs and expected result. The example adds no repository rule itself.

See [reviewer provenance](../reference/audit-evidence-and-reviewer-provenance.md)
and the [CLI reference](../reference/cli.md).
