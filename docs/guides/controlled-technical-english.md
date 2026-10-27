# Controlled technical English for ALK

This is a local writing profile inspired by Simplified Technical English (STE).
It covers new instruction text and the maintained skill routes. It does not
claim ASD-STE100 conformity or certification. It does not reproduce the licensed
manual or its dictionary. The Russian guide preserves meaning; it is not an
English-standard compliance claim.

## Write an instruction

- Name the actor when it is not clear. Use an active verb: “The controller checks
  the lock.” Use the imperative for an agent action: “Check the lock.”
- Put one action in each sentence. Put its condition before the action: “If the
  receipt is missing, stop.” Keep the condition and action together.
- Use one term for one concept. Use the ALK glossary below. Keep necessary
  technical terms; explain a new term before using an abbreviation.
- State an obligation with “must”, a prohibition with “do not” or “must not”,
  and an option with “may”. Do not replace an obligation with “should”.
- Name the required evidence and the refusal condition. “Run the check” alone
  does not explain what permits the next action.
- Keep commands, paths, schema fields, enum values, error codes, hashes, units
  and numeric limits exact. Use code formatting for identifiers. Do not translate
  them or shorten them to meet a sentence-length target.
- Preserve all conditions, exceptions, negations and ordering when splitting a
  sentence. A shorter instruction must not grant additional authority.

Example: “If telemetry is unavailable, keep its value null. Do not report zero.”
This retains the refusal boundary; “Use a default value” does not.

## ALK glossary

| Term | Meaning in ALK instructions |
| --- | --- |
| draft | Input that has not passed the required review and freeze. It grants no execution authority. |
| frozen plan | Reviewed matching plan inputs bound by the plan lock. A freeze alone does not authorize execution. |
| authorization | Permission for the selected action under the current plan and workflow state. A prose statement is not a native state transition. |
| task attempt | One bounded execution of a frozen task. A retry retains prior costs and evidence. |
| receipt | A recorded result bound to its inputs and operation. A file's existence alone does not prove acceptance. |
| evidence | Verifiable inputs or results supporting a stated claim. Missing evidence stays missing. |
| independent review | Assessment by a reviewer independent of the implementation author. A worker's self-check is not that review. |
| acceptance | The existing workflow transition after its required evidence and checks pass. |
| projection | A proposed action or display computed before apply. It grants no execution authority. |
| refusal | A required stop at an unmet contract condition. Do not rewrite it as success. |
| budget | A finite frozen limit, including retry and closeout constraints. Compaction does not reset it. |
| `UNKNOWN` / null | Usage that is unavailable remains unknown; null is not zero. Preserve the field's defined schema representation. |

## Read by stage

Each role keeps its complete hash-bound lifecycle contract mandatory. Keep the
latest user instruction and active packet verbatim. Use paths from the installed
skill root, not an unrelated consumer project's `docs/` directory. The portable
package supplies the required static guides and references.

| Requested case | Role | Applicable cookbook recipe |
| --- | --- | --- |
| Plan authoring | `agent-first-planning` | Research and planning only |
| Worker compilation | `agent-plan-to-workers` | None; use the complete compilation contract |
| Plan review | `audit-agent-plan` | Review a Markdown plan folder |
| Implementation audit | `audit-plan-implementation` | Audit implementation evidence |
| Defect repair | `bug-forensics` | Bug Forensics repair, only after explicit opt-in |
| Untrusted issue intake | `issue-to-spec` | None; use the draft-only intake contract |

For a role that uses a recipe, read the cookbook common route, recipe table,
safety rules, selected recipe and its required follow-ups. Load another recipe
when the stage changes. Compilation and intake must not borrow an unrelated
execution recipe. The orchestrator selects the recipe for its actual stage.
These reading routes add no workflow phase, audit pass or execution authority.
See [Lifecycle task scenarios](lifecycle-cookbook.md).

The existing `tools/release/validate_skill_parity.py` checks reference hashes,
package bytes and a bounded set of critical clauses. It reports UTF-8 byte counts
and whitespace-separated word counts (`len(text.split())`). These counts include
Markdown and code. They are not tokens, model calls, cost or behavior measures.
For a before/after comparison, retain the exact source bytes and hashes, name
the same requested stage, and list every selected section. Include the required
full reference on both sides and include every mandatory shared or transitive follow-up for that case.
If a required source is missing, mark the measurement `INCOMPLETE`. Record exact
UTF-8 byte intervals, document hashes and source identities. Union overlapping
intervals within one document and case; count reuse again in another case.
Report increases honestly. Do not infer reuse after compaction or omit a required
reference to obtain a smaller number. User/system input, active packets and model
overhead remain execution obligations outside this source-reading projection.

Clause checks cannot prove semantic equivalence or general STE compliance.
Independent semantic review must check authorization, refusal, budgets, unknown
usage, commands and schema identifiers against the original instructions. Do
not claim token savings or improved behavior without comparable measured data.
