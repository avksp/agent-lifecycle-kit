# Verify an anchored run in CI

Run `agent-lifecycle audit verify-chain` from a trusted installer or checkout.
A repository checkout supplies evidence. The verifier owner supplies the trust
configuration and terminal anchor from a separate protected source.

## Prepare the evidence

Select an immutable copy of one completed strict run. Include its frozen
plan and lock, task packet set, state and reachable storage, journal, reports
and applicable signatures. This profile covers one adopted plan, one initial
grant, one attempt per task and one final outcome. A retry, renewal or
additional unsupported admission yields NOT_CHECKED.

The bundle selects repository-relative paths to the manifest, lock, state,
journal and receipt chain. Use agent-chain-verification-bundle.v1. In the
receipt chain, include raw SHA-256 digests of the files used by the proof.
Exclude the bundle and chain files. The verifier derives the required closure from the native
evidence before it compares the chain inventory.

The trust configuration pins the canonical reviewer policy digest and the
operator policy digest when applicable. The terminal anchor binds the run ID,
package, plan, source, terminal revision and raw hashes of the bundle, lock,
state, journal, chain and trust configuration. Have the verifier owner select
the trust configuration and anchor from the expected run. Keep them outside the
evidence root and outside the PR's control.

The command prints one JSON result and leaves input files unchanged. Exit 0
means verification passed for the selected scope. Exit 1 reports an evidence
mismatch or NOT_CHECKED. Exit 2 reports an invalid selector or unreadable
input. An absent artifact in a known anchored archive is a mismatch.
Disabled operator signatures are explicitly NOT_APPLICABLE.

## Configure the job

Store the workflow in a protected verifier-owned source. Where your GitHub
organization or enterprise supports ruleset workflows, select that source
and workflow in the rule that requires workflows to pass before merge.
Bind the expected check to the selected PR commit. Verify the rule on a
test PR before relying on it. In this example the verifier provides
trust.json and anchor.json in a reviewed public repository at a full SHA.
Fetch private verifier inputs in a trusted checkout step with a read-only
credential scoped to that repository. Keep the credential outside the
verification container.

Prepare a credential-free image with the reviewed 2.51.0 CLI installed at
/usr/local/bin/agent-lifecycle and pin its image digest. Use the PR checkout as evidence.
[GitHub secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)
[GitHub ruleset workflows](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging)

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
      - env:
          CHAIN_VERIFIER_IMAGE: ghcr.io/OWNER/alk-verifier@sha256:REVIEWED_IMAGE_DIGEST
        run: |
          docker pull "$CHAIN_VERIFIER_IMAGE"
          docker run --rm --pull=never \
            --read-only --network none --user 65532:65532 \
            --cap-drop ALL --security-opt no-new-privileges \
            --env PYTHONDONTWRITEBYTECODE=1 \
            --mount "type=bind,src=$GITHUB_WORKSPACE/evidence,dst=/evidence,readonly,bind-recursive=disabled" \
            --mount "type=bind,src=$GITHUB_WORKSPACE/verifier,dst=/verifier,readonly,bind-recursive=disabled" \
            --entrypoint /usr/local/bin/agent-lifecycle "$CHAIN_VERIFIER_IMAGE" \
            audit verify-chain --repository-root /evidence \
            --bundle receipts/bundle.json \
            --trust-config /verifier/trust.json --anchor /verifier/anchor.json
```

Checkout and image pull happen before verification. Grant the selected UID
read and traversal permission on the two input mounts. Keep host tokens,
secrets and runtime sockets outside the container. Configure the protected
workflow and required status after the verifier owner confirms the inputs.
The example defines a container boundary. External account and key custody
claims require separate deployment evidence.
[Docker run options](https://docs.docker.com/reference/cli/docker/container/run/)

See [reviewer provenance](../reference/audit-evidence-and-reviewer-provenance.md)
and the [CLI reference](../reference/cli.md).
