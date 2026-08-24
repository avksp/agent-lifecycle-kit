# Project domain language

Project domain language is an optional, project-local vocabulary for terms that
must remain consistent across a specification, APIs, code symbols, tests and
documentation. It is useful when one word has several bounded contexts, such
as the three `qualification` contexts recorded for ALK. It is not a universal
naming policy and it does not require every identifier to be listed.

## Authority and boundaries

The artifact uses the `agent-project-domain-language.v1` contract. Each term
has a stable `termId`, English and Russian labels and definitions, optional
aliases, contexts and normalized repository references. The artifact is
source-controlled and carries a revision and self-digest.

The specification and frozen plan remain authoritative. The vocabulary cannot
grant ownership, change a requirement, approve a result or lower a security,
quality or risk gate. ALK never renames files or prose automatically. The
vocabulary does not grant write authority. The feature is inactive when a
project has no vocabulary artifact, so ordinary work has no additional scan or
runtime cost.

References are repository-relative. Absolute paths, `..`, URI-like values,
symlinked files, executable guidance, secrets and provider-specific content
are rejected. Audits are read-only and bounded; they do not write code,
plans, documentation or workflow state.

## Artifact shape

Create a project-local file such as `docs/domain-language.json`:

```json
{
  "schemaVersion": "agent-project-domain-language.v1",
  "languageId": "checkout-terms",
  "revision": 1,
  "defaultLocale": "en",
  "terms": [
    {
      "termId": "qualification",
      "labels": {"en": "Qualification", "ru": "Квалификация"},
      "definitions": {
        "en": "A bounded validation of a named capability.",
        "ru": "Ограниченная проверка названной возможности."
      },
      "aliases": [
        {"value": "qualification receipt", "locale": "en", "status": "ACTIVE"}
      ],
      "contexts": ["agent-plugin", "benchmark", "structured-result"],
      "references": [
        {"kind": "documentation", "path": "docs/terms.md", "locator": "qualification"}
      ]
    }
  ],
  "authority": {
    "role": "terminology-reference",
    "sourceOfTruth": "specification-and-frozen-plan",
    "semanticReview": "independent-review"
  },
  "source": {"kind": "project-local", "path": "docs/domain-language.json"},
  "productionPromotionClaimed": false,
  "languageDigest": "<sha256-of-the-object-without-languageDigest>"
}
```

The artifact is validated by `agent-project-domain-language-validation.v1`.
Use `ACTIVE` aliases during a transition and `DEPRECATED` aliases when a
reviewed rename must expose remaining references. A deprecated alias is a
finding, not an automatic edit.

## Commands

Validate the artifact without starting a model or host process:

```bash
agent-lifecycle project language check \
  --file docs/domain-language.json \
  --project-root .
```

Inspect selected terms and affected files without modifying them:

```bash
agent-lifecycle project language audit \
  --file docs/domain-language.json \
  --project-root . \
  --term-id qualification \
  --changed-path docs/terms.md \
  --out work/domain-language-audit.json
```

The audit returns `PASS`, `DRIFT` for declared aliases still found in
references, or `FAIL` for malformed, missing, escaping or unreadable inputs.
Its envelope is `agent-project-domain-language-audit.v1` and `readOnly` is
always `true`.

Bind two reviewed vocabulary revisions to a plan delta:

```bash
agent-lifecycle plan delta \
  --before path/to/plan-v1/plan.manifest.json \
  --after path/to/plan-v2/plan.manifest.json \
  --language-before path/to/domain-language-v1.json \
  --language-after path/to/domain-language-v2.json \
  --out work/plan-delta.json

agent-lifecycle plan delta-check --delta work/plan-delta.json
```

The `agent-project-domain-language-delta.v1` section reports added and removed
terms, label changes, deprecated aliases and a deterministic impacted-reference
set. It is digest-bound, read-only and requires a new language revision. It
does not replace the plan delta's review or lock decision.

## Adoption guidance

Start with a small set of terms that already causes review or documentation
drift. Give each term one stable ID and link only the governed files that a
reviewer needs to update. Keep the three ALK qualification contexts separate
when their requirements or acceptance evidence differ. Review changes to the
vocabulary as plan input; do not treat a term list as proof that an
implementation is correct.

See [project principles and plan deltas](project-principles-and-plan-deltas.md)
for the adjacent continuity controls and [public contracts](public-contracts.md)
for the published schema registry.
